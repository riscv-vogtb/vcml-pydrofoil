/*
 * handle_trap() fuer crt.S (trap_entry), in beiden Pfaden. Jeder Trap ist in
 * einem Benchmark ein Befund und wird maschinenlesbar gemeldet:
 *
 *   BENCH-TRAP: mcause=<n> mepc=0x<hex> mtval=0x<hex>
 *
 * Erwartet:
 *   mcause=2   illegale Instruktion: Poison-ELF auf dem Simulator ohne Poison
 *              (Negativkontrolle, messplan.md §3)
 *   mcause=24  E_Extension: Poison-Treffer. In einem Benchmark ist das ein
 *              echter Lesezugriff auf uninitialisierten Stack -> Befund, kein
 *              Messwert.
 */

#include <stdio.h>
#include <stdlib.h>
#include "bench.h"

unsigned long handle_trap(unsigned long cause, unsigned long epc,
			  unsigned long regs[32])
{
	(void)regs;
	printf("BENCH-TRAP: mcause=%lu mepc=0x%lx mtval=0x%lx\n", cause, epc,
	       BENCH_READ_CSR(mtval));
	exit(1337);
}
