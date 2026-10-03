/*
 * Hilfen fuer die Mikrobenchmarks (thesis/messplan.md §6.1).
 *
 * Jeder Mikrobenchmark variiert genau einen Term des Kostenmodells (§2.2):
 * Framegroesse, Aufrufrate, Load-Bytes, Store-Bytes, Rekursionstiefe.
 * Die Parameter kommen als -D aus build_in_container.sh; SCALE skaliert nur die
 * Laufzeit (Kalibrierung, §9.1), nicht die Struktur.
 *
 * escape() macht die Adresse eines Objekts fuer den Compiler sichtbar, damit
 * ein lokales Array auch bei -O2 wirklich auf dem Stack angelegt wird und der
 * Frame die gewollte Groesse hat. Ohne das wuerde -O2 die Arrays entfernen und
 * der Mikrobenchmark maesse etwas anderes als sein Name sagt.
 */

#ifndef MICRO_H_
#define MICRO_H_

#include "bench.h"

#ifndef SCALE
#define SCALE 1
#endif

#define NOINLINE __attribute__((noinline))

static inline void escape(void *p)
{
	__asm__ volatile("" : : "r"(p) : "memory");
}

/* Ergebnis, das der Compiler nicht wegoptimieren darf. */
extern volatile unsigned long micro_sink;

#endif /* MICRO_H_ */
