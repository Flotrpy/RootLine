package health

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestRecovered(t *testing.T) {
	base := Sample{ErrorRatio: 0.02, P99Ms: 400}
	tests := []struct {
		name    string
		base    Sample
		current Sample
		want    bool
	}{
		{"identical", base, base, true},
		{"at both limits", base, Sample{ErrorRatio: 0.03, P99Ms: 480}, true},
		{"errors too high", base, Sample{ErrorRatio: 0.031, P99Ms: 400}, false},
		{"latency too high", base, Sample{ErrorRatio: 0.02, P99Ms: 481}, false},
		{"zero baseline tolerates a trickle", Sample{0, 400}, Sample{ErrorRatio: 0.007, P99Ms: 400}, true},
		{"zero baseline still catches failures", Sample{0, 400}, Sample{ErrorRatio: 0.2, P99Ms: 400}, false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := Recovered(tt.base, tt.current); got != tt.want {
				t.Fatalf("Recovered = %v, want %v", got, tt.want)
			}
		})
	}
}

func TestPrometheusSample(t *testing.T) {
	srv := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		q := r.URL.Query().Get("query")
		switch {
		case strings.HasPrefix(q, "histogram_quantile"):
			_, _ = fmt.Fprint(w, `{"status":"success","data":{"resultType":"vector","result":[{"metric":{},"value":[1700000000,"412.5"]}]}}`)
		case strings.HasPrefix(q, "sum(rate"):
			_, _ = fmt.Fprint(w, `{"status":"success","data":{"resultType":"vector","result":[]}}`)
		default:
			_, _ = fmt.Fprint(w, `{"status":"error","error":"bad query"}`)
		}
	}))
	defer srv.Close()
	p := NewPrometheus(srv.URL)
	s, err := p.Sample(context.Background())
	if err != nil {
		t.Fatal(err)
	}
	if s.ErrorRatio != 0 || s.P99Ms != 412.5 {
		t.Fatalf("sample = %+v", s)
	}
	p.Queries.P99Ms = "nonsense"
	if _, err := p.Sample(context.Background()); err == nil {
		t.Fatal("want error on failed query")
	}
}
