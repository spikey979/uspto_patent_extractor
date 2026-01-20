package main

// Patent Application Number Backfill - Unified System
//
// This script fills in missing application numbers for patents in the database
// by extracting them from XML files in various archive formats.
//
// Handles multiple archive formats and edge cases:
//
// 1. Standard ZIP archives (2001-2004, early 2010):
//    - Format: 20030313.ZIP containing nested ZIPs
//    - Nested structure: 20030313/UTIL0046/US20030046754A1-20030313.ZIP
//
// 2. Split archives (2003 A/B):
//    - Some dates split into multiple files: 20030313A.ZIP, 20030313B.ZIP
//    - Patents from same date can be in different archives
//    - Solution: Load ALL variants (A, B) and try each
//
// 3. I-prefix archives (2010):
//    - Archive names: I20100107.ZIP (note the "I" prefix)
//    - Same nested structure as earlier years
//
// 4. Extracted directories (late 2010 Oct-Dec):
//    - TAR archives were pre-extracted to xml_extracted/I20101021/
//    - Directory structure: xml_extracted/I20101021/US20100266615A1-20101021/tmp*_US20100266615A1-20101021/
//    - No archives to load - read XML files directly from disk
//
// XML Format Handling:
// - Old format (2001-2004): <domestic-filing-data><application-number><doc-number>
// - New format (2005+): <application-reference><doc-number>
//
// Memory Management:
// - Processes one date at a time to avoid loading all archives simultaneously
// - Explicitly clears archive data and runs GC after each batch
// - Workers: 8, Batch size: 500

import (
	"archive/zip"
	"bytes"
	"database/sql"
	"fmt"
	"io/ioutil"
	"log"
	"os"
	"os/signal"
	"path/filepath"
	"regexp"
	"runtime"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"syscall"
	"time"

	_ "github.com/lib/pq"
)

type Config struct {
	DBHost     string
	DBPort     int
	DBName     string
	DBUser     string
	DBPassword string

	FilesRoot        string
	Workers          int
	BatchSize        int
	MaxCacheSize     int64 // Max cache size in bytes (default 2GB)
	CheckpointEvery  int   // Save progress every N patents
}

var cfg = Config{
	DBHost:     "localhost",
	DBPort:     5432,
	DBName:     "companies_db",
	DBUser:     "postgres",
	DBPassword: "qwklmn711",

	FilesRoot:       "/mnt/patents/originals",
	Workers:         8,  // Reduced from 16 to use less memory
	BatchSize:       500, // Reduced from 2000 to smaller batches
	MaxCacheSize:    2 * 1024 * 1024 * 1024, // 2GB cache limit
	CheckpointEvery: 10000,
}

type Stats struct {
	PatentsProcessed int64
	PatentsUpdated   int64
	ArchivesLoaded   int64
	ArchivesSkipped  int64
	Errors           int64
	StartTime        time.Time
	LastCheckpoint   int64
}

type PatentToFix struct {
	PubNumber string
	RawPath   string
}

type PatentUpdate struct {
	PubNumber         string
	ApplicationNumber string
}

type Extractor struct {
	db              *sql.DB
	stats           *Stats
	workChan        chan []PatentToFix
	resultChan      chan []PatentUpdate
	wg              sync.WaitGroup
	insWG           sync.WaitGroup
	shutdown        chan bool
	archiveCacheSize int64
	processedPubNums sync.Map // Track processed patents for checkpointing
}

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

