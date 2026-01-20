package main

import (
	"fmt"
	"regexp"
	"strings"
)

func cleanXMLText(text string) string {
	// Remove XML tags
	text = regexp.MustCompile(`<[^>]+>`).ReplaceAllString(text, " ")

	// CRITICAL: Remove null bytes explicitly (PostgreSQL JSON doesn't support \u0000)
	text = strings.ReplaceAll(text, "\x00", "")

	// Replace control characters and invalid UTF-8
	text = strings.Map(func(r rune) rune {
		// Remove control characters except newline, tab
		// Note: null bytes (0) already removed above
		if r < 32 && r != '\n' && r != '\t' {
			return -1
		}
		return r
	}, text)

	// Normalize whitespace
	text = regexp.MustCompile(`\s+`).ReplaceAllString(text, " ")
	text = strings.TrimSpace(text)

	return text
}

func main() {
	// Test with null bytes
	testText := "Hello\x00World\x00Test"
	cleaned := cleanXMLText(testText)
	fmt.Printf("Original (length %d): %q\n", len(testText), testText)
	fmt.Printf("Cleaned (length %d): %q\n", len(cleaned), cleaned)

	if strings.Contains(cleaned, "\x00") {
		fmt.Println("ERROR: Null bytes still present!")
	} else {
		fmt.Println("SUCCESS: Null bytes removed")
	}
}
