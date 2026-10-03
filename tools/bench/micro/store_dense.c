/*
 * store_dense: Stores in ein globales Array, ein einziger Aufruf.
 * -DWIDTH=1|8 waehlt Byte- bzw. Doppelwort-Stores.
 *
 * Erwartung (§2.2): ext_check_phys_mem_write ruft bei JEDEM Store im
 * RAM-Fenster shadow_fill(..., SHADOW_CLEAN) auf, byteweise. Ein 8-Byte-Store
 * kostet 8 Shadow-Writes. Gegenstueck zu load_dense.
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
	escape(data);

	bench_start();
	for (unsigned long p = 0; p < PASSES; p++) {
		for (unsigned long i = 0; i < N; i++)
			((volatile elem_t *)data)[i] = (elem_t)(i + p);
	}
	bench_stop();

	micro_sink = data[N - 1];
	return 0;
}
