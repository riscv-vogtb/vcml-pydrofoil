#!/usr/bin/env python3
"""Build and run Juliet testcases on the vcml-pydrofoil VP.

Covers the CWEs mpoison can say something about, see SUITES: uninitialised
stack variables, dangling stack pointers and stack buffer over/underreads.
Every testcase yields two elfs, one running its bad() half and one its good()
half, so that a fault in one cannot keep the other from being observed.

The two phases need different environments: building needs the poison LLVM
toolchain (glibc >= 2.39, so a container on older hosts), running needs podman
for the VP image. tools/juliet/run_suite.sh wires both together.

    juliet_suite.py --list --suite all
    juliet_suite.py --build-only --filter '*_01'
    juliet_suite.py --run-only   --suite cwe126,cwe127 --variants 01-18
"""

import argparse
import csv
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple

REPO = Path(__file__).resolve().parents[2]
ZEPHYR_DIR = REPO / "sw" / "zephyr"
APP = "juliet"
PHASES = ("bad", "good")

# Unanchored: a testcase may leave an unterminated line before the marker.
PHASE_RE = re.compile(r"VP-PHASE: (\w+)")
RESULT_RE = re.compile(r"VP-RESULT: (\w+) addr=(\S+) mcause=(\d+)")

# Column order of results.csv, and the only fields a record carries.
FIELDS = ("key", "suite", "name", "category", "variant", "phase", "expected",
          "outcome", "verdict", "detail", "exit_code", "seconds")
# Judged rows carry a verdict, observed ones their outcome -- the grid of an
# OBSERVE suite is the measurement, not a pass list.
MARKS = {"PASS": "+", "FAIL": "-"}
OBSERVED_MARKS = {"POISON": "P", "CLEAN": ".", "FAULT": "F", "TIMEOUT": "T"}


def stack_family(family):
    """Sub-families whose buffer lives on the stack, the only ones mpoison
    can see. The heap ones are covered by CWE457, and the rest draw their
    index from sockets, fscanf or rand and do not run under Zephyr."""
    return "_declare_" in f"_{family}_" or "_alloca_" in f"_{family}_"


@dataclass(frozen=True)
class Suite:
    cwe: str        # testcase directory name
    tag: str        # short id for --suite and for the key prefix
    include: object          # (family) -> bool
    bad_expected: object     # (family) -> expectation of the bad half


SUITES = (
    # mpoison instruments the stack only, so the heap categories must not
    # fault -- they are the negative control.
    Suite("CWE457_Use_of_Uninitialized_Variable", "cwe457", lambda f: True,
          lambda f: "CLEAN" if "_malloc_" in f else "POISON"),
    # Whether these fault depends on how the compiler lays out the frame, so
    # any target would be a guess. OBSERVE records the outcome without judging.
    Suite("CWE562_Return_of_Stack_Variable_Address", "cwe562", lambda f: True,
          lambda f: "OBSERVE"),
    Suite("CWE126_Buffer_Overread", "cwe126", stack_family,
          lambda f: "OBSERVE"),
    Suite("CWE127_Buffer_Underread", "cwe127", stack_family,
          lambda f: "OBSERVE"),
)


@dataclass
class Case:
    suite: Suite
    family: str
    variant: str
    files: list = field(default_factory=list)

    @property
    def category(self):
        # Tagged, because char_declare_loop exists in CWE126 and CWE127 alike.
        return f"{self.suite.tag}_{self.family}"

    @property
    def name(self):
        return f"{self.category}_{self.variant}"

    @property
    def entry(self):
        return f"{self.suite.cwe}__{self.family}_{self.variant}"

    def expected(self, phase):
        # good() never has a reason to fault, whatever the suite tests.
        if phase == "good":
            return "CLEAN"
        return self.suite.bad_expected(self.family)


@dataclass
class Unit:
    """One half of a testcase: what gets built, run and reported as one row."""
    case: Case
    phase: str

    @property
    def key(self):
        return f"{self.case.name}.{self.phase}"

    @property
    def expected(self):
        return self.case.expected(self.phase)


class RunResult(NamedTuple):
    outcome: str
    detail: str
    exit_code: int
    seconds: float


