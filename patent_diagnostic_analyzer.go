package main

import (
	"archive/zip"
	"bytes"
	"database/sql"
	"encoding/json"
	"fmt"
	"io/ioutil"
	"log"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"time"

	_ "github.com/lib/pq"
)

type Config struct {
	DBHost     string
	DBPort     int
	DBName     string
	DBUser     string
	DBPassword string
	FilesRoot  string
	LogFile    string
}

var cfg = Config{
	DBHost:     "localhost",
	DBPort:     5432,
	DBName:     "companies_db",
	DBUser:     "postgres",
	DBPassword: "qwklmn711",
	FilesRoot:  "/mnt/patents/originals",
	LogFile:    "/home/mark/projects/patent_extractor/logs/diagnostic_analysis.jsonl",
}

type DiagnosticEntry struct {
	Timestamp            string   `json:"timestamp"`
	PubNumber            string   `json:"pub_number"`
	RawXMLPath           string   `json:"raw_xml_path"`
	Year                 int      `json:"year"`
	FilingDate           string   `json:"filing_date"`
	PubDate              string   `json:"pub_date"`
	ArchiveName          string   `json:"archive_name"`
	ArchiveFound         bool     `json:"archive_found"`
	ArchiveLocation      string   `json:"archive_location,omitempty"`
	ArchiveSize          int64    `json:"archive_size,omitempty"`
	NestedZipFound       bool     `json:"nested_zip_found"`
	NestedZipName        string   `json:"nested_zip_name,omitempty"`
	XMLFileFound         bool     `json:"xml_file_found"`
	XMLFileName          string   `json:"xml_file_name,omitempty"`
	XMLSize              int64    `json:"xml_size,omitempty"`
	XMLReadable          bool     `json:"xml_readable"`
	DTDVersion           string   `json:"dtd_version,omitempty"`
	HasApplicationRef    bool     `json:"has_application_reference"`
	HasDomesticFiling    bool     `json:"has_domestic_filing_data"`
	HasAppNumber         bool     `json:"has_application_number_tag"`
	HasDocNumber         bool     `json:"has_doc_number_tag"`
	RawAppNumberText     string   `json:"raw_app_number_text,omitempty"`
	ExtractedAppNumber   string   `json:"extracted_app_number,omitempty"`
	FailureReason        string   `json:"failure_reason"`
	XMLSample            string   `json:"xml_sample,omitempty"`
	ErrorDetails         []string `json:"error_details,omitempty"`
}

var db *sql.DB
var logFile *os.File

func getEnv(key, def string) string {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		return v
	}
	return def
}

func getEnvInt(key string, def int) int {
	if v := strings.TrimSpace(os.Getenv(key)); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}

func initDB() error {
	cfg.DBHost = getEnv("DB_HOST", cfg.DBHost)
	cfg.DBPort = getEnvInt("DB_PORT", cfg.DBPort)
	cfg.DBName = getEnv("DB_NAME", cfg.DBName)
	cfg.DBUser = getEnv("DB_USER", cfg.DBUser)
	cfg.DBPassword = getEnv("DB_PASSWORD", cfg.DBPassword)
	cfg.FilesRoot = getEnv("FILES_ROOT", cfg.FilesRoot)
	cfg.LogFile = getEnv("LOG_FILE", cfg.LogFile)

	psqlInfo := fmt.Sprintf("host=%s port=%d user=%s password=%s dbname=%s sslmode=disable",
		cfg.DBHost, cfg.DBPort, cfg.DBUser, cfg.DBPassword, cfg.DBName)

	var err error
	db, err = sql.Open("postgres", psqlInfo)
	if err != nil {
		return err
	}

	return db.Ping()
}

