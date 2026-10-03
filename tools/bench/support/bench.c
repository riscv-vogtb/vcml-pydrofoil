/*
 * Implementierung von bench.h. Gebaut ohne -mllvm -riscv-stack-poison, damit
 * die Messschicht selbst in allen Konfigurationen identisch ist; poisoned wird
 * nur Workload-Code (s. build_in_container.sh).
 */

#include <stdio.h>
#include "bench.h"

static unsigned long start_instret;
static unsigned long start_cycle;
static int running;

void bench_start(void)
{
	running = 1;
	start_cycle = BENCH_READ_CSR(mcycle);
	start_instret = BENCH_READ_CSR(minstret);
}

void bench_stop(void)
{
	unsigned long instret = BENCH_READ_CSR(minstret);
	unsigned long cycle = BENCH_READ_CSR(mcycle);

	if (!running)
		return;
	running = 0;
	printf("BENCH: region_instret=%lu region_cycle=%lu total_instret=%lu\n",
	       instret - start_instret, cycle - start_cycle, instret);
}

void bench_setStats(int enable)
{
	if (enable)
		bench_start();
	else
		bench_stop();
}
