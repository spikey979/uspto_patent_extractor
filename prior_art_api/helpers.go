package main

import (
	"fmt"
	"regexp"
	"strings"
)

// normalizePubNumber converts various publication number formats to database format
// Accepts: "US20160148332A1", "20160148332A1", "20160148332"
// Returns: "20160148332"
func normalizePubNumber(input string) string {
	// Remove US prefix
	input = strings.ToUpper(strings.TrimSpace(input))
	if strings.HasPrefix(input, "US") {
		input = input[2:]
	}

	// Remove kind code (A1, B1, etc.)
	re := regexp.MustCompile(`[A-Z]\d*$`)
	input = re.ReplaceAllString(input, "")

	return input
}

// formatDate converts USPTO date format (YYYYMMDD) to standard formats
// Returns: ISO format (YYYY-MM-DD) and US format (MM/DD/YYYY)
func formatDate(dateStr string) (string, string) {
	if len(dateStr) != 8 {
		return dateStr, dateStr
	}

	year := dateStr[:4]
	month := dateStr[4:6]
	day := dateStr[6:8]

	isoFormat := fmt.Sprintf("%s-%s-%s", year, month, day)
	usFormat := fmt.Sprintf("%s/%s/%s", month, day, year)

	return isoFormat, usFormat
}

// cleanXMLText removes XML tags and normalizes whitespace from text content
func cleanXMLText(data []byte) string {
	text := string(data)

	// Remove XML tags
	re := regexp.MustCompile(`<[^>]+>`)
	text = re.ReplaceAllString(text, " ")

	// Normalize whitespace
	text = regexp.MustCompile(`\s+`).ReplaceAllString(text, " ")

	return strings.TrimSpace(text)
}

// formatLocation creates a location string from city, state, country
func formatLocation(city, state, country string) string {
	return fmt.Sprintf("%s, %s (%s)", city, state, country)
}

// formatClassification creates a classification string from components
func formatClassification(section, class, subclass, mainGroup, subgroup string) string {
	cls := fmt.Sprintf("%s%s%s %s/%s", section, class, subclass, mainGroup, subgroup)
	return strings.TrimSpace(cls)
}
