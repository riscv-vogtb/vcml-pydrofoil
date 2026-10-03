#!/usr/bin/env python3
"""Runner fuer die Performance-Messungen der POISON-Erweiterung.

Setzt thesis/messplan.md um. Die ELFs kommen aus tools/bench/build.sh
(results/bench/elf/manifest.tsv).

Konfigurationen (messplan.md §3):
    A  Sim ohne Poison, ELF plain     Referenz
    B  Sim mit Poison,  ELF plain     Kosten der Einbindung (B - A)
    C  Sim mit Poison,  ELF poison    Kosten der Nutzung    (C - B)
    A2 wie A, eigene Zelle            Rauschkontrolle A gegen A (nur timing)
    N  Sim ohne Poison, ELF poison    Negativkontrolle (erwartet mcause=2)
    Bo/Co wie B/C, aber Sim mit optimierten Shadow-Helfern (ein Shadow-Zugriff
          pro Load/Store, 8-Byte-Bloecke fuer mpoison; messplan.md §8.4b)

Pfade (§4):
    iss   Standalone pydrofoil-riscv-{with,without}-poison, HTIF-ELFs
    csim  Sail-C-Emulator riscv_sim_RV64_{with,without}_poison, HTIF-ELFs,
          immer mit --no-trace (der Emulator tract per Default alles)
    vp    sysc_vp-Image (Release), VP-ELFs (UART + simdev-STOP)

Modi:
    count     Instruktionszahlen (deterministisch): A/B/C je 1x, parallel,
              ungepinnt. Gegenprobe: A und B muessen identisch zaehlen.
    timing    Zeitmessung: A/A2/B/C x --reps, randomisierte verschraenkte
              Reihenfolge (Seed protokolliert), seriell, gepinnt (§9.2).
    twopoint  Nur iss/csim: wie timing, aber je Lauf --inst-limit N und 2N
              (§9.1). Keine BENCH-Zeile erwartet (Abbruch vor Regionsende).
    negctl    Konfiguration N je Workload 1x.

Beispiele:
    bench.py run --path iss --mode count --jobs 16
    bench.py run --path iss --mode timing --reps 5 --suite micro --dry-run
    bench.py run --path iss --mode timing --reps 3 --workload baseline_alu \\
        --opt O2 --tag precheck                      # Schritt 0, §8.1
    bench.py run --path csim --mode timing --suite embench     # Pfad 3
    bench.py summary --path iss --mode timing
"""

import argparse
import concurrent.futures
import csv
import datetime
import hashlib
import json
import os
import platform
import random
import re
import shlex
import socket
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
BENCH_DIR = REPO / "tools" / "bench"
RESULTS = REPO / "results" / "bench"
MANIFEST = RESULTS / "elf" / "manifest.tsv"
CFG_TEMPLATE = BENCH_DIR / "vp_bench.cfg.in"

CONFIGS = {
    # config: (simulator, ELF-Variante)
    "A": ("without", "plain"),
    "B": ("with", "plain"),
    "C": ("with", "poison"),
    "A2": ("without", "plain"),
    "N": ("without", "poison"),
    "Bo": ("opt", "plain"),
    "Co": ("opt", "poison"),
}
MODE_CONFIGS = {
    "count": ("A", "B", "C", "Bo", "Co"),
    "timing": ("A", "A2", "B", "C", "Bo", "Co"),
    "twopoint": ("A", "B", "C", "Bo", "Co"),
    "negctl": ("N",),
}
PLATFORM_FOR_PATH = {"iss": "htif", "csim": "htif", "vp": "vp"}
HTIF_PATHS = ("iss", "csim")

# GNU time des Hosts (EL8, glibc 2.28) laeuft auch im ubuntu:24.04-Container
# und misst dort den Simulatorprozess selbst, nicht den podman-Client
# (messplan.md §8.3).
GTIME_HOST = "/usr/bin/time"
GTIME_IN = "/usr/local/bin/gtime"
GTIME_FMT = "GTIME: wall=%e user=%U sys=%S maxrss_kb=%M exit=%x"

ISS_IMAGE = "ubuntu:24.04"
VP_BINARY = "/vcml-pydrofoil/build/sysc_vp"

