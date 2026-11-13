// Button debouncing with no Arduino dependencies, so it can be unit-tested
// on a desktop (test/debounce_test.cpp).
#pragma once

#include <stdint.h>

class Debouncer {
 public:
  explicit Debouncer(uint32_t settle_ms) : settle_ms_(settle_ms) {}

  // Feed the raw reading (true = pressed) and the current time in ms.
  // Returns true exactly once per press: when the input has stayed pressed
  // for settle_ms after being released. millis() wrap-around is handled by
  // unsigned subtraction.
  bool update(bool raw_pressed, uint32_t now_ms) {
    if (raw_pressed != last_raw_) {
      last_raw_ = raw_pressed;
      changed_at_ = now_ms;
      return false;
    }
    if (raw_pressed != stable_ && (uint32_t)(now_ms - changed_at_) >= settle_ms_) {
      stable_ = raw_pressed;
      return stable_;
    }
    return false;
  }

  bool pressed() const { return stable_; }

 private:
  uint32_t settle_ms_;
  bool last_raw_ = false;
  bool stable_ = false;
  uint32_t changed_at_ = 0;
};
