/*
 * Minimaler stdatomic.h-Ersatz fuer riscv-tests' util.h unter clang.
 *
 * util.h ruft in barrier() atomic_*_explicit auf 'volatile int *' auf. GCCs
 * stdatomic.h akzeptiert das, clangs verlangt _Atomic-Typen und bricht ab --
 * auch wenn barrier() (nur fuer mt-*-Benchmarks) gar nicht benutzt wird.
 * Die __atomic_*-Builtins arbeiten auf normalen Zeigern, in clang wie in GCC.
 *
 * Nur ueber -I fuer riscv-tests-Uebersetzungseinheiten eingebunden
 * (tools/bench/build_in_container.sh). Deckt nur ab, was util.h nutzt.
 */

#ifndef BENCH_CLANG_COMPAT_STDATOMIC_H_
#define BENCH_CLANG_COMPAT_STDATOMIC_H_

typedef enum {
	memory_order_relaxed = __ATOMIC_RELAXED,
	memory_order_consume = __ATOMIC_CONSUME,
	memory_order_acquire = __ATOMIC_ACQUIRE,
	memory_order_release = __ATOMIC_RELEASE,
	memory_order_acq_rel = __ATOMIC_ACQ_REL,
	memory_order_seq_cst = __ATOMIC_SEQ_CST
} memory_order;

#define atomic_fetch_add_explicit(p, v, mo) __atomic_fetch_add((p), (v), (mo))
#define atomic_store_explicit(p, v, mo) __atomic_store_n((p), (v), (mo))
#define atomic_load_explicit(p, mo) __atomic_load_n((p), (mo))

#endif /* BENCH_CLANG_COMPAT_STDATOMIC_H_ */
