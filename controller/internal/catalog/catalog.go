// Package catalog defines the pilot's 15 incident types and their ground-truth
// labels. It is the single source of truth for what each fault injects and
// what a correct diagnosis looks like.
package catalog

import (
	"bytes"
	"encoding/json"
	"fmt"
	"regexp"
	"sort"
	"strconv"
)

// Layer says where the root cause lives.
type Layer string

const (
	LayerApplication Layer = "application"
	LayerNetwork     Layer = "network"
	LayerNone        Layer = "none"
)

// Kind says which mechanism injects a fault.
type Kind string

const (
	KindFlag  Kind = "flag"  // flagd feature flag in the OpenTelemetry Demo
	KindToxic Kind = "toxic" // Toxiproxy toxic on an edge
	KindNetem Kind = "netem" // tc netem rule on an edge's proxy container
	KindNone  Kind = "none"  // healthy control
	// KindManual faults need a person: the controller prints the steps,
	// waits for confirmation and timestamps them (hardware arm only).
	KindManual Kind = "manual"
)

// Categories used in labels and in the model output contract.
const (
	CatError             = "error"
	CatDependency        = "dependency_unavailable"
	CatLockContention    = "lock_contention"
	CatMemoryLeak        = "memory_leak"
	CatQueueLag          = "queue_lag"
	CatLatency           = "latency"
	CatCPUSaturation     = "cpu_saturation"
	CatNetworkLatency    = "network_latency"
	CatNetworkLoss       = "network_loss"
	CatNetworkReset      = "network_reset"
	CatNetworkThroughput = "network_throughput"
	CatNone              = "none"
)

// Categories lists every valid category, sorted.
func Categories() []string {
	c := []string{
		CatError, CatDependency, CatLockContention, CatMemoryLeak, CatQueueLag,
		CatLatency, CatCPUSaturation, CatNetworkLatency, CatNetworkLoss,
		CatNetworkReset, CatNetworkThroughput, CatNone,
	}
	sort.Strings(c)
	return c
}

// Edges routed through Toxiproxy in compose.override.yml.
const (
	EdgeCheckoutPayment = "checkout->payment"
	EdgeFrontendCatalog = "frontend->product-catalog"
)

// Toxic describes one Toxiproxy toxic.
type Toxic struct {
	Type       string         `json:"type"`
	Toxicity   float64        `json:"toxicity"`
	Attributes map[string]int `json:"attributes"`
}

// Fault is one incident type.
type Fault struct {
	Name     string
	Kind     Kind
	Service  string // root-cause service as scored
	Category string
	Layer    Layer
	Edge     string // network faults only
	Flag     string // flag faults only
	Variant  string // flag variant to enable
	Toxic    *Toxic // toxic faults only
	LossPct  int    // netem faults only
	Steps    string // manual faults only: what the operator does to inject
	Undo     string // manual faults only: what the operator does to clear
	// Emulates names the emulated fault a hardware fault is compared with
	// in the emulation-validity analysis.
	Emulates string
}

// Label is the ground truth written to data/labels/<incident_id>.json.
// Field names follow the data contract in docs/BUILD_PROMPT.md section 4.
type Label struct {
	IncidentID string  `json:"-"` // the file name carries it
	Fault      string  `json:"fault"`
	Service    string  `json:"service"`
	Category   string  `json:"category"`
	Layer      Layer   `json:"layer"`
	Edge       *string `json:"edge"`
	Flag       *string `json:"flag"`
	Variant    *string `json:"variant"`
}

// TODO(flotrpy): verify every flag name and variant against demo.flagd.json
// at the pinned demo tag. flagd.Store.Set refuses unknown variants, so a
// mismatch fails loudly at the dry run rather than silently.
//
// TODO(flotrpy): confirm the scored service for paymentUnreachable and for
// network faults. Here it is the downstream service of the broken edge.
var faults = []Fault{
	// Application faults: OpenTelemetry Demo flagd flags.
	{Name: "paymentFailure", Kind: KindFlag, Service: "payment", Category: CatError, Layer: LayerApplication, Flag: "paymentFailure", Variant: "50%"},
	{Name: "paymentUnreachable", Kind: KindFlag, Service: "payment", Category: CatDependency, Layer: LayerApplication, Edge: EdgeCheckoutPayment, Flag: "paymentUnreachable", Variant: "on"},
	{Name: "productCatalogFailure", Kind: KindFlag, Service: "product-catalog", Category: CatError, Layer: LayerApplication, Flag: "productCatalogFailure", Variant: "on"},
	{Name: "productCatalogLockContention", Kind: KindFlag, Service: "product-catalog", Category: CatLockContention, Layer: LayerApplication, Flag: "productCatalogLockContention", Variant: "on"},
	{Name: "emailMemoryLeak", Kind: KindFlag, Service: "email", Category: CatMemoryLeak, Layer: LayerApplication, Flag: "emailMemoryLeak", Variant: "on"},
	{Name: "recommendationCacheFailure", Kind: KindFlag, Service: "recommendation", Category: CatMemoryLeak, Layer: LayerApplication, Flag: "recommendationCacheFailure", Variant: "on"},
	{Name: "kafkaQueueProblems", Kind: KindFlag, Service: "fraud-detection", Category: CatQueueLag, Layer: LayerApplication, Flag: "kafkaQueueProblems", Variant: "on"},
	{Name: "intlShippingSlowdown", Kind: KindFlag, Service: "shipping", Category: CatLatency, Layer: LayerApplication, Flag: "intlShippingSlowdown", Variant: "on"},
	{Name: "imageSlowLoad", Kind: KindFlag, Service: "frontend-proxy", Category: CatLatency, Layer: LayerApplication, Flag: "imageSlowLoad", Variant: "5sec"},
	{Name: "adHighCpu", Kind: KindFlag, Service: "ad", Category: CatCPUSaturation, Layer: LayerApplication, Flag: "adHighCpu", Variant: "on"},

	// Network faults: Toxiproxy toxics and tc netem.
	{Name: "toxiLatency", Kind: KindToxic, Service: "payment", Category: CatNetworkLatency, Layer: LayerNetwork, Edge: EdgeCheckoutPayment,
		Toxic: &Toxic{Type: "latency", Toxicity: 1, Attributes: map[string]int{"latency": 300, "jitter": 60}}},
	{Name: "netemLoss", Kind: KindNetem, Service: "product-catalog", Category: CatNetworkLoss, Layer: LayerNetwork, Edge: EdgeFrontendCatalog, LossPct: 5},
	{Name: "toxiReset", Kind: KindToxic, Service: "payment", Category: CatNetworkReset, Layer: LayerNetwork, Edge: EdgeCheckoutPayment,
		Toxic: &Toxic{Type: "reset_peer", Toxicity: 0.2, Attributes: map[string]int{"timeout": 0}}},
	{Name: "toxiBandwidth", Kind: KindToxic, Service: "product-catalog", Category: CatNetworkThroughput, Layer: LayerNetwork, Edge: EdgeFrontendCatalog,
		Toxic: &Toxic{Type: "bandwidth", Toxicity: 1, Attributes: map[string]int{"rate": 64}}},

	// Healthy control.
	{Name: "healthy", Kind: KindNone, Service: "none", Category: CatNone, Layer: LayerNone},
}

