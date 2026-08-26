from _pydrofoilcapi_cffi import ffi
import _pydrofoil

import sys
sys.modules['__main__'] = type(sys)('__main__')

all_cpu_handles = []

class C:
    def __init__(self, rv64, n=None):
        self.rv64 = rv64
        self.arg = n
        self.callbacks = None
        self.dma_regions = []  # list of (base_address, size, memory_buffer)
        self.breakpoints = []  # list of breakpoints
        self.verbosity = True
        self.reset()

    def _set_callbacks(self, read, write, payload):
        self.read = read
        self.write = write
        self.mem = ffi.new('uint64_t[1]')
        
        WIDTH_MAP = {
            8: ('uint64_t*', 64),
            4: ('uint32_t*', 32),
            2: ('uint16_t*', 16),
            1: ('uint8_t*', 8),
        }

        def resolve_width(width):
            try:
                return WIDTH_MAP[width]
            except KeyError:
                raise ValueError(f"Unsupported width: {width}")
            
        
        def dma_lookup(addr, ptr_type):
            for base, size, memory in self.dma_regions:
                if base <= addr < base + size:
                    offset = addr - base
                    return ffi.cast(ptr_type, memory + offset)
            return None

        def pyread(addr, width):
            addr = int(addr)
            ptr_type, bitv_size = resolve_width(width)

            # Check DMA regions first
            ptr = dma_lookup(addr, ptr_type)
            if ptr is not None:
                return _pydrofoil.bitvector(bitv_size, ptr[0])

            # Fall back to callback
            res = self.read(self._handle, addr, width, ffi.cast(ptr_type, self.mem), payload)
            assert res == 0
            return _pydrofoil.bitvector(bitv_size, self.mem[0])
        
        def pywrite(addr, width, value):
            addr = int(addr)
            value = int(value)
            ptr_type, bitv_size = resolve_width(width)

            # Check DMA regions first
            ptr = dma_lookup(addr, ptr_type)
            if ptr is not None: # How useful can it be if we're not using ptr afterwards?
                ptr[0] = value
                return

            # Fall back to callback
            res = self.write(self._handle, addr, width, value, payload)
            assert res == 0
        self.callbacks = _pydrofoil.Callbacks(mem_read_intercept=pyread, mem_write_intercept=pywrite)

    def set_verbosity(self, verbosity):
        self.verbosity = verbosity
        self.cpu.set_verbosity(verbosity)

    def step(self):
        self.steps += 1
        self.cpu.step()

    def reset(self):
        if self.rv64:
            cls = _pydrofoil.RISCV64
        else:
            cls = _pydrofoil.RISCV32
        if self.callbacks:
            self.cpu = cls(self.arg, callbacks=self.callbacks)
        else:
            self.cpu = cls(self.arg)
        self.steps = 0
        self.cpu._set_sail_memory_bounds(0x00000000, 0x4000000000)
        self.set_verbosity(self.verbosity)
        # Sail defaults rv_htif_tohost to 0x80001000, which sits inside the
        # loaded image. HTIF addresses are excluded from physical memory, so a
        # fetch from there raises an instruction access fault. Move it out of
        # the way of anything the VP maps.
        self.cpu._set_htif_tohost(0x900F0000)

@ffi.def_extern()
def pydrofoil_allocate_cpu(spec, fn):
    if spec:
        rv64 = "64" in ffi.string(spec).decode('utf-8')
    else:
        rv64 = True
    if fn:
        filename = ffi.string(fn).decode('utf-8')
    else:
        filename = None
    print("rv64" if rv64 else "rv32")
    print(filename)

    all_cpu_handles.append(res := ffi.new_handle(cpu := C(rv64, filename)))
    cpu._handle = res
    return res

@ffi.def_extern()
def pydrofoil_free_cpu(i):
    try:
        all_cpu_handles.remove(i)
    except Exception:
        return -1
    return 0

