/*
 * frame_size: feste Aufrufzahl, variable Framegroesse (-DFRAME=<Bytes>).
 * Erwartung (Kostenmodell §2.2): Overhead linear in FRAME, weil mpoison pro
 * Aufruf shadow_fill ueber den ganzen Locals-Bereich ausfuehrt.
 *
 * Der Rumpf schreibt nur ein Element, damit Auto-Unpoison (Stores) den Term
 * nicht ueberlagert.
 */

#include "micro.h"

#ifndef FRAME
#define FRAME 256
#endif

#define CALLS (100000UL * SCALE)

volatile unsigned long micro_sink;

static NOINLINE unsigned long callee(unsigned long x)
{
	unsigned char buf[FRAME];

	buf[0] = (unsigned char)x;
	escape(buf);
	return buf[0];
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
