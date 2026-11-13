package flagd

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

const fixture = `{
  "$schema": "https://flagd.dev/schema/v0/flags.json",
  "flags": {
    "paymentFailure": {
      "description": "Fail payment service charge requests n%",
      "state": "ENABLED",
      "variants": {"100%": 1, "50%": 0.5, "off": 0},
      "defaultVariant": "off"
    },
    "adHighCpu": {
      "state": "ENABLED",
      "variants": {"on": true, "off": false},
      "defaultVariant": "on"
    },
    "noOffVariant": {
      "state": "ENABLED",
      "variants": {"a": 1, "b": 2},
      "defaultVariant": "a"
    }
  }
}`

func newStore(t *testing.T) *Store {
	t.Helper()
	p := filepath.Join(t.TempDir(), "demo.flagd.json")
	if err := os.WriteFile(p, []byte(fixture), 0o644); err != nil {
		t.Fatal(err)
	}
	return NewStore(p)
}

func TestSet(t *testing.T) {
	tests := []struct {
		name, flag, variant string
		wantErr             bool
	}{
		{"valid percentage", "paymentFailure", "50%", false},
		{"valid boolean", "adHighCpu", "off", false},
		{"unknown variant", "paymentFailure", "on", true},
		{"unknown flag", "nope", "on", true},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			s := newStore(t)
			err := s.Set(tt.flag, tt.variant)
			if (err != nil) != tt.wantErr {
				t.Fatalf("err = %v, wantErr %v", err, tt.wantErr)
			}
			if tt.wantErr {
				return
			}
			got, err := s.Get(tt.flag)
			if err != nil || got != tt.variant {
				t.Fatalf("Get = %q, %v", got, err)
			}
		})
	}
}

func TestResetAllAndPreservesFields(t *testing.T) {
	s := newStore(t)
	if err := s.Set("paymentFailure", "100%"); err != nil {
		t.Fatal(err)
	}
	if err := s.ResetAll(); err != nil {
		t.Fatal(err)
	}
	for flag, want := range map[string]string{"paymentFailure": "off", "adHighCpu": "off", "noOffVariant": "a"} {
		if got, _ := s.Get(flag); got != want {
			t.Errorf("%s = %q, want %q", flag, got, want)
		}
	}
	raw, err := os.ReadFile(s.path)
	if err != nil {
		t.Fatal(err)
	}
	var doc map[string]any
	if err := json.Unmarshal(raw, &doc); err != nil {
		t.Fatal(err)
	}
	if doc["$schema"] != "https://flagd.dev/schema/v0/flags.json" {
		t.Error("$schema was lost")
	}
	pf := doc["flags"].(map[string]any)["paymentFailure"].(map[string]any)
	if pf["description"] == nil || pf["state"] != "ENABLED" {
		t.Error("unknown fields were lost")
	}
}

func TestNoTempFilesLeft(t *testing.T) {
	s := newStore(t)
	if err := s.Set("adHighCpu", "off"); err != nil {
		t.Fatal(err)
	}
	entries, _ := os.ReadDir(filepath.Dir(s.path))
	if len(entries) != 1 {
		t.Fatalf("want only the flagd file, got %d entries", len(entries))
	}
}