func NewExtractor() (*Extractor, error) {
	cfg.DBHost = getEnv("DB_HOST", cfg.DBHost)
	cfg.DBPort = getEnvInt("DB_PORT", cfg.DBPort)
	cfg.DBName = getEnv("DB_NAME", cfg.DBName)
	cfg.DBUser = getEnv("DB_USER", cfg.DBUser)
	cfg.DBPassword = getEnv("DB_PASSWORD", cfg.DBPassword)
	cfg.Workers = getEnvInt("WORKERS", cfg.Workers)
	cfg.BatchSize = getEnvInt("BATCH_SIZE", cfg.BatchSize)
	cfg.FilesRoot = getEnv("FILES_ROOT", cfg.FilesRoot)

	psqlInfo := fmt.Sprintf("host=%s port=%d user=%s password=%s dbname=%s sslmode=disable",
		cfg.DBHost, cfg.DBPort, cfg.DBUser, cfg.DBPassword, cfg.DBName)

	db, err := sql.Open("postgres", psqlInfo)
	if err != nil {
		return nil, err
	}

	if err = db.Ping(); err != nil {
		return nil, err
	}

	db.SetMaxOpenConns(25)
	db.SetMaxIdleConns(5)

	e := &Extractor{
		db:         db,
		stats:      &Stats{StartTime: time.Now()},
		workChan:   make(chan []PatentToFix, 100),
		resultChan: make(chan []PatentUpdate, 100),
		shutdown:   make(chan bool),
	}

	return e, nil
}

// Extract application number from XML - supports both old and new formats
func (e *Extractor) extractAppNumber(data []byte) string {
	// Try new format first (2005+): <application-reference>
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

	// Try old format (2001-2004): <domestic-filing-data><application-number>
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

// Extract publication date from path
func extractPubDate(path string) string {
	if match := regexp.MustCompile(`-(\d{8})`).FindStringSubmatch(path); len(match) > 1 {
		return match[1]
	}
	return ""
}

// Build archive filename from publication date
// Note: 2010 archives have "I" prefix (e.g., I20100107.ZIP)
func buildArchiveName(pubDate string) string {
	if len(pubDate) == 8 {
		// Check if this is a 2010 date (starts with "2010")
		if pubDate[:4] == "2010" {
			return "I" + pubDate + ".ZIP"
		}
		return pubDate + ".ZIP"
	}
	return ""
}

// Load archive without caching (to avoid OOM)
func (e *Extractor) loadArchive(archivePath string) ([]byte, error) {
	data, err := ioutil.ReadFile(archivePath)
	if err != nil {
		return nil, err
	}
	atomic.AddInt64(&e.stats.ArchivesLoaded, 1)
	return data, nil
}

// Try to extract from xml_extracted directory (for late 2010 and some 2002 patents)
func (e *Extractor) extractFromDirectory(pubDate string, xmlFilename string) string {
	// Late 2010 patents (Oct-Dec) are in xml_extracted directories with I-prefix
	// Some 2002 patents are in xml_extracted without I-prefix
	// Path structure: xml_extracted/I20101021/... or xml_extracted/20020725/...

	// Try I-prefix first (2010)
	extractedDir := filepath.Join(cfg.FilesRoot, "xml_extracted", "I"+pubDate)

	// If not found, try without I-prefix (2002 and others)
	if _, err := os.Stat(extractedDir); os.IsNotExist(err) {
		extractedDir = filepath.Join(cfg.FilesRoot, "xml_extracted", pubDate)
		if _, err := os.Stat(extractedDir); os.IsNotExist(err) {
			return ""
		}
	}

	// Expected structure: xml_extracted/I20101021/US20100266615A1-20101021/tmp*_US20100266615A1-20101021/US20100266615A1-20101021.XML
	// We need to find the file by walking the directory
	patentDir := filepath.Dir(xmlFilename)
	targetFile := filepath.Base(xmlFilename)

	// Look for the patent directory
	patentDirPath := filepath.Join(extractedDir, patentDir)
	if _, err := os.Stat(patentDirPath); os.IsNotExist(err) {
		// Patent directory doesn't exist at expected location
		// Fall back to recursive search (handles PG-PUB and other anomalies)
		return e.recursiveSearchForXML(extractedDir, targetFile)
	}

	// List subdirectories (should be one tmp* directory)
	entries, err := ioutil.ReadDir(patentDirPath)
	if err != nil {
		return ""
	}

	for _, entry := range entries {
		if entry.IsDir() {
			// Check for XML file in this subdirectory
			xmlPath := filepath.Join(patentDirPath, entry.Name(), targetFile)
			if xmlData, err := ioutil.ReadFile(xmlPath); err == nil {
				return e.extractAppNumber(xmlData)
			}
		}
	}

	// If not found in expected structure, try recursive search
	// This handles edge cases like PG-PUB-2 directory structure
	return e.recursiveSearchForXML(extractedDir, targetFile)
}

// Recursively search for XML file in directory tree
// Used as fallback for non-standard directory structures (e.g., PG-PUB-2)
func (e *Extractor) recursiveSearchForXML(rootDir string, targetFilename string) string {
	var result string
	filepath.Walk(rootDir, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return nil // Skip errors, continue walking
		}
		if !info.IsDir() && info.Name() == targetFilename {
			// Found the XML file - extract application number
			if xmlData, err := ioutil.ReadFile(path); err == nil {
				result = e.extractAppNumber(xmlData)
				return filepath.SkipDir // Stop walking once found
			}
		}
		return nil
	})
	return result
}

