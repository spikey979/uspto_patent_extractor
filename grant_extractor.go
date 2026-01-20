package main

import (
	"archive/zip"
	"bytes"
	"database/sql"
	"encoding/xml"
	"flag"
	"fmt"
	"html"
	"io"
	"log"
	"os"
	"path/filepath"
	"regexp"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	_ "github.com/lib/pq"
)

// GrantExtractor configuration
type GrantConfig struct {
	DBHost     string
	DBPort     int
	DBName     string
	DBUser     string
	DBPassword string

	FilesRoot    string // /mnt/patents/originals_ptgrmp2
	ProcessedLog string
	LogDir       string

	Workers   int
	BatchSize int
}

var grantCfg = GrantConfig{
	DBHost:       "localhost",
	DBPort:       5432,
	DBName:       "companies_db",
	DBUser:       "postgres",
	DBPassword:   "qwklmn711",
	FilesRoot:    "/mnt/patents/data/grants/xml",
	ProcessedLog: "/home/mark/projects/patent_extractor/processed_grant_archives.txt",
	LogDir:       "/home/mark/projects/patent_extractor/logs",
	Workers:      8,
	BatchSize:    500,
}

// Patent Grant structures matching USPTO XML format
type USPatentGrant struct {
	XMLName xml.Name `xml:"us-patent-grant"`
	Lang    string   `xml:"lang,attr"`
	File    string   `xml:"file,attr"`
	BibData GrantBibData `xml:"us-bibliographic-data-grant"`
	Abstract GrantAbstract `xml:"abstract"`
	Description GrantDescription `xml:"description"`
	Claims  GrantClaims `xml:"claims"`
}

type GrantBibData struct {
	PubRef    GrantDocRef `xml:"publication-reference>document-id"`
	AppRef    GrantDocRef `xml:"application-reference>document-id"`
	Title     string      `xml:"invention-title"`
	References GrantReferences `xml:"us-references-cited"`
}

type GrantDocRef struct {
	Country   string `xml:"country"`
	DocNumber string `xml:"doc-number"`
	Kind      string `xml:"kind"`
	Date      string `xml:"date"`
}

type GrantReferences struct {
	USCitations []GrantUSCitation `xml:"us-citation"`
}

type GrantUSCitation struct {
	PatCit   GrantPatCit `xml:"patcit"`
	NPLCit   struct{Othercit string `xml:"othercit"`} `xml:"nplcit"`
	Category string      `xml:"category"`
}

type GrantPatCit struct {
	Num    string      `xml:"num,attr"`
	DocID  GrantDocRef `xml:"document-id"`
}

type GrantAbstract struct {
	Paragraphs []GrantParagraph `xml:"p"`
}

type GrantDescription struct {
	Paragraphs []GrantParagraph `xml:"p"`
}

type GrantParagraph struct {
	Text string `xml:",chardata"`
}

type GrantClaims struct {
	Claims []GrantClaim `xml:"claim"`
}

type GrantClaim struct {
	Num  string `xml:"num,attr"`
	Text string `xml:",innerxml"`
}

// Database structure for patent grants - METADATA ONLY
// Citations, claims, and bulk data are fetched on-demand from raw_xml_source
type PatentGrant struct {
	GrantNumber       string     `json:"grant_number"`
	Kind              string     `json:"kind"`
	Title             string     `json:"title"`
	GrantDate         *time.Time `json:"grant_date"`
	ApplicationNumber string     `json:"application_number"`
	ApplicationDate   *time.Time `json:"application_date"`
	AbstractText      string     `json:"abstract_text"`
	Year              int        `json:"year"`
	RawXMLSource      string     `json:"raw_xml_source"` // "ipg250107.zip/ipg250107.xml"
}

type GrantStats struct {
	TotalFiles      int64
	FilesProcessed  int64
	FilesSkipped    int64
	FilesFailed     int64
	GrantsExtracted int64
	GrantsInserted  int64
	GrantsFailed    int64
	FailuresByType  map[string]int64
	mu              sync.Mutex
}

type GrantExtractor struct {
	db               *sql.DB
	processedArchives map[string]bool
	mu               sync.Mutex
	stats            GrantStats
}

