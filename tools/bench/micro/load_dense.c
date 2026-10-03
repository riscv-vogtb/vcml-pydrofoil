/*
 * load_dense: Loads aus einem globalen Array, ein einziger Aufruf.
 * -DWIDTH=1|8 waehlt Byte- bzw. Doppelwort-Loads.
 *
 * Erwartung (§2.2): shadow_any_poisoned prueft byteweise ohne Early-Exit,
 * ein 8-Byte-Load kostet also 8 Shadow-Reads, ein 1-Byte-Load einen. Bei
 * gleicher Zahl an Loads muss der Overhead von WIDTH=8 deutlich ueber dem von
 * WIDTH=1 liegen. Das Array ist global (nicht Stack), damit kein mpoison-Term
 * hinzukommt.
 */

#include <stdint.h>
#include "micro.h"

#ifndef WIDTH
#define WIDTH 8
#endif

#if WIDTH == 1
typedef uint8_t elem_t;
#elif WIDTH == 8
typedef uint64_t elem_t;
#else
#error "WIDTH muss 1 oder 8 sein"
#endif

#define N 4096
#define PASSES (100UL * SCALE)

volatile unsigned long micro_sink;
static elem_t data[N];

int main(void)
{
	unsigned long acc = 0;

	for (unsigned long i = 0; i < N; i++)
		data[i] = (elem_t)i;
	escape(data);

	bench_start();
	for (unsigned long p = 0; p < PASSES; p++) {
		for (unsigned long i = 0; i < N; i++)
			acc += ((volatile elem_t *)data)[i];
	}
	bench_stop();

	micro_sink = acc;
	return 0;
}
