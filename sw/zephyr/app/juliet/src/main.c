/*
 * SPDX-License-Identifier: Apache-2.0
 *
 * Driver for one Juliet testcase. juliet_case.c, generated into the build
 * directory, names the case and runs either its good() or its bad() half --
 * one per elf, so neither can hide a fault in the other.
 */

#include <stdio.h>

#include <vp/sim.h>

extern const char *juliet_case_name;
extern const char *juliet_phase;
extern void juliet_run(void);

int main(void)
{
	printf("VP-TEST: %s\n", juliet_case_name);

	printf("VP-PHASE: %s\n", juliet_phase);
	juliet_run();

	/* Reached only when nothing faulted; ends the run instead of idling. */
	printf("VP-PHASE: done\n");
	vp_sim_exit(VP_EXIT_OK);

	return 0;
}
