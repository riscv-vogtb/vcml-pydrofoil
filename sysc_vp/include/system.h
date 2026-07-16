/******************************************************************************
 *                                                                            *
 * Copyright 2026 Chiara Ghinami                                              *
 *                                                                            *
 * This software is licensed under the MIT license found in the               *
 * LICENSE file at the root directory of this source tree.                    *
 *                                                                            *
 ******************************************************************************/

#ifndef SYSTEM_H
#define SYSTEM_H

#include <vcml.h>
#include "core.h"
#include "vcml/models/riscv/plic.h"
#include "uart_injector.h"

namespace virtual_platform {

enum : mwr::u64 {
    SRAM_SZ = 128 * mwr::KiB,
    SRAM_LO = 0x80000000,
    SRAM_HI = SRAM_LO + SRAM_SZ - 1,

    BOOT_SZ = 4 * mwr::KiB,
    BOOT_LO = 0x00001000,
    BOOT_HI = BOOT_LO + BOOT_SZ - 1,

    // Currently we use byte-byte, instead of byte-bit (optimized) shadow memory
    SHADOW_SZ = SRAM_SZ,
    // Must match SHADOW_BASE in riscv/riscv_shadow_mem.sail,
    // and rv_shadow_base in pydrofoil riscv/supportcoderiscv.py.
    SHADOW_LO = 0xC0000000,
    SHADOW_HI = SHADOW_LO + SHADOW_SZ - 1,

    UART0_LO = 0x10009000,
    UART0_HI = UART0_LO + 0x1000 - 1,

    PLIC_LO = 0x1000a000,
    PLIC_HI = PLIC_LO + 0x224FFF - 1,

    SIMDEV_LO = 0x10008000,
    SIMDEV_HI = SIMDEV_LO + 0x1000 - 1
};

enum : mwr::u64 { IRQ_UART0 = 5 };

class system : public vcml::system {
    public:
    using u16 = vcml::u16;
    using u32 = vcml::u32;
    using u64 = vcml::u64;
    using range = vcml::range;

    vcml::property<range> ram;
    vcml::property<range> bram;
    vcml::property<range> shadow;
    vcml::property<range> addr_uart0;
    vcml::property<range> addr_plic;
    vcml::property<vcml::range> addr_simdev;
    vcml::property<int> irq_uart0;

    system(const sc_core::sc_module_name& nm);
    virtual ~system();
    VCML_KIND(sysc_vp::system);
    // virtual const char *version() const override;

    virtual int run() override;

    private:
    core::PydrofoilCore m_core;

    vcml::generic::bus m_bus;
    vcml::generic::memory m_ram;
    vcml::generic::memory m_bram;
    vcml::generic::memory m_shadow;

    // A throttle ensures the simulation runs
    // at a controlled pace, not faster than real time.
    vcml::meta::throttle m_throttle;
    vcml::meta::loader m_loader;

    vcml::generic::clock m_clock_cpu;
    vcml::generic::reset m_reset;

    vcml::serial::nrf51 m_uart0;
    vcml::riscv::plic m_plic;

    vcml::serial::terminal m_term;
    vcml::meta::simdev m_simdev;
};

} // namespace virtual_platform

#endif
