package main

import (
	"fmt"
	"log"
	"net/http"
)

func main() {
	log.SetFlags(log.LstdFlags | log.Lshortfile)
	log.Printf("Starting Prior Art API server...")

	// Initialize database connection
	if err := initDB(); err != nil {
		log.Fatalf("Failed to connect to database: %v", err)
	}
	log.Printf("Connected to database: %s@%s:%d/%s",
		cfg.DBUser, cfg.DBHost, cfg.DBPort, cfg.DBName)

	// Setup HTTP routes
	http.HandleFunc("/", handleRoot)
	http.HandleFunc("/health", handleHealth)
	http.HandleFunc("/api/patent/", handleGetPatent)

	// Start server
	addr := fmt.Sprintf(":%d", cfg.ServerPort)
	log.Printf("Server listening on %s", addr)
	log.Printf("Try: curl http://localhost%s/api/patent/US20160148332A1", addr)

	if err := http.ListenAndServe(addr, nil); err != nil {
		log.Fatalf("Server error: %v", err)
	}
}
