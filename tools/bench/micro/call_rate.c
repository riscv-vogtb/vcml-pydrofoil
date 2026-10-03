/*
 * call_rate: kleiner fester Frame, variable Arbeit pro Aufruf (-DWORK=<n>).
 * Variiert die Aufrufrate (Aufrufe pro Instruktion). Erwartung: der
 * absolute Overhead pro Aufruf ist konstant, der relative faellt mit ~1/WORK.
 *
 * Die Arbeit ist reine Registerarithmetik (bei -O2), damit kein
 * Speicherzugriffsterm hinzukommt. Bei -O0 liegen auch Schleifenzaehler im
 * Speicher -- das ist eine Eigenschaft von -O0 und wird so berichtet (§7).
 */

#include "micro.h"

#ifndef WORK
#define WORK 16
#endif

#define CALLS (100000UL * SCALE)

volatile unsigned long micro_sink;

static NOINLINE unsigned long callee(unsigned long x)
{
	unsigned char buf[32];
	unsigned long v = x;

	buf[0] = (unsigned char)x;
	escape(buf);
	for (int k = 0; k < WORK; k++) {
		v = v * 6364136223846793005UL + 1442695040888963407UL;
		__asm__ volatile("" : "+r"(v));
	}
	return v + buf[0];
}

int main(void)
{
	unsigned long acc = 0;

	bench_start();
	for (unsigned long i = 0; i < CALLS; i++)
		acc += callee(i);
	bench_stop();

	micro_sink = acc;
	return 0;
}