func main() {
	var (
		testMode = flag.Bool("test", false, "Test mode: process one file only")
		workers  = flag.Int("workers", grantCfg.Workers, "Number of concurrent workers")
	)
	flag.Parse()

	grantCfg.Workers = *workers

	log.SetFlags(log.LstdFlags | log.Lshortfile)
	log.Printf("Grant Extractor Starting - Workers: %d, BatchSize: %d", grantCfg.Workers, grantCfg.BatchSize)

	// Connect to database
	connStr := fmt.Sprintf("host=%s port=%d dbname=%s user=%s password=%s sslmode=disable",
		grantCfg.DBHost, grantCfg.DBPort, grantCfg.DBName, grantCfg.DBUser, grantCfg.DBPassword)

	db, err := sql.Open("postgres", connStr)
	if err != nil {
		log.Fatalf("Database connection error: %v", err)
	}
	defer db.Close()

	if err := db.Ping(); err != nil {
		log.Fatalf("Database ping failed: %v", err)
	}
	log.Println("Database connection established")

	// Create table if not exists
	if err := createGrantTable(db); err != nil {
		log.Fatalf("Failed to create grant table: %v", err)
	}

	// Initialize extractor
	extractor := &GrantExtractor{
		db:                db,
		processedArchives: make(map[string]bool),
		stats: GrantStats{
			FailuresByType: make(map[string]int64),
		},
	}

	// Load processed archives
	if err := extractor.loadProcessedArchives(); err != nil {
		log.Printf("Warning: Could not load processed archives: %v", err)
	}

	// Find grant archives (ipgYYMMDD.zip files)
	archives, err := extractor.findGrantArchives()
	if err != nil {
		log.Fatalf("Failed to find grant archives: %v", err)
	}

	log.Printf("Found %d grant archives", len(archives))
	extractor.stats.TotalFiles = int64(len(archives))

	if *testMode && len(archives) > 0 {
		log.Println("TEST MODE: Processing first file only")
		archives = archives[:1]
	}

	// Process archives
	startTime := time.Now()
	extractor.processArchives(archives)
	duration := time.Since(startTime)

	// Print final statistics
	log.Println("===========================================")
	log.Println("GRANT EXTRACTION COMPLETE")
	log.Println("===========================================")
	log.Printf("Total Files: %d", extractor.stats.TotalFiles)
	log.Printf("Files Processed: %d", extractor.stats.FilesProcessed)
	log.Printf("Files Skipped: %d", extractor.stats.FilesSkipped)
	log.Printf("Files Failed: %d", extractor.stats.FilesFailed)
	log.Printf("Grants Extracted: %d", extractor.stats.GrantsExtracted)
	log.Printf("Grants Inserted: %d", extractor.stats.GrantsInserted)
	log.Printf("Grants Failed: %d", extractor.stats.GrantsFailed)

	if extractor.stats.GrantsExtracted > 0 {
		successRate := float64(extractor.stats.GrantsInserted) / float64(extractor.stats.GrantsExtracted) * 100
		log.Printf("Success Rate: %.2f%%", successRate)

		// CRITICAL: 100% success rate required - raise alarm if not achieved
		if successRate < 100.0 {
			log.Println("")
			log.Println("🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨")
			log.Printf("🚨 CRITICAL ALERT: NOT 100%% SUCCESS RATE! 🚨")
			log.Printf("🚨 %d grants FAILED out of %d total (%.2f%% success)",
				extractor.stats.GrantsFailed, extractor.stats.GrantsExtracted, successRate)
			log.Println("🚨 INVESTIGATION REQUIRED - Check /tmp/grant_failure_*.json files")
			log.Println("🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨")
			log.Println("")
		} else {
			log.Println("")
			log.Println("✅ 100% SUCCESS RATE ACHIEVED - ALL GRANTS IMPORTED SUCCESSFULLY ✅")
			log.Println("")
		}
	}

	if len(extractor.stats.FailuresByType) > 0 {
		log.Println("\nFailure Breakdown:")
		for failType, count := range extractor.stats.FailuresByType {
			pct := float64(count) / float64(extractor.stats.GrantsFailed) * 100
			log.Printf("  %s: %d (%.1f%%)", failType, count, pct)
		}
		log.Printf("\nDetailed failures logged to: %s", filepath.Join(grantCfg.LogDir, "grant_failures.log"))
	}

	log.Printf("\nDuration: %v", duration)
	if extractor.stats.GrantsInserted > 0 {
		log.Printf("Avg Rate: %.1f grants/sec", float64(extractor.stats.GrantsInserted)/duration.Seconds())
	}
}