func (e *Extractor) processPatentBatch(patents []PatentToFix) []PatentUpdate {
	var results []PatentUpdate

	// Group by archive
	archiveGroups := make(map[string][]PatentToFix)
	for _, p := range patents {
		pubDate := extractPubDate(p.RawPath)
		if pubDate == "" {
			continue
		}
		archiveName := buildArchiveName(pubDate)
		archiveGroups[archiveName] = append(archiveGroups[archiveName], p)
	}

	// Process each archive (one at a time to manage memory)
	for archiveName, group := range archiveGroups {
		// IMPORTANT: Archives may be split (e.g., 20030313.ZIP -> 20030313A.ZIP + 20030313B.ZIP)
		// Patents from the same date can be in different archives!
		// We need to try ALL archive variants for each patent, not just load one archive per date.
		baseArchive := strings.TrimSuffix(archiveName, ".ZIP")

		archivePaths := []string{
			filepath.Join(cfg.FilesRoot, archiveName),
			filepath.Join(cfg.FilesRoot, "NewFiles", archiveName),
			filepath.Join(cfg.FilesRoot, baseArchive+"A.ZIP"),
			filepath.Join(cfg.FilesRoot, baseArchive+"B.ZIP"),
			filepath.Join(cfg.FilesRoot, "NewFiles", baseArchive+"A.ZIP"),
			filepath.Join(cfg.FilesRoot, "NewFiles", baseArchive+"B.ZIP"),
		}

		// Load all available archives for this date (A, B, etc.)
		var availableArchives [][]byte
		for _, path := range archivePaths {
			archiveData, err := e.loadArchive(path)
			if err == nil {
				availableArchives = append(availableArchives, archiveData)
			}
		}

		// Process each patent by trying all available archives OR extracted directory
		for _, patent := range group {
			var appNum string

			// Try archives first
			for _, archiveData := range availableArchives {
				appNum = e.extractFromArchive(archiveData, patent.RawPath)
				if appNum != "" {
					break // Found it!
				}
			}

			// If not found in archives, try xml_extracted directory (for late 2010 patents)
			if appNum == "" {
				pubDate := extractPubDate(patent.RawPath)
				if pubDate != "" {
					appNum = e.extractFromDirectory(pubDate, patent.RawPath)
				}
			}

			if appNum != "" {
				results = append(results, PatentUpdate{
					PubNumber:         patent.PubNumber,
					ApplicationNumber: appNum,
				})
			}
			atomic.AddInt64(&e.stats.PatentsProcessed, 1)

			// Checkpoint progress
			processed := atomic.LoadInt64(&e.stats.PatentsProcessed)
			if processed > 0 && processed%int64(cfg.CheckpointEvery) == 0 {
				lastCheck := atomic.LoadInt64(&e.stats.LastCheckpoint)
				if processed > lastCheck {
					atomic.StoreInt64(&e.stats.LastCheckpoint, processed)
					e.printProgress()
				}
			}
		}

		// Clear archive data to free memory
		availableArchives = nil
		runtime.GC()
	}

	return results
}

