#!/usr/bin/env bash
set -e

# CMAKE_BUILD_TYPE waehlt den VP-Buildtyp (Default Debug, wie bisher).
# Fuer Performance-Messungen: CMAKE_BUILD_TYPE=Release ./build_sim.sh


#Generate C-based glue code that exposes python functions (gluecode.py code ends up in _pydrofoilcapi_cffi.c)
#Compile the generated C glue code to an object file (_pydrofoilcapi_cffi.o)
#Compile a test C file (testmain.c) that uses the API functions
#Link both C files with the PyPy runtime library (libpypy3.11-c.so)
#Execute the test file (test main() -> API function -> PyPy interpreter runs python ISS)
./pypy-pydrofoil-scripting-experimental/bin/pypy3 build_ext.py
gcc -pthread -DNDEBUG -O2 -fPIC -I./pypy-pydrofoil-scripting-experimental/include/pypy3.11 -c _pydrofoilcapi_cffi.c -o ./_pydrofoilcapi_cffi.o
gcc -pthread -shared -Wl,-Bsymbolic-functions ./_pydrofoilcapi_cffi.o -L./pypy-pydrofoil-scripting-experimental/bin -L./pypy-pydrofoil-scripting-experimental/pypy/goal -lpypy3.11-c -o ./libpydrofoilcapi_cffi.so
gcc -pthread -I./pypy-pydrofoil-scripting-experimental/include/pypy3.11/ -Wl,-Bsymbolic-functions testmain.c ./_pydrofoilcapi_cffi.c -L ./pypy-pydrofoil-scripting-experimental/bin  -l pypy3.11-c -o testplugin
LD_LIBRARY_PATH=.:./pypy-pydrofoil-scripting-experimental/bin

#Build SystemC environment
mkdir -p build
cd build

cmake ../sysc_vp \
    -DCMAKE_PREFIX_PATH="${SYSTEMC_HOME}" \
    -DCMAKE_BUILD_TYPE="${CMAKE_BUILD_TYPE:-Debug}"

make -j"$(nproc)"
