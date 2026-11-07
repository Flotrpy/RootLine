package toxi

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"
)

// fakeServer mimics the parts of the Toxiproxy API the client uses.
type fakeServer struct {
	mu     sync.Mutex
	toxics map[string][]Toxic
}

func (f *fakeServer) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	f.mu.Lock()
	defer f.mu.Unlock()
	parts := strings.Split(strings.Trim(r.URL.Path, "/"), "/")
	if len(parts) < 3 || parts[0] != "proxies" || parts[2] != "toxics" {
		http.NotFound(w, r)
		return
	}
	proxy := parts[1]
	if proxy == "missing" {
		http.Error(w, `{"error":"proxy not found"}`, http.StatusNotFound)
		return
	}
	switch {
	case r.Method == http.MethodPost && len(parts) == 3:
		var t Toxic
		if err := json.NewDecoder(r.Body).Decode(&t); err != nil {
			http.Error(w, err.Error(), http.StatusBadRequest)
			return
		}
		f.toxics[proxy] = append(f.toxics[proxy], t)
		_ = json.NewEncoder(w).Encode(t)
	case r.Method == http.MethodGet && len(parts) == 3:
		_ = json.NewEncoder(w).Encode(append([]Toxic{}, f.toxics[proxy]...))
	case r.Method == http.MethodDelete && len(parts) == 4:
		kept := f.toxics[proxy][:0]
		for _, t := range f.toxics[proxy] {
			if t.Name != parts[3] {
				kept = append(kept, t)
			}
		}
		f.toxics[proxy] = kept
		w.WriteHeader(http.StatusNoContent)
	default:
		http.Error(w, "bad request", http.StatusMethodNotAllowed)
	}
}

func TestClientLifecycle(t *testing.T) {
	fake := &fakeServer{toxics: map[string][]Toxic{}}
	srv := httptest.NewServer(fake)
	defer srv.Close()
	c := NewClient(srv.URL)
	ctx := context.Background()

	add := []Toxic{
		{Name: "lat", Type: "latency", Toxicity: 1, Attributes: map[string]int{"latency": 300, "jitter": 60}},
		{Name: "rst", Type: "reset_peer", Toxicity: 0.2, Attributes: map[string]int{"timeout": 0}},
	}
	for _, tx := range add {
		if err := c.AddToxic(ctx, "payment", tx); err != nil {
			t.Fatal(err)
		}
	}
	got, err := c.ListToxics(ctx, "payment")
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != 2 || got[0].Stream != "downstream" || got[0].Attributes["latency"] != 300 {
		t.Fatalf("unexpected toxics: %+v", got)
	}
	if err := ClearAll(ctx, c, "payment"); err != nil {
		t.Fatal(err)
	}
	if got, _ := c.ListToxics(ctx, "payment"); len(got) != 0 {
		t.Fatalf("toxics left after clear: %+v", got)
	}
}

func TestClientErrors(t *testing.T) {
	srv := httptest.NewServer(&fakeServer{toxics: map[string][]Toxic{}})
	defer srv.Close()
	c := NewClient(srv.URL)
	err := c.AddToxic(context.Background(), "missing", Toxic{Name: "x", Type: "latency"})
	if err == nil || !strings.Contains(err.Error(), "404") {
		t.Fatalf("want 404 error, got %v", err)
	}
}