def discover(juliet_root, suites, variants=None):
    """Group the testcase files of each suite into cases. Flow variants split
    over several files (63a/63b, up to 54a-54e) are one case: the parts are
    compiled together and the entry point drops the letter."""
    cases = []
    for suite in suites:
        case_re = re.compile(rf"^{suite.cwe}__(?P<family>.+)"
                             rf"_(?P<variant>\d\d)(?P<part>[a-e]?)\.c$")
        grouped = {}
        for path in sorted((juliet_root / "testcases" / suite.cwe).glob("**/*.c")):
            m = case_re.match(path.name)
            if not m or not suite.include(m["family"]):
                continue
            if variants and m["variant"] not in variants:
                continue
            grouped.setdefault((m["family"], m["variant"]), []).append(path)
        cases += [Case(suite, fam, var, files)
                  for (fam, var), files in sorted(grouped.items())]
    return cases


def new_record(unit):
    record = dict.fromkeys(FIELDS, "")
    record.update(key=unit.key, suite=unit.case.suite.tag, name=unit.case.name,
                  category=unit.case.category, variant=unit.case.variant,
                  phase=unit.phase, expected=unit.expected)
    return record


def verdict_for(expected, outcome):
    # An OBSERVE case has no defensible target; it is measured, not judged.
    if expected == "OBSERVE":
        return "INFO"
    return "PASS" if outcome == expected else "FAIL"


def case_source(unit, juliet_root):
    case = unit.case
    includes = "\n".join(
        f'#include "{f.relative_to(juliet_root / "testcases").as_posix()}"'
        for f in case.files
    )
    return f"""/* Generated by tools/juliet/juliet_suite.py -- do not edit. */

{includes}

const char *juliet_case_name = "{case.name}";
const char *juliet_phase = "{unit.phase}";

void juliet_run(void)
{{
\t{case.entry}_{unit.phase}();
}}
"""


def configure(board, fresh):
    """Bring up the one build directory every testcase is then built in."""
    build_dir = ZEPHYR_DIR / "workspace" / "zephyr" / "build" / f"{APP}-{board}"
    if fresh and build_dir.exists():
        shutil.rmtree(build_dir)
    if not (build_dir / "build.ninja").exists():
        subprocess.run([str(ZEPHYR_DIR / "build.sh"), APP, board],
                       cwd=ZEPHYR_DIR, check=True)
    return build_dir


