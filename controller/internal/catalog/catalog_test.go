package catalog

import (
	"bytes"
	"encoding/json"
	"reflect"
	"slices"
	"testing"
)

func TestCatalogShape(t *testing.T) {
	all := All()
	if len(all) != 15 {
		t.Fatalf("want 15 incident types, got %d", len(all))
	}
	counts := map[Layer]int{}
	seen := map[string]bool{}
	for _, f := range all {
		if seen[f.Name] {
			t.Errorf("duplicate fault %q", f.Name)
		}
		seen[f.Name] = true
		counts[f.Layer]++
		if !slices.Contains(Categories(), f.Category) {
			t.Errorf("%s: unknown category %q", f.Name, f.Category)
		}
		switch f.Kind {
		case KindFlag:
			if f.Flag == "" || f.Variant == "" {
				t.Errorf("%s: flag fault needs flag and variant", f.Name)
			}
		case KindToxic:
			if f.Toxic == nil || f.Edge == "" {
				t.Errorf("%s: toxic fault needs toxic and edge", f.Name)
			}
		case KindNetem:
			if f.LossPct <= 0 || f.Edge == "" {
				t.Errorf("%s: netem fault needs loss and edge", f.Name)
			}
		}
	}
	want := map[Layer]int{LayerApplication: 10, LayerNetwork: 4, LayerNone: 1}
	for l, n := range want {
		if counts[l] != n {
			t.Errorf("layer %s: want %d, got %d", l, n, counts[l])
		}
	}
}

func TestIncidentIDRoundTrip(t *testing.T) {
	tests := []struct {
		id      string
		fault   string
		replica int
		wantErr bool
	}{
		{"paymentFailure-r1", "paymentFailure", 1, false},
		{"toxiLatency-r2", "toxiLatency", 2, false},
		{"healthy-r12", "healthy", 12, false},
		{"healthy-r0", "", 0, true},
		{"healthy", "", 0, true},
		{"bad-name-r1", "", 0, true},
	}
	for _, tt := range tests {
		t.Run(tt.id, func(t *testing.T) {
			f, r, err := ParseIncidentID(tt.id)
			if (err != nil) != tt.wantErr {
				t.Fatalf("err = %v, wantErr %v", err, tt.wantErr)
			}
			if tt.wantErr {
				return
			}
			if f != tt.fault || r != tt.replica {
				t.Fatalf("got %s/%d", f, r)
			}
			if IncidentID(f, r) != tt.id {
				t.Fatalf("round trip mismatch")
			}
		})
	}
}

func TestLabelJSON(t *testing.T) {
	f, _ := Lookup("toxiReset")
	b, err := MarshalLabel(f.LabelFor("toxiReset-r1"))
	if err != nil {
		t.Fatal(err)
	}
	var got map[string]any
	if err := json.Unmarshal(b, &got); err != nil {
		t.Fatal(err)
	}
	if bytes.Contains(b, []byte(`\u003e`)) {
		t.Fatalf("edge name was HTML-escaped: %s", b)
	}
	want := map[string]any{"fault": "toxiReset", "service": "payment",
		"category": "network_reset", "layer": "network", "edge": "checkout->payment", "flag": nil, "variant": nil}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got  %s\nwant %s", b, want)
	}
	h, _ := Lookup("healthy")
	if l := h.LabelFor("healthy-r1"); l.Edge != nil || l.Flag != nil || l.Layer != LayerNone {
		t.Fatalf("healthy label: %+v", l)
	}
}

func TestByFlagService(t *testing.T) {
	got := ByFlagService("product-catalog")
	if len(got) != 2 {
		t.Fatalf("want 2 product-catalog flag faults, got %d", len(got))
	}
	if len(ByFlagService("checkout")) != 0 {
		t.Fatal("checkout has no flag fault")
	}
}

func TestHardwareFaults(t *testing.T) {
	hw := Hardware()
	if len(hw) != 3 {
		t.Fatalf("want 3 hardware faults, got %d", len(hw))
	}
	for _, f := range hw {
		if f.Kind != KindManual || f.Layer != LayerNetwork || f.Steps == "" || f.Undo == "" {
			t.Errorf("%s: incomplete hardware fault %+v", f.Name, f)
		}
		emu, ok := Lookup(f.Emulates)
		if !ok || emu.Layer != LayerNetwork || emu.Category != f.Category {
			t.Errorf("%s: emulated counterpart %q must be a network fault with the same category", f.Name, f.Emulates)
		}
		if got, ok := Lookup(f.Name); !ok || got.Name != f.Name {
			t.Errorf("Lookup(%s) failed", f.Name)
		}
	}
	for _, f := range All() {
		if f.Kind == KindManual {
			t.Errorf("pilot catalog must not contain manual fault %s", f.Name)
		}
	}
}