FIELDS = [
    "run_key", "timestamp", "path", "mode", "tag", "config", "sim", "sim_id",
    "suite", "workload", "params", "opt", "variant", "elf_id", "elf_sha256",
    "rep", "order_idx", "seed", "inst_limit", "quantum", "cpus",
    "status", "exit_code", "mcause",
    "region_instret", "region_cycle", "total_instret",
    "vp_instructions", "vp_runtime_s", "vp_mips",
    "host_wall_s", "host_user_s", "host_sys_s", "max_rss_kb", "outer_wall_s",
    "text", "data", "bss", "mpoison_static",
    "functions_total", "functions_instrumented",
    "gsf", "warmup_heat", "micro_scale", "log",
]

RE_BENCH = re.compile(
    r"BENCH: region_instret=(\d+) region_cycle=(\d+) total_instret=(\d+)")
RE_TRAP = re.compile(r"BENCH-TRAP: mcause=(\d+) mepc=(0x[0-9a-f]+) mtval=(0x[0-9a-f]+)")
RE_EXIT = re.compile(r"BENCH-EXIT: code=(-?\d+)")
RE_GTIME = re.compile(
    r"GTIME: wall=([0-9.]+) user=([0-9.]+) sys=([0-9.]+) maxrss_kb=(\d+) exit=(-?\d+)")
RE_VP_RUNTIME = re.compile(r"runtime\s*:\s*([0-9.]+)s")
RE_VP_INSN = re.compile(r"instructions\s*:\s*(\d+)")
RE_ISS_FAIL = re.compile(r"FAILURE:")


#----------------------------------------------------------------------------
# Manifest und Auswahl
#----------------------------------------------------------------------------

def load_manifest():
    if not MANIFEST.exists():
        sys.exit(f"{MANIFEST} fehlt - erst tools/bench/build.sh ausfuehren")
    with MANIFEST.open() as f:
        return list(csv.DictReader(f, delimiter="\t"))


def select_elfs(manifest, args):
    """ELF-Zeilen fuer die Plattform des Pfads, gefiltert, nach (Workload, opt)."""
    plat = PLATFORM_FOR_PATH[args.path]
    rows = {}
    for r in manifest:
        if r["platform"] != plat or r["status"] != "ok":
            continue
        if args.suite and r["suite"] not in args.suite:
            continue
        if args.workload and r["workload"] not in args.workload:
            continue
        if args.opt and r["opt"] not in args.opt:
            continue
        if args.match and not re.search(args.match, r["id"]):
            continue
        rows[(r["suite"], r["workload"], r["params"], r["opt"], r["variant"])] = r
    return rows


def cells(elf_rows, configs):
    """(config, elf-row) fuer jede Konfiguration, fuer die das ELF existiert."""
    out = []
    keys = sorted({k[:4] for k in elf_rows})
    for k in keys:
        for cfg in configs:
            _, variant = CONFIGS[cfg]
            row = elf_rows.get(k + (variant,))
            if row is not None:
                out.append((cfg, row))
    return out


#----------------------------------------------------------------------------
# Simulatoren
#----------------------------------------------------------------------------

def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def image_id(image):
    proc = subprocess.run(["podman", "image", "inspect", "--format", "{{.Id}}", image],
                          stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                          universal_newlines=True)
    return proc.stdout.strip() if proc.returncode == 0 else ""


def resolve_sims(args):
    """sim -> (Beschreibung, Identitaet). Bricht ab, wenn ein noetiger Sim fehlt."""
    needed = {CONFIGS[c][0] for c in (args.config or MODE_CONFIGS[args.mode])}
    sims = {}
    for sim in sorted(needed):
        if args.path in HTIF_PATHS:
            if args.path == "iss":
                path = Path({"with": args.iss_with, "without": args.iss_without,
                             "opt": args.iss_opt}[sim])
            else:
                path = Path({"with": args.csim_with, "without": args.csim_without,
                             "opt": args.csim_opt}[sim])
            if not path.is_absolute():
                path = REPO / path
            if not path.exists():
                sys.exit(f"Simulator fehlt: {path}")
            try:
                path.relative_to(REPO)
            except ValueError:
                sys.exit(f"Simulator muss im Repo liegen (Mount): {path}")
            sims[sim] = (str(path), "sha256:" + sha256_file(path))
        else:
            image = {"with": args.vp_with_image, "without": args.vp_without_image,
                     "opt": args.vp_opt_image}[sim]
            iid = image_id(image)
            if not iid:
                sys.exit(f"Image fehlt: {image}")
            sims[sim] = (image, iid)
    return sims


