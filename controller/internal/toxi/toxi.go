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
