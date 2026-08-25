/*
 * SPDX-License-Identifier: Apache-2.0
 *
 * Polling UART driver for the vcml::serial::nrf51 model used by the
 * vcml-pydrofoil virtual platform.
 *
 * Register offsets and semantics taken from
 * sysc_vp/deps/vcml/src/vcml/models/serial/nrf51.cpp.
 */

// uart_nrfx_uart.c could also work

#define DT_DRV_COMPAT vcml_nrf51_uart

#include <zephyr/kernel.h>
#include <zephyr/arch/cpu.h>
#include <zephyr/device.h>
#include <zephyr/devicetree.h>
#include <zephyr/drivers/uart.h>
#include <zephyr/sys/device_mmio.h>

/* nrf51.cpp:217-240 */
#define NRF51_STARTRX 0x000
#define NRF51_STARTTX 0x008
#define NRF51_RXDRDY 0x108
#define NRF51_ENABLE 0x500
#define NRF51_RXD 0x518
#define NRF51_TXD 0x51c

/* write_enable() compares against 4, not 1 (nrf51.cpp:121) */
#define NRF51_ENABLE_ON 4u
#define NRF51_TASK_TRIGGER 1u

struct uart_pydrofoil_config
{
	DEVICE_MMIO_ROM;
};

struct uart_pydrofoil_data
{
	DEVICE_MMIO_RAM;
};

static inline void uart_pydrofoil_write(const struct device *dev, uint32_t off, uint32_t val)
{
	sys_write32(val, DEVICE_MMIO_GET(dev) + off);
}

static inline uint32_t uart_pydrofoil_read(const struct device *dev, uint32_t off)
{
	return sys_read32(DEVICE_MMIO_GET(dev) + off);
}

static void uart_pydrofoil_poll_out(const struct device *dev, unsigned char c)
{
	/*
	 * write_txd() hands the byte to the serial socket synchronously
	 * (nrf51.cpp:150). There is no TX FIFO and no busy flag to wait on.
	 */
	uart_pydrofoil_write(dev, NRF51_TXD, c);
}

static int uart_pydrofoil_poll_in(const struct device *dev, unsigned char *c)
{
	/*
	 * read_rxd() returns 0 when the FIFO is empty (nrf51.cpp:78), which is
	 * indistinguishable from a received NUL byte. RXDRDY has to be checked
	 * first; update() keeps it in sync with the FIFO (nrf51.cpp:180).
	 */
	if (uart_pydrofoil_read(dev, NRF51_RXDRDY) == 0u)
	{
		return -1;
	}

	*c = (unsigned char)uart_pydrofoil_read(dev, NRF51_RXD);

	return 0;
}

static int uart_pydrofoil_init(const struct device *dev)
{
	DEVICE_MMIO_MAP(dev, K_MEM_CACHE_NONE);

	uart_pydrofoil_write(dev, NRF51_ENABLE, NRF51_ENABLE_ON);
	uart_pydrofoil_write(dev, NRF51_STARTTX, NRF51_TASK_TRIGGER);

	/* Without STARTRX the model silently drops incoming bytes
	 * (serial_receive(), nrf51.cpp:197).
	 */
	uart_pydrofoil_write(dev, NRF51_STARTRX, NRF51_TASK_TRIGGER);

	return 0;
}

static DEVICE_API(uart, uart_pydrofoil_driver_api) = {
	.poll_in = uart_pydrofoil_poll_in,
	.poll_out = uart_pydrofoil_poll_out,
};

#define UART_PYDROFOIL_INIT(n)                                              \
	static struct uart_pydrofoil_data uart_pydrofoil_data_##n;              \
	static const struct uart_pydrofoil_config uart_pydrofoil_config_##n = { \
		DEVICE_MMIO_ROM_INIT(DT_DRV_INST(n)),                               \
	};                                                                      \
	DEVICE_DT_INST_DEFINE(n,                                                \
						  uart_pydrofoil_init,                              \
						  NULL,                                             \
						  &uart_pydrofoil_data_##n,                         \
						  &uart_pydrofoil_config_##n,                       \
						  PRE_KERNEL_1,                                     \
						  CONFIG_SERIAL_INIT_PRIORITY,                      \
						  &uart_pydrofoil_driver_api);

DT_INST_FOREACH_STATUS_OKAY(UART_PYDROFOIL_INIT)
