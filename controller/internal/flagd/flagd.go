// Package flagd toggles OpenTelemetry Demo feature flags by rewriting the
// flagd JSON file that the demo mounts. flagd watches the file and picks up
// the change within a second or so.
package flagd

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"sync"
)

// OffVariant is the variant every demo flag uses for "disabled".
const OffVariant = "off"

// Flags is what the rest of the controller needs from flagd.
type Flags interface {
	Set(name, variant string) error
	Get(name string) (string, error)
	ResetAll() error
}

// Store edits a flagd file on disk. It keeps every field it does not
// understand, so the demo's file round-trips unchanged apart from the
// defaultVariant values it touches.
type Store struct {
	path string
	mu   sync.Mutex
}

// NewStore returns a Store for the flagd file at path.
func NewStore(path string) *Store { return &Store{path: path} }

type document map[string]any

func (s *Store) load() (document, map[string]any, error) {
	raw, err := os.ReadFile(s.path)
	if err != nil {
		return nil, nil, fmt.Errorf("read flagd file: %w", err)
	}
	var doc document
	if err := json.Unmarshal(raw, &doc); err != nil {
		return nil, nil, fmt.Errorf("parse flagd file: %w", err)
	}
	flags, ok := doc["flags"].(map[string]any)
	if !ok {
		return nil, nil, fmt.Errorf("flagd file has no \"flags\" object")
	}
	return doc, flags, nil
}

func (s *Store) save(doc document) error {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", "  ")
	if err := enc.Encode(doc); err != nil {
		return err
	}
	// Write then rename so flagd never reads a half-written file.
	tmp, err := os.CreateTemp(filepath.Dir(s.path), ".flagd-*.json")
	if err != nil {
		return err
	}
	defer func() { _ = os.Remove(tmp.Name()) }()
	if _, err := tmp.Write(buf.Bytes()); err != nil {
		_ = tmp.Close()
		return err
	}
	if err := tmp.Close(); err != nil {
		return err
	}
	if info, err := os.Stat(s.path); err == nil {
		_ = os.Chmod(tmp.Name(), info.Mode().Perm())
	}
	return os.Rename(tmp.Name(), s.path)
}

func flagEntry(flags map[string]any, name string) (map[string]any, error) {
	f, ok := flags[name].(map[string]any)
	if !ok {
		return nil, fmt.Errorf("unknown flag %q", name)
	}
	return f, nil
}

func hasVariant(f map[string]any, variant string) bool {
	v, ok := f["variants"].(map[string]any)
	if !ok {
		return false
	}
	_, ok = v[variant]
	return ok
}

// Set makes variant the default for flag name. It refuses variants the file
// does not define.
func (s *Store) Set(name, variant string) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	doc, flags, err := s.load()
	if err != nil {
		return err
	}
	f, err := flagEntry(flags, name)
	if err != nil {
		return err
	}
	if !hasVariant(f, variant) {
		return fmt.Errorf("flag %q has no variant %q (have %v)", name, variant, variantNames(f))
	}
	f["defaultVariant"] = variant
	return s.save(doc)
}

// Get returns the current default variant of a flag.
func (s *Store) Get(name string) (string, error) {
	s.mu.Lock()
	defer s.mu.Unlock()
	_, flags, err := s.load()
	if err != nil {
		return "", err
	}
	f, err := flagEntry(flags, name)
	if err != nil {
		return "", err
	}
	v, _ := f["defaultVariant"].(string)
	return v, nil
}

// ResetAll sets every flag that has an "off" variant back to "off".
func (s *Store) ResetAll() error {
	s.mu.Lock()
	defer s.mu.Unlock()
	doc, flags, err := s.load()
	if err != nil {
		return err
	}
	for _, raw := range flags {
		f, ok := raw.(map[string]any)
		if ok && hasVariant(f, OffVariant) {
			f["defaultVariant"] = OffVariant
		}
	}
	return s.save(doc)
}

func variantNames(f map[string]any) []string {
	v, _ := f["variants"].(map[string]any)
	names := make([]string, 0, len(v))
	for k := range v {
		names = append(names, k)
	}
	sort.Strings(names)
	return names
}
