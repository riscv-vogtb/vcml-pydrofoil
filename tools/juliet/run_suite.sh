#!/usr/bin/env bash
# Run the Juliet CWE457 suite end to end.
#
#   ./tools/juliet/run_suite.sh --filter '*_01'
#
# Building happens inside a container because the poison LLVM toolchain needs
# glibc >= 2.39; the VP runs from its own image on the host. Every argument is
# forwarded to juliet_suite.py.

set -e

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

LLVM_TOOLCHAIN_PATH="${LLVM_TOOLCHAIN_PATH:-/scratch/vogtb/llvm-poison-install}"
ZEPHYR_SDK_INSTALL_DIR="${ZEPHYR_SDK_INSTALL_DIR:-$HOME/zephyr-sdk-0.17.4}"
BUILD_IMAGE="${BUILD_IMAGE:-ubuntu:24.04}"
PYTHON_FOR_RUN="${PYTHON_FOR_RUN:-python3.12}"

# printf would still emit one empty argument when called with none.
ARGS=""
[[ $# -gt 0 ]] && ARGS="$(printf ' %q' "$@")"

podman run --rm --security-opt label=disable \
  -v "$REPO:$REPO" \
  -v "$ZEPHYR_SDK_INSTALL_DIR:$ZEPHYR_SDK_INSTALL_DIR:ro" \
  -v "$LLVM_TOOLCHAIN_PATH:$LLVM_TOOLCHAIN_PATH:ro" \
  "$BUILD_IMAGE" bash -c "
    apt-get update -qq
    apt-get install -y -qq cmake ninja-build python3 python3-venv device-tree-compiler git
    cd $REPO
    ZEPHYR_TOOLCHAIN_VARIANT=llvm \
    LLVM_TOOLCHAIN_PATH=$LLVM_TOOLCHAIN_PATH \
    ZEPHYR_SDK_INSTALL_DIR=$ZEPHYR_SDK_INSTALL_DIR \
      python3 tools/juliet/juliet_suite.py --build-only$ARGS
  "

"$PYTHON_FOR_RUN" "$REPO/tools/juliet/juliet_suite.py" --run-only "$@"
