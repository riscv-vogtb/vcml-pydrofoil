# Benchmark-Harness für die POISON-Erweiterung

Setzt [thesis/messplan.md](../../thesis/messplan.md) um. Begründungen stehen
dort; hier steht nur, wie man es bedient.

## Überblick

| Datei | Zweck |
|---|---|
| `build.sh` | baut alle ELFs im `ubuntu:24.04`-Container (Poison-clang braucht glibc ≥ 2.39) |
| `build_in_container.sh` | die eigentliche Build-Logik |
| `build_vp_image.sh` | VP-Image mit beliebigem Plugin, abgeleitet vom Release-Image |
| `run_all.sh` | **ein Befehl** für alle Messreihen (Stufen, fortsetzbar, `--detach`) |
| `bench.py` | Runner: Messreihen planen, ausführen, fortsetzen, zusammenfassen |
| `calibrate.py` | Skalierung pro Workload und opt aus einem count-Lauf (§9.1) |
| `quickcompare.py` | Schnellvergleich Simulator-Varianten (alt/opt), keine Messreihe |
| `vp_bench.cfg.in` | VP-Konfiguration, von `bench.py` pro ELF ausgefüllt |
| `support/` | Messschicht (`bench.c`), Trap-Bericht, Plattformschicht (`platform.c`), Embench-Board |
| `micro/` | Mikrobenchmarks (§6.1) |

Ergebnisse landen unter `results/bench/` (ELFs, Manifest, CSVs, Logs).

## Voraussetzungen

- Poison-LLVM: `/scratch/vogtb/llvm-poison-install` (`LLVM_TOOLCHAIN_PATH`)
- Zephyr-SDK 0.17.4 (`ZEPHYR_SDK_INSTALL_DIR`): newlib + libgcc für
  `rv64imafdc/lp64d/medany`
- `/scratch/vogtb/Pydrofoil-RISCV-benchmarks` mit Submodulen, **rekursiv**
  (`riscv_tests/env` liefert `encoding.h`):
  `git submodule update --init --recursive baremetal/embench_iot baremetal/riscv_tests`
- Pfad 1: `pydrofoil-riscv-{with,without}-poison`, `pydrofoil-riscv-with-poison-opt` im Repo-Root
- Pfad 2: Images `vcml-pydrofoil:release-{poison,nopoison,poison-opt}`
- Pfad 3: `riscv_sim_RV64_O3_{with,without}_poison`, `riscv_sim_RV64_with_poison_opt`
  im Repo-Root, mit `-O3 -flto` gebaut (der Debug-Build ist nicht verwertbar, §8.4a)

Konfigurationen (§3, §8.4b): A ohne Poison · A2 = A (Rauschkontrolle) · B/C mit
Poison (byteweise Shadow-Helfer) · Bo/Co mit Poison, optimierte Shadow-Helfer ·
N Negativkontrolle. Simulatoren per `--iss-with/--iss-without/--iss-opt`,
`--csim-…`, `--vp-…-image` überschreibbar.

## Ein Befehl

```bash
./tools/bench/run_all.sh --list            # Stufen und ihre bench.py-Befehle
./tools/bench/run_all.sh --detach          # Standard-Stufen, losgelöst (überlebt Logout)
tail -f results/bench/run_all.log
./tools/bench/run_all.sh timing-iss-O0     # einzelne Stufen
```

Standard: `count` → `negctl` → `timing-iss-O2` → `timing-csim-O2`. `timing-iss-O0`,
`count-vp`, `timing-vp` nur auf Anfrage (O0 abgespeckt: A/A2/Bo/Co; VP mit ~0,7–4 MIPS
nur auf einer Auswahl von vier Workloads, `VP_MATCH` im Skript). Jede Stufe ist
fortsetzbar; nach Abbruch denselben Befehl erneut starten. Es läuft immer nur eine
Instanz (mit `--wait` reiht sich eine weitere dahinter ein), und `run_all.sh` startet nicht, solange
ein anderer `bench.py run` aktiv ist (parallele Läufe verfälschen die Zeitmessung).
Der Build ist keine Stufe: ein Neubau ändert die ELF-Hashes.

## Ablauf (messplan.md §10)

