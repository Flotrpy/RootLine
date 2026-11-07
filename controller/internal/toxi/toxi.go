// Package toxi is a small client for the Toxiproxy HTTP API.
// API reference: https://github.com/Shopify/toxiproxy#http-api
package toxi

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

// Toxic is one toxic as Toxiproxy represents it.
type Toxic struct {
	Name       string         `json:"name"`
	Type       string         `json:"type"`
	Stream     string         `json:"stream"`
	Toxicity   float64        `json:"toxicity"`
	Attributes map[string]int `json:"attributes"`
}

// Proxies is what the controller needs from Toxiproxy.
type Proxies interface {
	AddToxic(ctx context.Context, proxy string, t Toxic) error
	ListToxics(ctx context.Context, proxy string) ([]Toxic, error)
	RemoveToxic(ctx context.Context, proxy, toxic string) error
}

// Client talks to one Toxiproxy server.
type Client struct {
	base string
	http *http.Client
}

// NewClient returns a client for a Toxiproxy server such as
// http://localhost:8474.
func NewClient(base string) *Client {
	return &Client{base: base, http: &http.Client{Timeout: 10 * time.Second}}
}

func (c *Client) do(ctx context.Context, method, path string, body, out any) error {
	var r io.Reader
	if body != nil {
		b, err := json.Marshal(body)
		if err != nil {
			return err
		}
		r = bytes.NewReader(b)
	}
	req, err := http.NewRequestWithContext(ctx, method, c.base+path, r)
	if err != nil {
		return err
	}
	if body != nil {
		req.Header.Set("Content-Type", "application/json")
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return fmt.Errorf("toxiproxy %s %s: %w", method, path, err)
	}
	defer func() { _ = resp.Body.Close() }()
	if resp.StatusCode >= 300 {
		msg, _ := io.ReadAll(io.LimitReader(resp.Body, 512))
		return fmt.Errorf("toxiproxy %s %s: %s: %s", method, path, resp.Status, bytes.TrimSpace(msg))
	}
	if out != nil {
		return json.NewDecoder(resp.Body).Decode(out)
	}
	return nil
}

// AddToxic adds a toxic to a proxy. Stream defaults to "downstream".
func (c *Client) AddToxic(ctx context.Context, proxy string, t Toxic) error {
	if t.Stream == "" {
		t.Stream = "downstream"
	}
	return c.do(ctx, http.MethodPost, "/proxies/"+url.PathEscape(proxy)+"/toxics", t, nil)
}

// ListToxics lists a proxy's toxics.
func (c *Client) ListToxics(ctx context.Context, proxy string) ([]Toxic, error) {
	var out []Toxic
	err := c.do(ctx, http.MethodGet, "/proxies/"+url.PathEscape(proxy)+"/toxics", nil, &out)
	return out, err
}

// RemoveToxic deletes one toxic.
func (c *Client) RemoveToxic(ctx context.Context, proxy, toxic string) error {
	return c.do(ctx, http.MethodDelete, "/proxies/"+url.PathEscape(proxy)+"/toxics/"+url.PathEscape(toxic), nil, nil)
}

// ClearAll removes every toxic from a proxy.
func ClearAll(ctx context.Context, p Proxies, proxy string) error {
	toxics, err := p.ListToxics(ctx, proxy)
	if err != nil {
		return err
	}
	for _, t := range toxics {
		if err := p.RemoveToxic(ctx, proxy, t.Name); err != nil {
			return err
		}
	}
	return nil
}

// Router sends each proxy's calls to the Toxiproxy server that owns it.
// Rootline runs one Toxiproxy container per edge, so a netem rule on one
// edge's container never touches the other edge.
type Router map[string]Proxies

func (r Router) route(proxy string) (Proxies, error) {
	p, ok := r[proxy]
	if !ok {
		return nil, fmt.Errorf("no Toxiproxy server configured for proxy %q", proxy)
	}
	return p, nil
}

// AddToxic implements Proxies.
func (r Router) AddToxic(ctx context.Context, proxy string, t Toxic) error {
	p, err := r.route(proxy)
	if err != nil {
		return err
	}
	return p.AddToxic(ctx, proxy, t)
}

// ListToxics implements Proxies.
func (r Router) ListToxics(ctx context.Context, proxy string) ([]Toxic, error) {
	p, err := r.route(proxy)
	if err != nil {
		return nil, err
	}
	return p.ListToxics(ctx, proxy)
}

// RemoveToxic implements Proxies.
func (r Router) RemoveToxic(ctx context.Context, proxy, toxic string) error {
	p, err := r.route(proxy)
	if err != nil {
		return err
	}
	return p.RemoveToxic(ctx, proxy, toxic)
}

// ParseRouter reads "proxy=url,proxy=url" into a Router of HTTP clients.
func ParseRouter(spec string) (Router, error) {
	r := Router{}
	for _, part := range strings.Split(spec, ",") {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}
		name, base, ok := strings.Cut(part, "=")
		if !ok || name == "" || base == "" {
			return nil, fmt.Errorf("bad Toxiproxy entry %q, want proxy=url", part)
		}
		r[name] = NewClient(base)
	}
	if len(r) == 0 {
		return nil, fmt.Errorf("no Toxiproxy servers in %q", spec)
	}
	return r, nil
}
