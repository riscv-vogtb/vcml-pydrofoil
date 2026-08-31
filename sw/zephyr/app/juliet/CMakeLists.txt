# SPDX-License-Identifier: Apache-2.0

cmake_minimum_required(VERSION 3.20.0)

find_package(Zephyr REQUIRED HINTS $ENV{ZEPHYR_BASE})
project(juliet)

# Point to the "C" folder from juliet
# If env isnt set, we assume it to live under "juliet_test_suite" in vcml base
if(DEFINED ENV{JULIET_ROOT})
  set(JULIET_ROOT $ENV{JULIET_ROOT})
else()
  set(JULIET_ROOT ${CMAKE_CURRENT_SOURCE_DIR}/../../../../juliet_test_suite)
endif()

# The testcase is pulled in by juliet_case.c, which tools/juliet regenerates
# per test. It lives in the build directory, so a suite run never touches the
# source tree; src/case_default.c seeds it for a standalone build.
set(JULIET_CASE_C ${CMAKE_CURRENT_BINARY_DIR}/juliet_case.c)
if(NOT EXISTS ${JULIET_CASE_C})
  configure_file(src/case_default.c ${JULIET_CASE_C} COPYONLY)
endif()

# This source list stays constant across testcases, so CMake never re-runs.
target_sources(app PRIVATE
  src/main.c
  ${JULIET_CASE_C}
  ${JULIET_ROOT}/testcasesupport/io.c
)
target_include_directories(app PRIVATE
  ${JULIET_ROOT}/testcasesupport
  ${JULIET_ROOT}/testcases
)
target_compile_options(app PRIVATE -mllvm -riscv-stack-poison)
# picolibc does not declare alloca, which the alloca testcases go through.
target_compile_definitions(app PRIVATE alloca=__builtin_alloca)
