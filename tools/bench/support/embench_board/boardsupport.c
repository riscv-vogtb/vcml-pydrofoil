/*
 * Embench-Board fuer die Pydrofoil-Messungen. Ersetzt
 * examples/native/speed/boardsupport.c: start_trigger/stop_trigger messen
 * die Region um benchmark() ueber minstret/mcycle (tools/bench/support/bench.c).
 */

#include <support.h>
#include "bench.h"

void initialise_board(void)
{
}

void __attribute__((noinline)) __attribute__((externally_visible))
start_trigger(void)
{
	bench_start();
}

void __attribute__((noinline)) __attribute__((externally_visible))
stop_trigger(void)
{
	bench_stop();
}
