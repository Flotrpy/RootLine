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
	// waits for confirmation and timestamps them.
	KindManual Kind = "manual"
	// KindRemote faults run a command on one of the Arduino boards over SSH
	// (hardware arm), so the hardware campaign can run unattended.
	KindRemote Kind = "remote"
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
	// Remote faults only: which board ("A" or "B") and the shell commands
	// that inject and clear the fault there. {placeholders} are filled from
	// the controller's environment (see internal/board).
	Board        string
	RemoteInject string
	RemoteClear  string
	// Emulates names the emulated fault a hardware fault is compared with
	// in the emulation-validity analysis.
	Emulates string
	// SelfClearing faults end by themselves (a timed iperf3 run, a revert
	// timer on the board), so a failed clear after the snapshot is logged
	// instead of failing the incident. Contention can make Board B
	// unreachable over SSH until its own flood stops.
	SelfClearing bool
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

// Flag names and variants checked against demo.flagd.json at demo 3.1.0
// (emailMemoryLeak offers 1x..10000x, intlShippingSlowdown 5sec/10sec).
// TODO(flotrpy): confirm the 100x memory-leak level. flagd.Store.Set refuses unknown variants, so a
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
	{Name: "emailMemoryLeak", Kind: KindFlag, Service: "email", Category: CatMemoryLeak, Layer: LayerApplication, Flag: "emailMemoryLeak", Variant: "100x"},
	{Name: "recommendationCacheFailure", Kind: KindFlag, Service: "recommendation", Category: CatMemoryLeak, Layer: LayerApplication, Flag: "recommendationCacheFailure", Variant: "on"},
	{Name: "kafkaQueueProblems", Kind: KindFlag, Service: "fraud-detection", Category: CatQueueLag, Layer: LayerApplication, Flag: "kafkaQueueProblems", Variant: "on"},
	{Name: "intlShippingSlowdown", Kind: KindFlag, Service: "shipping", Category: CatLatency, Layer: LayerApplication, Flag: "intlShippingSlowdown", Variant: "5sec"},
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

// The hardware arm (Phase 3): real faults on the Wi-Fi link of Board A,
// the UNO Q relaying checkout -> payment. Not part of the 15-type pilot;
// collected with plans/hardware.yaml, unattended. Each fault degrades the
// real radio link (transmit power, channel contention, radio off), triggered
// over SSH; hw/board/rootline-fault always schedules its own undo on the
// board, so a lost SSH session cannot leave a fault in place.
//
// TODO(flotrpy): confirm each category and its emulated counterpart.
var hardware = []Fault{
	{Name: "hwWeakSignal", Kind: KindRemote, Service: "payment", Category: CatNetworkLoss, Layer: LayerNetwork, Edge: EdgeCheckoutPayment,
		Board:        "A",
		RemoteInject: "sudo -n /usr/local/bin/rootline-fault weak-on {txpower_mbm}",
		RemoteClear:  "sudo -n /usr/local/bin/rootline-fault weak-off",
		Emulates:     "netemLoss", SelfClearing: true},
	{Name: "hwContention", Kind: KindRemote, Service: "payment", Category: CatNetworkLatency, Layer: LayerNetwork, Edge: EdgeCheckoutPayment,
		Board:        "B",
		RemoteInject: "IPERF_SERVER={iperf_server} BITRATE={contention_bitrate} DURATION=300 nohup bash ~/iperf_contention.sh >/tmp/rootline-iperf.log 2>&1 </dev/null &",
		RemoteClear:  "pkill -f 'iperf3 --client' || true",
		Emulates:     "toxiLatency", SelfClearing: true},
	{Name: "hwWifiOutage", Kind: KindRemote, Service: "payment", Category: CatNetworkReset, Layer: LayerNetwork, Edge: EdgeCheckoutPayment,
		Board:        "A",
		RemoteInject: "sudo -n /usr/local/bin/rootline-fault outage 30",
		RemoteClear:  "sudo -n /usr/local/bin/rootline-fault status >/dev/null",
		Emulates:     "toxiReset", SelfClearing: true},
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
