#!/usr/bin/env python3
"""Leitet aus einem Kalibrierlauf die Skalierung pro Workload ab (messplan.md §9.1).

Eingabe: results/bench/<path>/count-<tag>/results.csv. Der Faktor, mit dem
jedes ELF gebaut wurde, steht dort pro Zeile (gsf bzw. micro_scale). Damit
laesst sich das Skript auch auf einen spaeteren Lauf mit bereits skalierten
ELFs anwenden und schaerft die Faktoren nach (wichtig fuer Workloads, deren
Kalibrierlauf nur Bruchteile einer Sekunde dauerte und deshalb von t0
dominiert war).

Modell je (Workload, opt, config): t(s) = t0 + k * s, mit t0 = feste Startzeit
des Simulators und s = Skalierungsfaktor. k ergibt sich aus dem Kalibrierlauf.

Regel (vorab festgelegt, vor Ansicht der Ergebnisse):
  Je opt getrennt:
  1. s so klein wie moeglich, dass die schnellste Konfiguration (A)
     mindestens --target-s dauert.
  2. Kein Einzellauf (A, B, C) darf --cap-s ueberschreiten.
  3. Bei Konflikt gewinnt (2); der Workload wird als "kurz" markiert und in der
     Auswertung ueber C - B statt ueber das Verhaeltnis zu A betrachtet.
  Laeufe, die im Kalibrierlauf in den Timeout liefen, werden ueber eine
  Untergrenze von k behandelt (k >= Timeout / s_kalib).

riscv-tests sind nicht skalierbar und werden nur berichtet.

Ausgabe: Tabelle, tools/bench/scales.tsv (fuer SCALE_FILE, Schluessel
<workload>__<opt>; vorhandene Eintraege anderer opts bleiben erhalten) und
Zeitbudget fuer eine timing-Reihe (A, A2, B, C x --reps) je opt.
"""

import argparse
import csv
import math
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--path", default="iss")
    ap.add_argument("--tag", default="calib")
    ap.add_argument("--calib-scale", type=int, default=None,
                    help="Faktor erzwingen statt gsf/micro_scale aus results.csv")
    ap.add_argument("--target-s", type=float, default=5.0)
    ap.add_argument("--cap-s", type=float, default=120.0)
    ap.add_argument("--t0", type=float, default=0.1, help="feste Startzeit [s]")
    ap.add_argument("--timeout", type=float, default=300.0, help="Timeout des Kalibrierlaufs")
    ap.add_argument("--reps", type=int, default=5)
    ap.add_argument("--opts", default="O0,O2", help="fuer das Budget")
    ap.add_argument("--overhead-s", type=float, default=1.5,
                    help="Container-Start u. a. pro Lauf, fuer das Budget")
    ap.add_argument("--out", default="tools/bench/scales.tsv")
    args = ap.parse_args()

    mode_dir = f"count-{args.tag}" if args.tag else "count"
    res = REPO / "results" / "bench" / args.path / mode_dir / "results.csv"
    rows = list(csv.DictReader(open(res)))

    # k [s pro Skalierungseinheit], lower = nur Untergrenze (Timeout)
    # riscv_tests: k bezieht sich auf "Faktor 1" (nicht skalierbar)
    k = {}
    lower = set()
    status = {}
    used = {}
    for r in rows:
        key = (r["suite"], r["workload"], r["params"], r["opt"], r["config"])
        status[key] = r["status"]
        col = {"embench": "gsf", "micro": "micro_scale"}.get(r["suite"])
        if args.calib_scale is not None and col:
            sc = args.calib_scale
        elif col:
            sc = int(r[col])
        else:
            sc = 1
        used[key[:3] + (key[3],)] = sc
        if r["status"] == "timeout":
            k[key] = args.timeout / sc
            lower.add(key)
        elif r["host_wall_s"]:
            t = float(r["host_wall_s"])
            k[key] = max(t - args.t0, 0.001) / sc

    workloads = sorted({key[:3] for key in k})
    opts = args.opts.split(",")
    configs = ("A", "B", "C")

    # Faktor pro (Workload, opt): -O0 ist um ein Vielfaches langsamer, ein
    # gemeinsamer Faktor wuerde -O2 unter das Ziel druecken.
    out = {}
    hdr = [f"# erzeugt von tools/bench/calibrate.py; Regel s. Docstring",
           f"# Ziel A >= {args.target_s} s, Einzellauf <= {args.cap_s} s, je opt"]
    outp = REPO / args.out
    if outp.exists():  # Eintraege anderer opts/Workloads behalten
        for line in outp.read_text().splitlines():
            if line and not line.startswith("#"):
                key, val = line.split("\t")
                out[key] = val
    total_h = 0.0
    for o in opts:
        budget = 0.0
        n_runs = 0
        print(f"\n== -{o}")
        print(f"{'Workload':38s} {'alt>neu':12s} {'A':>7s} {'B':>7s} {'C':>7s}  Hinweis")
        for wl in workloads:
            suite, name, params = wl
            label = f"{suite}__{name}" + (f"__{params}" if params else "")
            kA = k.get(wl + (o, "A"))
            if suite == "riscv_tests" or kA is None:
                s = used.get(wl + (o,), 1) if suite != "riscv_tests" else 1
                note = "nicht skalierbar" if suite == "riscv_tests" else "keine A-Daten"
            else:
                s = max(1, math.ceil((args.target_s - args.t0) / kA))
                note = ""
            kmax = max(k.get(wl + (o, c), 0.0) for c in configs)
            if suite != "riscv_tests" and args.t0 + kmax * s > args.cap_s:
                s = max(1, math.floor((args.cap_s - args.t0) / kmax))
                note = "kurz (Deckel)"
            if any(wl + (o, c) in lower for c in configs):
                note = (note + ", " if note else "") + "Timeout im Kalib.-Lauf (Untergrenze)"
            if any(status.get(wl + (o, c)) == "trap" for c in configs):
                note = (note + ", " if note else "") + "Trap in C"

            times = {c: (args.t0 + k[wl + (o, c)] * s) if wl + (o, c) in k else float("nan")
                     for c in configs}
            for c in ("A", "A2", "B", "C"):
                v = times["A" if c == "A2" else c]
                if not math.isnan(v):
                    budget += args.reps * (v + args.overhead_s)
                    n_runs += args.reps
            print(f"{label:38.38s} {used.get(wl + (o,), 0):5d}>{s:<6d} {times['A']:7.1f} {times['B']:7.1f} "
                  f"{times['C']:7.1f}  {note}")
            if suite != "riscv_tests":
                out[f"{label}__{o}"] = str(s)
        print(f"Budget timing -{o} ({args.path}, A/A2/B/C x {args.reps}): "
              f"{n_runs} Laeufe, {budget / 3600:.1f} h")
        total_h += budget / 3600

    outp.write_text("\n".join(hdr + [f"{key}\t{val}" for key, val in sorted(out.items())]) + "\n")
    print(f"\n{args.out} geschrieben ({len(out)} Eintraege); Budget gesamt {total_h:.1f} h")


if __name__ == "__main__":
    main()