func initLogFile() error {
	// Ensure log directory exists
	logDir := filepath.Dir(cfg.LogFile)
	if err := os.MkdirAll(logDir, 0755); err != nil {
		return err
	}

	var err error
	logFile, err = os.OpenFile(cfg.LogFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	return err
}

func writeLog(entry DiagnosticEntry) {
	entry.Timestamp = time.Now().Format(time.RFC3339)
	data, err := json.Marshal(entry)
	if err != nil {
		log.Printf("Error marshaling log entry: %v", err)
		return
	}
	logFile.WriteString(string(data) + "\n")
}

func extractPubDate(path string) string {
	if match := regexp.MustCompile(`-(\d{8})`).FindStringSubmatch(path); len(match) > 1 {
		return match[1]
	}
	return ""
}

func buildArchiveName(pubDate string) string {
	if len(pubDate) == 8 {
		return pubDate + ".ZIP"
	}
	return ""
}

func findArchive(archiveName string) (string, int64, error) {
	// Try multiple archive name variations
	// Some archives are split: 20030313.ZIP -> 20030313A.ZIP + 20030313B.ZIP
	baseArchive := strings.TrimSuffix(archiveName, ".ZIP")

	paths := []string{
		filepath.Join(cfg.FilesRoot, archiveName),
		filepath.Join(cfg.FilesRoot, "NewFiles", archiveName),
		filepath.Join(cfg.FilesRoot, baseArchive+"A.ZIP"),
		filepath.Join(cfg.FilesRoot, baseArchive+"B.ZIP"),
		filepath.Join(cfg.FilesRoot, "NewFiles", baseArchive+"A.ZIP"),
		filepath.Join(cfg.FilesRoot, "NewFiles", baseArchive+"B.ZIP"),
	}

	for _, path := range paths {
		if info, err := os.Stat(path); err == nil {
			return path, info.Size(), nil
		}
	}

	return "", 0, fmt.Errorf("archive not found")
}

func analyzeXMLContent(xmlData []byte) map[string]interface{} {
	result := make(map[string]interface{})

	// Extract DTD version
	if match := regexp.MustCompile(`<!DOCTYPE[^>]*SYSTEM\s+"([^"]+)"`).FindSubmatch(xmlData); len(match) > 1 {
		result["dtd_version"] = string(match[1])
	}

	// Check for various XML structures
	result["has_application_reference"] = regexp.MustCompile(`<application-reference`).Match(xmlData)
	result["has_domestic_filing_data"] = regexp.MustCompile(`<domestic-filing-data`).Match(xmlData)
	result["has_application_number"] = regexp.MustCompile(`<application-number`).Match(xmlData)
	result["has_doc_number"] = regexp.MustCompile(`<doc-number`).Match(xmlData)

	// Try to extract raw application number section
	if match := regexp.MustCompile(`(?is)<application-number[^>]*>(.*?)</application-number>`).FindSubmatch(xmlData); len(match) > 1 {
		result["raw_app_number_text"] = strings.TrimSpace(string(match[1]))
	} else if match := regexp.MustCompile(`(?is)<domestic-filing-data[^>]*>(.*?)</domestic-filing-data>`).FindSubmatch(xmlData); len(match) > 1 {
		// Get application-number within domestic-filing-data
		if appMatch := regexp.MustCompile(`(?is)<application-number[^>]*>(.*?)</application-number>`).FindSubmatch(match[1]); len(appMatch) > 1 {
			result["raw_app_number_text"] = strings.TrimSpace(string(appMatch[1]))
		}
	}

	// Get XML sample (first 2000 chars after DOCTYPE)
	if idx := bytes.Index(xmlData, []byte("]>")); idx > 0 && len(xmlData) > idx+2000 {
		result["xml_sample"] = string(xmlData[idx+2:idx+2000])
	} else if len(xmlData) > 2000 {
		result["xml_sample"] = string(xmlData[:2000])
	} else {
		result["xml_sample"] = string(xmlData)
	}

	return result
}

func extractAppNumber(data []byte) string {
	// Try new format (2005+)
	appRefBlock := regexp.MustCompile(`(?is)<application-reference[^>]*>(.*?)</application-reference>`).FindSubmatch(data)
	if len(appRefBlock) > 1 {
		if match := regexp.MustCompile(`(?is)<doc-number[^>]*>([^<]+)</doc-number>`).FindSubmatch(appRefBlock[1]); len(match) > 1 {
			raw := string(match[1])
			return strings.Map(func(r rune) rune {
				if r >= '0' && r <= '9' {
					return r
				}
				return -1
			}, raw)
		}
	}

	// Try old format (2001-2004)
	domesticBlock := regexp.MustCompile(`(?is)<domestic-filing-data[^>]*>(.*?)</domestic-filing-data>`).FindSubmatch(data)
	if len(domesticBlock) > 1 {
		appNumBlock := regexp.MustCompile(`(?is)<application-number[^>]*>(.*?)</application-number>`).FindSubmatch(domesticBlock[1])
		if len(appNumBlock) > 1 {
			if match := regexp.MustCompile(`(?is)<doc-number[^>]*>([^<]+)</doc-number>`).FindSubmatch(appNumBlock[1]); len(match) > 1 {
				raw := string(match[1])
				return strings.Map(func(r rune) rune {
					if r >= '0' && r <= '9' {
						return r
					}
					return -1
				}, raw)
			}
		}
	}

	return ""
}

func diagnosePatent(pubNumber, rawPath string, year int, filingDate, pubDate string) {
	entry := DiagnosticEntry{
		PubNumber:  pubNumber,
		RawXMLPath: rawPath,
		Year:       year,
		FilingDate: filingDate,
		PubDate:    pubDate,
		ErrorDetails: []string{},
	}

	// Step 1: Extract archive name
	extractedDate := extractPubDate(rawPath)
	if extractedDate == "" {
		entry.FailureReason = "cannot_extract_date_from_path"
		entry.ErrorDetails = append(entry.ErrorDetails, "Path format doesn't match expected pattern with -YYYYMMDD")
		writeLog(entry)
		return
	}

	archiveName := buildArchiveName(extractedDate)
	entry.ArchiveName = archiveName

	// Step 2: Find archive file
	archivePath, archiveSize, err := findArchive(archiveName)
	if err != nil {
		entry.FailureReason = "archive_not_found"
		entry.ErrorDetails = append(entry.ErrorDetails, fmt.Sprintf("Archive %s not found in expected locations", archiveName))
		writeLog(entry)
		return
	}

	entry.ArchiveFound = true
	entry.ArchiveLocation = archivePath
	entry.ArchiveSize = archiveSize

	// Step 3: Load and parse archive
	archiveData, err := ioutil.ReadFile(archivePath)
	if err != nil {
		entry.FailureReason = "archive_read_error"
		entry.ErrorDetails = append(entry.ErrorDetails, fmt.Sprintf("Failed to read archive: %v", err))
		writeLog(entry)
		return
	}

	zr, err := zip.NewReader(bytes.NewReader(archiveData), int64(len(archiveData)))
	if err != nil {
		entry.FailureReason = "archive_parse_error"
		entry.ErrorDetails = append(entry.ErrorDetails, fmt.Sprintf("Failed to parse ZIP: %v", err))
		writeLog(entry)
		return
	}

	// Step 4: Find nested ZIP
	targetFile := filepath.Base(rawPath)
	targetDir := filepath.Dir(rawPath)
	targetZip := targetDir + ".ZIP"
	entry.NestedZipName = targetZip

	var nestedZipData []byte
	for _, f := range zr.File {
		if strings.HasSuffix(strings.ToUpper(f.Name), targetZip) {
			entry.NestedZipFound = true
			rc, err := f.Open()
			if err != nil {
				entry.ErrorDetails = append(entry.ErrorDetails, fmt.Sprintf("Failed to open nested ZIP: %v", err))
				continue
			}
			nestedZipData, err = ioutil.ReadAll(rc)
			rc.Close()
			if err != nil {
				entry.ErrorDetails = append(entry.ErrorDetails, fmt.Sprintf("Failed to read nested ZIP: %v", err))
			}
			break
		}
	}

	if !entry.NestedZipFound {
		entry.FailureReason = "nested_zip_not_found"
		entry.ErrorDetails = append(entry.ErrorDetails, fmt.Sprintf("Nested ZIP %s not found in archive", targetZip))
		writeLog(entry)
		return
	}

	// Step 5: Parse nested ZIP and find XML
	nestedZr, err := zip.NewReader(bytes.NewReader(nestedZipData), int64(len(nestedZipData)))
	if err != nil {
		entry.FailureReason = "nested_zip_parse_error"
		entry.ErrorDetails = append(entry.ErrorDetails, fmt.Sprintf("Failed to parse nested ZIP: %v", err))
		writeLog(entry)
		return
	}

	entry.XMLFileName = targetFile
	var xmlData []byte
	for _, nf := range nestedZr.File {
		if strings.HasSuffix(nf.Name, targetFile) {
			entry.XMLFileFound = true
			entry.XMLSize = int64(nf.UncompressedSize64)

			nrc, err := nf.Open()
			if err != nil {
				entry.ErrorDetails = append(entry.ErrorDetails, fmt.Sprintf("Failed to open XML file: %v", err))
				continue
			}
			xmlData, err = ioutil.ReadAll(nrc)
			nrc.Close()
			if err != nil {
				entry.ErrorDetails = append(entry.ErrorDetails, fmt.Sprintf("Failed to read XML file: %v", err))
			} else {
				entry.XMLReadable = true
			}
			break
		}
	}

	if !entry.XMLFileFound {
		entry.FailureReason = "xml_file_not_found"
		entry.ErrorDetails = append(entry.ErrorDetails, fmt.Sprintf("XML file %s not found in nested ZIP", targetFile))
		writeLog(entry)
		return
	}

	if !entry.XMLReadable {
		entry.FailureReason = "xml_read_error"
		writeLog(entry)
		return
	}

	// Step 6: Analyze XML content
	analysis := analyzeXMLContent(xmlData)

	if dtd, ok := analysis["dtd_version"].(string); ok {
		entry.DTDVersion = dtd
	}
	if val, ok := analysis["has_application_reference"].(bool); ok {
		entry.HasApplicationRef = val
	}
	if val, ok := analysis["has_domestic_filing_data"].(bool); ok {
		entry.HasDomesticFiling = val
	}
	if val, ok := analysis["has_application_number"].(bool); ok {
		entry.HasAppNumber = val
	}
	if val, ok := analysis["has_doc_number"].(bool); ok {
		entry.HasDocNumber = val
	}
	if val, ok := analysis["raw_app_number_text"].(string); ok {
		entry.RawAppNumberText = val
	}
	if val, ok := analysis["xml_sample"].(string); ok {
		entry.XMLSample = val
	}

	// Step 7: Try to extract application number
	appNum := extractAppNumber(xmlData)
	entry.ExtractedAppNumber = appNum

	// Determine failure reason
	if appNum == "" {
		if !entry.HasApplicationRef && !entry.HasDomesticFiling {
			entry.FailureReason = "no_application_section_in_xml"
		} else if !entry.HasAppNumber {
			entry.FailureReason = "no_application_number_tag"
		} else if !entry.HasDocNumber {
			entry.FailureReason = "no_doc_number_tag"
		} else {
			entry.FailureReason = "extraction_failed_unknown"
			entry.ErrorDetails = append(entry.ErrorDetails, "Has required tags but extraction failed - possible format mismatch")
		}
	} else {
		entry.FailureReason = "extracted_successfully_but_not_in_db"
		entry.ErrorDetails = append(entry.ErrorDetails, "Successfully extracted app number - possible DB update issue?")
	}

	writeLog(entry)
}

func main() {
	log.SetOutput(os.Stdout)
	log.Println("Starting Patent Diagnostic Analyzer...")
	log.Printf("Log output: %s", cfg.LogFile)

	if err := initDB(); err != nil {
		log.Fatalf("DB init failed: %v", err)
	}
	defer db.Close()

	if err := initLogFile(); err != nil {
		log.Fatalf("Log file init failed: %v", err)
	}
	defer logFile.Close()

	// Query missing patents
	query := `
		SELECT pub_number, raw_xml_path, year, filing_date, pub_date
		FROM patent_data_unified
		WHERE (application_number IS NULL OR application_number = '')
		  AND raw_xml_path IS NOT NULL
		  AND raw_xml_path != ''
		  AND year IN (2001, 2002, 2003, 2004, 2010)
		ORDER BY year, pub_number
		LIMIT 1000
	`

	log.Println("Querying database for missing patents...")
	rows, err := db.Query(query)
	if err != nil {
		log.Fatalf("Query failed: %v", err)
	}
	defer rows.Close()

	count := 0
	for rows.Next() {
		var pubNumber, rawPath string
		var year int
		var filingDate, pubDate *string

		if err := rows.Scan(&pubNumber, &rawPath, &year, &filingDate, &pubDate); err != nil {
			log.Printf("Scan error: %v", err)
			continue
		}

		fd := ""
		if filingDate != nil {
			fd = *filingDate
		}
		pd := ""
		if pubDate != nil {
			pd = *pubDate
		}

		count++
		if count%100 == 0 {
			log.Printf("Analyzed %d patents...", count)
		}

		diagnosePatent(pubNumber, rawPath, year, fd, pd)
	}

	log.Printf("\n=== Diagnostic Analysis Complete ===")
	log.Printf("Analyzed: %d patents", count)
	log.Printf("Results written to: %s", cfg.LogFile)
	log.Println("\nTo analyze results, use:")
	log.Printf("  jq '.failure_reason' %s | sort | uniq -c", cfg.LogFile)
	log.Printf("  jq 'select(.failure_reason == \"no_application_section_in_xml\")' %s", cfg.LogFile)
}
