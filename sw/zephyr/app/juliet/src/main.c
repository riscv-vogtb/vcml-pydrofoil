/*
 * SPDX-License-Identifier: Apache-2.0
 *
 * Driver for one Juliet testcase. juliet_case.c, generated into the build
 * directory, supplies the case name and the two entry points.
 *
 * The VP-PHASE markers say where a fault hit: in bad() it is the expected
 * detection, in good() a false positive.
 */

#include <stdio.h>

#include <vp/sim.h>

extern const char *juliet_case_name;
extern void juliet_good(void);
extern void juliet_bad(void);

int main(void)
{
	printf("VP-TEST: %s\n", juliet_case_name);

	printf("VP-PHASE: good\n");
	juliet_good();

	printf("VP-PHASE: bad\n");
	juliet_bad();

	/* Reached only when nothing faulted; ends the run instead of idling. */
	printf("VP-PHASE: done\n");
	vp_sim_exit(VP_EXIT_OK);

	return 0;
}
