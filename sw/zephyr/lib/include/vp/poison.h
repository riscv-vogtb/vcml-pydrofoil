/*
 * SPDX-License-Identifier: Apache-2.0
 *
 * The VP's poison instructions and the classification of a poison fault.
 *
 * Encoding: custom-0 space (opcode 0x0b), R-type,
 * funct7 = 0. rs1 is a physical guest address, rs2 a length in bytes.
 */

#ifndef VP_POISON_H_
#define VP_POISON_H_

#include <zephyr/kernel.h>
#include <zephyr/devicetree.h>

/** Mark [addr, addr + len) as uninitialised. */
#define vp_poison(addr, len)									\
	__asm__ volatile(".insn r 0x0b, 0x0, 0x00, x0, %0, %1"		\
			 :													\
			 : "r"((uintptr_t)(addr)), "r"((uintptr_t)(len))	\
			 : "memory")

/** Mark [addr, addr + len) as initialised. */
#define vp_unpoison(addr, len)									\
	__asm__ volatile(".insn r 0x0b, 0x1, 0x00, x0, %0, %1"		\
			 :													\
			 : "r"((uintptr_t)(addr)), "r"((uintptr_t)(len))	\
			 : "memory")

/**
 * Query whether any byte in [addr, addr + len) is poisoned.
 *
 * This is a query, not a load: it does not fault on poisoned memory.
 */
static inline int vp_check_poison(const void *addr, size_t len)
{
	uintptr_t result;

	__asm__ volatile(".insn r 0x0b, 0x2, 0x00, %0, %1, %2"
			 : "=r"(result)
			 : "r"((uintptr_t)addr), "r"((uintptr_t)len));

	return (int)result;
}

/** What kind of fault the guest took. */
enum vp_fault_kind {
	VP_FAULT_KIND_POISON,
	VP_FAULT_KIND_OTHER,
};

/*
 * 24 - E_Extension, what the newer Sail model raises for a poisoned read.
 * (5 is legacy, old pydrofoil build - it took long so I kept this branch here)
 */
#define VP_MCAUSE_LOAD_ACCESS_FAULT 5UL
#define VP_MCAUSE_EXTENSION         24UL

#define VP_RAM_BASE DT_REG_ADDR(DT_CHOSEN(zephyr_sram))
#define VP_RAM_SIZE DT_REG_SIZE(DT_CHOSEN(zephyr_sram))

static inline enum vp_fault_kind vp_classify_fault(unsigned long mcause, unsigned long mtval)
{
	if (mcause == VP_MCAUSE_EXTENSION) {
		return VP_FAULT_KIND_POISON;
	}

	if (mcause == VP_MCAUSE_LOAD_ACCESS_FAULT &&
	    mtval >= VP_RAM_BASE && mtval < VP_RAM_BASE + VP_RAM_SIZE) {
		return VP_FAULT_KIND_POISON;
	}

	return VP_FAULT_KIND_OTHER;
}

#endif /* VP_POISON_H_ */
