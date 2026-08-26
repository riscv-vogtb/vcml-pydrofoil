## Installation / Prerequisites

### Python

python3.12 must be installed. Otherwise, change the version (> 3.12) in build.sh

### Zephyr SDK

We expect zephyr SDK to exist under
$HOME/zephyr-sdk-0.17.4 (or set ZEPHYR_SDK_INSTALL_DIR)

To install only riscv:

```bash
cd "$HOME"
wget https://github.com/zephyrproject-rtos/sdk-ng/releases/download/v0.17.4/zephyr-sdk-0.17.4_linux-x86_64_minimal.tar.xz
tar xf zephyr-sdk-0.17.4_linux-x86_64_minimal.tar.xz
rm zephyr-sdk-0.17.4_linux-x86_64_minimal.tar.xz

cd zephyr-sdk-0.17.4
./setup.sh -t riscv64-zephyr-elf -h -c
```

(to install more, remove the "-t riscv64-zephyr-elf")


## Building

### Native (Ubuntu 24.04):

```bash
export ZEPHYR_TOOLCHAIN_VARIANT=llvm
export LLVM_TOOLCHAIN_PATH=/scratch/vogtb/llvm-poison-install
./build.sh juliet_cwe457_int_array_declare_no_init_01 pydrofoil_64
```

Needs glibc >= 2.39 (e.g. Ubuntu 24.04+); older hosts need the podman path below.

### Using podman:

```bash
podman run --rm --security-opt label=disable \
  -v /scratch/vogtb/vcml-pydrofoil:/scratch/vogtb/vcml-pydrofoil \
  -v /net/home/vogtb/zephyr-sdk-0.17.4:/net/home/vogtb/zephyr-sdk-0.17.4:ro \
  -v /scratch/vogtb/llvm-poison-install:/scratch/vogtb/llvm-poison-install:ro \
  ubuntu:24.04 bash -c '
    apt-get update -qq && apt-get install -y -qq cmake ninja-build python3 python3-venv device-tree-compiler git
    cd /scratch/vogtb/vcml-pydrofoil/sw/zephyr
    ZEPHYR_TOOLCHAIN_VARIANT=llvm LLVM_TOOLCHAIN_PATH=/scratch/vogtb/llvm-poison-install \
    ZEPHYR_SDK_INSTALL_DIR=/net/home/vogtb/zephyr-sdk-0.17.4 \
      ./build.sh juliet_cwe457_int_array_declare_no_init_01 pydrofoil_64
  '
```

## llvm-objdump

### Native (Ubuntu 24.04):

```bash
/scratch/vogtb/llvm-poison-install/bin/llvm-objdump -d \
  app/juliet_cwe457_int_array_declare_no_init_01/build/pydrofoil_64/zephyr.elf
```

### Using podman:

```bash
podman run --rm --security-opt label=disable \
  -v /scratch/vogtb/llvm-poison-install:/scratch/vogtb/llvm-poison-install:ro \
  -v /scratch/vogtb/vcml-pydrofoil:/scratch/vogtb/vcml-pydrofoil:ro \
  ubuntu:24.04 \
  /scratch/vogtb/llvm-poison-install/bin/llvm-objdump -d \
  /scratch/vogtb/vcml-pydrofoil/sw/zephyr/app/juliet_cwe457_int_array_declare_no_init_01/build/pydrofoil_64/zephyr.elf
```


## Instructions for new apps

Apps that test mpoison should add
`target_compile_options(app PRIVATE -mllvm -riscv-stack-poison)`
to their CMakeLists

Example in `app/mpoison_minimal`

