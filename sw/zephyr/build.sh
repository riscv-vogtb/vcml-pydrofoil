#!/usr/bin/env bash
# Build a Zephyr application for the vcml-pydrofoil virtual platform.
#
#   ./build.sh hello_world pydrofoil_32
#   ./build.sh hello_world pydrofoil_64
#
# Everything specific to the VP lives in this directory and is injected into an
# otherwise untouched Zephyr tree via BOARD_ROOT / DTS_ROOT / ZEPHYR_EXTRA_MODULES.
#
# Set ZEPHYR_WORKSPACE to reuse an existing west workspace. Without it, one is
# bootstrapped into ./workspace, but only after asking -- that download is
# several gigabytes.

set -e

SOURCE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Upstream Zephyr revision this tree is validated against. Luis' local_backup
# branch is exactly this commit plus one of his own, holding his in-tree board
# and samples -- both replaced by the boards, dts and app next to this script.
# Bump only after checking that every board still builds and boots.
ZEPHYR_URL="https://github.com/zephyrproject-rtos/zephyr"
ZEPHYR_REV="8a0b4d715ae5d8473da9e6fc98a49a041437fa46"

if [[ $# -ne 2 ]]; then
  echo "Usage: $0 <application_name> <board>"
  echo "  applications: $(cd "$SOURCE/app" && echo */ | tr -d '/')"
  echo "  boards:       pydrofoil_32 pydrofoil_64"
  exit 1
fi

APP="$1"
APP_PATH="$SOURCE/app/$APP"
BOARD="$2"

if [[ ! -d "$APP_PATH" ]]; then
  echo "Error: application not found at '$APP_PATH'"
  exit 1
fi

# The SDK provides riscv64-zephyr-elf, which builds both rv32 and rv64.
export ZEPHYR_TOOLCHAIN_VARIANT="${ZEPHYR_TOOLCHAIN_VARIANT:-zephyr}"
export ZEPHYR_SDK_INSTALL_DIR="${ZEPHYR_SDK_INSTALL_DIR:-$HOME/zephyr-sdk-0.17.4}"

# Zephyr requires Python >= 3.12; `python3` defaults to 3.6 on RHEL 8.
PYTHON_FOR_VENV=python3.12

WORKSPACE="${ZEPHYR_WORKSPACE:-$SOURCE/workspace}"

if [[ ! -d "$WORKSPACE/zephyr" ]]; then
  cat <<EOF

No Zephyr workspace found at:
    $WORKSPACE

Bootstrapping one downloads the Zephyr tree and its modules (several GB) and
installs the Python dependencies. To reuse a workspace you already have, abort
and re-run with:

    ZEPHYR_WORKSPACE=/path/to/zephyrproject $0 $*

EOF
  read -r -p "Bootstrap a new workspace here? [y/N] " reply
  [[ "$reply" =~ ^[Yy]$ ]] || { echo "Aborted."; exit 1; }

  mkdir -p "$WORKSPACE"
  cd "$WORKSPACE"
  "$PYTHON_FOR_VENV" -m venv .venv
  source "$WORKSPACE/.venv/bin/activate"
  pip install --quiet west
  # The revision has to be checked out after cloning: west turns --mr into
  # git clone --branch, which takes branches and tags but not commit hashes.
  # west update then reads west.yml at that revision and pins the modules.
  west init -m "$ZEPHYR_URL" .
  git -C zephyr checkout --quiet "$ZEPHYR_REV"
  west update
  west zephyr-export
  west packages pip --install
else
  # west lives in the workspace venv; fall back to whatever is on PATH.
  for venv in "$WORKSPACE/.venv" "$WORKSPACE/zephyr/.venv"; do
    if [[ -f "$venv/bin/activate" ]]; then
      source "$venv/bin/activate"
      break
    fi
  done
fi

export ZEPHYR_BASE="$WORKSPACE/zephyr"
cd "$ZEPHYR_BASE"

# One build directory per application and board. west refuses to reuse a build
# directory for a different application, and mixing boards in one would carry
# over the previous board's generated headers. Keeping them apart also makes
# rebuilds incremental -- devicetree and Kconfig files land in
# CMAKE_CONFIGURE_DEPENDS, so edits under this directory still retrigger CMake.
BUILD_DIR="$ZEPHYR_BASE/build/$APP-$BOARD"

# Pass the roots only on the first configure. west forces a full CMake re-run
# whenever arguments follow --, which costs ~9 s even when nothing changed; after
# the first run they are in the CMakeCache anyway.
if [[ -f "$BUILD_DIR/CMakeCache.txt" ]]; then
  west build --build-dir "$BUILD_DIR" -b "$BOARD" "$APP_PATH"
else
  EXTRA_CMAKE_ARGS=(
    -DBOARD_ROOT="$SOURCE"
    -DDTS_ROOT="$SOURCE"
    -DZEPHYR_EXTRA_MODULES="$SOURCE/drivers;$SOURCE/lib"
  )
  if [[ "$ZEPHYR_TOOLCHAIN_VARIANT" == "llvm" ]]; then
    # DTS preprocessing calls clang directly, without CMake's usual --target
    # injection; clang's own default triple may not even be valid.
    case "$BOARD" in
      *64) triple=riscv64-unknown-elf ;;
      *) triple=riscv32-unknown-elf ;;
    esac
    EXTRA_CMAKE_ARGS+=(-DDTS_EXTRA_CPPFLAGS=--target=$triple)
    # Default linker is the SDK's cross ld; use the self-contained lld instead.
    EXTRA_CMAKE_ARGS+=(-DCONFIG_LLVM_USE_LLD=y)
    # Default runtime lib is GCC's libgcc regardless of toolchain; use compiler-rt.
    EXTRA_CMAKE_ARGS+=(-DCONFIG_COMPILER_RT_RTLIB=y)
    # The llvm variant here is for -riscv-stack-poison testing, which only
    # instruments real stack loads/stores -- -O0 keeps those from being
    # optimized away. lld can't relocate the kernel's TLS accessors at -O0,
    # so TLS (unused by these apps) is dropped too.
    EXTRA_CMAKE_ARGS+=(-DCONFIG_NO_OPTIMIZATIONS=y)
    EXTRA_CMAKE_ARGS+=(-DCONFIG_THREAD_LOCAL_STORAGE=n)
  fi
  west build --build-dir "$BUILD_DIR" -b "$BOARD" "$APP_PATH" -- "${EXTRA_CMAKE_ARGS[@]}"
fi

# Copy the artifacts next to the application so the VP configs can reference a
# stable path instead of reaching into the west build directory.
out="$APP_PATH/build/$BOARD"
mkdir -p "$out"
for f in zephyr.elf zephyr.bin; do
  src="$BUILD_DIR/zephyr/$f"
  [[ -f "$src" ]] || { echo "Error: $f not produced at '$src'"; exit 1; }
  cp "$src" "$out/"
done
# Kept for diffing what the board definition actually resolved to.
cp "$BUILD_DIR/zephyr/zephyr.dts" "$out/" 2>/dev/null || true
cp "$BUILD_DIR/zephyr/.config" "$out/" 2>/dev/null || true

# Best-effort: needs glibc >= 2.39 for this LLVM build, so silently skip on
# hosts where it can't run (see README).
if [[ "$ZEPHYR_TOOLCHAIN_VARIANT" == "llvm" ]]; then
  "$LLVM_TOOLCHAIN_PATH/bin/llvm-objdump" -d "$out/zephyr.elf" > "$out/zephyr.elf.dump" 2>/dev/null || rm -f "$out/zephyr.elf.dump"
fi

echo
echo "Artifacts in ${out#"$SOURCE"/}:"
ls -1 "$out"
