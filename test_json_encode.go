package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"log"

	_ "github.com/lib/pq"
)

func main() {
	// Test problematic characters that might cause PostgreSQL JSON issues
	testCases := [][]string{
		// Simple case (should work)
		{"The ornamental design for a glove, as shown and described."},
		// With backslash
		{"The ornamental design\\for a device"},
		// With unicode
		{"The ornamental design for a device with \u0000 null character"},
		// With tabs and newlines
		{"The ornamental design\nfor a\tdevice"},
		// With quotes
		{`The ornamental design for a "device"`},
		// With escaped unicode
		{"The ornamental design for a device \u2028"},
	}

	// Connect to database
	connStr := "host=localhost port=5432 user=mark password=mark123 dbname=companies_db sslmode=disable"
	db, err := sql.Open("postgres", connStr)
	if err != nil {
		log.Fatal(err)
	}
	defer db.Close()

	for i, testCase := range testCases {
		// Marshal to JSON
		jsonData, err := json.Marshal(testCase)
		if err != nil {
			fmt.Printf("Test %d: json.Marshal failed: %v\n", i, err)
			continue
		}

		fmt.Printf("Test %d: JSON: %s\n", i, string(jsonData))

		// Try to insert into PostgreSQL
		_, err = db.Exec("SELECT $1::jsonb", jsonData)
		if err != nil {
			fmt.Printf("Test %d: PostgreSQL FAILED: %v\n", i, err)
		} else {
			fmt.Printf("Test %d: PostgreSQL SUCCESS\n", i)
		}
	}
}
