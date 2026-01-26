package main

import (
	"database/sql"
	"fmt"

	_ "github.com/lib/pq"
)

var db *sql.DB

// initDB establishes database connection
func initDB() error {
	connStr := fmt.Sprintf(
		"host=%s port=%d user=%s password=%s dbname=%s sslmode=disable",
		cfg.DBHost, cfg.DBPort, cfg.DBUser, cfg.DBPassword, cfg.DBName,
	)

	var err error
	db, err = sql.Open("postgres", connStr)
	if err != nil {
		return fmt.Errorf("failed to open database: %w", err)
	}

	// Connection pool settings
	db.SetMaxOpenConns(10)
	db.SetMaxIdleConns(5)

	// Verify connection
	if err := db.Ping(); err != nil {
		return fmt.Errorf("failed to ping database: %w", err)
	}

	return nil
}

// lookupPatent retrieves patent information from database by publication number
func lookupPatent(pubNumber string) (*PatentLookup, error) {
	normalized := normalizePubNumber(pubNumber)

	var patent PatentLookup
	var pubDate sql.NullTime
	var rawPath sql.NullString
	var title sql.NullString

	err := db.QueryRow(`
		SELECT pub_number, pub_date, raw_xml_path, year, title
		FROM patent_data_unified
		WHERE pub_number = $1
	`, normalized).Scan(&patent.PubNumber, &pubDate, &rawPath, &patent.Year, &title)

	if err != nil {
		return nil, err
	}

	if pubDate.Valid {
		patent.PubDate = &pubDate.Time
	}
	if rawPath.Valid {
		patent.RawXMLPath = rawPath.String
	}
	if title.Valid {
		patent.Title = title.String
	}

	return &patent, nil
}
