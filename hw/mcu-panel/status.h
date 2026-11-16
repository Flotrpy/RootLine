// Panel states, matching the controller's /status "state" field.
#pragma once

#include <string.h>

enum PanelState { STATE_UNKNOWN = -1, STATE_HEALTHY = 0, STATE_FAULTY = 1, STATE_DIAGNOSING = 2 };

inline PanelState parse_state(const char* s) {
  if (strcmp(s, "healthy") == 0) return STATE_HEALTHY;
  if (strcmp(s, "faulty") == 0) return STATE_FAULTY;
  if (strcmp(s, "diagnosing") == 0) return STATE_DIAGNOSING;
  return STATE_UNKNOWN;
}
