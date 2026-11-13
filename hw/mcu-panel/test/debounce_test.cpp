// Desktop unit tests for the panel's pure logic:
//   g++ -std=c++17 -Wall -Wextra -Werror -I.. debounce_test.cpp -o t && ./t
#include <cassert>
#include <cstdint>
#include <cstdio>

#include "debounce.h"
#include "status.h"

static int presses(Debouncer& d, const bool* raw, int n, uint32_t start, uint32_t step) {
  int count = 0;
  for (int i = 0; i < n; i++) count += d.update(raw[i], start + i * step);
  return count;
}

int main() {
  {  // Clean press held 50 ms: exactly one event.
    Debouncer d(30);
    bool raw[60];
    for (int i = 0; i < 60; i++) raw[i] = i >= 5 && i < 55;
    assert(presses(d, raw, 60, 0, 1) == 1);
  }
  {  // Contact bounce, then held: still one event.
    Debouncer d(30);
    bool raw[] = {1, 0, 1, 0, 1, 1, 0, 1};
    int n = presses(d, raw, 8, 0, 2);
    for (uint32_t t = 16; t < 80; t++) n += d.update(true, t);
    assert(n == 1);
    assert(d.pressed());
  }
  {  // Glitch shorter than the settle time: no event.
    Debouncer d(30);
    int n = 0;
    for (uint32_t t = 0; t < 20; t++) n += d.update(true, t);
    for (uint32_t t = 20; t < 100; t++) n += d.update(false, t);
    assert(n == 0);
  }
  {  // Two separate presses: two events.
    Debouncer d(30);
    int n = 0;
    for (uint32_t t = 0; t < 300; t++) n += d.update((t / 100) % 2 == 0, t);
    assert(n == 2);
  }
  {  // millis() wrap-around mid-press.
    Debouncer d(30);
    int n = 0;
    uint32_t start = 0xFFFFFFF0u;
    for (uint32_t i = 0; i < 60; i++) n += d.update(true, start + i);
    assert(n == 1);
  }
  assert(parse_state("healthy") == STATE_HEALTHY);
  assert(parse_state("faulty") == STATE_FAULTY);
  assert(parse_state("diagnosing") == STATE_DIAGNOSING);
  assert(parse_state("broken") == STATE_UNKNOWN);
  std::puts("debounce/status tests passed");
  return 0;
}
