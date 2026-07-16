#include <stdint.h>

#define UART_BASE 0x10009000
#define PLIC_BASE 0x1000a000
#define SIMDEV_STOP 0x10008000

#define NIRQ 1024
#define NIRQ_LINES 32                  // Number of interrupt lines per register
#define NUM_EN_REG (NIRQ / NIRQ_LINES) // Number of enable registers per context

#define UART_IRQ 5
#define PLIC_CTX_M 0

#define UART_START_RX (*(volatile uint8_t *)(UART_BASE + 0x0))
#define UART_START_TX (*(volatile uint8_t *)(UART_BASE + 0x8))
#define UART_IRQ_EN (*(volatile uint32_t *)(UART_BASE + 0x300))
#define UART_ENABLE (*(volatile uint32_t *)(UART_BASE + 0x500))
#define UART_RX (*(volatile uint8_t *)(UART_BASE + 0x518))
#define UART_TX (*(volatile uint8_t *)(UART_BASE + 0x51c))

#define UART_BAUDRATE (*(volatile uint32_t *)(UART_BASE + 0x524))

// More might be necessary to configure the uart

// Context: A context is an interrupt source group of a specific privilege
//          level (Machine or Supervisor mode) on a specific hardware thread (Hart).

#define PLIC_PRIORITY(id) \
    (*(volatile uint32_t *)(PLIC_BASE + (id) * 4))

// For each context, the PLIC stores enable bits of every interrupt sources
#define PLIC_ENABLE(ctx, id) \
    (*(volatile uint32_t *)(PLIC_BASE + 0x2000 + (ctx) * NUM_EN_REG * 4 + ((id) / 32) * 4))

// For each context, the PLIC has 1 threshold register and 1 claim register
// The spacing between threshold registers is of 0x1000, the rest is free (reserved)
#define PLIC_THRESHOLD(ctx) \
    (*(volatile uint32_t *)(PLIC_BASE + 0x200000 + (ctx) * 0x1000))

#define PLIC_CLAIM(ctx) \
    (*(volatile uint32_t *)(PLIC_BASE + 0x200004 + (ctx) * 0x1000))

volatile int irq_flag = 0;

// Write the mask parameter to the mie register (machine interrupt enable)
// This can enable the machine software/timer/external interrupt
static inline void csr_set_mie(uintptr_t mask)
{
    asm volatile("csrs mie, %0" ::"r"(mask));
}

// Setting the global machine interrupt enable bit
static inline void csr_set_mstatus(uintptr_t mask)
{
    asm volatile("csrs mstatus, %0" ::"r"(mask));
}

void uart_putc(char c)
{
    UART_START_TX = 1;
    UART_TX = c;
    UART_START_TX = 0;
}

void uart_print(char *s)
{
    while (*s)
        uart_putc(*s++);
}

void uart_print_long(long value)
{
    char buf[32];
    int i = 0;
    int neg = 0;

    if (value == 0)
    {
        uart_putc('0');
        return;
    }

    if (value < 0)
    {
        neg = 1;
        value = -value;
    }

    while (value > 0)
    {
        buf[i++] = '0' + (value % 10);
        value /= 10;
    }

    if (neg)
        uart_putc('-');

    while (i > 0)
        uart_putc(buf[--i]);
}

void m_irq_handler(void)
{
    uint32_t irq = PLIC_CLAIM(PLIC_CTX_M);

    if (irq == UART_IRQ)
    {
        char data = UART_RX;
        uart_print(&data);
        irq_flag = 1;
    }

    PLIC_CLAIM(PLIC_CTX_M) = irq;
}

void plic_init(void)
{

    // priority
    PLIC_PRIORITY(UART_IRQ) = 1;

    // enable UART IRQ
    PLIC_ENABLE(PLIC_CTX_M, UART_IRQ) |=
        (1 << (UART_IRQ % 32));

    // allow all priorities
    PLIC_THRESHOLD(PLIC_CTX_M) = 0;
}

void uart_init(void)
{
    // other things are probably missing
    UART_ENABLE = 0x4;
    UART_BAUDRATE = 0x00275000;
    UART_IRQ_EN = 4; // enable rx interrupt
    UART_START_RX = 1;
}

// called from assembly trap entry
void trap_dispatch(void)
{

    uintptr_t cause;
    asm volatile("csrr %0, mcause" : "=r"(cause));

    int is_interrupt = cause >> (sizeof(uintptr_t) * 8 - 1);
    int code = cause & 0xfff;

    if (is_interrupt && code == 11)
        m_irq_handler();
}

void stop_simulation()
{
    *((int *)SIMDEV_STOP) = 1; // stop the simulation using the simdev

    while (1)
    {
        asm volatile("wfi");
    }
}

__attribute__((noinline, noclone, noipa)) static void mpoison(long offset, long len)
{

    // .insn r opcode, funct3, funct7, rd, rs1, rs2
    asm volatile(".insn r 0x0b, 0x0, 0x00, x0, %0, %1"
                 :
                 : "r"(offset), "r"(len)
                 : "memory");
}
__attribute__((noinline, noclone, noipa)) static void munpoison(long offset, long len)
{

    // .insn r opcode, funct3, funct7, rd, rs1, rs2
    asm volatile(
        ".insn r 0x0b, 0x1, 0x00, x0, %0, %1"
        :
        : "r"(offset), "r"(len)
        : "memory");
}
__attribute__((noinline, noclone, noipa)) static long mcheckpoison(long offset, long len)
{
    long result;

    // .insn r opcode, funct3, funct7, rd, rs1, rs2
    asm volatile(".insn r 0x0b, 0x2, 0x00, %0, %1, %2"
                 : "=r"(result)
                 : "r"(offset), "r"(len)
                 : "memory");

    return result;
}

int main(void)
{

    uart_init();
    plic_init();

    uart_print("Booting interrupt demo...\n");

    // enable supervisor external interrupt
    csr_set_mie(1 << 11);    // MEIE
    csr_set_mstatus(1 << 3); // global MIE

    while (!irq_flag)
        ;
    uart_print("Interrupt received\n");
    long res;
    res = mcheckpoison(0x20, 8);
    uart_print("Result: ");
    uart_print_long(res);

    mpoison(0x20, 8);

    res = mcheckpoison(0x20, 8);
    uart_print("Result: ");
    uart_print_long(res);

    munpoison(0x20, 8);

    res = mcheckpoison(0x20, 8);
    uart_print("Result: ");
    uart_print_long(res);
    uart_putc('\n');

    stop_simulation();
}