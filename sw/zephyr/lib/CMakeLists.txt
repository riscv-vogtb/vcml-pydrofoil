# SPDX-License-Identifier: Apache-2.0

zephyr_include_directories(include)

if(CONFIG_VP_FAULT_REPORT)
  zephyr_library()
  zephyr_library_sources(src/fault_report.c)
endif()
