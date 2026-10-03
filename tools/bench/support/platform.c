/*
 * Plattformschicht fuer beide Messpfade, ersetzt riscv-tests' syscalls.c.
 * Ein Backend wird beim Bauen gewaehlt:
 *
 *   -DBENCH_PLATFORM_HTIF  Pfad 1, Standalone-Pydrofoil
 *   -DBENCH_PLATFORM_VP    Pfad 2, sysc_vp
 *
 * Bis auf Zeichenausgabe und Programmende ist der Harness damit in beiden
 * Pfaden identisch (printf ueber newlib's vsnprintf, _init, exit, abort).
 *
 * Warum nicht syscalls.c: dessen printf laeuft ueber den HTIF-Syscall-Proxy
 * (Zeiger auf magic_mem in tohost, Warten auf fromhost). Das Sail-Modell
 * implementiert vom Geraet 0 nur Exit und setzt fromhost nie
 * (model/riscv_platform.sail: htif_store, "todo: fromhost"); jedes printf
 * haengt dort endlos.
 *
 * HTIF (riscv_platform.sail, htif_store):
 *   Exit:     tohost = (code << 1) | 1                 Geraet 0, Bit 0 gesetzt
 *   Putchar:  tohost = 1 << 56 | 1 << 48 | Zeichen     Geraet 1, Kommando 1
 *   Ein 64-Bit-Store gilt als vollstaendiges Kommando und wird sofort
 *   ausgefuehrt; der Terminal-Zweig quittiert per reset_htif().
 *
 * VP:
 *   Ausgabe ueber den nRF51-UART (Registerfolge wie
 *   sw/zephyr/drivers/serial/uart_pydrofoil.c; TXD ist synchron).
 *   Ende ueber das simdev-STOP-Register, NICHT ueber EXIT: EXIT ruft ::exit()
 *   innerhalb von sc_start(), dann druckt der VP seinen Performance-Block
 *   (sysc_vp/src/system.cpp) nie (messplan.md §8.2). Der Exit-Code geht dabei
 *   verloren und wird deshalb vorher ausgegeben:  BENCH-EXIT: code=<n>
 *   Nach dem STOP laeuft der Kern bis zum Ende des Quantums weiter (Spin).
 */

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "bench.h"

#if defined(BENCH_PLATFORM_HTIF) == defined(BENCH_PLATFORM_VP)
#error "genau eines von BENCH_PLATFORM_HTIF / BENCH_PLATFORM_VP definieren"
#endif

/* Auch im VP noetig: crt.S schreibt im Fehlerpfad (kein FPU) nach tohost. */
volatile uint64_t tohost __attribute__((section(".tohost")));
volatile uint64_t fromhost __attribute__((section(".tohost")));

#ifdef BENCH_PLATFORM_HTIF

#define HTIF_CMD(dev, cmd, payload) \
	(((uint64_t)(dev) << 56) | ((uint64_t)(cmd) << 48) | (uint64_t)(payload))

static void platform_init(void)
{
}

static void platform_putchar(int ch)
{
	tohost = HTIF_CMD(1, 1, (uint8_t)ch);
}

static void __attribute__((noreturn)) platform_exit(int code)
{
	tohost = ((uint64_t)(unsigned)code << 1) | 1;
	for (;;)
		;
}

#else /* BENCH_PLATFORM_VP */

#define VP_UART_BASE 0x10009000UL
#define NRF51_STARTTX 0x008
#define NRF51_ENABLE 0x500
#define NRF51_TXD 0x51c
#define NRF51_ENABLE_ON 4u
#define NRF51_TASK_TRIGGER 1u

#define VP_SIMDEV_STOP 0x10008000UL

static inline void mmio_write32(unsigned long addr, uint32_t val)
{
	*(volatile uint32_t *)addr = val;
}

static void platform_init(void)
{
	mmio_write32(VP_UART_BASE + NRF51_ENABLE, NRF51_ENABLE_ON);
	mmio_write32(VP_UART_BASE + NRF51_STARTTX, NRF51_TASK_TRIGGER);
}

static void platform_putchar(int ch)
{
	mmio_write32(VP_UART_BASE + NRF51_TXD, (uint8_t)ch);
}

static void __attribute__((noreturn)) platform_exit(int code)
{
	printf("BENCH-EXIT: code=%d\n", code);
	mmio_write32(VP_SIMDEV_STOP, 1);
	for (;;)
		;
}

#endif

#undef putchar
int putchar(int ch)
{
	platform_putchar(ch);
	return ch;
}

void printstr(const char *s)
{
	while (*s)
		platform_putchar(*s++);
}

int puts(const char *s)
{
	printstr(s);
	platform_putchar('\n');
	return 0;
}

/* Nur Ganzzahl-/String-Formate werden genutzt (BENCH-Zeile, dhrystone);
 * newlib's vsnprintf allokiert dafuer nicht. */
int printf(const char *fmt, ...)
{
	char buf[256];
	va_list ap;
	int n;

	va_start(ap, fmt);
	n = vsnprintf(buf, sizeof(buf), fmt, ap);
	va_end(ap);
	printstr(buf);
	return n;
}

void __attribute__((noreturn)) exit(int code)
{
	platform_exit(code);
}

void __attribute__((noreturn)) abort(void)
{
	exit(134);
}

extern int main(int argc, char **argv);

/* wie in riscv-tests' syscalls.c */
static void init_tls(void)
{
	register void *thread_pointer asm("tp");
	extern char _tdata_begin, _tdata_end, _tbss_end;
	size_t tdata_size = &_tdata_end - &_tdata_begin;
	memcpy(thread_pointer, &_tdata_begin, tdata_size);
	size_t tbss_size = &_tbss_end - &_tdata_end;
	memset((char *)thread_pointer + tdata_size, 0, tbss_size);
}

/* Einsprung aus crt.S (j _init). Beide Plattformen sind einkernig. */
void _init(int cid, int nc)
{
	(void)cid;
	(void)nc;
	init_tls();
	platform_init();
	exit(main(0, 0));
}