func (e *Extractor) extractFromArchive(archiveData []byte, xmlPath string) string {
	zr, err := zip.NewReader(bytes.NewReader(archiveData), int64(len(archiveData)))
	if err != nil {
		return ""
	}

	targetFile := filepath.Base(xmlPath)
	targetDir := filepath.Dir(xmlPath)
	targetZip := targetDir + ".ZIP"

	// Search for nested ZIP with matching suffix
	// The nested ZIP may be in subdirectories (e.g., "20030313/UTIL0046/filename.ZIP")
	for _, f := range zr.File {
		upperName := strings.ToUpper(f.Name)
		if strings.HasSuffix(upperName, targetZip) {
			rc, err := f.Open()
			if err != nil {
				continue
			}
			nestedData, err := ioutil.ReadAll(rc)
			rc.Close()
			if err != nil {
				continue
			}

			nestedZr, err := zip.NewReader(bytes.NewReader(nestedData), int64(len(nestedData)))
			if err != nil {
				continue
			}

			// Search for target XML file in nested ZIP
			for _, nf := range nestedZr.File {
				if strings.HasSuffix(nf.Name, targetFile) {
					nrc, err := nf.Open()
					if err != nil {
						continue
					}
					xmlData, err := ioutil.ReadAll(nrc)
					nrc.Close()
					if err != nil {
						continue
					}

					return e.extractAppNumber(xmlData)
				}
			}
		}
	}

	return ""
}

func (e *Extractor) worker(id int) {
	defer e.wg.Done()
	for batch := range e.workChan {
		select {
		case <-e.shutdown:
			log.Printf("Worker %d shutting down gracefully", id)
			return
		default:
			results := e.processPatentBatch(batch)
			if len(results) > 0 {
				e.resultChan <- results
			}
		}
	}
}

func (e *Extractor) inserter() {
	defer e.insWG.Done()

	batch := make([]PatentUpdate, 0, cfg.BatchSize)

	flush := func() {
		if len(batch) == 0 {
			return
		}
		e.updatePatents(batch)
		batch = batch[:0]
	}

	for results := range e.resultChan {
		for _, pu := range results {
			batch = append(batch, pu)
			if len(batch) >= cfg.BatchSize {
				flush()
			}
		}
	}
	flush()
}

func (e *Extractor) updatePatents(items []PatentUpdate) {
	tx, err := e.db.Begin()
	if err != nil {
		log.Printf("Tx Error: %v", err)
		atomic.AddInt64(&e.stats.Errors, 1)
		return
	}
	defer tx.Rollback()

	stmt, err := tx.Prepare(`
		UPDATE patent_data_unified
		SET application_number = $1
		WHERE pub_number = $2
	`)
	if err != nil {
		log.Printf("Prep Error: %v", err)
		atomic.AddInt64(&e.stats.Errors, 1)
		return
	}
	defer stmt.Close()

	updated := 0
	for _, item := range items {
		res, err := stmt.Exec(item.ApplicationNumber, item.PubNumber)
		if err == nil {
			if rows, _ := res.RowsAffected(); rows > 0 {
				updated++
			}
		}
	}

	if err := tx.Commit(); err != nil {
		log.Printf("Commit Error: %v", err)
		atomic.AddInt64(&e.stats.Errors, 1)
		return
	}

	if updated > 0 {
		atomic.AddInt64(&e.stats.PatentsUpdated, int64(updated))
		log.Printf("Updated %d patents (Total: %d)", updated, atomic.LoadInt64(&e.stats.PatentsUpdated))
	}
}