func createGrantTable(db *sql.DB) error {
	// SIMPLIFIED SCHEMA: Metadata only, no citations/claims JSONB
	// Bulk data (citations, claims, NPL) fetched on-demand from raw_xml_source
	query := `
	CREATE TABLE IF NOT EXISTS patent_grants (
		id SERIAL PRIMARY KEY,
		grant_number VARCHAR(20) NOT NULL UNIQUE,
		kind VARCHAR(5),
		title TEXT,
		grant_date DATE,
		application_number VARCHAR(20),
		application_date DATE,
		abstract_text TEXT,
		year INTEGER,
		raw_xml_source VARCHAR(255),
		created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
	);

	CREATE INDEX IF NOT EXISTS idx_grants_number ON patent_grants(grant_number);
	CREATE INDEX IF NOT EXISTS idx_grants_year ON patent_grants(year);
	CREATE INDEX IF NOT EXISTS idx_grants_app_number ON patent_grants(application_number);
	`

	_, err := db.Exec(query)
	return err
}

func (e *GrantExtractor) loadProcessedArchives() error {
	data, err := os.ReadFile(grantCfg.ProcessedLog)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return err
	}

	for _, line := range strings.Split(string(data), "\n") {
		line = strings.TrimSpace(line)
		if line != "" {
			e.processedArchives[line] = true
		}
	}

	log.Printf("Loaded %d processed archives from log", len(e.processedArchives))
	return nil
}

func (e *GrantExtractor) markProcessed(archivePath string) error {
	e.mu.Lock()
	defer e.mu.Unlock()

	e.processedArchives[archivePath] = true

	f, err := os.OpenFile(grantCfg.ProcessedLog, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return err
	}
	defer f.Close()

	_, err = f.WriteString(archivePath + "\n")
	return err
}

func (e *GrantExtractor) findGrantArchives() ([]string, error) {
	var archives []string

	err := filepath.Walk(grantCfg.FilesRoot, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}

		if info.IsDir() {
			return nil
		}

		// Match ipgYYMMDD.zip pattern
		if strings.HasPrefix(info.Name(), "ipg") && strings.HasSuffix(info.Name(), ".zip") {
			archives = append(archives, path)
		}

		return nil
	})

	return archives, err
}

func (e *GrantExtractor) processArchives(archives []string) {
	var wg sync.WaitGroup
	archiveChan := make(chan string, grantCfg.Workers)

	// Start workers
	for i := 0; i < grantCfg.Workers; i++ {
		wg.Add(1)
		go func(workerID int) {
			defer wg.Done()
			for archivePath := range archiveChan {
				e.processArchive(archivePath, workerID)
			}
		}(i)
	}

	// Feed archives to workers
	for _, archivePath := range archives {
		// Skip if already processed
		e.mu.Lock()
		alreadyProcessed := e.processedArchives[archivePath]
		e.mu.Unlock()

		if alreadyProcessed {
			atomic.AddInt64(&e.stats.FilesSkipped, 1)
			log.Printf("Skipping already processed: %s", filepath.Base(archivePath))
			continue
		}

		archiveChan <- archivePath
	}

	close(archiveChan)
	wg.Wait()
}

