/*
 * SPDX-License-Identifier: Apache-2.0
 *
 * Access to the VP's simulation control device (vcml::meta::simdev), mapped at
 * SIMDEV_LO (sysc_vp/include/system.h:42).
 */

#ifndef VP_SIM_H_
#define VP_SIM_H_

#include <zephyr/kernel.h>
#include <zephyr/arch/cpu.h>

#define VP_SIMDEV_BASE 0x10008000UL

/* simdev.cpp: stop at offset 0x00 calls request_stop(), exit at 0x08 calls
 * ::exit(value).
 */
#define VP_SIMDEV_STOP (VP_SIMDEV_BASE + 0x00)
#define VP_SIMDEV_EXIT (VP_SIMDEV_BASE + 0x08)

/** Exit codes reported through the simdev. */
enum vp_exit_code {
	VP_EXIT_OK = 0,        /**< ran to completion, no fault */
	VP_EXIT_POISON = 1,    /**< read from poisoned memory */
	VP_EXIT_FAULT = 2,     /**< any other fatal error */
};

/** End the simulation with @p code as the process exit status. */
static inline void vp_sim_exit(uint32_t code)
{
	sys_write32(code, VP_SIMDEV_EXIT);
	CODE_UNREACHABLE;
}

/** Stop the simulation without an exit status. */
static inline void vp_sim_stop(void)
{
	sys_write32(1, VP_SIMDEV_STOP);
	CODE_UNREACHABLE;
}

#endif /* VP_SIM_H_ */
