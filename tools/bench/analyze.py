#!/usr/bin/env python3
"""Auswertung aller Messreihen -> thesis/auswertung.md (messplan.md §13).

Liest nur die Ergebnisdateien unter results/bench/ (und das Manifest), braucht
also weder Simulatoren noch Container; laeuft auch auf einer Kopie der
Ergebnisse mit derselben Verzeichnisstruktur (z. B. der Sicherung unter
/net/heap/vogtb/bench-results/...). Nur Standardbibliothek.

    python3 tools/bench/analyze.py [--out thesis/auswertung.md]

Kennzahlen (Definitionen auch im erzeugten Dokument):
  T         Median der Wandzeit des Simulatorprozesses ueber die Wiederholungen
  X/A       T_X / T_A je Workload; ueber eine Suite geometrisches Mittel
  I         Instruktionen aus minstret (deterministisch, count-Modus)
  t         Zeit pro Instruktion = T / I_total
  csim      t = (T(2N) - T(N)) / N je Wiederholung, Median (Zwei-Punkt)
"""

import argparse
import csv
import datetime
import math
import statistics
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RES = REPO / "results" / "bench"

EMB = "embench"
MIC = "micro"
RT = "riscv_tests"


# --------------------------------------------------------------------------
# Hilfen

def load(rel):
    p = RES / rel / "results.csv"
    return list(csv.DictReader(open(p))) if p.exists() else []


def label(r):
    return r["workload"] + (f"[{r['params']}]" if r["params"] else "")


def num(x, nd=2, pct=False, signed=False):
    """Deutsche Zahl; None/nan -> '–'."""
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return "–"
    if pct:
        x *= 100
    s = f"{x:+.{nd}f}" if signed else f"{x:.{nd}f}"
    s = s.replace(".", ",")
    return s + (" %" if pct else "")


def big(x):
    """Grosse Zahl mit Zehnerpotenz, z. B. 1,8·10⁹."""
    if x is None:
        return "–"
    e = int(math.floor(math.log10(abs(x)))) if x else 0
    sup = str(e).translate(str.maketrans("-0123456789", "⁻⁰¹²³⁴⁵⁶⁷⁸⁹"))
    return f"{num(x / 10 ** e, 1)}·10{sup}"


def gmean(xs):
    xs = [x for x in xs if x and x > 0 and not math.isnan(x)]
    return math.exp(sum(map(math.log, xs)) / len(xs)) if xs else float("nan")


def ratio(a, b):
    return a / b if a and b else float("nan")