@ffi.def_extern()
def pydrofoil_cpu_set_pc(i, value):
    cpu = ffi.from_handle(i)
    cpu.cpu.write_register('pc', value)
    cpu.reset()
    return 0


@ffi.def_extern()
def pydrofoil_cpu_pc(i):
    cpu = ffi.from_handle(i)
    return cpu.cpu.read_register('pc')

@ffi.def_extern()
def pydrofoil_cpu_set_breakpoint(i, addr):
    cpu = ffi.from_handle(i)
    
    if addr in cpu.breakpoints:
        return 0
    
    cpu.breakpoints.append(addr)
    return 0

@ffi.def_extern()
def pydrofoil_cpu_remove_breakpoint(i, addr):
    cpu = ffi.from_handle(i)

    try:
        cpu.breakpoints.remove(addr)
        return 0
    except ValueError:
        return 1


@ffi.def_extern()
def pydrofoil_cpu_set_ram_read_write_callback(i, read_cb, write_cb, payload):
    cpu = ffi.from_handle(i)
    cpu._set_callbacks(read_cb, write_cb, payload)
    cpu.reset()
    return 0

@ffi.def_extern()
def pydrofoil_cpu_simulate(i, steps):
    cpu = ffi.from_handle(i)
    cpu.steps = 0

    for _ in range(steps):

        if cpu.breakpoints: # Only if the breakpoint list is not empty, read the pc
            pc_val = cpu.cpu.read_register('pc')

            if pc_val in cpu.breakpoints: # Check if the pc is in the list
                return cpu.steps # return if it is

        cpu.step()
    return cpu.steps

@ffi.def_extern()
def pydrofoil_cpu_cycles(i):
    cpu = ffi.from_handle(i)
    return cpu.steps

@ffi.def_extern()
def pydrofoil_cpu_read_reg(i, name):
    cpu = ffi.from_handle(i)
    try:
        reg_name = ffi.string(name).decode('utf-8')
        return cpu.cpu.read_register(reg_name)
    except ValueError:
        print("Register " + reg_name + " not found")
        return 1

@ffi.def_extern()
def pydrofoil_set_interrupt_pending(i, value):
    cpu = ffi.from_handle(i)

    bit_size = 64 if cpu.rv64 else 32

    if value > 0:
        cpu.cpu.write_register('mip', _pydrofoil.bitvector(bit_size, 1) << value)
    else:
        cpu.cpu.write_register('mip', _pydrofoil.bitvector(bit_size, 0))

    mstatus = cpu.cpu.lowlevel.read_CSR(0x300)
    mie = cpu.cpu.lowlevel.read_CSR(0x304)
    mip = cpu.cpu.lowlevel.read_CSR(0x344)
    print("value, mstatus, mie, mip:", value, hex(mstatus), hex(mie), hex(mip))
    return 0

@ffi.def_extern()
def pydrofoil_cpu_reset(i):
    cpu = ffi.from_handle(i)
    cpu.reset()
    return 0

@ffi.def_extern()
def pydrofoil_cpu_set_verbosity(i, v):
    cpu = ffi.from_handle(i)
    cpu.set_verbosity(bool(v))
    return 0

@ffi.def_extern()
def pydrofoil_cpu_write_reg(i, name, val):
    cpu = ffi.from_handle(i)
    reg_name = ffi.string(name).decode('utf-8')
    try:
        cpu.cpu.write_register(reg_name, val)
        return 0
    except ValueError:
        print("Register " + reg_name + " not found")
        return 1

@ffi.def_extern()
def pydrofoil_cpu_set_dma_region(i, base_address, size, memory):
    cpu = ffi.from_handle(i)
    if cpu.callbacks is None:
        return -1  # RAM callbacks must be set first
    cpu.dma_regions.append((base_address, size, memory))
    return 0

sys.modules['__main__'].__dict__.update(globals())
sys.argv = ['embedded-pypy']
