/*
 * SPDX-License-Identifier: Apache-2.0
 *
 * Fatal error handler for the vcml-pydrofoil VP: classifies the fault and ends
 * the run with an exit code a harness can read, instead of returning to an
 * idle loop that only stops when system.duration runs out.
 */

#include <zephyr/kernel.h>
#include <zephyr/fatal.h>
#include <zephyr/sys/printk.h>

#include <vp/poison.h>
#include <vp/sim.h>

void k_sys_fatal_error_handler(unsigned int reason, const struct arch_esf *esf)
{
	unsigned long mcause, mtval;

	ARG_UNUSED(reason);
	ARG_UNUSED(esf);

	__asm__ volatile("csrr %0, mcause" : "=r"(mcause));
	__asm__ volatile("csrr %0, mtval" : "=r"(mtval));

	mcause &= CONFIG_RISCV_MCAUSE_EXCEPTION_MASK;

	/*
	 * One line, greppable, so a batch run does not have to parse the
	 * register dump above it.
	 */
	if (vp_classify_fault(mcause, mtval) == VP_FAULT_KIND_POISON) {
		printk("VP-RESULT: POISON addr=0x%lx mcause=%lu\n", mtval, mcause);
		vp_sim_exit(VP_EXIT_POISON);
	}

	printk("VP-RESULT: FAULT addr=0x%lx mcause=%lu\n", mtval, mcause);
	vp_sim_exit(VP_EXIT_FAULT);
}
