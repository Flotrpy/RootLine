// Rootline demo panel, Board B microcontroller (STM32U585, Arduino on Zephyr).
//
// Two buttons send "fault" and "reset" to the Linux-side bridge app over
// Arduino Bridge RPC; the bridge app calls the controller's HTTP API and
// sets the LEDs back through set_status. Wiring: see README.md.

#include <Arduino_RouterBridge.h>

#include "debounce.h"
#include "status.h"

const int PIN_BUTTON_FAULT = 2;     // to GND, internal pull-up
const int PIN_BUTTON_RESET = 3;     // to GND, internal pull-up
const int PIN_LED_HEALTHY = 5;      // green
const int PIN_LED_FAULTY = 6;       // red
const int PIN_LED_DIAGNOSING = 7;   // yellow
const uint32_t DEBOUNCE_MS = 30;

Debouncer faultButton(DEBOUNCE_MS);
Debouncer resetButton(DEBOUNCE_MS);

void show(PanelState state) {
  digitalWrite(PIN_LED_HEALTHY, state == STATE_HEALTHY ? HIGH : LOW);
  digitalWrite(PIN_LED_FAULTY, state == STATE_FAULTY ? HIGH : LOW);
  digitalWrite(PIN_LED_DIAGNOSING, state == STATE_DIAGNOSING ? HIGH : LOW);
}

// Called by the bridge app. provide_safe runs it between loop() passes, so
// the LED writes never race the button polling.
bool set_status(String state) {
  PanelState s = parse_state(state.c_str());
  if (s == STATE_UNKNOWN) {
    return false;
  }
  show(s);
  return true;
}

void setup() {
  pinMode(PIN_BUTTON_FAULT, INPUT_PULLUP);
  pinMode(PIN_BUTTON_RESET, INPUT_PULLUP);
  pinMode(PIN_LED_HEALTHY, OUTPUT);
  pinMode(PIN_LED_FAULTY, OUTPUT);
  pinMode(PIN_LED_DIAGNOSING, OUTPUT);

  // All LEDs on until the bridge app reports a state: a quick lamp test.
  digitalWrite(PIN_LED_HEALTHY, HIGH);
  digitalWrite(PIN_LED_FAULTY, HIGH);
  digitalWrite(PIN_LED_DIAGNOSING, HIGH);

  Bridge.begin();
  Bridge.provide_safe("set_status", set_status);
}

void loop() {
  uint32_t now = millis();
  // Buttons pull the pin low when pressed.
  if (faultButton.update(digitalRead(PIN_BUTTON_FAULT) == LOW, now)) {
    Bridge.notify("button_pressed", String("fault"));
  }
  if (resetButton.update(digitalRead(PIN_BUTTON_RESET) == LOW, now)) {
    Bridge.notify("button_pressed", String("reset"));
  }
  delay(2);
}