def base_podman(args, cpus):
    cmd = ["podman", "run", "--rm", "--security-opt", "label=disable",
           "-v", f"{REPO}:/w:ro", "-v", f"{GTIME_HOST}:{GTIME_IN}:ro"]
    if cpus:
        cmd += ["--cpuset-cpus", cpus]
    return cmd


def htif_command(args, sim_path, elf_rel, inst_limit, cpus):
    """Standalone-Pydrofoil und Sail-C-Emulator: gleiche ELFs, gleiche Optionen."""
    sim_rel = Path(sim_path).relative_to(REPO)
    cmd = base_podman(args, cpus) + ["-w", "/w", "--entrypoint", GTIME_IN, ISS_IMAGE,
                                     "-f", GTIME_FMT, f"./{sim_rel}"]
    if args.path == "csim":
        cmd.append("--no-trace")
    if args.ram_size:
        cmd += ["--ram-size", str(args.ram_size)]
    if inst_limit:
        cmd += ["--inst-limit", str(inst_limit)]
    return cmd + [elf_rel]


def vp_cfg(args, elf_row):
    """Erzeugt die cfg fuer ein VP-ELF (deterministisch aus den Parametern)."""
    ram = args.vp_ram_mib * 1024 * 1024
    text = CFG_TEMPLATE.read_text()
    for key, val in {
        "@NAME@": elf_row["id"],
        "@QUANTUM@": args.quantum,
        "@DURATION@": args.vp_duration,
        "@ELF@": f"/w/{elf_row['elf']}",
        "@RAM_HI@": hex(0x80000000 + ram - 1),
        "@SHADOW_HI@": hex(0xC0000000 + ram - 1),
    }.items():
        text = text.replace(key, val)
    cfg_dir = RESULTS / "cfg" / f"q{args.quantum}_ram{args.vp_ram_mib}"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg = cfg_dir / f"{elf_row['id']}.cfg"
    cfg.write_text(text)
    return cfg.relative_to(REPO)


def vp_command(args, image, cfg_rel, cpus):
    return base_podman(args, cpus) + ["--entrypoint", GTIME_IN, image,
                                      "-f", GTIME_FMT, VP_BINARY, "-f", f"/w/{cfg_rel}"]


#----------------------------------------------------------------------------
# Lauf und Auswertung eines Laufs
#----------------------------------------------------------------------------

def classify(path, mode, output, rc, timed_out):
    """-> (status, exit_code, mcause)"""
    if timed_out:
        return "timeout", "", ""
    trap = RE_TRAP.search(output)
    if trap:
        return "trap", "", trap.group(1)
    if path == "vp":
        ex = RE_EXIT.search(output)
        if not ex:
            return "incomplete", "", ""
        code = int(ex.group(1))
        if code != 0:
            return "fail", code, ""
        return ("ok" if RE_BENCH.search(output) else "no_bench_line"), 0, ""
    # iss / csim: beide Simulatoren enden immer mit Exit-Code 0, auch bei
    # HTIF-Fehlercode; massgeblich ist "FAILURE: <code>".
    if mode == "twopoint":
        return "limit", rc, ""
    if rc != 0 or RE_ISS_FAIL.search(output):
        return "fail", rc, ""
    return ("ok" if RE_BENCH.search(output) else "no_bench_line"), rc, ""


def parse_metrics(output):
    m = {}
    b = RE_BENCH.search(output)
    if b:
        m["region_instret"], m["region_cycle"], m["total_instret"] = b.groups()
    g = RE_GTIME.search(output)
    if g:
        (m["host_wall_s"], m["host_user_s"], m["host_sys_s"],
         m["max_rss_kb"], _) = g.groups()
    rt = RE_VP_RUNTIME.search(output)
    ni = RE_VP_INSN.search(output)
    if rt and ni:
        m["vp_runtime_s"], m["vp_instructions"] = rt.group(1), ni.group(1)
        if float(rt.group(1)) > 0:
            m["vp_mips"] = f"{int(ni.group(1)) / float(rt.group(1)) / 1e6:.4f}"
    return m