func (e *Extractor) loadMissingPatents() {
	log.Println("Loading patents missing application numbers from database...")

	rows, err := e.db.Query(`
		SELECT pub_number, raw_xml_path
		FROM patent_data_unified
		WHERE (application_number IS NULL OR application_number = '')
		  AND raw_xml_path IS NOT NULL
		  AND raw_xml_path != ''
		  AND year IN (2001, 2002, 2003, 2004, 2010)
		ORDER BY year, pub_number
	`)
	if err != nil {
		log.Fatalf("Failed to query database: %v", err)
	}
	defer rows.Close()

	batch := make([]PatentToFix, 0, cfg.BatchSize)
	total := 0

	for rows.Next() {
		var p PatentToFix
		if err := rows.Scan(&p.PubNumber, &p.RawPath); err != nil {
			log.Printf("Scan error: %v", err)
			continue
		}

		batch = append(batch, p)
		total++

		if len(batch) >= cfg.BatchSize {
			e.workChan <- batch
			batch = make([]PatentToFix, 0, cfg.BatchSize)

			if total%10000 == 0 {
				log.Printf("Queued %d patents for processing...", total)
			}
		}
	}

	if len(batch) > 0 {
		e.workChan <- batch
	}

	close(e.workChan)
	log.Printf("Finished loading %d patents to process", total)
}

func (e *Extractor) printProgress() {
	elapsed := time.Since(e.stats.StartTime)
	processed := atomic.LoadInt64(&e.stats.PatentsProcessed)
	updated := atomic.LoadInt64(&e.stats.PatentsUpdated)
	loaded := atomic.LoadInt64(&e.stats.ArchivesLoaded)
	skipped := atomic.LoadInt64(&e.stats.ArchivesSkipped)
	errors := atomic.LoadInt64(&e.stats.Errors)

	var m runtime.MemStats
	runtime.ReadMemStats(&m)

	log.Printf("\n=== Progress Update ===")
	log.Printf("Processed: %d | Updated: %d | Success Rate: %.1f%%",
		processed, updated, float64(updated)/float64(processed)*100)
	log.Printf("Archives: %d loaded, %d skipped | Errors: %d", loaded, skipped, errors)
	log.Printf("Memory: Alloc=%dMB Sys=%dMB NumGC=%d", m.Alloc/1024/1024, m.Sys/1024/1024, m.NumGC)
	log.Printf("Elapsed: %s\n", elapsed)
}

func (e *Extractor) setupSignalHandler() {
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	go func() {
		<-sigChan
		log.Println("\n\nReceived shutdown signal. Finishing current batch...")
		close(e.shutdown)
		e.printProgress()
	}()
}

func (e *Extractor) Run() {
	e.setupSignalHandler()

	// Start workers
	for i := 0; i < cfg.Workers; i++ {
		e.wg.Add(1)
		go e.worker(i)
	}

	// Start inserter
	e.insWG.Add(1)
	go e.inserter()

	// Start progress monitor
	go func() {
		ticker := time.NewTicker(60 * time.Second)
		defer ticker.Stop()
		for range ticker.C {
			e.printProgress()
		}
	}()

	// Load missing patents from DB
	e.loadMissingPatents()

	// Wait for completion
	e.wg.Wait()
	close(e.resultChan)
	e.insWG.Wait()

	elapsed := time.Since(e.stats.StartTime)
	log.Printf("\n=== Targeted Backfill Complete ===")
	log.Printf("Patents Processed: %d", atomic.LoadInt64(&e.stats.PatentsProcessed))
	log.Printf("Patents Updated: %d", atomic.LoadInt64(&e.stats.PatentsUpdated))
	log.Printf("Archives Loaded: %d", atomic.LoadInt64(&e.stats.ArchivesLoaded))
	log.Printf("Archives Skipped: %d", atomic.LoadInt64(&e.stats.ArchivesSkipped))
	log.Printf("Errors: %d", atomic.LoadInt64(&e.stats.Errors))
	log.Printf("Time Elapsed: %s", elapsed)
}

func main() {
	runtime.GOMAXPROCS(runtime.NumCPU())
	log.SetOutput(os.Stdout)
	log.Println("Starting Targeted Patent Backfill (Memory-Optimized v2)...")
	log.Printf("Config: %d workers, batch size %d, checkpoint every %d patents",
		cfg.Workers, cfg.BatchSize, cfg.CheckpointEvery)

	e, err := NewExtractor()
	if err != nil {
		log.Fatalf("Init failed: %v", err)
	}
	e.Run()
}
