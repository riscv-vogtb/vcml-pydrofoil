#include "uart_injector.h"

void UartInjector::uart_transmit()
{
  while (true)
  {
    wait(sc_ev);
    uart_tx.send(uart_data);
  }
}

void UartInjector::send_to_guest(uint8_t data)
{
  uart_data = data;
  vcml::on_next_update([&]() -> void
                       { sc_ev.notify(sc_core::SC_ZERO_TIME); });
}

UartInjector::UartInjector(const sc_core::sc_module_name &nm)
    : module(nm),
      sc_ev("rxev"),
      uart_tx("uart_tx")
{
  SC_HAS_PROCESS(UartInjector);
  SC_THREAD(uart_transmit);
}

UartInjector::~UartInjector()
{
}