// The hardware arm (Phase 3): real faults on the Wi-Fi link through the
// Arduino UNO Q relay on the checkout -> payment edge. Not part of the
// 15-type pilot; collected with plans/hardware.yaml.
//
// TODO(flotrpy): confirm each category and its emulated counterpart.
var hardware = []Fault{
	{Name: "hwWeakSignal", Kind: KindManual, Service: "payment", Category: CatNetworkLoss, Layer: LayerNetwork, Edge: EdgeCheckoutPayment,
		Steps:    "Move Board A (relay) until its RSSI is below -75 dBm (check the Board B logger or `iw dev wlan0 link`).",
		Undo:     "Move Board A back to its normal spot and confirm RSSI is back near baseline.",
		Emulates: "netemLoss"},
	{Name: "hwContention", Kind: KindManual, Service: "payment", Category: CatNetworkLatency, Layer: LayerNetwork, Edge: EdgeCheckoutPayment,
		Steps:    "Force Board A onto 2.4 GHz, then start hw/contention/iperf_contention.sh on Board B against your LOCAL iperf3 server.",
		Undo:     "Stop the iperf3 script on Board B and put Board A back on its normal band.",
		Emulates: "toxiLatency"},
	{Name: "hwPowerCut", Kind: KindManual, Service: "payment", Category: CatNetworkReset, Layer: LayerNetwork, Edge: EdgeCheckoutPayment,
		Steps:    "Cut Board A's power for 30 seconds, then restore it and wait for the relay to come back.",
		Undo:     "Confirm the relay service on Board A is running (systemctl status edge-relay).",
		Emulates: "toxiReset"},
}

// Hardware returns the hardware-arm faults.
func Hardware() []Fault {
	out := make([]Fault, len(hardware))
	copy(out, hardware)
	return out
}

// All returns the 15 pilot faults in catalog order.
func All() []Fault {
	out := make([]Fault, len(faults))
	copy(out, faults)
	return out
}

// Lookup finds a pilot or hardware fault by name.
func Lookup(name string) (Fault, bool) {
	for _, f := range append(All(), hardware...) {
		if f.Name == name {
			return f, true
		}
	}
	return Fault{}, false
}

// ByFlagService returns the flag fault that targets a service, used by the
// disable_feature remediation action.
func ByFlagService(service string) []Fault {
	var out []Fault
	for _, f := range faults {
		if f.Kind == KindFlag && f.Service == service {
			out = append(out, f)
		}
	}
	return out
}

var incidentRe = regexp.MustCompile(`^([A-Za-z]+)-r([1-9][0-9]*)$`)

// IncidentID builds "<fault>-r<replica>".
func IncidentID(fault string, replica int) string {
	return fmt.Sprintf("%s-r%d", fault, replica)
}

// ParseIncidentID splits "<fault>-r<replica>".
func ParseIncidentID(id string) (fault string, replica int, err error) {
	m := incidentRe.FindStringSubmatch(id)
	if m == nil {
		return "", 0, fmt.Errorf("invalid incident id %q", id)
	}
	replica, err = strconv.Atoi(m[2])
	if err != nil {
		return "", 0, fmt.Errorf("invalid replica in %q: %w", id, err)
	}
	return m[1], replica, nil
}

// LabelFor builds the ground-truth label for an incident.
func (f Fault) LabelFor(incidentID string) Label {
	l := Label{
		IncidentID: incidentID,
		Fault:      f.Name,
		Service:    f.Service,
		Category:   f.Category,
		Layer:      f.Layer,
	}
	if f.Edge != "" {
		e := f.Edge
		l.Edge = &e
	}
	if f.Flag != "" {
		fl, v := f.Flag, f.Variant
		l.Flag, l.Variant = &fl, &v
	}
	return l
}

// MarshalLabel encodes a label as indented JSON without HTML escaping, so edge
// names such as "checkout->payment" stay readable on disk.
func MarshalLabel(l Label) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", "  ")
	if err := enc.Encode(l); err != nil {
		return nil, err
	}
	return buf.Bytes(), nil
}
