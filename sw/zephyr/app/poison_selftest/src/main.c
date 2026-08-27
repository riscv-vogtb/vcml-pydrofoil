/*
 * SPDX-License-Identifier: Apache-2.0
 *
 * Exercises the poison detector without the instrumenting toolchain: the
 * buffer is marked by hand with MPOISON, so the read that follows has to fault.
 */

#include <zephyr/kernel.h>
#include <zephyr/sys/printk.h>

#include <vp/poison.h>
#include <vp/sim.h>

static volatile uint8_t buf[64];

int main(void)
{
	printk("poison selftest on %s\n", CONFIG_BOARD_TARGET);

	// Clean to begin with
	vp_unpoison(buf, sizeof(buf));
	printk("after unpoison: check=%d (expect 0)\n",
	       vp_check_poison((const void *)buf, sizeof(buf)));

	// A read of clean memory must not fault
	printk("clean read: %u\n", buf[0]);

	// Classification is a pure function, so every branch can be checked
	printk("classify(5, ram)   = %d (expect 0 POISON)\n",
	       vp_classify_fault(5, VP_RAM_BASE));
	printk("classify(5, mmio)  = %d (expect 1 OTHER)\n",
	       vp_classify_fault(5, 0x10009000));
	printk("classify(24, mmio) = %d (expect 0 POISON)\n",
	       vp_classify_fault(24, 0x10009000));
	printk("classify(2, ram)   = %d (expect 1 OTHER)\n",
	       vp_classify_fault(2, VP_RAM_BASE));

	vp_poison(buf, sizeof(buf));
	printk("after poison:   check=%d (expect 1)\n",
	       vp_check_poison((const void *)buf, sizeof(buf)));

	/* This read has to fault; the handler reports and exits. */
	printk("reading poisoned memory now\n");
	printk("unreachable: %u\n", buf[0]);

	printk("ERROR: poisoned read did not fault\n");
	vp_sim_exit(VP_EXIT_OK);

	return 0;
}
