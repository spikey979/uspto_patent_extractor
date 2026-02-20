package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"image/png"
	"log"
	"net/http"
	"strconv"
	"strings"

	"golang.org/x/image/tiff"
)

// handleRoot serves the API info page
func handleRoot(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")

	json.NewEncoder(w).Encode(map[string]interface{}{
		"service": "Prior Art API",
		"version": "2.0.0",
		"endpoints": map[string]string{
			"GET /api/patent/{pub}":                        "Get full patent document as JSON",
			"GET /api/patent/{pub}/figures/{num}/image":    "Get figure image as PNG (or ?format=tif)",
			"POST /api/patent/{pub}/figures/descriptions":  "Save figure descriptions (from fileApi)",
			"GET /api/patent/{pub}/figures/descriptions":   "Get latest figure descriptions",
			"GET /api/patent/{pub}/figures/{num}/descriptions": "Get all versions of a figure description",
			"GET /health": "Health check",
		},
		"examples": []string{
			"/api/patent/US20160148332A1",
			"/api/patent/US20160148332A1/figures/1/image",
			"/api/patent/US20160148332A1/figures/descriptions",
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

// handleFigureImage serves a patent figure as PNG (or raw TIF with ?format=tif)
func handleFigureImage(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Access-Control-Allow-Origin", "*")

	pubNumber := r.PathValue("pub")
	numStr := r.PathValue("num")

	figureNum, err := strconv.Atoi(numStr)
	if err != nil {
		http.Error(w, "Invalid figure number", http.StatusBadRequest)
		return
	}

	log.Printf("Image request: patent=%s figure=%d", pubNumber, figureNum)

	// Lookup patent
	lookup, err := lookupPatent(pubNumber)
	if err != nil {
		http.Error(w, fmt.Sprintf("Patent not found: %s", pubNumber), http.StatusNotFound)
		return
	}

	// Extract TIF from archive
	tifData, tifFilename, err := extractTIFFromArchive(lookup, figureNum)
	if err != nil {
		http.Error(w, fmt.Sprintf("Failed to extract figure: %v", err), http.StatusNotFound)
		return
	}

	log.Printf("Extracted TIF: %s (%d bytes)", tifFilename, len(tifData))

	// Check if raw TIF was requested
	if r.URL.Query().Get("format") == "tif" {
		w.Header().Set("Content-Type", "image/tiff")
		w.Header().Set("Content-Disposition", fmt.Sprintf("inline; filename=%q", tifFilename))
		w.Write(tifData)
		return
	}

	// Convert TIF to PNG
	img, err := tiff.Decode(bytes.NewReader(tifData))
	if err != nil {
		// Fallback: serve raw TIF if conversion fails
		log.Printf("TIF decode failed, serving raw: %v", err)
		w.Header().Set("Content-Type", "image/tiff")
		w.Header().Set("Content-Disposition", fmt.Sprintf("inline; filename=%q", tifFilename))
		w.Write(tifData)
		return
	}

	w.Header().Set("Content-Type", "image/png")
	if err := png.Encode(w, img); err != nil {
		log.Printf("PNG encode error: %v", err)
		http.Error(w, "Failed to encode PNG", http.StatusInternalServerError)
	}
}

// handleSaveFigureDescriptions saves figure descriptions from fileApi (POST)
func handleSaveFigureDescriptions(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	pubNumber := r.PathValue("pub")
	normalized := normalizePubNumber(pubNumber)

	var req SaveFigureDescriptionsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		json.NewEncoder(w).Encode(SaveFigureDescriptionsResponse{
			Success: false, Error: fmt.Sprintf("Invalid JSON: %v", err),
		})
		return
	}

	if len(req.Figures) == 0 {
		json.NewEncoder(w).Encode(SaveFigureDescriptionsResponse{
			Success: false, Error: "No figures provided",
		})
		return
	}

	log.Printf("Saving %d figure descriptions for patent %s", len(req.Figures), normalized)

	var versions []SavedVersion
	for _, fig := range req.Figures {
		if fig.Desc == "" {
			continue
		}
		version, err := saveFigureDescription(normalized, fig)
		if err != nil {
			log.Printf("Error saving figure %d: %v", fig.FigureNum, err)
			json.NewEncoder(w).Encode(SaveFigureDescriptionsResponse{
				Success: false, Error: fmt.Sprintf("Failed to save figure %d: %v", fig.FigureNum, err),
			})
			return
		}
		versions = append(versions, SavedVersion{FigureNum: fig.FigureNum, Version: version})
	}

	log.Printf("Saved %d descriptions for patent %s", len(versions), normalized)

	json.NewEncoder(w).Encode(SaveFigureDescriptionsResponse{
		Success:  true,
		Saved:    len(versions),
		Versions: versions,
	})
}

// handleGetFigureDescriptions returns latest descriptions for all figures (GET)
func handleGetFigureDescriptions(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	pubNumber := r.PathValue("pub")
	normalized := normalizePubNumber(pubNumber)

	records, err := getLatestFigureDescriptions(normalized)
	if err != nil {
		json.NewEncoder(w).Encode(FigureDescriptionsResponse{
			Success: false, Error: fmt.Sprintf("Query error: %v", err),
		})
		return
	}

	if records == nil {
		records = []FigureDescriptionRecord{}
	}

	json.NewEncoder(w).Encode(FigureDescriptionsResponse{
		Success:   true,
		PubNumber: normalized,
		Figures:   records,
	})
}

// handleGetFigureVersions returns all versions of a specific figure's description (GET)
func handleGetFigureVersions(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("Access-Control-Allow-Origin", "*")

	pubNumber := r.PathValue("pub")
	numStr := r.PathValue("num")
	normalized := normalizePubNumber(pubNumber)

	figureNum, err := strconv.Atoi(numStr)
	if err != nil {
		json.NewEncoder(w).Encode(FigureDescriptionsResponse{
			Success: false, Error: "Invalid figure number",
		})
		return
	}

	records, err := getFigureVersions(normalized, figureNum)
	if err != nil {
		json.NewEncoder(w).Encode(FigureDescriptionsResponse{
			Success: false, Error: fmt.Sprintf("Query error: %v", err),
		})
		return
	}

	if records == nil {
		records = []FigureDescriptionRecord{}
	}

	json.NewEncoder(w).Encode(FigureDescriptionsResponse{
		Success:   true,
		PubNumber: normalized,
		Figures:   records,
	})
}
