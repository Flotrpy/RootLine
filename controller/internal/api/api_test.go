package api

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/flotrpy/rootline/controller/internal/catalog"
	"github.com/flotrpy/rootline/controller/internal/inject"
)

func newServer(t *testing.T) (*httptest.Server, *inject.FakeFlags) {
	t.Helper()
	var flags []string
	for _, f := range catalog.All() {
		if f.Flag != "" {
			flags = append(flags, f.Flag)
		}
	}
	in, ff, _, _ := inject.NewFake(flags...)
	srv := httptest.NewServer(New(in).Handler())
	t.Cleanup(srv.Close)
	return srv, ff
}

func do(t *testing.T, method, url, body string) (int, Status) {
	t.Helper()
	req, _ := http.NewRequest(method, url, strings.NewReader(body))
	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	var st Status
	_ = json.NewDecoder(resp.Body).Decode(&st)
	return resp.StatusCode, st
}

func TestPanelFlow(t *testing.T) {
	srv, ff := newServer(t)
	steps := []struct {
		method, path, body string
		wantCode           int
		wantState          string
	}{
		{"GET", "/status", "", 200, StateHealthy},
		{"POST", "/faults/paymentFailure", "", 200, StateFaulty},
		{"POST", "/faults/adHighCpu", "", 409, ""},
		{"POST", "/diagnosis", `{"diagnosing":true}`, 200, StateDiagnosing},
		{"POST", "/diagnosis", `{"hypothesis":"payment / error"}`, 200, StateFaulty},
		{"POST", "/reset", "", 200, StateHealthy},
		{"POST", "/faults/healthy", "", 404, ""},
		{"POST", "/faults/nope", "", 404, ""},
		{"POST", "/faults/hwWifiOutage", "", 403, ""},
		{"POST", "/diagnosis", `not json`, 400, ""},
	}
	for _, s := range steps {
		code, st := do(t, s.method, srv.URL+s.path, s.body)
		if code != s.wantCode {
			t.Fatalf("%s %s: code %d, want %d", s.method, s.path, code, s.wantCode)
		}
		if s.wantState != "" && st.State != s.wantState {
			t.Fatalf("%s %s: state %q, want %q", s.method, s.path, st.State, s.wantState)
		}
		if s.path == "/diagnosis" && s.body == `{"hypothesis":"payment / error"}` && st.Hypothesis != "payment / error" {
			t.Fatalf("hypothesis not kept: %+v", st)
		}
	}
	if ff.State["paymentFailure"] != "off" {
		t.Fatal("reset did not clear the flag")
	}
}

func TestHealthAndFaultList(t *testing.T) {
	srv, _ := newServer(t)
	resp, err := http.Get(srv.URL + "/faults")
	if err != nil {
		t.Fatal(err)
	}
	defer func() { _ = resp.Body.Close() }()
	var out map[string][]string
	if err := json.NewDecoder(resp.Body).Decode(&out); err != nil {
		t.Fatal(err)
	}
	if len(out["faults"]) != 14 {
		t.Fatalf("want 14 injectable faults, got %d", len(out["faults"]))
	}
	if code, _ := do(t, "GET", srv.URL+"/health", ""); code != 200 {
		t.Fatal("health not ok")
	}
}
