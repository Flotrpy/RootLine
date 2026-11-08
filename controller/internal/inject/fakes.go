package inject

import (
	"context"
	"fmt"
	"sync"

	"github.com/flotrpy/rootline/controller/internal/toxi"
)

// FakeFlags records flag state in memory. Exported for other packages' tests.
type FakeFlags struct {
	mu    sync.Mutex
	State map[string]string
}

func (f *FakeFlags) Set(name, variant string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.State == nil {
		f.State = map[string]string{}
	}
	f.State[name] = variant
	return nil
}

func (f *FakeFlags) Get(name string) (string, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	v, ok := f.State[name]
	if !ok {
		return "", fmt.Errorf("unknown flag %q", name)
	}
	return v, nil
}

func (f *FakeFlags) ResetAll() error {
	f.mu.Lock()
	defer f.mu.Unlock()
	for k := range f.State {
		f.State[k] = "off"
	}
	return nil
}

// FakeToxi keeps toxics in memory.
type FakeToxi struct {
	mu     sync.Mutex
	Toxics map[string][]toxi.Toxic
}

func (f *FakeToxi) AddToxic(_ context.Context, proxy string, t toxi.Toxic) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.Toxics == nil {
		f.Toxics = map[string][]toxi.Toxic{}
	}
	f.Toxics[proxy] = append(f.Toxics[proxy], t)
	return nil
}

func (f *FakeToxi) ListToxics(_ context.Context, proxy string) ([]toxi.Toxic, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	return append([]toxi.Toxic{}, f.Toxics[proxy]...), nil
}

func (f *FakeToxi) RemoveToxic(_ context.Context, proxy, name string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	kept := f.Toxics[proxy][:0]
	for _, t := range f.Toxics[proxy] {
		if t.Name != name {
			kept = append(kept, t)
		}
	}
	f.Toxics[proxy] = kept
	return nil
}

// FakeNetem keeps loss settings in memory.
type FakeNetem struct {
	mu    sync.Mutex
	Rules map[string]int
}

func (f *FakeNetem) Loss(_ context.Context, container string, pct int) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.Rules == nil {
		f.Rules = map[string]int{}
	}
	f.Rules[container] = pct
	return nil
}

func (f *FakeNetem) Clear(_ context.Context, container string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	delete(f.Rules, container)
	return nil
}

// NewFake returns an Injector wired to in-memory fakes with every catalog
// flag present and off.
func NewFake(flagNames ...string) (*Injector, *FakeFlags, *FakeToxi, *FakeNetem) {
	ff := &FakeFlags{State: map[string]string{}}
	for _, n := range flagNames {
		ff.State[n] = "off"
	}
	ft, fn := &FakeToxi{}, &FakeNetem{}
	return &Injector{Flags: ff, Toxi: ft, Netem: fn, Edges: DefaultEdges}, ff, ft, fn
}

// FakeOperator records operator steps instead of asking a person.
type FakeOperator struct {
	mu    sync.Mutex
	Steps []string // "fault/phase"
}

func (f *FakeOperator) Do(_ context.Context, fault, phase, _ string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.Steps = append(f.Steps, fault+"/"+phase)
	return nil
}

// FakeBoards records remote commands instead of running them.
type FakeBoards struct {
	mu    sync.Mutex
	Calls []string // "board|cmd|attempts"
	Err   error
}

func (f *FakeBoards) Exec(_ context.Context, board, cmd string, attempts int) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.Calls = append(f.Calls, fmt.Sprintf("%s|%s|%d", board, cmd, attempts))
	return f.Err
}