def run_one(args, job, sims, log_dir):
    cfg, row, rep, inst_limit, order_idx = job
    sim, _ = CONFIGS[cfg]
    sim_desc, sim_id = sims[sim]
    key = run_key(args, cfg, row, rep, inst_limit)
    cpus = args.cpus if args.mode != "count" else ""

    if args.path in HTIF_PATHS:
        cmd = htif_command(args, sim_desc, row["elf"], inst_limit, cpus)
    else:
        cmd = vp_command(args, sim_desc, vp_cfg(args, row), cpus)

    started = time.time()
    timed_out = False
    try:
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              universal_newlines=True, errors="replace",
                              timeout=args.timeout)
        output, rc = proc.stdout, proc.returncode
    except subprocess.TimeoutExpired as exc:
        out = exc.output or ""
        output = out.decode(errors="replace") if isinstance(out, bytes) else out
        rc, timed_out = "", True
    outer = time.time() - started

    log = log_dir / f"{key}.log"
    log.write_text("$ " + " ".join(shlex.quote(c) for c in cmd) + "\n\n" + output)

    status, exit_code, mcause = classify(args.path, args.mode, output, rc, timed_out)
    rec = {f: "" for f in FIELDS}
    rec.update({
        "run_key": key,
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "path": args.path, "mode": args.mode, "tag": args.tag, "config": cfg,
        "sim": sim, "sim_id": sim_id,
        "suite": row["suite"], "workload": row["workload"], "params": row["params"],
        "opt": row["opt"], "variant": row["variant"], "elf_id": row["id"],
        "elf_sha256": row["elf_sha256"], "rep": rep, "order_idx": order_idx,
        "seed": args.seed, "inst_limit": inst_limit or "",
        "quantum": args.quantum if args.path == "vp" else "",
        "cpus": cpus, "status": status, "exit_code": exit_code, "mcause": mcause,
        "outer_wall_s": f"{outer:.3f}",
        "text": row["text"], "data": row["data"], "bss": row["bss"],
        "mpoison_static": row["mpoison_static"],
        "functions_total": row["functions_total"],
        "functions_instrumented": row["functions_instrumented"],
        "gsf": row["gsf"], "warmup_heat": row["warmup_heat"],
        "micro_scale": row["micro_scale"],
        "log": str(log.relative_to(REPO)),
    })
    rec.update(parse_metrics(output))
    return rec


def run_key(args, cfg, row, rep, inst_limit):
    # ELF-Hash im Schluessel: nach einem Neubau (andere Skalierung) gilt ein
    # alter Lauf nicht als erledigt und wird nicht mit dem neuen vermischt.
    lim = f"__L{inst_limit}" if inst_limit else ""
    return f"{args.path}__{cfg}__{row['id']}__{row['elf_sha256'][:12]}{lim}__r{rep}"


#----------------------------------------------------------------------------
# Ergebnisdatei (gemerged, nie ueberschrieben)
#----------------------------------------------------------------------------

def out_dir(args):
    name = args.mode + (f"-{args.tag}" if args.tag else "")
    return RESULTS / args.path / name


def load_results(path):
    if not path.exists():
        return {}
    with path.open() as f:
        return {r["run_key"]: r for r in csv.DictReader(f)}


class ResultWriter:
    """Haengt Zeilen sofort an, damit ein Abbruch nichts verliert.
    Fehlgeschlagene Laeufe werden bei Wiederholung ersetzt (rewrite am Ende)."""

    def __init__(self, path):
        self.path = path
        self.lock = threading.Lock()
        new = not path.exists()
        self.f = path.open("a", newline="")
        self.w = csv.DictWriter(self.f, fieldnames=FIELDS)
        if new:
            self.w.writeheader()
            self.f.flush()

    def add(self, rec):
        with self.lock:
            self.w.writerow(rec)
            self.f.flush()

    def close(self):
        self.f.close()
        # Duplikate (wiederholte Laeufe) aufloesen: letzter Eintrag gewinnt.
        rows = load_results(self.path)
        tmp = self.path.with_suffix(".tmp")
        with tmp.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=FIELDS)
            w.writeheader()
            for r in rows.values():
                w.writerow({k: r.get(k, "") for k in FIELDS})
        tmp.replace(self.path)


