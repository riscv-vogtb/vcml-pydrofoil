# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20.0)
find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(juliet_cwe457_int_array_declare_no_init_01)

# Point to the "C" folder from juliet
# If env isnt set, we assume it to live under "juliet_test_suite" in vcml base
if(DEFINED ENV{JULIET_ROOT})
  set(JULIET_ROOT $ENV{JULIET_ROOT})
else()
  set(JULIET_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/../../../../juliet_test_suite)
endif()

set(JULIET_CASE
  ${JULIET_ROOT}/testcases/CWE457_Use_of_Uninitialized_Variable/s01/CWE457_Use_of_Uninitialized_Variable__int_array_declare_no_init_01.c
)

target_sources(app PRIVATE
  src/main.c
  ${JULIET_ROOT}/testcasesupport/io.c
  ${JULIET_CASE}
)
target_include_directories(app PRIVATE ${JULIET_ROOT}/testcasesupport)
target_compile_options(app PRIVATE -mllvm -riscv-stack-poison)
