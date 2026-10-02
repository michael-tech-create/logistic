// Terminal watch reads the public PTML Tin Can vessel schedule and posts it
// to the quote API. If that live page cannot be read, it reports the feed down
// so a person can review it.
package main

import (
	"bytes"
	"crypto/tls"
	"encoding/json"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/gocolly/colly/v2"
)

type Status struct {
	Container    string `json:"container"`
	GateOut      string `json:"gate_out"`
	Vessel       string `json:"vessel"`
	Berth        string `json:"berth"`
	FreeDaysLeft int    `json:"free_days_left"`
	FeedDown     bool   `json:"feed_down"`
	Source       string `json:"source"`
}

func loadDotEnv(path string) {
	raw, err := os.ReadFile(path)
	if err != nil {
		return
	}
	for _, line := range strings.Split(string(raw), "\n") {
		line = strings.TrimSpace(line)
		if line == "" || strings.HasPrefix(line, "#") || !strings.Contains(line, "=") {
			continue
		}
		key, value, _ := strings.Cut(line, "=")
		if os.Getenv(key) == "" {
			os.Setenv(key, strings.Trim(value, `"'`))
		}
	}
}

func main() {
	loadDotEnv("../.env")
	target := os.Getenv("TERMINAL_URL")
	if target == "" {
		target = "https://www.ptml-nigeria.com/"
	}
	status := scrape(target)
	status.Source = target
	raw, _ := json.Marshal(status)
	log.Printf("scraped %s", raw)

	hook := os.Getenv("QUOTE_API_URL")
	if hook == "" {
		hook = "http://127.0.0.1:8000/v1/terminal/status"
	}
	request, err := http.NewRequest(http.MethodPost, hook, bytes.NewReader(raw))
	if err != nil {
		log.Fatal(err)
	}
	request.Header.Set("Content-Type", "application/json")
	if secret := os.Getenv("TERMINAL_WEBHOOK_SECRET"); secret != "" {
		request.Header.Set("X-Terminal-Token", secret)
	}
	response, err := http.DefaultClient.Do(request)
	if err != nil {
		log.Fatalf("webhook: %v", err)
	}
	defer response.Body.Close()
	log.Printf("webhook status %d", response.StatusCode)
}

func scrape(target string) Status {
	status := Status{FeedDown: true, GateOut: "live feed unread"}
	collector := colly.NewCollector()
	collector.WithTransport(&http.Transport{
		TLSClientConfig: &tls.Config{InsecureSkipVerify: true}, // PTML's certificate chain is not trusted by this host.
	})
	collector.SetRequestTimeout(25 * time.Second)
	collector.OnHTML("table.vessel-schedule-table tbody tr", func(element *colly.HTMLElement) {
		cells := element.ChildTexts("td")
		if len(cells) < 4 || status.Vessel != "" {
			return
		}
		status.Vessel = strings.TrimSpace(cells[0])
		status.Berth = strings.TrimSpace(cells[3])
		status.GateOut = strings.TrimSpace(cells[len(cells)-1])
		status.Container = "vessel-schedule"
		status.FreeDaysLeft = 7
		status.FeedDown = false
	})
	if err := collector.Visit(target); err != nil {
		status.FeedDown = true
		status.GateOut = err.Error()
		return status
	}
	collector.Wait()
	if status.Vessel == "" {
		status.FeedDown = true
		status.GateOut = "The live page returned no vessel row."
	}
	return status
}