func (e *GrantExtractor) processArchive(archivePath string, workerID int) {
	archiveName := filepath.Base(archivePath)
	log.Printf("[Worker %d] Processing: %s", workerID, archiveName)

	// Open ZIP file
	r, err := zip.OpenReader(archivePath)
	if err != nil {
		log.Printf("[Worker %d] Failed to open archive %s: %v", workerID, archiveName, err)
		atomic.AddInt64(&e.stats.FilesFailed, 1)
		return
	}
	defer r.Close()

	// Should contain one large XML file
	if len(r.File) == 0 {
		log.Printf("[Worker %d] Empty archive: %s", workerID, archiveName)
		atomic.AddInt64(&e.stats.FilesFailed, 1)
		return
	}

	// Process the XML file
	xmlFile := r.File[0]
	rc, err := xmlFile.Open()
	if err != nil {
		log.Printf("[Worker %d] Failed to open XML in %s: %v", workerID, archiveName, err)
		atomic.AddInt64(&e.stats.FilesFailed, 1)
		return
	}
	defer rc.Close()

	// Read entire XML (it's large but fits in memory)
	xmlData, err := io.ReadAll(rc)
	if err != nil {
		log.Printf("[Worker %d] Failed to read XML from %s: %v", workerID, archiveName, err)
		atomic.AddInt64(&e.stats.FilesFailed, 1)
		return
	}

	log.Printf("[Worker %d] Read %d bytes from %s, parsing grants...", workerID, len(xmlData), archiveName)

	// Construct full XML path: "ipg250415.zip/ipg250415.xml"
	xmlPath := archiveName + "/" + xmlFile.Name

	// Parse grants from XML (streaming approach for large files)
	grants, err := e.parseGrants(xmlData, xmlPath)
	if err != nil {
		log.Printf("[Worker %d] Failed to parse grants from %s: %v", workerID, archiveName, err)
		atomic.AddInt64(&e.stats.FilesFailed, 1)
		return
	}

	log.Printf("[Worker %d] Extracted %d grants from %s", workerID, len(grants), archiveName)
	atomic.AddInt64(&e.stats.GrantsExtracted, int64(len(grants)))

	// Insert grants in batches
	inserted, failed := e.insertGrants(grants, workerID)
	atomic.AddInt64(&e.stats.GrantsInserted, int64(inserted))
	atomic.AddInt64(&e.stats.GrantsFailed, int64(failed))

	// Mark archive as processed
	if err := e.markProcessed(archivePath); err != nil {
		log.Printf("[Worker %d] Warning: Could not mark archive as processed: %v", workerID, err)
	}

	atomic.AddInt64(&e.stats.FilesProcessed, 1)

	// CRITICAL: 100% success rate required - raise alarm if any failures
	if failed > 0 {
		log.Printf("🚨🚨🚨 ALERT: [Worker %d] %s had %d FAILURES out of %d grants (%.1f%% success) 🚨🚨🚨",
			workerID, archiveName, failed, inserted+failed, float64(inserted)*100/float64(inserted+failed))
	} else {
		log.Printf("[Worker %d] Completed %s - Inserted: %d, Failed: %d (100%% SUCCESS)", workerID, archiveName, inserted, failed)
	}
}

func (e *GrantExtractor) parseGrants(xmlData []byte, source string) ([]PatentGrant, error) {
	var grants []PatentGrant

	// Split XML into individual grant documents
	// Each grant starts with <us-patent-grant and ends with </us-patent-grant>
	decoder := xml.NewDecoder(bytes.NewReader(xmlData))

	for {
		token, err := decoder.Token()
		if err == io.EOF {
			break
		}
		if err != nil {
			return grants, fmt.Errorf("XML decode error: %v", err)
		}

		// Look for start element
		if se, ok := token.(xml.StartElement); ok && se.Name.Local == "us-patent-grant" {
			var uspg USPatentGrant
			if err := decoder.DecodeElement(&uspg, &se); err != nil {
				log.Printf("Warning: Failed to decode grant: %v", err)
				continue
			}

			grant := e.convertGrant(&uspg, source)
			if grant != nil {
				grants = append(grants, *grant)
			}
		}
	}

	return grants, nil
}

func (e *GrantExtractor) convertGrant(uspg *USPatentGrant, archivePath string) *PatentGrant {
	// METADATA ONLY - no citations, no claims, no description
	// Bulk data fetched on-demand from raw_xml_source
	grant := &PatentGrant{
		GrantNumber:  cleanXMLText(uspg.BibData.PubRef.DocNumber),
		Kind:         cleanXMLText(uspg.BibData.PubRef.Kind),
		Title:        cleanXMLText(uspg.BibData.Title),
		RawXMLSource: archivePath, // "ipg250107.zip/ipg250107.xml"
	}

	// Parse grant date
	if uspg.BibData.PubRef.Date != "" {
		if t, err := parseUSPTODate(uspg.BibData.PubRef.Date); err == nil {
			grant.GrantDate = &t
			grant.Year = t.Year()
		}
	}

	// Parse application data
	grant.ApplicationNumber = cleanXMLText(uspg.BibData.AppRef.DocNumber)
	if uspg.BibData.AppRef.Date != "" {
		if t, err := parseUSPTODate(uspg.BibData.AppRef.Date); err == nil {
			grant.ApplicationDate = &t
		}
	}

	// Extract abstract only (for search) - clean text
	var abstractParts []string
	for _, p := range uspg.Abstract.Paragraphs {
		cleaned := cleanXMLText(p.Text)
		if cleaned != "" {
			abstractParts = append(abstractParts, cleaned)
		}
	}
	grant.AbstractText = strings.Join(abstractParts, " ")

	// NOTE: Citations, claims, description, NPL are NOT stored
	// Fetch on-demand from raw_xml_source when needed

	return grant
}

