package main

import (
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
)

// handleRoot serves the API info page
func handleRoot(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	json.NewEncoder(w).Encode(map[string]interface{}{
		"service": "Prior Art API",
		"version": "1.0.0",
		"endpoints": map[string]string{
			"GET /api/patent/{pub_number}": "Get full patent document as JSON",
			"GET /health":                  "Health check",
		},
		"examples": []string{
			"/api/patent/US20160148332A1",
			"/api/patent/20160148332",
		},
	})
}

// handleHealth serves the health check endpoint
func handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(map[string]string{"status": "ok"})
}

// handleGetPatent serves the main patent retrieval endpoint
func handleGetPatent(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	// Extract pub_number from path: /api/patent/{pub_number}
	path := strings.TrimPrefix(r.URL.Path, "/api/patent/")
	pubNumber := strings.TrimSpace(path)

	if pubNumber == "" {
		sendError(w, "Missing publication number")
		return
	}

	log.Printf("Request for patent: %s", pubNumber)

	// Step 1: Lookup in database
	lookup, err := lookupPatent(pubNumber)
	if err != nil {
		log.Printf("Lookup error: %v", err)
		sendError(w, fmt.Sprintf("Patent not found: %s", pubNumber))
		return
	}

	log.Printf("Found: %s (year: %d)", lookup.Title, lookup.Year)

	// Step 2: Extract from archive
	extracted, err := extractFromArchive(lookup)
	if err != nil {
		log.Printf("Extraction error: %v", err)
		sendError(w, fmt.Sprintf("Failed to extract patent files: %v", err))
		return
	}

	// Step 3: Parse XML and build document
	doc, err := parsePatentXML(extracted.XMLData, extracted, lookup)
	if err != nil {
		log.Printf("Parse error: %v", err)
		sendError(w, fmt.Sprintf("Failed to parse patent XML: %v", err))
		return
	}

	log.Printf("Successfully built document: %s - %s", doc.PubNumber, doc.Title)

	// Send success response
	json.NewEncoder(w).Encode(APIResponse{
		Success: true,
		Patent:  doc,
	})
}

// sendError sends an error response
func sendError(w http.ResponseWriter, message string) {
	json.NewEncoder(w).Encode(APIResponse{
		Success: false,
		Error:   message,
	})
}