```bash
# ELFs (Kalibrierbuild: GSF=1, MICRO_SCALE=1)
./tools/bench/build.sh

# VP-Images. Basis einmal:
podman build --build-arg CMAKE_BUILD_TYPE=Release -t vcml-pydrofoil:release-poison .
# Plugins tauschen -- beide aus DEMSELBEN Build verwenden:
./tools/bench/build_vp_image.sh <poison-plugin>   release-poison   --expect poison
./tools/bench/build_vp_image.sh <nopoison-plugin> release-nopoison --expect plain

# 0. print_mem-Befund (§8.1): alter (ungeschützter) gegen neuen Poison-Build, Konfiguration B
python3.12 tools/bench/bench.py run --path iss --mode timing --tag printmem-alt \
    --iss-with pydrofoil-riscv-with-poison-printmem --workload load_dense --opt O2 --config B --reps 3
python3.12 tools/bench/bench.py run --path iss --mode timing --tag printmem-neu \
    --workload load_dense --opt O2 --config B --reps 3
#    + Juliet-Gegenprobe gegen das neue Image (Kommandos in messplan.md §8.1)

# 1. Instruktionszahlen (deterministisch, parallel) + Gegenprobe A == B
python3.12 tools/bench/bench.py run --path iss --mode count --jobs 16
python3.12 tools/bench/bench.py summary --path iss --mode count

# Kalibrierung (messplan.md §9.1, Umsetzung): Kalibrierbuild mit festem Faktor,
# count-Lauf, daraus Faktor pro Workload und opt (A >= 5 s, Einzellauf <= 120 s):
GSF=100 MICRO_SCALE=100 ./tools/bench/build.sh
python3.12 tools/bench/bench.py run --path iss --mode count --tag calib --jobs 8 --timeout 300
python3.12 tools/bench/calibrate.py --tag calib            # -> tools/bench/scales.tsv + Budget
SCALE_FILE=tools/bench/scales.tsv ./tools/bench/build.sh
# Nachschärfen: calibrate.py auf den count-Lauf der skalierten ELFs anwenden
# (liest den tatsächlichen Faktor pro Zeile), ggf. erneut bauen:
python3.12 tools/bench/calibrate.py --tag ''

# 2./3. Zeitmessung (seriell, gepinnt, randomisiert); einzeln oder über run_all.sh
python3.12 tools/bench/bench.py run --path iss --mode timing --opt O2 --reps 5
python3.12 tools/bench/bench.py run --path iss --mode negctl
# lange Reihen losgelöst starten (ueberlebt Logout, Linger aktiv):
setsid nohup python3.12 tools/bench/bench.py run ... >> <log> 2>&1 < /dev/null &

# Schnellvergleich alt/opt (Messreihe vorher pausieren: kill <bench.py-PID>,
# laufenden Container stoppen; Fortsetzen mit demselben Befehl)
python3.12 tools/bench/quickcompare.py iss
python3.12 tools/bench/quickcompare.py csim --inst-limit 2e7

# Zwei-Punkt-Messung (nur iss)
python3.12 tools/bench/bench.py run --path iss --mode twopoint --inst-limit <N> --suite micro

# 4. VP
python3.12 tools/bench/bench.py run --path vp --mode count --jobs 8
python3.12 tools/bench/bench.py run --path vp --mode timing --reps 5

# 5. C-Emulator (--no-trace setzt der Harness). Volle Läufe dauern im Median
# 0,4 h (0,5 MIPS, GMP-lastig), daher Zwei-Punkt-Messung N/2N:
python3.12 tools/bench/bench.py run --path csim --mode twopoint --inst-limit 10000000 \
    --suite embench --opt O2 --reps 3

# Quantum-Sweep (eine Reihe je Quantum)
python3.12 tools/bench/bench.py run --path vp --mode timing --tag q100ns --quantum 100ns \
    --workload baseline_alu --opt O2
```

Jede Messreihe ist fortsetzbar: abgeschlossene Läufe (`run_key` in der CSV,
enthält den ELF-Hash) werden übersprungen, fehlgeschlagene wiederholt. `--dry-run` zeigt Plan und
Zeitschätzung (aus vorhandenen `count`-Daten), ohne etwas auszuführen.

## Was gemessen wird

Jeder Workload gibt am Ende der Messregion genau eine Zeile aus:

```
BENCH: region_instret=<n> region_cycle=<n> total_instret=<n>
```

Die Instruktionszahl kommt aus dem Gast (`minstret`), nicht aus dem
Simulator — exakt und für beide Pfade gleich definiert. Host-Zeit und Max-RSS
misst GNU time **im** Container (der Host-`/usr/bin/time` wird hineingemountet),
also am Simulatorprozess, nicht am podman-Client.

Weitere Markierungen: `BENCH-TRAP: mcause=… mepc=… mtval=…` (jeder Trap),
`BENCH-EXIT: code=…` (nur VP, weil dort über das simdev-STOP-Register beendet
wird, damit der VP seinen Performance-Block druckt).

## Build-Details, die man wissen muss

- Instrumentiert und mit der Opt-Stufe variiert wird **nur Workload-Code**.
  Harness, Startup und newlib bleiben in allen Varianten gleich (`-O2`, ohne
  Poison).
- Ein Workload-Objekt wird einmal gebaut und für beide Plattformen gelinkt —
  der Workload-Code ist pfadübergreifend bitidentisch.
- riscv-tests' `syscalls.c` wird **nicht** verwendet: dessen `printf` nutzt den
  HTIF-Syscall-Proxy, den das Sail-Modell nicht beantwortet (hängt endlos).
  `support/platform.c` ersetzt es, mit Backend `BENCH_PLATFORM_HTIF`
  (HTIF-Terminal) bzw. `BENCH_PLATFORM_VP` (UART + simdev-STOP).
- `dhrystone` trappt in Konfiguration C (Padding-Bytes bei Struct-Kopie,
  messplan.md §6.2) — nur A/B messen: `--config A --config B`.
- `support/clang-compat/stdatomic.h` ersetzt für riscv-tests `stdatomic.h`:
  `util.h` ruft in `barrier()` Atomics auf `volatile int*` auf, was clangs
  Header ablehnt.
- Das Linkerskript ist Ghinamis `test.ld` mit `FLAGS(6)` statt
  `FLAGS(SHF_ALLOC | SHF_EXECINSTR)` — lld kennt die Namen nicht, GNU ld setzt
  genau 6 ein.
- `mm` aus riscv-tests fehlt bewusst (misst sich selbst über `thread_entry`,
  kein `setStats`); `matmult-int` deckt Matrixmultiplikation ab.

## Manifest

`results/bench/elf/manifest.tsv`, eine Zeile pro ELF: ID, Suite, Workload,
Parameter, Opt-Stufe, Variante, Plattform, Status, SHA-256, `text`/`data`/`bss`,
`mpoison_static`, `functions_total`/`functions_instrumented` (nur
Workload-Objekte, lokale Labels ausgenommen), GSF, Warmup, Micro-Scale.