// cleanXMLText removes XML tags and ensures text is valid for JSON encoding
func cleanXMLText(text string) string {
	// Remove XML tags
	text = regexp.MustCompile(`<[^>]+>`).ReplaceAllString(text, " ")

	// CRITICAL: Remove null bytes explicitly (PostgreSQL JSON doesn't support \u0000)
	text = strings.ReplaceAll(text, "\x00", "")

	// CRITICAL: Decode HTML entities using Go's standard library
	// This prevents double-encoding issues when json.Marshal later processes the text
	text = html.UnescapeString(text)

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

func parseUSPTODate(dateStr string) (time.Time, error) {
	// Try YYYYMMDD format first (20251104)
	if len(dateStr) == 8 {
		return time.Parse("20060102", dateStr)
	}
	// Try YYYY-MM-DD format
	if len(dateStr) == 10 {
		return time.Parse("2006-01-02", dateStr)
	}
	return time.Time{}, fmt.Errorf("unknown date format: %s", dateStr)
}

func (e *GrantExtractor) insertGrants(grants []PatentGrant, workerID int) (int, int) {
	inserted := 0
	failed := 0

	// Process in batches
	for i := 0; i < len(grants); i += grantCfg.BatchSize {
		end := i + grantCfg.BatchSize
		if end > len(grants) {
			end = len(grants)
		}

		batch := grants[i:end]
		batchInserted, batchFailed := e.insertBatch(batch, workerID)
		inserted += batchInserted
		failed += batchFailed
	}

	return inserted, failed
}

func (e *GrantExtractor) insertBatch(grants []PatentGrant, workerID int) (int, int) {
	inserted := 0
	failed := 0

	// SIMPLIFIED: Metadata only, no JSONB fields
	for _, grant := range grants {
		_, err := e.db.Exec(`
			INSERT INTO patent_grants (
				grant_number, kind, title, grant_date,
				application_number, application_date,
				abstract_text, year, raw_xml_source
			) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
			ON CONFLICT (grant_number) DO NOTHING
		`,
			grant.GrantNumber, grant.Kind, grant.Title, grant.GrantDate,
			grant.ApplicationNumber, grant.ApplicationDate,
			grant.AbstractText, grant.Year, grant.RawXMLSource,
		)

		if err != nil {
			errType := categorizeDBError(err)
			e.recordFailure(errType, grant.GrantNumber, err.Error())
			failed++
		} else {
			inserted++
		}
	}

	return inserted, failed
}

func categorizeDBError(err error) string {
	errStr := err.Error()
	if strings.Contains(errStr, "invalid input syntax for type json") {
		return "db_invalid_json"
	}
	if strings.Contains(errStr, "duplicate key") {
		return "db_duplicate"
	}
	if strings.Contains(errStr, "violates foreign key") {
		return "db_foreign_key"
	}
	if strings.Contains(errStr, "value too long") {
		return "db_value_too_long"
	}
	return "db_other"
}

func (e *GrantExtractor) recordFailure(failureType, grantNumber, details string) {
	e.stats.mu.Lock()
	e.stats.FailuresByType[failureType]++
	e.stats.mu.Unlock()

	// Log to file for analysis
	logFile := filepath.Join(grantCfg.LogDir, "grant_failures.log")
	f, err := os.OpenFile(logFile, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err == nil {
		defer f.Close()
		timestamp := time.Now().Format("2006-01-02 15:04:05")
		f.WriteString(fmt.Sprintf("%s\t%s\t%s\t%s\n", timestamp, failureType, grantNumber, details))
	}
}
