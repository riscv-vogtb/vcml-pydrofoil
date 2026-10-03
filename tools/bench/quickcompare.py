#!/usr/bin/env python3
"""Schnellvergleich Simulator-Varianten auf wenigen Workloads (messplan.md §8.4a/b).

Kein Teil der Messreihe: je Zelle ein Lauf, bis zu --jobs parallel, jeder auf
einem eigenen physischen Kern gepinnt. Gedacht als Plausibilitaetsprobe vor
einer grossen Messreihe (z. B. "wirkt die Optimierung?"); die Messreihe selbst
sollte dafuer pausiert sein, sonst stoeren sich beide.

    quickcompare.py iss                      # Pydrofoil, volle Laeufe
    quickcompare.py csim --inst-limit 2e7    # C-Emulator (sonst ~0,4 h/Lauf)

Konfigurationen: A (ohne Poison), B (mit Poison), Bo (mit Poison, optimiert)
auf plain-ELFs; C, Co auf poison-ELFs. Simulatoren wie bench.py
(--iss-with usw.). Ausgabe: Tabelle und Logs unter
results/bench/quickcompare/<path>-<zeitstempel>/.
"""

import argparse
import concurrent.futures as cf
import datetime
import json
import queue
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "tools" / "bench"))
import bench  # noqa: E402

PLAIN = ["micro__baseline_alu", "micro__load_dense__WIDTH1", "micro__load_dense__WIDTH8",
         "micro__store_dense__WIDTH1", "micro__store_dense__WIDTH8", "embench__crc32",
         "embench__md5sum", "embench__statemate", "embench__wikisort", "embench__nettle-aes"]
POISON = ["micro__frame_size__FRAME256", "micro__frame_size__FRAME4096",
          "micro__recurse__DEPTH64", "micro__call_rate__WORK4", "embench__statemate"]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("path", choices=("iss", "csim"))
    ap.add_argument("--opt", default="O2")
    ap.add_argument("--inst-limit", type=float)
    ap.add_argument("--jobs", type=int, default=10)
    ap.add_argument("--first-cpu", type=int, default=2,
                    help="Kerne first-cpu .. first-cpu+jobs-1 (physische Kerne, SMT-Geschwister meiden)")
    ap.add_argument("--timeout", type=int, default=1800)
    ap.add_argument("--iss-with", default="pydrofoil-riscv-with-poison")
    ap.add_argument("--iss-without", default="pydrofoil-riscv-without-poison")
    ap.add_argument("--iss-opt", default="pydrofoil-riscv-with-poison-opt")
    ap.add_argument("--csim-with", default="riscv_sim_RV64_O3_with_poison")
    ap.add_argument("--csim-without", default="riscv_sim_RV64_O3_without_poison")
    ap.add_argument("--csim-opt", default="riscv_sim_RV64_with_poison_opt")
    args = ap.parse_args()

    p = args.path
    sims = {"A": getattr(args, f"{p}_without"), "B": getattr(args, f"{p}_with"),
            "Bo": getattr(args, f"{p}_opt")}
    sims["C"], sims["Co"] = sims["B"], sims["Bo"]
    for s in set(sims.values()):
        if not (REPO / s).exists():
            sys.exit(f"Simulator fehlt: {s}")
    limit = str(int(args.inst_limit)) if args.inst_limit else None

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = REPO / "results" / "bench" / "quickcompare" / f"{p}-{stamp}"
    (out / "logs").mkdir(parents=True)
    (out / "env.json").write_text(json.dumps({
        "argv": sys.argv, "inst_limit": limit,
        "sims": {c: {"path": s, "sha256": bench.sha256_file(REPO / s)} for c, s in sims.items()},
        "manifest_sha256": bench.sha256_file(bench.MANIFEST),
    }, indent=2))

    jobs = [(c, w, "plain") for w in PLAIN for c in ("A", "B", "Bo")]
    jobs += [(c, w, "poison") for w in POISON for c in ("C", "Co")]
    cpus = queue.Queue()
    for c in range(args.first_cpu, args.first_cpu + args.jobs):
        cpus.put(c)

    def run(job):
        cfg, w, var = job
        elf = f"results/bench/elf/htif/{w}__{args.opt}__{var}.elf"
        cpu = cpus.get()
        try:
            cmd = bench.base_podman(None, str(cpu)) + [
                "-w", "/w", "--entrypoint", bench.GTIME_IN, bench.ISS_IMAGE,
                "-f", bench.GTIME_FMT, f"./{sims[cfg]}"]
            if p == "csim":
                cmd.append("--no-trace")
            if limit:
                cmd += ["--inst-limit", limit]
            res = subprocess.run(cmd + [elf], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 text=True, timeout=args.timeout).stdout
        except subprocess.TimeoutExpired:
            res = "TIMEOUT"
        finally:
            cpus.put(cpu)
        (out / "logs" / f"{cfg}__{w}__{var}.log").write_text(" ".join(cmd + [elf]) + "\n" + res)
        t = re.search(r"wall=([\d.]+)", res)
        i = re.search(r"region_instret=(\d+)", res)
        st = ("timeout" if res == "TIMEOUT" else "trap" if "BENCH-TRAP" in res
              else "fail" if "FAILURE" in res else "ok")
        return job, (float(t.group(1)) if t else None, int(i.group(1)) if i else None, st)

    res = {}
    with cf.ThreadPoolExecutor(args.jobs) as ex:
        for (cfg, w, _), r in ex.map(run, jobs):
            res[(cfg, w)] = r

    f = lambda v: f"{v:7.1f}" if v is not None else "      -"
    q = lambda x, y: f"{x / y:6.2f}" if x and y else "     -"
    lines = [f"{'Workload':30s} {'A':>7s} {'B':>7s} {'Bo':>7s} {'B/A':>6s} {'Bo/A':>6s} {'B/Bo':>6s}  instret gleich, Status"]
    for w in PLAIN:
        a, b, bo = res[("A", w)], res[("B", w)], res[("Bo", w)]
        same = "-" if limit else a[1] == b[1] == bo[1]
        lines.append(f"{w:30s} {f(a[0])} {f(b[0])} {f(bo[0])} {q(b[0], a[0])} {q(bo[0], a[0])} "
                     f"{q(b[0], bo[0])}  {same} {a[2]}/{b[2]}/{bo[2]}")
    lines.append(f"\n{'Workload (poison-ELF)':30s} {'C':>7s} {'Co':>7s} {'C/Co':>6s}  instret gleich, Status")
    for w in POISON:
        c, co = res[("C", w)], res[("Co", w)]
        same = "-" if limit else c[1] == co[1]
        lines.append(f"{w:30s} {f(c[0])} {f(co[0])} {q(c[0], co[0])}  {same} {c[2]}/{co[2]}")
    text = "\n".join(lines)
    (out / "summary.txt").write_text(text + "\n")
    print(text)
    print(f"\n-> {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