def write_env(args, sims, odir):
    def cmd(c):
        try:
            return subprocess.run(c, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                  universal_newlines=True, cwd=REPO).stdout.strip()
        except OSError:
            return ""
    cpu = ""
    try:
        for line in Path("/proc/cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                cpu = line.split(":", 1)[1].strip()
                break
    except OSError:
        pass
    env = {
        "started": datetime.datetime.now().isoformat(timespec="seconds"),
        "argv": sys.argv,
        "host": socket.gethostname(),
        "kernel": platform.release(),
        "cpu": cpu,
        "nproc": os.cpu_count(),
        "repo_commit": cmd(["git", "rev-parse", "HEAD"]),
        "repo_dirty": bool(cmd(["git", "status", "--porcelain"])),
        "manifest_sha256": sha256_file(MANIFEST),
        "sims": {k: {"desc": v[0], "id": v[1]} for k, v in sims.items()},
        "load_before": os.getloadavg(),
    }
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    (odir / f"env-{stamp}.json").write_text(json.dumps(env, indent=2) + "\n")


#----------------------------------------------------------------------------
# Kommandos
#----------------------------------------------------------------------------

def build_jobs(args, selected):
    configs = args.config or MODE_CONFIGS[args.mode]
    reps = 1 if args.mode in ("count", "negctl") else args.reps
    limits = [None]
    if args.mode == "twopoint":
        if not args.inst_limit:
            sys.exit("--mode twopoint braucht --inst-limit N (gemessen werden N und 2N)")
        limits = [args.inst_limit, 2 * args.inst_limit]
    jobs = []
    for cfg, row in cells(selected, configs):
        for rep in range(1, reps + 1):
            for lim in limits:
                jobs.append([cfg, row, rep, lim])
    # Verschraenkte, randomisierte Reihenfolge (messplan.md §9.2)
    random.Random(args.seed).shuffle(jobs)
    return [tuple(j) + (i,) for i, j in enumerate(jobs)]


def estimate(args, jobs):
    """Grobe Laufzeitschaetzung aus vorhandenen count-Ergebnissen."""
    # Instruktionszahlen sind pfadunabhaengig (Gast-minstret); fehlen sie fuer
    # diesen Pfad, tun es die von iss.
    counts = load_results(RESULTS / args.path / "count" / "results.csv") \
        or load_results(RESULTS / "iss" / "count" / "results.csv")
    instr = {}
    for r in counts.values():
        if r["status"] == "ok" and r["total_instret"]:
            instr[r["elf_id"]] = int(r["total_instret"])
    total, unknown = 0.0, 0
    for cfg, row, rep, lim, _ in jobs:
        n = lim or instr.get(row["id"])
        if n is None:
            unknown += 1
            continue
        total += n / (args.assume_mips * 1e6) + args.startup_s
    return total, unknown


def cmd_run(args):
    manifest = load_manifest()
    selected = select_elfs(manifest, args)
    if not selected:
        sys.exit("Keine ELFs passen zur Auswahl.")
    if args.mode == "twopoint" and args.path not in HTIF_PATHS:
        sys.exit("twopoint gibt es nur auf den Pfaden iss/csim (--inst-limit)")

    jobs = build_jobs(args, selected)
    odir = out_dir(args)
    res_path = odir / "results.csv"
    done = {k for k, r in load_results(res_path).items()
            if r["status"] in ("ok", "limit") or (args.mode == "negctl" and r["status"] == "trap")}
    todo = [j for j in jobs if run_key(args, j[0], j[1], j[2], j[3]) not in done]

    secs, unknown = estimate(args, todo)
    print(f"Pfad {args.path}, Modus {args.mode}, Tag '{args.tag}', Seed {args.seed}")
    print(f"  {len(jobs)} Laeufe geplant, {len(jobs) - len(todo)} schon erledigt, {len(todo)} offen")
    print(f"  Schaetzung: {secs / 3600:.1f} h bei {args.assume_mips} MIPS"
          + (f" ({unknown} Laeufe ohne count-Daten nicht eingerechnet)" if unknown else ""))
    if args.dry_run:
        for cfg, row, rep, lim, idx in todo[:40]:
            print(f"  {idx:5d}  {cfg}  {row['id']}  r{rep}" + (f"  L{lim}" if lim else ""))
        if len(todo) > 40:
            print(f"  ... {len(todo) - 40} weitere")
        return
    if not todo:
        return

    sims = resolve_sims(args)
    odir.mkdir(parents=True, exist_ok=True)
    log_dir = odir / "logs"
    log_dir.mkdir(exist_ok=True)
    write_env(args, sims, odir)

    if args.mode != "count" and not args.no_prewarm:
        prewarm(args, sims, todo, log_dir)

    writer = ResultWriter(res_path)
    started = time.time()
    n = 0

    def report(rec):
        nonlocal n
        n += 1
        writer.add(rec)
        extra = ""
        if rec["host_wall_s"]:
            extra = f" {float(rec['host_wall_s']):8.2f}s"
        if rec["mcause"]:
            extra += f" mcause={rec['mcause']}"
        print(f"[{n}/{len(todo)}] {rec['config']} {rec['elf_id']} r{rec['rep']}"
              f" {rec['status']}{extra}", flush=True)

    try:
        if args.mode == "count":
            with concurrent.futures.ThreadPoolExecutor(max_workers=args.jobs) as ex:
                futs = [ex.submit(run_one, args, j, sims, log_dir) for j in todo]
                for fut in concurrent.futures.as_completed(futs):
                    report(fut.result())
        else:
            for j in todo:
                report(run_one(args, j, sims, log_dir))
    finally:
        writer.close()
    print(f"fertig in {(time.time() - started) / 60:.1f} min -> {res_path.relative_to(REPO)}")


def prewarm(args, sims, todo, log_dir):
    """Je Simulator ein verworfener Lauf, damit Page Cache und Image-Layer warm
    sind, bevor die erste gezaehlte Messung startet (§9.2). Nicht in der CSV."""
    seen = set()
    for job in todo:
        sim = CONFIGS[job[0]][0]
        if sim in seen:
            continue
        seen.add(sim)
        print(f"Vorwaermlauf: {sim} ({job[1]['id']})", flush=True)
        rec = run_one(args, job[:4] + ("prewarm",), sims, log_dir)
        Path(REPO / rec["log"]).rename(log_dir / f"prewarm__{sim}.log")


def cmd_summary(args):
    rows = list(load_results(out_dir(args) / "results.csv").values())
    if not rows:
        sys.exit("Keine Ergebnisse.")
    status = {}
    for r in rows:
        status[r["status"]] = status.get(r["status"], 0) + 1
    print("Status:", ", ".join(f"{k}={v}" for k, v in sorted(status.items())))

    metric = "region_instret" if args.mode == "count" else "host_wall_s"
    groups = {}
    for r in rows:
        if r["status"] != "ok" or not r[metric]:
            continue
        k = (r["suite"], r["workload"], r["params"], r["opt"])
        groups.setdefault(k, {}).setdefault(r["config"], []).append(float(r[metric]))

    print(f"\nMedian {metric}, normiert auf A (B/A = Einbindung, C/A = gesamt)")
    print(f"{'Workload':42s} {'opt':3s} {'n':>3s} {'A':>12s} {'A2/A':>7s} {'B/A':>7s} {'C/A':>7s} {'C/B':>7s}"
          f" {'Bo/A':>7s} {'Co/A':>7s} {'Co/Bo':>7s}")
    for k in sorted(groups):
        g = groups[k]
        if "A" not in g:
            continue
        a = statistics.median(g["A"])
        med = {c: statistics.median(v) for c, v in g.items()}
        ratio = lambda x, y: f"{med[x] / med[y]:7.3f}" if x in med and y in med and med[y] else "      -"
        name = k[1] + (f"[{k[2]}]" if k[2] else "")
        n = min(len(v) for v in g.values())
        print(f"{name:42.42s} {k[3]:3s} {n:3d} {a:12.4g} {ratio('A2', 'A')} {ratio('B', 'A')} {ratio('C', 'A')} {ratio('C', 'B')}"
              f" {ratio('Bo', 'A')} {ratio('Co', 'A')} {ratio('Co', 'Bo')}")

    # Traps sind Befunde, keine verworfenen Messungen (messplan.md §5)
    traps = sorted({(r["config"], r["elf_id"], r["mcause"]) for r in rows if r["status"] == "trap"})
    if traps:
        print("\nBefunde (Traps, einzeln einordnen: False Positive oder echter Lesezugriff):")
        for cfg, elf, mc in traps:
            print(f"  {cfg}  {elf}  mcause={mc}")
    fails = sorted({(r["config"], r["elf_id"], r["status"]) for r in rows
                    if r["status"] not in ("ok", "trap", "limit")})
    if fails:
        print("\nNicht auswertbar (fail = Selbstpruefung des Benchmarks fehlgeschlagen):")
        for cfg, elf, st in fails:
            print(f"  {cfg}  {elf}  {st}")

    if args.mode == "count":
        # Gegenprobe: A und B fuehren dasselbe ELF aus -> identische Zaehlung
        bad = [k for k, g in groups.items() if "A" in g and "B" in g and g["A"] != g["B"]]
        print(f"\nGegenprobe A == B (identisches ELF): "
              + ("OK" if not bad else f"{len(bad)} Abweichungen: {bad[:5]}"))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--path", choices=("iss", "csim", "vp"), required=True)
        p.add_argument("--mode", choices=tuple(MODE_CONFIGS), required=True)
        p.add_argument("--tag", default="", help="freier Name fuer eine Messreihe (z.B. precheck, D)")

    run = sub.add_parser("run", help="Messreihe ausfuehren (fortsetzbar)")
    common(run)
    run.add_argument("--suite", action="append", help="micro, riscv_tests, embench")
    run.add_argument("--workload", action="append")
    run.add_argument("--opt", action="append", choices=("O0", "O2"))
    run.add_argument("--config", action="append", choices=tuple(CONFIGS))
    run.add_argument("--match", help="Regex auf die ELF-ID")
    run.add_argument("--reps", type=int, default=5)
    run.add_argument("--seed", type=int, default=20261003)
    run.add_argument("--inst-limit", type=int, help="twopoint: N (gemessen N und 2N)")
    run.add_argument("--jobs", type=int, default=16, help="Parallelitaet im count-Modus")
    run.add_argument("--cpus", default=None,
                     help="--cpuset-cpus fuer timing (Default iss: 2, vp: 2,3)")
    run.add_argument("--timeout", type=float, default=3600.0)
    run.add_argument("--dry-run", action="store_true", help="nur Plan und Schaetzung")
    run.add_argument("--no-prewarm", action="store_true")
    run.add_argument("--assume-mips", type=float, default=2.2,
                     help="fuer die Schaetzung; 2.2 = gemessen Debug-VP, 10us")
    run.add_argument("--startup-s", type=float, default=1.0,
                     help="fuer die Schaetzung: fester Anteil pro Lauf")
    run.add_argument("--iss-with", default="pydrofoil-riscv-with-poison")
    run.add_argument("--iss-without", default="pydrofoil-riscv-without-poison")
    run.add_argument("--csim-with", default="riscv_sim_RV64_O3_with_poison")
    run.add_argument("--csim-without", default="riscv_sim_RV64_O3_without_poison")
    run.add_argument("--iss-opt", default="pydrofoil-riscv-with-poison-opt")
    run.add_argument("--csim-opt", default="riscv_sim_RV64_with_poison_opt")
    run.add_argument("--vp-opt-image", default="vcml-pydrofoil:release-poison-opt")
    run.add_argument("--ram-size", type=int, help="iss/csim: --ram-size in MiB (Default: Simulator-Default)")
    run.add_argument("--vp-with-image", default="vcml-pydrofoil:release-poison")
    run.add_argument("--vp-without-image", default="vcml-pydrofoil:release-nopoison")
    run.add_argument("--quantum", default="10us")
    run.add_argument("--vp-duration", default="100s",
                     help="nur Haengeschutz, simulierte Zeit (1 GHz)")
    run.add_argument("--vp-ram-mib", type=int, default=16)

    summ = sub.add_parser("summary", help="kurze Uebersicht einer Messreihe")
    common(summ)

    args = ap.parse_args()
    if args.cmd == "run":
        if args.cpus is None:
            # Der VP hat zwei aktive Threads (SystemC + Python-Worker,
            # core.cpp Task-Queue); auf einem Kern wuerden sie sich
            # gegenseitig verdraengen.
            args.cpus = "2,3" if args.path == "vp" else "2"
        cmd_run(args)
    elif args.cmd == "summary":
        cmd_summary(args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
