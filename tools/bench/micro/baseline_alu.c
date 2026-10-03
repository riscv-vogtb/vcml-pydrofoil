/*
 * baseline_alu: reine Registerarithmetik in einer einzigen Funktion, keine
 * Aufrufe in der Messregion. Untergrenze: bei -O2 erwartet Overhead ~0
 * (Instruktionen identisch bis auf das eine mpoison im Prolog von main).
 *
 * Bei -O0 ist das KEIN speicherfreier Workload: Schleifenzaehler und Variablen
 * liegen im Stack, jede Iteration erzeugt Loads und Stores. Das ist der
 * -O0-Effekt aus §7 und wird so berichtet, nicht korrigiert.
 */

#include "micro.h"

#define ITERS (1000000UL * SCALE)

volatile unsigned long micro_sink;

int main(void)
{
	unsigned long v = 1;

	bench_start();
	for (unsigned long i = 0; i < ITERS; i++) {
		v = v * 6364136223846793005UL + 1442695040888963407UL;
		__asm__ volatile("" : "+r"(v));
	}
	bench_stop();

	micro_sink = v;
	return 0;
}
