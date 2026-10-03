/*
 * recurse: Rekursion bis -DDEPTH=<n>, Frame ~64 Byte, wiederholt.
 * Worst Case nach §2.2: jeder Abstieg ist ein Prolog mit mpoison, und die
 * Stackadressen wandern ueber einen grossen Bereich (kein wiederholtes
 * Ueberschreiben desselben Shadow-Fensters wie bei frame_size).
 *
 * Die Gesamtzahl der Aufrufe ist ueber alle DEPTH-Werte gleich gehalten
 * (REPS * DEPTH konstant), damit sich nur die Tiefe aendert.
 */

#include "micro.h"

#ifndef DEPTH
#define DEPTH 64
#endif

#define TOTAL_CALLS (65536UL * SCALE)
#define REPS (TOTAL_CALLS / DEPTH)

volatile unsigned long micro_sink;

static NOINLINE unsigned long down(unsigned long d)
{
	unsigned char buf[64];

	buf[0] = (unsigned char)d;
	escape(buf);
	if (d == 0)
		return buf[0];
	return down(d - 1) + buf[0];
}

int main(void)
{
	unsigned long acc = 0;

	bench_start();
	for (unsigned long r = 0; r < REPS; r++)
		acc += down(DEPTH - 1);
	bench_stop();

	micro_sink = acc;
	return 0;
}
