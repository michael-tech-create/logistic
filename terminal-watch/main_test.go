package main

import (
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestScrapeLiveTable(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`<table class="vessel-schedule-table"><tbody><tr><td>GRANDE LAGOS</td><td>0626</td><td>US</td><td>30 Sep 2026</td><td>Not Yet Arrived</td></tr></tbody></table>`))
	}))
	defer server.Close()

	status := scrape(server.URL)
	if status.FeedDown {
		t.Fatalf("feed marked down: %s", status.GateOut)
	}
	if status.Vessel != "GRANDE LAGOS" {
		t.Fatalf("vessel %q", status.Vessel)
	}
	if status.Berth != "30 Sep 2026" {
		t.Fatalf("berth %q", status.Berth)
	}
	if status.GateOut != "Not Yet Arrived" {
		t.Fatalf("status %q", status.GateOut)
	}
}

func TestScrapeEmptyPageIsDown(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = w.Write([]byte(`<html><body>no schedule</body></html>`))
	}))
	defer server.Close()

	status := scrape(server.URL)
	if !status.FeedDown {
		t.Fatal("empty page should be feed down")
	}
}
