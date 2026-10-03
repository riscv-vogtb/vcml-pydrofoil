#!/usr/bin/env bash
# Baut alle Benchmark-ELFs (thesis/messplan.md) im ubuntu:24.04-Container.
#
#   ./tools/bench/build.sh                       # Kalibrierbuild (GSF=1, SCALE=1)
#   GSF=40 MICRO_SCALE=20 ./tools/bench/build.sh  # nach der Kalibrierung (§9.1)
#   ONLY='micro__frame' ./tools/bench/build.sh    # nur passende Workload-IDs
#   SCALE_FILE=tools/bench/scales.tsv ./tools/bench/build.sh   # Faktor pro Workload
#
# Ausgabe: results/bench/elf/{htif,vp}/*.elf und results/bench/elf/manifest.tsv

set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

LLVM_TOOLCHAIN_PATH="${LLVM_TOOLCHAIN_PATH:-/scratch/vogtb/llvm-poison-install}"
ZEPHYR_SDK_INSTALL_DIR="${ZEPHYR_SDK_INSTALL_DIR:-$HOME/zephyr-sdk-0.17.4}"
BENCH_REPO="${BENCH_REPO:-/scratch/vogtb/Pydrofoil-RISCV-benchmarks}"
BUILD_IMAGE="${BUILD_IMAGE:-ubuntu:24.04}"

for d in "$LLVM_TOOLCHAIN_PATH/bin" "$ZEPHYR_SDK_INSTALL_DIR/riscv64-zephyr-elf" \
	"$BENCH_REPO/baremetal/riscv_tests/benchmarks" "$BENCH_REPO/baremetal/embench_iot/src"; do
	[[ -d $d ]] || { echo "fehlt: $d" >&2; exit 1; }
done

# Voller Build: alte ELFs/Objekte entfernen, damit das Manifest nur den
# aktuellen Build beschreibt (GSF/SCALE stehen pro Zeile drin). Ein ONLY-Build
# laesst den Rest stehen; sein Manifest beschreibt dann nur die Teilmenge.
if [[ "${ONLY:-.}" == "." ]]; then
	rm -rf "$REPO/results/bench/elf" "$REPO/results/bench/build"
fi

podman run --rm --security-opt label=disable \
	-e GSF="${GSF:-1}" -e WARMUP_HEAT="${WARMUP_HEAT:-1}" \
	-e MICRO_SCALE="${MICRO_SCALE:-1}" -e ONLY="${ONLY:-.}" \
	-e SCALE_FILE="${SCALE_FILE:-}" \
	-v "$LLVM_TOOLCHAIN_PATH:/llvm:ro" \
	-v "$ZEPHYR_SDK_INSTALL_DIR/riscv64-zephyr-elf:/sdk:ro" \
	-v "$BENCH_REPO/baremetal:/bm:ro" \
	-v "$REPO:/repo" \
	"$BUILD_IMAGE" bash /repo/tools/bench/build_in_container.sh
