// Package api serves the controller's HTTP API on :8088. The Arduino bridge
// app uses it to trigger faults from the panel's buttons and to drive the
// status LEDs and display.
package api

import (
	"encoding/json"
	"net/http"
	"sync"
	"time"

	"github.com/flotrpy/rootline/controller/internal/catalog"
	"github.com/flotrpy/rootline/controller/internal/inject"
)

// Panel states, one per LED.
const (
	StateHealthy    = "healthy"
	StateFaulty     = "faulty"
	StateDiagnosing = "diagnosing"
)

// Status is what GET /status returns.
type Status struct {
	State       string `json:"state"`
	ActiveFault string `json:"active_fault,omitempty"`
	SinceUnixMs int64  `json:"since_unix_ms"`
	Hypothesis  string `json:"hypothesis,omitempty"`
}

// Server holds the panel state. Only one fault is active at a time.
type Server struct {
	Injector *inject.Injector
	Now      func() time.Time

	mu     sync.Mutex
	status Status
	active *catalog.Fault
}

// New returns a Server in the healthy state.
func New(in *inject.Injector) *Server {
	s := &Server{Injector: in, Now: time.Now}
	s.status = Status{State: StateHealthy, SinceUnixMs: s.Now().UnixMilli()}
	return s
}

// Handler returns the API routes.
func (s *Server) Handler() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok"})
	})
	mux.HandleFunc("GET /status", s.getStatus)
	mux.HandleFunc("GET /faults", s.listFaults)
	mux.HandleFunc("POST /faults/{name}", s.postFault)
	mux.HandleFunc("POST /reset", s.postReset)
	mux.HandleFunc("POST /diagnosis", s.postDiagnosis)
	return mux
}

func (s *Server) setLocked(state, fault, hypothesis string) {
	s.status = Status{State: state, ActiveFault: fault, SinceUnixMs: s.Now().UnixMilli(), Hypothesis: hypothesis}
}

func (s *Server) getStatus(w http.ResponseWriter, _ *http.Request) {
	s.mu.Lock()
	st := s.status
	s.mu.Unlock()
	writeJSON(w, http.StatusOK, st)
}

func (s *Server) listFaults(w http.ResponseWriter, _ *http.Request) {
	names := []string{}
	for _, f := range catalog.All() {
		if f.Kind != catalog.KindNone {
			names = append(names, f.Name)
		}
	}
	writeJSON(w, http.StatusOK, map[string][]string{"faults": names})
}

func (s *Server) postFault(w http.ResponseWriter, r *http.Request) {
	f, ok := catalog.Lookup(r.PathValue("name"))
	if !ok || f.Kind == catalog.KindNone {
		writeJSON(w, http.StatusNotFound, map[string]string{"error": "unknown fault"})
		return
	}
	if f.Kind == catalog.KindManual {
		// Physical steps are never triggered remotely.
		writeJSON(w, http.StatusForbidden, map[string]string{"error": "manual faults need an operator; use rootlinectl"})
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	if s.active != nil {
		writeJSON(w, http.StatusConflict, map[string]string{"error": "fault already active: " + s.active.Name})
		return
	}
	if err := s.Injector.Inject(r.Context(), f); err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": err.Error()})
		return
	}
	s.active = &f
	s.setLocked(StateFaulty, f.Name, "")
	writeJSON(w, http.StatusOK, s.status)
}

func (s *Server) postReset(w http.ResponseWriter, r *http.Request) {
	s.mu.Lock()
	defer s.mu.Unlock()
	if err := s.Injector.ClearAll(r.Context()); err != nil {
		writeJSON(w, http.StatusBadGateway, map[string]string{"error": err.Error()})
		return
	}
	s.active = nil
	s.setLocked(StateHealthy, "", "")
	writeJSON(w, http.StatusOK, s.status)
}

// diagnosisRequest marks the start ("diagnosing") or end (a hypothesis) of a
// model's diagnosis, for the panel's LED and display.
type diagnosisRequest struct {
	Diagnosing bool   `json:"diagnosing"`
	Hypothesis string `json:"hypothesis"`
}

func (s *Server) postDiagnosis(w http.ResponseWriter, r *http.Request) {
	var req diagnosisRequest
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4096)).Decode(&req); err != nil {
		writeJSON(w, http.StatusBadRequest, map[string]string{"error": "bad json"})
		return
	}
	s.mu.Lock()
	defer s.mu.Unlock()
	fault := s.status.ActiveFault
	switch {
	case req.Diagnosing:
		s.setLocked(StateDiagnosing, fault, "")
	case s.active != nil:
		s.setLocked(StateFaulty, fault, req.Hypothesis)
	default:
		s.setLocked(StateHealthy, "", req.Hypothesis)
	}
	writeJSON(w, http.StatusOK, s.status)
}

func writeJSON(w http.ResponseWriter, code int, v any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(code)
	_ = json.NewEncoder(w).Encode(v)
}
