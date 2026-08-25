# SPDX-License-Identifier: Apache-2.0

if(CONFIG_UART_PYDROFOIL)
  zephyr_library()
  zephyr_library_sources(serial/uart_pydrofoil.c)
endif()