def build_unit(unit, build_dir, juliet_root, elf_dir):
    (build_dir / "juliet_case.c").write_text(case_source(unit, juliet_root))
    proc = subprocess.run(["ninja", "-C", str(build_dir)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        return proc.stdout + proc.stderr
    shutil.copy(build_dir / "zephyr" / "zephyr.elf", elf_dir / f"{unit.key}.elf")
    return None


def write_cfg(key, template, cfg_path):
    elf = f"${{dir}}/../elf/{key}.elf"
    overrides = {"system.core.symbols": elf,
                 "system.core.elf": elf,
                 "system.loader.images": elf,
                 "system.name": f"juliet {key}"}
    out = []
    for line in template.splitlines():
        field_name = line.split("=", 1)[0].strip()
        if field_name in overrides:
            out.append(f"{field_name} = {overrides[field_name]}")
        else:
            out.append(line)
    cfg_path.write_text("\n".join(out) + "\n")


def podman_run(cmd, timeout):
    """Return exit code, combined output, and whether the VP had to be killed."""
    try:
        # An out-of-bounds read puts arbitrary bytes on the UART, so decoding
        # has to tolerate them rather than raise.
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              errors="replace", timeout=timeout)
        return proc.returncode, proc.stdout + proc.stderr, False
    except subprocess.TimeoutExpired as exc:
        return -1, (exc.stdout or b"").decode(errors="replace"), True


def run_unit(unit, results, template, image, timeout):
    cfg = results / "cfg" / f"{unit.key}.cfg"
    write_cfg(unit.key, template, cfg)
    cmd = ["podman", "run", "--rm", "--userns", "keep-id",
           "--security-opt", "label=disable", "-v", f"{REPO}:/configs:ro",
           image, str(cfg.relative_to(REPO))]
    started = time.time()
    # A run that normally takes seconds can stall under load; retry once so a
    # flake does not read as a result.
    for _ in range(2):
        rc, output, timed_out = podman_run(cmd, timeout)
        outcome, detail = classify(rc, output, timed_out)
        if outcome != "TIMEOUT":
            break
    (results / "logs" / f"{unit.key}.log").write_text(output)
    return RunResult(outcome, detail, rc, time.time() - started)


def classify(rc, output, timed_out):
    if timed_out:
        return "TIMEOUT", ""
    phases = PHASE_RE.findall(output)
    last = phases[-1] if phases else "none"
    result = RESULT_RE.search(output)
    if result:
        return ("POISON" if result.group(1) == "POISON" else "FAULT"), result.group(0)
    if rc == 0 and last == "done":
        return "CLEAN", ""
    if rc == 0:
        return "HANG", f"last phase: {last}"
    return "ERROR", f"exit {rc}, last phase: {last}"


def merge_results(path, rows):
    """Keep rows of testcases this run did not cover, so a filtered rerun does
    not throw away the rest of the report."""
    merged = {}
    if path.exists():
        with path.open(newline="") as fh:
            for old in csv.DictReader(fh):
                merged[old["key"]] = {f: old.get(f, "") for f in FIELDS}
    for row in rows:
        merged[row["key"]] = row
    ordered = sorted(merged.values(), key=lambda r: r["key"])
    with path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(ordered)
    return ordered


def print_grid(phase, categories, variants, marks):
    width = max(len(c) for c in categories)
    print(f"\nphase {phase}")
    print(f"{'category'.ljust(width)}  " + " ".join(v.rjust(2) for v in variants))
    for cat in categories:
        cells = (marks.get((cat, var), "").rjust(2) for var in variants)
        print(f"{cat.ljust(width)}  " + " ".join(cells))


def mark_for(record):
    if record["verdict"] == "INFO":
        return OBSERVED_MARKS.get(record["outcome"], "?")
    return MARKS.get(record["verdict"], "?")


def report(records):
    categories = sorted({r["category"] for r in records})
    variants = sorted({r["variant"] for r in records})
    for phase in PHASES:
        marks = {(r["category"], r["variant"]): mark_for(r)
                 for r in records if r["phase"] == phase}
        if marks:
            print_grid(phase, categories, variants, marks)
    print("\n  judged: + expected  - unexpected")
    print("  observed: P poison  . clean  F fault  T timeout\n")

    counts = Counter((r["phase"], r["verdict"], r["outcome"]) for r in records)
    for (phase, verdict, outcome), n in sorted(counts.items()):
        print(f"  {phase:4}  {verdict:4}  {outcome:15} {n:4}")

    judged = [r for r in records if r["verdict"] in ("PASS", "FAIL")]
    failed = sorted((r for r in judged if r["verdict"] == "FAIL"),
                    key=lambda r: r["key"])
    if judged:
        print(f"\n  {len(judged) - len(failed)}/{len(judged)} as expected")
    for rec in failed:
        print(f"    {rec['key']}: expected {rec['expected']}, got {rec['outcome']} "
              f"{rec['detail']}")

    # The detection rate is the whole point of the OBSERVE suites.
    observed = Counter((r["suite"], r["phase"], r["outcome"])
                       for r in records if r["verdict"] == "INFO")
    if observed:
        print(f"\n  {sum(observed.values())} observed, no expectation:")
        for (suite, phase, outcome), n in sorted(observed.items()):
            print(f"    {suite:8} {phase:4} {outcome:10} {n:4}")


def build_all(units, records, args):
    if os.environ.get("ZEPHYR_TOOLCHAIN_VARIANT") != "llvm":
        sys.exit("ZEPHYR_TOOLCHAIN_VARIANT must be llvm; gcc emits no mpoison")
    build_dir = configure(args.board, fresh=not args.no_fresh)
    started = time.time()
    for i, unit in enumerate(units, 1):
        error = build_unit(unit, build_dir, args.juliet_root, args.results / "elf")
        if error:
            records[unit.key].update(outcome="BUILD_FAIL", verdict="FAIL",
                                     detail=error.strip().splitlines()[-1][:200])
            (args.results / "logs" / f"{unit.key}.build.log").write_text(error)
        print(f"[{i}/{len(units)}] build {unit.key}{' FAILED' if error else ''}",
              flush=True)
    print(f"built {len(units)} in {time.time() - started:.0f}s")


def run_all(units, records, args):
    runnable = []
    for unit in units:
        record = records[unit.key]
        if record["outcome"] == "BUILD_FAIL":
            continue
        if (args.results / "elf" / f"{unit.key}.elf").exists():
            runnable.append(unit)
        else:
            record.update(outcome="NO_ELF", verdict="FAIL",
                          detail="build phase did not produce an elf")
    template = (REPO / "benchmark" / "zephyr" / "juliet.cfg").read_text()
    started = time.time()

    def work(unit):
        return unit, run_unit(unit, args.results, template, args.image,
                              args.timeout)

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        for i, (unit, result) in enumerate(pool.map(work, runnable), 1):
            record = records[unit.key]
            verdict = verdict_for(record["expected"], result.outcome)
            record.update(outcome=result.outcome, detail=result.detail,
                          exit_code=result.exit_code,
                          seconds=f"{result.seconds:.1f}", verdict=verdict)
            print(f"[{i}/{len(runnable)}] {verdict:4} {unit.key} "
                  f"-> {result.outcome}", flush=True)
    print(f"ran {len(runnable)} in {time.time() - started:.0f}s")


def parse_suites(spec):
    by_tag = {s.tag: s for s in SUITES}
    if spec == "all":
        return SUITES
    chosen = []
    for tag in spec.split(","):
        if tag.strip() not in by_tag:
            sys.exit(f"unknown suite {tag.strip()!r}; known: {', '.join(by_tag)}")
        chosen.append(by_tag[tag.strip()])
    return tuple(chosen)


def parse_variants(spec):
    """"01-18" or "01,63,64"; None means every variant the suite has."""
    if not spec:
        return None
    chosen = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = (int(x) for x in part.split("-", 1))
            chosen |= {f"{i:02d}" for i in range(lo, hi + 1)}
        else:
            chosen.add(f"{int(part):02d}")
    return chosen


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--filter", default="*", help="fnmatch pattern on the case name")
    ap.add_argument("--suite", default="cwe457",
                    help="comma separated suite tags, or 'all' (default cwe457)")
    ap.add_argument("--variants",
                    help="flow variants to keep, e.g. '01-18' (default all)")
    ap.add_argument("--phase", choices=PHASES, help="only one half of each testcase")
    ap.add_argument("--board", default="pydrofoil_64")
    ap.add_argument("--build-only", action="store_true")
    ap.add_argument("--run-only", action="store_true")
    ap.add_argument("--jobs", type=int, default=4, help="parallel VP runs")
    ap.add_argument("--timeout", type=int, default=120, help="seconds per VP run")
    ap.add_argument("--no-fresh", action="store_true",
                    help="keep an existing build directory (see README)")
    ap.add_argument("--results", type=Path, default=REPO / "results" / "juliet")
    ap.add_argument("--image", default="localhost/vcml-pydrofoil:latest")
    ap.add_argument("--juliet-root", type=Path,
                    default=Path(os.environ.get("JULIET_ROOT",
                                                REPO / "juliet_test_suite")))
    ap.add_argument("--list", action="store_true", help="list cases and exit")
    args = ap.parse_args()
    args.suites = parse_suites(args.suite)
    args.variants = parse_variants(args.variants)

    # The VP reads its config through the repo mounted as /configs.
    args.results = (args.results if args.results.is_absolute()
                    else REPO / args.results).resolve()
    if not args.results.is_relative_to(REPO):
        sys.exit(f"--results must be inside {REPO}")
    return args


def main():
    args = parse_args()

    # Alle testcases sammeln
    cases = [c for c in discover(args.juliet_root, args.suites, args.variants)
             if fnmatch.fnmatch(c.name, args.filter)]
    if not cases:
        sys.exit(f"no testcases match {args.filter!r}")
    if args.list:
        for case in cases:
            print(f"{case.name:52} bad={case.expected('bad'):8} "
                  f"{' '.join(f.name for f in case.files)}")
        print(f"\n{len(cases)} testcases")
        return

    # Default: run both good and bad, which each have their own elf, unit + record
    phases = (args.phase,) if args.phase else PHASES
    units = [Unit(c, p) for c in cases for p in phases]
    records = {u.key: new_record(u) for u in units}

    # Everything a run produces lands under --results.
    for subdir in ("elf", "cfg", "logs"):
        (args.results / subdir).mkdir(parents=True, exist_ok=True)

    # Build, then run; either half can be left to the other environment.
    if not args.run_only:
        build_all(units, records, args)
    if not args.build_only:
        run_all(units, records, args)

    # Fold this run into the report of the ones before it.
    rows = merge_results(args.results / "results.csv", list(records.values()))
    print(f"\nresults in {args.results.relative_to(REPO)}")

    if args.build_only:
        # Only a total build failure is worth stopping the wrapper for.
        failed = [r for r in rows if r["outcome"] == "BUILD_FAIL"]
        sys.exit(1 if len(failed) == len(rows) else 0)

    # The exit code carries the verdict, so run_suite.sh can stop on it.
    report(rows)
    sys.exit(1 if any(r["verdict"] == "FAIL" for r in rows) else 0)


if __name__ == "__main__":
    main()
