/*
 * Gemeinsame Messschicht fuer alle Benchmark-Workloads (Embench, riscv-tests,
 * Mikrobenchmarks), siehe thesis/messplan.md §5.
 *
 * Die Instruktionszahl kommt aus dem Gast (minstret), nicht aus dem Simulator:
 * exakt, simulatorunabhaengig und fuer Pfad 1 (Standalone) und Pfad 2 (VP)
 * identisch definiert.
 *
 * Am Ende der Messregion wird genau eine maschinenlesbare Zeile ausgegeben:
 *
 *   BENCH: region_instret=<n> region_cycle=<n> total_instret=<n>
 *
 * region_*      nur die Messregion (start/stop)
 * total_instret minstret seit Reset bis zum Ende der Messregion; zusammen mit
 *               der Host-Laufzeit des ganzen Prozesses ergibt das die MIPS.
 *               Nicht enthalten ist nur der kurze Rest (Verify, Ausgabe, Exit).
 */

#ifndef BENCH_H_
#define BENCH_H_

#define BENCH_READ_CSR(reg) ({ unsigned long __v; \
	__asm__ volatile ("csrr %0, " #reg : "=r"(__v)); __v; })

void bench_start(void);
void bench_stop(void);

/* Ziel der Umleitung -DsetStats=bench_setStats fuer riscv-tests-Mains
 * (deren util.h deklariert setStats, die Implementierung stand in syscalls.c,
 * das hier durch platform.c ersetzt ist). */
void bench_setStats(int enable);

#endif /* BENCH_H_ */