def spearman(xs, ys):
    def rank(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        r = [0] * len(v)
        for k, i in enumerate(o):
            r[i] = k
        return r
    rx, ry = rank(xs), rank(ys)
    n = len(xs)
    return 1 - 6 * sum((a - b) ** 2 for a, b in zip(rx, ry)) / (n * (n * n - 1))


def count_fmt(x):
    return "0" if not x else (f"{x:.0f}" if x < 1000 else big(x))


def table(head, rows, align=None):
    align = align or ["l"] + ["r"] * (len(head) - 1)
    sep = ["---:" if a == "r" else "---" for a in align]
    out = ["| " + " | ".join(head) + " |", "| " + " | ".join(sep) + " |"]
    out += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    return "\n".join(out)


def cells(rows, field, key=lambda r: (r["suite"], label(r), r["opt"], r["config"]), ok=("ok",)):
    """key -> Liste der Werte (nur Laeufe mit Status in ok)."""
    d = defaultdict(list)
    for r in rows:
        if r["status"] in ok and r[field]:
            d[key(r)].append(float(r[field]))
    return d


def med(d, k):
    return statistics.median(d[k]) if d.get(k) else float("nan")


def spread(v):
    """(max - min) / median."""
    return (max(v) - min(v)) / statistics.median(v) if v else float("nan")


# --------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="thesis/auswertung.md")
    args = ap.parse_args()

    tim = load("iss/timing")
    cnt = load("iss/count")
    neg = load("iss/negctl")
    tp = load("csim/twopoint")
    vpt = load("vp/timing")
    vpc = load("vp/count")
    man = {r["id"]: r for r in csv.DictReader(open(RES / "elf" / "manifest.tsv"), delimiter="\t")
           if r["platform"] == "htif"}

    T = cells(tim, "host_wall_s")
    RSS = cells(tim, "max_rss_kb")
    I = {(r["suite"], label(r), r["opt"], r["config"]): r for r in cnt if r["status"] in ("ok", "trap")}

    wl = defaultdict(set)  # (suite, opt) -> Workload-Labels
    for (s, w, o, c) in T:
        wl[(s, o)].add(w)

    def Tm(s, w, o, c):
        return med(T, (s, w, o, c))

    def Iv(s, w, o, c, f="total_instret"):
        r = I.get((s, w, o, c))
        return int(r[f]) if r and r[f] else None

    md = []
    w = md.append
    now = datetime.datetime.now().strftime("%d.%m.%Y %H:%M")
    w("# Auswertung der Performance-Messungen (POISON-Erweiterung)\n")
    w(f"Erzeugt von `tools/bench/analyze.py` am {now} aus `results/bench/` "
      "(Methodik: `thesis/messmethodik.md`, Plan und Befunde: `thesis/messplan.md`). "
      "Nicht von Hand bearbeiten, sondern das Skript neu ausführen.\n")
    w("**Lesart.** A = Simulator ohne Poison; B/C = mit Poison, byteweise "
      "Shadow-Helfer (erste Implementierung); Bo/Co = mit Poison, optimierte Helfer "
      "(ein Shadow-Zugriff pro Load/Store, 8-Byte-Blöcke für `mpoison`). B/Bo führen "
      "das unveränderte Programm aus (**Kosten der Einbindung**), C/Co das "
      "instrumentierte (zusätzlich **Kosten der Nutzung**). Verhältnisse X/A beziehen "
      "sich auf den Median der Wandzeit je Workload (5 Wiederholungen auf Pydrofoil, "
      "3 auf VP und C-Emulator); Mittel über eine Suite = geometrisches Mittel. "
      "1,00 = keine Mehrkosten.\n")

    # ------------------------------------------------------------------
    # Kennwerte vorab berechnen
    def suite_gm(o, cfg, s=EMB):
        return gmean([ratio(Tm(s, x, o, cfg), Tm(s, x, o, "A")) for x in wl[(s, o)]])

    gm = {(o, c): suite_gm(o, c) for o in ("O2", "O0") for c in ("A2", "B", "C", "Bo", "Co")}
    emb2 = sorted(wl[(EMB, "O2")])
    emb0 = sorted(wl[(EMB, "O0")])

    def rng(o, c, ws, s=EMB):
        v = [ratio(Tm(s, x, o, c), Tm(s, x, o, "A")) for x in ws]
        v = [x for x in v if not math.isnan(x)]
        return (min(v), max(v)) if v else (float("nan"),) * 2

    # csim: Zeit pro Instruktion je (Workload, Konfig.)
    tpd = defaultdict(dict)
    for r in tp:
        if r["host_wall_s"]:
            tpd[(label(r), r["config"], r["rep"])][int(r["inst_limit"])] = float(r["host_wall_s"])
    cs_diff = defaultdict(list)
    cs_full = defaultdict(list)
    for (x, c, _), v in tpd.items():
        if len(v) == 2:
            n = min(v)
            cs_diff[(x, c)].append((v[2 * n] - v[n]) / n)
            cs_full[(x, c)].append(v[2 * n] / (2 * n))
    cs_w = sorted({x for x, _ in cs_diff})

    def cs(x, c, d=cs_diff):
        return statistics.median(d[(x, c)]) if d.get((x, c)) else float("nan")

    cs_gm = {c: gmean([ratio(cs(x, c), cs(x, "A")) for x in cs_w]) for c in ("B", "C", "Bo", "Co")}

    # VP
    VT = cells(vpt, "host_wall_s")
    VM = cells(vpt, "vp_mips")
    VR = cells(vpt, "max_rss_kb")
    vp_w = sorted({k[1] for k in VT})
    vp_s = {x: next(k[0] for k in VT if k[1] == x) for x in vp_w}

    def Vt(x, c):
        return med(VT, (vp_s[x], x, "O2", c))

    # ------------------------------------------------------------------
    w("## 1. Kennwerte auf einen Blick\n")
    rows = [
        ["Pydrofoil, Embench `-O2` (19)", num(gm[("O2", "B")]), num(gm[("O2", "C")]),
         num(gm[("O2", "Bo")]), num(gm[("O2", "Co")])],
        ["Pydrofoil, Embench `-O0` (19)", "–", "–", num(gm[("O0", "Bo")]), num(gm[("O0", "Co")])],
        ["C-Emulator, Embench `-O2` (19), pro Instruktion", num(cs_gm["B"]), num(cs_gm["C"]),
         num(cs_gm["Bo"]), num(cs_gm["Co"])],
        [f"VP, Auswahl `-O2` ({len(vp_w)})",
         num(gmean([ratio(Vt(x, "B"), Vt(x, "A")) for x in vp_w])),
         num(gmean([ratio(Vt(x, "C"), Vt(x, "A")) for x in vp_w])),
         num(gmean([ratio(Vt(x, "Bo"), Vt(x, "A")) for x in vp_w])),
         num(gmean([ratio(Vt(x, "Co"), Vt(x, "A")) for x in vp_w]))],
    ]
    w("Geometrisches Mittel der Laufzeit relativ zu A (Spalten B/A … Co/A):\n")
    w(table(["Simulator, Suite", "B/A", "C/A", "Bo/A", "Co/A"], rows) + "\n")
    lo, hi = rng("O2", "B", emb2)
    lo2, hi2 = rng("O2", "Bo", emb2)
    mips = {x: ratio(Iv(EMB, x, "O2", "A"), Tm(EMB, x, "O2", "A")) / 1e6 for x in emb2}
    ba = {x: ratio(Tm(EMB, x, "O2", "B"), Tm(EMB, x, "O2", "A")) for x in emb2}
    rho = spearman([mips[x] for x in emb2], [ba[x] for x in emb2])
    cb0 = [ratio(Tm(EMB, x, "O0", "Co"), Tm(EMB, x, "O0", "Bo")) for x in emb0]
    w(f"- **Einbindung:** B/A über Embench `-O2` {num(lo)}–{num(hi)}, mit optimierten "
      f"Helfern Bo/A {num(lo2)}–{num(hi2)}; die Optimierung senkt die Laufzeit mit "
      f"Poison im Mittel um den Faktor {num(gm[('O2', 'B')] / gm[('O2', 'Bo')])} (B/Bo).")
    w(f"- **Nutzung:** reine Nutzungskosten Co/Bo über Embench im Mittel "
      f"{num(gm[('O2', 'Co')] / gm[('O2', 'Bo')])} (`-O2`) bzw. "
      f"{num(gm[('O0', 'Co')] / gm[('O0', 'Bo')])} (`-O0`, Spanne "
      f"{num(min(cb0))}–{num(max(cb0))}). Auch bei `-O0` werden nur "
      f"{num(gmean([ratio(Iv(EMB, x, 'O0', 'C'), Iv(EMB, x, 'O0', 'A')) for x in emb0]) - 1, 1, pct=True)} "
      "zusätzliche Instruktionen ausgeführt (Abschnitt 5); deutlich werden die "
      "Nutzungskosten nur bei vielen Aufrufen mit großen Frames (Mikrobenchmarks, "
      "Abschnitt 7.2). Werte unter 1 bei `-O0` zeigen, dass das instrumentierte Programm "
      "den JIT anders trifft (Code-Layout), nicht Rauschen (A2/A ≈ 1).")
    w(f"- **Grundgeschwindigkeit bestimmt die relativen Kosten:** Pydrofoil führt Embench "
      f"`-O2` mit {num(min(mips.values()), 0)}–{num(max(mips.values()), 0)} MIPS aus "
      f"(dauerhaft, nicht nur beim Anlauf); je schneller A, desto größer tendenziell "
      f"B/A (Rangkorrelation ρ = {num(rho)}, Abschnitt 3.1). Der C-Emulator (~0,4–0,5 MIPS) und der VP "
      "(~0,7–4 MIPS) zeigen dieselben Hooks mit viel kleineren Verhältnissen.")
    w(f"- **Rauschkontrolle** A2/A (geom. Mittel Embench): {num(gm[('O2', 'A2')], 3)} (`-O2`), "
      f"{num(gm[('O0', 'A2')], 3)} (`-O0`).\n")

    # ------------------------------------------------------------------
    w("## 2. Umfang und Status\n")
    rows = []
    for name, rs in [("Pydrofoil Zeitmessung (`iss/timing`)", tim), ("Pydrofoil Zählung (`iss/count`)", cnt),
                     ("Negativkontrolle (`iss/negctl`)", neg), ("C-Emulator Zwei-Punkt (`csim/twopoint`)", tp),
                     ("VP Zeitmessung (`vp/timing`)", vpt), ("VP Zählung (`vp/count`)", vpc)]:
        st = defaultdict(int)
        for r in rs:
            st[r["status"]] += 1
        rows.append([name, len(rs), ", ".join(f"{k} {v}" for k, v in sorted(st.items()))])
    w(table(["Messreihe", "Läufe", "Status"], rows, ["l", "r", "l"]) + "\n")
    traps = sorted({(r["config"], r["elf_id"], r["mcause"]) for r in tim + cnt if r["status"] == "trap"})
    w("Traps (alle erwartet, Fehlalarm durch Padding in `Rec`): " +
      ", ".join(f"{c} `{e}` (mcause={m})" for c, e, m in traps) + ".")
    n_ok = [r["elf_id"] for r in neg if r["status"] != "trap"]
    mc = {r["mcause"] for r in neg if r["status"] == "trap"}
    w(f"Negativkontrolle: {sum(r['status'] == 'trap' for r in neg)} von {len(neg)} mit "
      f"mcause={'/'.join(sorted(mc))}; ohne Trap nur Programme ohne `mpoison` "
      f"({', '.join('`' + x + '`' for x in n_ok)}).")
    # Gegenproben Instruktionszahl
    same_ab = same_cc = tot_ab = tot_cc = 0
    for (s, x, o, c), r in I.items():
        if c == "A":
            v = {Iv(s, x, o, k, "region_instret") for k in ("A", "B", "Bo")}
            tot_ab += 1
            same_ab += len(v) == 1
        if c == "C":
            v = {Iv(s, x, o, k, "region_instret") for k in ("C", "Co")}
            tot_cc += 1
            same_cc += len(v) == 1
    w(f"Gegenprobe Instruktionszahl: A = B = Bo in {same_ab}/{tot_ab} Zellen, "
      f"C = Co in {same_cc}/{tot_cc} Zellen (dhrystone C/Co trappt, zählt bis zum Trap).\n")

    # ------------------------------------------------------------------
    def emb_table(o, cfgs):
        rows = []
        for x in sorted(wl[(EMB, o)]):
            a = Tm(EMB, x, o, "A")
            sp = spread(T[(EMB, x, o, "A")])
            ia, ic = Iv(EMB, x, o, "A"), Iv(EMB, x, o, "C")
            row = [x, num(a, 1), num(sp, 1, pct=True), num(ratio(ia, a) / 1e6, 0)]
            row += [num(ratio(Tm(EMB, x, o, c), a)) for c in cfgs]
            if "B" in cfgs:
                row.append(num(ratio(Tm(EMB, x, o, "B"), Tm(EMB, x, o, "Bo")), 1))
            row.append(num(ratio(Tm(EMB, x, o, "Co"), Tm(EMB, x, o, "Bo"))))
            row.append(num(ratio(ic, ia), 3))
            rows.append(row)
        g = ["**geom. Mittel**", "", "", ""] + [f"**{num(gm[(o, c)])}**" for c in cfgs]
        if "B" in cfgs:
            g.append(f"**{num(gm[(o, 'B')] / gm[(o, 'Bo')], 1)}**")
        g.append(f"**{num(gm[(o, 'Co')] / gm[(o, 'Bo')])}**")
        g.append(f"**{num(gmean([ratio(Iv(EMB, x, o, 'C'), Iv(EMB, x, o, 'A')) for x in wl[(EMB, o)]]), 3)}**")
        rows.append(g)
        head = ["Workload", "A [s]", "Spanne A", "MIPS A"] + [f"{c}/A" for c in cfgs]
        head += (["B/Bo"] if "B" in cfgs else []) + ["Co/Bo", "I_C/I_A"]
        return table(head, rows)

    w("## 3. Pydrofoil standalone, Embench `-O2`\n")
    w("A [s] = Median der Wandzeit ohne Poison; Spanne A = (max − min)/Median über 5 "
      "Läufe; MIPS A = Instruktionen bis Regionsende / Wandzeit (inkl. Start). "
      "B/Bo = Gewinn der Optimierung; Co/Bo = reine Nutzungskosten (optimiert); "
      "I_C/I_A = zusätzliche Instruktionen durch `li`+`mpoison`.\n")
    w(emb_table("O2", ["A2", "B", "C", "Bo", "Co"]) + "\n")

    w("### 3.1 Grundgeschwindigkeit und relative Kosten\n")
    w("Embench `-O2`, sortiert nach MIPS von A; Mehrkosten pro ausgeführter Instruktion "
      "(T_X − T_A)/I in ns. Beides hängt vom Workload ab: von der Dichte der "
      "Speicherzugriffe (Hook-Aufrufe) und davon, wie gut Pydrofoils Tracing-JIT den "
      "Code übersetzt. Bei langsamen Workloads (wenige MIPS, der JIT findet keine "
      "guten Traces) sind auch die Hooks pro Instruktion teurer, das Verhältnis zu A "
      "bleibt aber klein, weil der Grundfall ebenso leidet.\n")
    rows = []
    for x in sorted(emb2, key=lambda x: -mips[x]):
        ia = Iv(EMB, x, "O2", "A")
        rows.append([x, num(mips[x], 0), num(ba[x]), num((Tm(EMB, x, "O2", "B") - Tm(EMB, x, "O2", "A")) / ia * 1e9, 2),
                     num((Tm(EMB, x, "O2", "Bo") - Tm(EMB, x, "O2", "A")) / ia * 1e9, 2)])
    w(table(["Workload", "MIPS A", "B/A", "B−A ns/Instr.", "Bo−A ns/Instr."], rows) + "\n")

    w("## 4. Pydrofoil standalone, Embench `-O0` (nur A/A2/Bo/Co)\n")
    w("Bei `-O0` hat jede Funktion einen Stack-Frame und damit ein `mpoison`; B/C "
      "(byteweise) wurden hier nur gezählt, nicht zeitgemessen.\n")
    w(emb_table("O0", ["A2", "Bo", "Co"]) + "\n")

    # ------------------------------------------------------------------
    w("## 5. Instrumentierung: statisch und dynamisch\n")
    w("Statisch aus dem Manifest (Programm mit Poison), dynamisch aus den "
      "Instruktionszahlen: `mpoison` pro Aufruf = (I_C − I_B)/2 (je ein `li` + "
      "`mpoison`; exakt für Frames < 2 KiB). Dichte = ausgeführte `mpoison` pro 1000 "
      "Instruktionen. Die absoluten Zahlen sind zwischen `-O0` und `-O2` nicht "
      "vergleichbar (eigener Skalierungsfaktor je Stufe), die Dichte schon.\n")
    rows = []
    for x in emb2:
        r = []
        for o in ("O2", "O0"):
            m = man.get(f"{EMB}__{x}__{o}__poison", {})
            ib, ic = Iv(EMB, x, o, "B", "region_instret"), Iv(EMB, x, o, "C", "region_instret")
            dyn = (ic - ib) / 2 if ib and ic else None
            r += [f"{m.get('functions_instrumented', '–')}/{m.get('functions_total', '–')}",
                  m.get("mpoison_static", "–"), count_fmt(dyn),
                  num(1000 * dyn / ib, 2) if dyn else "0,00"]
        rows.append([x] + r)
    w(table(["Workload", "Fkt. instr. O2", "statisch O2", "dyn. O2", "Dichte O2",
             "Fkt. instr. O0", "statisch O0", "dyn. O0", "Dichte O0"], rows) + "\n")

    # ------------------------------------------------------------------
    w("## 6. Zerlegung: mehr Instruktionen oder teurere Instruktionen?\n")
    w("T_X/T_A = (I_X/I_A) × (t_X/t_A), t = Zeit pro Instruktion = T/I. Der erste "
      "Faktor ist der Anteil der zusätzlich ausgeführten Instruktionen, der zweite "
      "die Verteuerung jeder Instruktion (Hooks, `mpoison`-Arbeit). Embench, "
      "geometrisches Mittel und Extremwerte.\n")
    rows = []
    for o, c in (("O2", "C"), ("O2", "Co"), ("O0", "Co")):
        ws = sorted(wl[(EMB, o)])
        ir = [ratio(Iv(EMB, x, o, c), Iv(EMB, x, o, "A")) for x in ws]
        tr = [ratio(Tm(EMB, x, o, c) / Iv(EMB, x, o, c), Tm(EMB, x, o, "A") / Iv(EMB, x, o, "A")) for x in ws]
        tot = [a * b for a, b in zip(ir, tr)]
        k = max(range(len(ws)), key=lambda i: tot[i])
        rows.append([f"{c}/A `-{o}`", num(gmean(tot)), num(gmean(ir), 3), num(gmean(tr)),
                     f"{ws[k]}: {num(tot[k])} = {num(ir[k], 3)} × {num(tr[k])}"])
    w(table(["", "T-Verhältnis", "I-Verhältnis", "t-Verhältnis", "größter Wert"], rows,
            ["l", "r", "r", "r", "l"]) + "\n")

    # ------------------------------------------------------------------
    w("## 7. Mikrobenchmarks (Pydrofoil, `-O2`)\n")
    w("### 7.1 Kosten pro Speicherzugriff\n")
    w("`load_dense`/`store_dense`: 4096 Elemente × 100 × Skalierung Zugriffe in der "
      "Messregion. Mehrkosten pro Zugriff = (T_X − T_A) / Zugriffe (Start- und "
      "Initialisierungsanteile sind in A und X gleich und fallen heraus).\n")
    rows = []
    for x in ("load_dense", "store_dense"):
        for wd in ("1", "8"):
            lab = f"{x}[WIDTH{wd}]"
            m = man.get(f"{MIC}__{x}__WIDTH{wd}__O2__plain", {})
            acc = 4096 * 100 * int(m.get("micro_scale", 0) or 0)
            a, b, bo = (Tm(MIC, lab, "O2", c) for c in ("A", "B", "Bo"))
            rows.append([lab, big(acc), num(a / acc * 1e9, 2), num((b - a) / acc * 1e9, 1),
                         num((bo - a) / acc * 1e9, 1), num((b - a) / acc * 1e9 / int(wd), 1),
                         num(ratio(b, a)), num(ratio(bo, a))])
    w(table(["Workload", "Zugriffe", "A ns/Zugriff", "B−A ns/Zugriff", "Bo−A ns/Zugriff",
             "B−A ns/Byte", "B/A", "Bo/A"], rows) + "\n")

    w("### 7.2 Kosten pro `mpoison`\n")
    w("Aufrufe aus dem Quelltext (`frame_size`, `call_rate`: 10⁵ × Skalierung; "
      "`recurse`: 65 536 × Skalierung), je Aufruf ein `mpoison` über den Frame. "
      "Kosten = (T_C − T_B) / Aufrufe bzw. (T_Co − T_Bo) / Aufrufe. Bei diesen "
      "Workloads ist A wegen des 120-s-Deckels für C teils < 1 s; aussagekräftig sind "
      "hier die Differenzen, nicht die Verhältnisse zu A. „≈ 0“: Differenz unter 5 % "
      "der Laufzeit, also im Rauschen (Variationskoeffizient von A bis ~3 %).\n")
    rows = []
    for x, par, calls_per in ([("frame_size", f"FRAME{f}", 100000) for f in (16, 64, 256, 1024, 4096)] +
                              [("recurse", f"DEPTH{d}", 65536) for d in (4, 64, 512)] +
                              [("call_rate", f"WORK{k}", 100000) for k in (0, 4, 16, 64, 256)]):
        lab = f"{x}[{par}]"
        m = man.get(f"{MIC}__{x}__{par}__O2__poison", {})
        calls = calls_per * int(m.get("micro_scale", 0) or 0)
        ib, ic = Iv(MIC, lab, "O2", "B", "region_instret"), Iv(MIC, lab, "O2", "C", "region_instret")
        b, c, bo, co = (Tm(MIC, lab, "O2", k) for k in ("B", "C", "Bo", "Co"))
        # unter 5 % von T: im Rauschen (VK von A bis ~3 %, A2/A bis ~±3 %)
        res = lambda d, base: num(d / calls * 1e9, 0) if abs(d) > 0.05 * base else "≈ 0"
        both = c - b > 0.05 * b and co - bo > 0.05 * bo
        rows.append([lab, big(calls), num((ic - ib) / calls, 2) if ib and ic else "–",
                     res(c - b, b), res(co - bo, bo),
                     num(ratio(c - b, co - bo), 1) if both else "–",
                     num(ratio(c, b), 1), num(ratio(co, bo), 1)])
    w(table(["Workload", "Aufrufe", "Zusatz-Instr./Aufruf", "C−B ns/Aufruf", "Co−Bo ns/Aufruf",
             "Gewinn", "C/B", "Co/Bo"], rows) + "\n")

    w("### 7.3 Alle Mikrobenchmarks, Verhältnisse\n")
    rows = []
    for x in sorted(wl[(MIC, "O2")]):
        a = Tm(MIC, x, "O2", "A")
        rows.append([x, num(a, 2)] + [num(ratio(Tm(MIC, x, "O2", c), a)) for c in ("A2", "B", "C", "Bo", "Co")]
                    + [num(ratio(Tm(MIC, x, "O0", c), Tm(MIC, x, "O0", "A"))) for c in ("Bo", "Co")])
    w(table(["Workload", "A [s] O2", "A2/A", "B/A", "C/A", "Bo/A", "Co/A", "Bo/A O0", "Co/A O0"], rows) + "\n")

    # ------------------------------------------------------------------
    w("## 8. Sail-C-Emulator (`-O3`), Embench `-O2`, Zwei-Punkt-Messung\n")
    w("t = (T(2·10⁷) − T(10⁷)) / 10⁷ je Wiederholung, Median über 3. Spanne = (max − min)/"
      "Median der drei Differenzwerte für A. Kontrolle: Bo/A* aus T(2N)/2N (ein Lauf "
      "statt Differenz, Startkosten < 2 %, robuster gegen Einzelstörungen).\n")
    rows = []
    for x in cs_w:
        a = cs(x, "A")
        rows.append([x, num(a * 1e6, 2), num(1 / a / 1e6, 2), num(spread(cs_diff[(x, 'A')]), 0, pct=True)]
                    + [num(ratio(cs(x, c), a)) for c in ("B", "C", "Bo", "Co")]
                    + [num(ratio(cs(x, "Bo", cs_full), cs(x, "A", cs_full)))])
    rows.append(["**geom. Mittel**", "", "", ""] + [f"**{num(cs_gm[c])}**" for c in ("B", "C", "Bo", "Co")]
                + [f"**{num(gmean([ratio(cs(x, 'Bo', cs_full), cs(x, 'A', cs_full)) for x in cs_w]))}**"])
    w(table(["Workload", "A µs/Instr.", "MIPS A", "Spanne A", "B/A", "C/A", "Bo/A", "Co/A", "Bo/A*"], rows) + "\n")
    bad = sorted(((x, c), spread(v)) for (x, c), v in cs_diff.items() if spread(v) > 0.2)
    if bad:
        w("Zellen mit Spanne > 20 % (einzelne gestörte Läufe; Median fängt einen Ausreißer "
          "von drei ab): " + ", ".join(f"{x} {c} ({num(s, 0, pct=True)})" for (x, c), s in bad) + ".\n")

    # ------------------------------------------------------------------
    w("## 9. VP (SystemC/VCML + Pydrofoil-Plugin), Auswahl `-O2`\n")
    w("Quantum 10 µs, 3 Wiederholungen, dieselben Programme wie auf Pydrofoil und dem "
      "C-Emulator. MIPS laut VP.\n")
    rows = []
    for x in vp_w:
        s = vp_s[x]
        a = Vt(x, "A")
        rows.append([x, num(a, 1), num(spread(VT[(s, x, "O2", "A")]), 1, pct=True),
                     num(med(VM, (s, x, "O2", "A")), 2)]
                    + [num(ratio(Vt(x, c), a)) for c in ("A2", "B", "C", "Bo", "Co")]
                    + [num(ratio(Vt(x, "C"), Vt(x, "B"))), num(ratio(Vt(x, "Co"), Vt(x, "Bo")))])
    w(table(["Workload", "A [s]", "Spanne A", "MIPS A", "A2/A", "B/A", "C/A", "Bo/A", "Co/A", "C/B", "Co/Bo"],
            rows) + "\n")

    w("### 9.1 Dieselben Workloads auf allen drei Simulatoren\n")
    w("Pydrofoil und VP: Wandzeit; C-Emulator: Zeit pro Instruktion. "
      "Verlangsamung VP = T_A(VP)/T_A(Pydrofoil).\n")
    rows = []
    for x in vp_w:
        s = vp_s[x]
        for c in ("B", "Bo", "C", "Co"):
            rows.append([x, f"{c}/A", num(ratio(Tm(s, x, "O2", c), Tm(s, x, "O2", "A"))),
                         num(ratio(cs(x, c), cs(x, "A"))) if (x, "A") in cs_diff else "–",
                         num(ratio(Vt(x, c), Vt(x, "A"))),
                         (num(ratio(Vt(x, "A"), Tm(s, x, "O2", "A")), 0)
                          if Tm(s, x, "O2", "A") >= 2 else "– (A < 2 s)") if c == "B" else ""])
    w(table(["Workload", "Kennzahl", "Pydrofoil", "C-Emulator", "VP", "Verlangsamung VP"], rows,
            ["l", "l", "r", "r", "r", "r"]) + "\n")

    # ------------------------------------------------------------------
    w("## 10. Speicherbedarf (max-RSS des Simulatorprozesses)\n")
    rows = []
    for name, d, keyf in [("Pydrofoil `-O2`", RSS, lambda k: k[2] == "O2"),
                          ("Pydrofoil `-O0`", RSS, lambda k: k[2] == "O0"),
                          ("VP `-O2`", VR, lambda k: True),
                          ("C-Emulator `-O2` (bis 2·10⁷ Instr.)", cells(tp, "max_rss_kb", ok=("limit",)), lambda k: True)]:
        by = defaultdict(list)
        for k, v in d.items():
            if keyf(k):
                by[k[3]].append(statistics.median(v) / 1024)
        a = statistics.median(by["A"]) if by.get("A") else float("nan")
        row = [name]
        for c in ("A", "B", "C", "Bo", "Co"):
            v = by.get(c)
            row.append(f"{num(statistics.median(v), 0)} ({num(max(v), 0)})" if v else "–")
        row.append(num(ratio(statistics.median(by["Co"]), a), 2) if by.get("Co") else "–")
        rows.append(row)
    w("Median über alle Workloads der Mediane je Zelle, in Klammern das Maximum [MB]:\n")
    w(table(["Simulator", "A", "B", "C", "Bo", "Co", "Co/A"], rows) + "\n")

    # ------------------------------------------------------------------
    w("## 11. Messgüte\n")
    rows = []
    for o in ("O2", "O0"):
        q, cv = [], []
        for s in (EMB, MIC):
            for x in wl[(s, o)]:
                a = T.get((s, x, o, "A"))
                if a and statistics.median(a) >= 2:
                    q.append(ratio(Tm(s, x, o, "A2"), Tm(s, x, o, "A")))
                    if len(a) > 1:
                        cv.append(statistics.stdev(a) / statistics.mean(a))
        rows.append([f"Pydrofoil `-{o}`", len(q), num(min(q), 3), num(statistics.median(q), 3), num(max(q), 3),
                     num(statistics.median(cv), 1, pct=True), num(max(cv), 1, pct=True)])
    q = [ratio(Vt(x, "A2"), Vt(x, "A")) for x in vp_w]
    cv = [statistics.stdev(VT[(vp_s[x], x, "O2", "A")]) / statistics.mean(VT[(vp_s[x], x, "O2", "A")]) for x in vp_w]
    rows.append(["VP", len(q), num(min(q), 3), num(statistics.median(q), 3), num(max(q), 3),
                 num(statistics.median(cv), 1, pct=True), num(max(cv), 1, pct=True)])
    w("Workloads mit A ≥ 2 s. A2/A = unabhängige Wiederholung derselben Konfiguration "
      "(ideal 1); VK = Variationskoeffizient der Wiederholungen von A.\n")
    w(table(["Messreihe", "Workloads", "A2/A min", "A2/A Median", "A2/A max", "VK Median", "VK max"], rows) + "\n")
    ratios = sorted(v[20000000] / v[10000000] for v in tpd.values() if len(v) == 2)
    w(f"C-Emulator: T(2N)/T(N) ideal 2; gemessen Median {num(statistics.median(ratios))}, "
      f"{sum(not 1.8 <= r <= 2.2 for r in ratios)} von {len(ratios)} Paaren außerhalb [1,8; 2,2].\n")

    w("## 12. Nicht zeitlich ausgewertet\n")
    w("- riscv-tests (9): 0,04–0,09 s pro Lauf, nicht skalierbar; nur Instruktionszahlen und "
      "Korrektheit.\n- dhrystone C/Co: Trap (Fehlalarm), keine Zeit.\n- VP nur 4 Workloads, ein "
      "Quantum (10 µs), ein VCML-Stand.\n")

    out = REPO / args.out
    out.write_text("\n".join(md))
    print(f"-> {out.relative_to(REPO)}")


if __name__ == "__main__":
    main()
