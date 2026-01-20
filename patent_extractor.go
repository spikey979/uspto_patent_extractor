package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"compress/gzip"
	"database/sql"
	"encoding/json"
	"encoding/xml"
	"flag"
	"fmt"
	"io"
	"io/ioutil"
	"log"
	"os"
	"path/filepath"
	"regexp"
	"runtime"
    "sort"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"time"

	_ "github.com/lib/pq"
)

// Runtime configuration with sensible defaults, overridable via env vars
type Config struct {
    DBHost string
    DBPort int
    DBName string
    DBUser string
    DBPassword string

    WorkDir      string
    LogDir       string
    FilesRoot    string
    ProcessedLog string

    Workers            int
    BatchSize          int
    ScanNewOnly        bool
    Recursive          bool
    MinArchiveSizeMB   int64
    ReprocessAll       bool
    ForceOverwrite     bool

    PriorityMinYear int
    PriorityMaxYear int
    
    TestConfig bool
}

var cfg = Config{
    DBHost: "localhost",
    DBPort: 5432,
    DBName: "companies_db",
    DBUser: "postgres",
    DBPassword: "qwklmn711",

    WorkDir:      "/home/mark/projects/patent_extractor/temp",
    LogDir:       "/home/mark/projects/patent_extractor/logs",
    FilesRoot:    "/mnt/patents/data/historical",
    ProcessedLog: "/home/mark/projects/patent_extractor/processed_archives.txt",

    Workers:          8,
    BatchSize:        100,
    ScanNewOnly:      false,
    Recursive:        true,
    MinArchiveSizeMB: 1,
    ReprocessAll:     false,
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

func getEnvBool(key string, def bool) bool {
    if v := strings.TrimSpace(os.Getenv(key)); v != "" {
        v = strings.ToLower(v)
        return v == "1" || v == "true" || v == "yes"
    }
    return def
}

type Stats struct {
	ArchivesProcessed int64
	PatentsExtracted  int64
	PatentsInserted   int64
	Errors           int64
	StartTime        time.Time
}

type Patent struct {
	PubNumber         string          `json:"pub_number"`
	Title             string          `json:"title"`
	AbstractText      string          `json:"abstract_text"`
	DescriptionText   string          `json:"description_text"`
	Claims            []string        `json:"claims"`
	FilingDate        *time.Time      `json:"filing_date"`
	PubDate           *time.Time      `json:"pub_date"`
	Year              int             `json:"year"`
	ApplicationNumber string          `json:"application_number"`
	Inventors         json.RawMessage `json:"inventors"`
	Assignees         json.RawMessage `json:"assignees"`
	RawXMLPath        string          `json:"raw_xml_path"`
}

type Inventor struct {
	Name    string            `json:"name"`
	Type    string            `json:"type"`
	Address map[string]string `json:"address,omitempty"`
}

type Assignee struct {
	Name    string            `json:"name"`
	Type    string            `json:"type"`
	Address map[string]string `json:"address,omitempty"`
}

type Extractor struct {
    db               *sql.DB
    processedArchives map[string]bool
    mu               sync.RWMutex
    stats            *Stats
    workChan         chan string
    resultChan       chan []Patent
    wg               sync.WaitGroup
    insWG            sync.WaitGroup
}

func loadConfig() {
    // Load config from environment first
    cfg.DBHost = getEnv("DB_HOST", cfg.DBHost)
    cfg.DBPort = getEnvInt("DB_PORT", cfg.DBPort)
    cfg.DBName = getEnv("DB_NAME", cfg.DBName)
    cfg.DBUser = getEnv("DB_USER", cfg.DBUser)
    cfg.DBPassword = getEnv("DB_PASSWORD", cfg.DBPassword)

    cfg.Workers = getEnvInt("WORKERS", cfg.Workers)
    cfg.BatchSize = getEnvInt("BATCH_SIZE", cfg.BatchSize)
    cfg.FilesRoot = getEnv("FILES_ROOT", cfg.FilesRoot)
    cfg.ScanNewOnly = getEnvBool("SCAN_NEW", cfg.ScanNewOnly)
    cfg.Recursive = getEnvBool("RECURSIVE", cfg.Recursive)
    cfg.MinArchiveSizeMB = int64(getEnvInt("MIN_ARCHIVE_SIZE_MB", int(cfg.MinArchiveSizeMB)))
    cfg.ReprocessAll = getEnvBool("REPROCESS_ALL", cfg.ReprocessAll)
    cfg.ForceOverwrite = getEnvBool("FORCE_OVERWRITE", cfg.ForceOverwrite)
    cfg.PriorityMinYear = getEnvInt("PRIORITY_MIN_YEAR", 0)
    cfg.PriorityMaxYear = getEnvInt("PRIORITY_MAX_YEAR", 0)

    // Define flags to override environment (using env vars as defaults)
    flag.StringVar(&cfg.DBHost, "db-host", cfg.DBHost, "Database host")
    flag.IntVar(&cfg.DBPort, "db-port", cfg.DBPort, "Database port")
    flag.StringVar(&cfg.DBName, "db-name", cfg.DBName, "Database name")
    flag.StringVar(&cfg.DBUser, "db-user", cfg.DBUser, "Database user")
    
    flag.IntVar(&cfg.Workers, "workers", cfg.Workers, "Number of worker threads")
    flag.StringVar(&cfg.FilesRoot, "root", cfg.FilesRoot, "Root directory for files")
    flag.BoolVar(&cfg.ScanNewOnly, "scan-new", cfg.ScanNewOnly, "Only scan NewFiles subdirectory")
    flag.BoolVar(&cfg.Recursive, "recursive", cfg.Recursive, "Recursively scan directories")
    flag.BoolVar(&cfg.ReprocessAll, "reprocess", cfg.ReprocessAll, "Reprocess already processed archives")
    flag.BoolVar(&cfg.ForceOverwrite, "force", cfg.ForceOverwrite, "Force overwrite of existing records")
    flag.BoolVar(&cfg.TestConfig, "test-config", false, "Test configuration and database connection then exit")
    
    flag.Parse()
}

func NewExtractor() (*Extractor, error) {
    // Ensure directories
    os.MkdirAll(cfg.WorkDir, 0755)
    os.MkdirAll(cfg.LogDir, 0755)
    os.MkdirAll(filepath.Join(cfg.FilesRoot, "NewFiles"), 0775)

    // Connect to database
    psqlInfo := fmt.Sprintf("host=%s port=%d user=%s password=%s dbname=%s sslmode=disable",
        cfg.DBHost, cfg.DBPort, cfg.DBUser, cfg.DBPassword, cfg.DBName)
    
    db, err := sql.Open("postgres", psqlInfo)
    if err != nil {
        return nil, err
    }
	
	if err = db.Ping(); err != nil {
		return nil, err
	}
	
	// Set connection pool settings
	db.SetMaxOpenConns(25)
	db.SetMaxIdleConns(5)
	
    e := &Extractor{
        db:                db,
        processedArchives: make(map[string]bool),
        stats:            &Stats{StartTime: time.Now()},
        workChan:         make(chan string, 100),
        resultChan:       make(chan []Patent, 100),
    }
    
    // Load processed archives
    e.loadProcessedArchives()

    return e, nil
}

func (e *Extractor) loadProcessedArchives() {
    data, err := ioutil.ReadFile(cfg.ProcessedLog)
	if err != nil {
		return
	}
	
	lines := strings.Split(string(data), "\n")
	for _, line := range lines {
		if line = strings.TrimSpace(line); line != "" {
			e.processedArchives[line] = true
		}
	}
	
	log.Printf("Loaded %d processed archives", len(e.processedArchives))
}

func (e *Extractor) markProcessed(archive string) {
	e.mu.Lock()
	defer e.mu.Unlock()
	
	e.processedArchives[archive] = true
	
    f, err := os.OpenFile(cfg.ProcessedLog, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0644)
	if err != nil {
		return
	}
	defer f.Close()
	
	f.WriteString(archive + "\n")
}

func (e *Extractor) isProcessed(archive string) bool {
	e.mu.RLock()
	defer e.mu.RUnlock()
	return e.processedArchives[archive]
}

// sniffZip returns true if the file appears to be a ZIP by magic
func sniffZip(path string) bool {
    f, err := os.Open(path)
    if err != nil { return false }
    defer f.Close()
    buf := make([]byte, 4)
    if _, err := io.ReadFull(f, buf); err != nil { return false }
    // ZIP: PK\x03\x04 or end records PK\x05\x06 / PK\x07\x08
    return (buf[0] == 'P' && buf[1] == 'K')
}

// sniffTar returns true if the file appears to be a TAR by ustar magic
func sniffTar(path string) bool {
    f, err := os.Open(path)
    if err != nil { return false }
    defer f.Close()
    // TAR header is 512 bytes; magic at offset 257 of length 5 = "ustar"
    if _, err := f.Seek(257, io.SeekStart); err != nil { return false }
    buf := make([]byte, 5)
    if _, err := io.ReadFull(f, buf); err != nil { return false }
    return string(buf) == "ustar"
}

func isCandidateArchive(path string, d os.DirEntry) bool {
    if d.IsDir() { return false }
    name := d.Name()
    upper := strings.ToUpper(name)
    lower := strings.ToLower(name)
    // Include known archive extensions
    if strings.HasSuffix(lower, ".zip") || strings.HasSuffix(lower, ".tar") || strings.HasSuffix(lower, ".tgz") || strings.HasSuffix(lower, ".tar.gz") {
        return true
    }
    // Include special SUPP zips
    if strings.Contains(upper, "SUPP") && strings.HasSuffix(upper, ".ZIP") { return true }
    // Include large extensionless files if they sniff as zip/tar
    if filepath.Ext(name) == "" {
        // size check
        if info, err := d.Info(); err == nil {
            if info.Size() >= cfg.MinArchiveSizeMB*1024*1024 {
                if sniffZip(path) || sniffTar(path) { return true }
            }
        }
    }
    return false
}

func (e *Extractor) getArchives() []string {
    var archives []string

    if cfg.ScanNewOnly {
        // Backwards-compatible behavior: only scan NewFiles in top-level
        patterns := []string{
            filepath.Join(cfg.FilesRoot, "NewFiles", "*.ZIP"),
            filepath.Join(cfg.FilesRoot, "NewFiles", "*.zip"),
            filepath.Join(cfg.FilesRoot, "NewFiles", "*.tar"),
            filepath.Join(cfg.FilesRoot, "NewFiles", "*.tar.gz"),
            filepath.Join(cfg.FilesRoot, "NewFiles", "*SUPP*.ZIP"),
        }
        for _, pattern := range patterns {
            matches, _ := filepath.Glob(pattern)
            for _, match := range matches {
                if !cfg.ReprocessAll && e.isProcessed(match) {
                    log.Printf("Skipping already processed file in NewFiles: %s (moving to originals)", filepath.Base(match))
                    e.moveToOriginals(match)
                    continue
                }
                archives = append(archives, match)
            }
        }
    } else {
        // Recursive scan under FilesRoot, honoring sniff and size rules
        walkFn := func(path string, d os.DirEntry, err error) error {
            if err != nil { return nil }
            if d.IsDir() { return nil }
            if isCandidateArchive(path, d) {
                if cfg.ReprocessAll || !e.isProcessed(path) {
                    archives = append(archives, path)
                }
            }
            return nil
        }
        if cfg.Recursive {
            _ = filepath.WalkDir(cfg.FilesRoot, walkFn)
        } else {
            // Non-recursive: list only top-level files
            entries, _ := os.ReadDir(cfg.FilesRoot)
            for _, d := range entries {
                p := filepath.Join(cfg.FilesRoot, d.Name())
                if isCandidateArchive(p, d) {
                    if cfg.ReprocessAll || !e.isProcessed(p) { archives = append(archives, p) }
                }
            }
        }
    }

    // If a priority year window is configured, put those archives first.
    if cfg.PriorityMinYear > 0 && cfg.PriorityMaxYear >= cfg.PriorityMinYear {
        yearOf := func(base string) int {
            // Patterns: IYYYYMMDD.* or YYYYMMDD.* (ZIP/TAR)
            if m := regexp.MustCompile(`(?i)^i(\d{4})`).FindStringSubmatch(base); len(m) > 1 {
                if y, err := strconv.Atoi(m[1]); err == nil { return y }
            }
            if m := regexp.MustCompile(`^(\d{4})`).FindStringSubmatch(base); len(m) > 1 {
                if y, err := strconv.Atoi(m[1]); err == nil { return y }
            }
            return -1
        }
        var pri, rest []string
        for _, a := range archives {
            y := yearOf(filepath.Base(a))
            if y >= cfg.PriorityMinYear && y <= cfg.PriorityMaxYear {
                pri = append(pri, a)
            } else {
                rest = append(rest, a)
            }
        }
        // Sort priority group by base name descending (latest first);
        // others by base name ascending to avoid starving old sets.
        sort.Slice(pri, func(i, j int) bool { return filepath.Base(pri[i]) > filepath.Base(pri[j]) })
        sort.Slice(rest, func(i, j int) bool { return filepath.Base(rest[i]) < filepath.Base(rest[j]) })
        archives = append(pri, rest...)
        log.Printf("Priority window %d-%d: %d archives first, %d remaining", cfg.PriorityMinYear, cfg.PriorityMaxYear, len(pri), len(rest))
    }

    log.Printf("Found %d unprocessed archives under %s", len(archives), cfg.FilesRoot)
    return archives
}

func (e *Extractor) extractFromZIP(archivePath string) ([]Patent, error) {
	r, err := zip.OpenReader(archivePath)
	if err != nil {
		return nil, err
	}
	defer r.Close()
	
	var patents []Patent
	xmlCount := 0
	nestedZips := 0
	
	// First pass: check for nested ZIPs (older format 2001-2010)
	hasNestedZips := false
	for _, f := range r.File {
		if strings.HasSuffix(strings.ToUpper(f.Name), ".ZIP") {
			hasNestedZips = true
			break
		}
	}
	
	if hasNestedZips {
		// Process nested ZIPs (2001-2010 format)
		for _, f := range r.File {
			if !strings.HasSuffix(strings.ToUpper(f.Name), ".ZIP") {
				continue
			}
			
			// Skip DTDS and ENTITIES zips
			if strings.Contains(f.Name, "DTDS") || strings.Contains(f.Name, "ENTITIES") {
				continue
			}
			
			nestedZips++
			
			// Extract nested ZIP to memory
			rc, err := f.Open()
			if err != nil {
				continue
			}
			
			data, err := ioutil.ReadAll(rc)
			rc.Close()
			if err != nil {
				continue
			}
			
			// Open nested ZIP from memory
			zr, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
			if err != nil {
				continue
			}
			
			// Process XML files in nested ZIP
			for _, nf := range zr.File {
				if !strings.HasSuffix(strings.ToUpper(nf.Name), ".XML") {
					continue
				}

				xmlCount++

				nrc, err := nf.Open()
				if err != nil {
					continue
				}

				xmlData, err := ioutil.ReadAll(nrc)
				nrc.Close()
				if err != nil {
					continue
				}

				// Prepend archive name to XML path
				xmlPath := filepath.Base(archivePath) + "/" + nf.Name
				patent := e.parseXML(xmlData, xmlPath)
				if patent != nil {
					patents = append(patents, *patent)
				}
			}
		}
		
		log.Printf("Processed %d nested ZIPs with %d XML files in %s", 
			nestedZips, xmlCount, filepath.Base(archivePath))
	} else {
		// Process direct XML files (2011+ format)
		for _, f := range r.File {
			if !strings.HasSuffix(strings.ToUpper(f.Name), ".XML") {
				continue
			}

			xmlCount++

			rc, err := f.Open()
			if err != nil {
				log.Printf("Error opening %s: %v", f.Name, err)
				continue
			}

			data, err := ioutil.ReadAll(rc)
			rc.Close()

			if err != nil {
				log.Printf("Error reading %s: %v", f.Name, err)
				continue
			}

			// Prepend archive name to XML path
			xmlPath := filepath.Base(archivePath) + "/" + f.Name
			patent := e.parseXML(data, xmlPath)
			if patent != nil {
				patents = append(patents, *patent)
			}
		}
		
		log.Printf("Extracted %d patents from %d XML files in %s", 
			len(patents), xmlCount, filepath.Base(archivePath))
	}
	
	return patents, nil
}

func (e *Extractor) extractFromTAR(archivePath string) ([]Patent, error) {
	file, err := os.Open(archivePath)
	if err != nil {
		return nil, err
	}
	defer file.Close()
	
	var tarReader *tar.Reader
	
	// Check if gzipped
	if strings.HasSuffix(archivePath, ".tar.gz") || strings.HasSuffix(archivePath, ".tgz") {
		gzr, err := gzip.NewReader(file)
		if err != nil {
			return nil, err
		}
		defer gzr.Close()
		tarReader = tar.NewReader(gzr)
	} else {
		tarReader = tar.NewReader(file)
	}
	
	var patents []Patent
	xmlCount := 0
	
	for {
		header, err := tarReader.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, err
		}
		
			upper := strings.ToUpper(header.Name)
			if strings.HasSuffix(upper, ".XML") {
				xmlCount++
				data, err := ioutil.ReadAll(tarReader)
				if err != nil {
					log.Printf("Error reading %s: %v", header.Name, err)
					continue
				}
				// Prepend archive name to XML path
				xmlPath := filepath.Base(archivePath) + "/" + header.Name
				patent := e.parseXML(data, xmlPath)
				if patent != nil {
					patents = append(patents, *patent)
				}
			} else if strings.HasSuffix(upper, ".ZIP") {
				zipData, err := ioutil.ReadAll(tarReader)
				if err != nil {
					log.Printf("Error reading nested ZIP %s: %v", header.Name, err)
					continue
				}
				zr, err := zip.NewReader(bytes.NewReader(zipData), int64(len(zipData)))
				if err != nil {
					log.Printf("Error opening nested ZIP %s: %v", header.Name, err)
					continue
				}
				for _, zf := range zr.File {
					if !strings.HasSuffix(strings.ToUpper(zf.Name), ".XML") { continue }
					rc, err := zf.Open()
					if err != nil { continue }
					xdata, err := ioutil.ReadAll(rc)
					rc.Close()
					if err != nil { continue }
					xmlCount++
					// Prepend archive name to XML path
					xmlPath := filepath.Base(archivePath) + "/" + zf.Name
					patent := e.parseXML(xdata, xmlPath)
					if patent != nil {
						patents = append(patents, *patent)
					}
				}
			} else {
				continue
			}
	}
	
	log.Printf("Extracted %d patents from %d XML files in %s",
		len(patents), xmlCount, filepath.Base(archivePath))
	
	return patents, nil
}

func (e *Extractor) parseXML(data []byte, xmlPath string) *Patent {
	// Try to extract patent number from filename first
	pubNumber := ""
	if match := regexp.MustCompile(`US(\d+)`).FindStringSubmatch(xmlPath); len(match) > 1 {
		pubNumber = match[1]
	}
	
	// Basic XML structure for patent
	var doc struct {
		XMLName xml.Name
		Title   string `xml:"invention-title"`
		Abstract struct {
			Text string `xml:",innerxml"`
		} `xml:"abstract"`
		Claims struct {
			Claim []struct {
				Text string `xml:",innerxml"`
			} `xml:"claim"`
		} `xml:"claims"`
		Description struct {
			Text string `xml:",innerxml"`
		} `xml:"description"`
		PublicationReference struct {
			DocumentID struct {
				DocNumber string `xml:"doc-number"`
				Date      string `xml:"date"`
			} `xml:"document-id"`
		} `xml:"publication-reference"`
		ApplicationReference struct {
			DocumentID struct {
				Date string `xml:"date"`
			} `xml:"document-id"`
		} `xml:"application-reference"`
		Inventors struct {
			Inventor []struct {
				Name struct {
					GivenName  string `xml:"given-name"`
					FamilyName string `xml:"family-name"`
				} `xml:"name"`
				Address struct {
					City    string `xml:"city"`
					Country string `xml:"country"`
				} `xml:"address"`
			} `xml:"inventor"`
		} `xml:"inventors"`
		Assignees struct {
			Assignee []struct {
				OrgName string `xml:"orgname"`
				Name    struct {
					GivenName  string `xml:"given-name"`
					FamilyName string `xml:"family-name"`
				} `xml:"name"`
				Address struct {
					City    string `xml:"city"`
					Country string `xml:"country"`
				} `xml:"address"`
			} `xml:"assignee"`
		} `xml:"assignees"`
	}
	
	if err := xml.Unmarshal(data, &doc); err != nil {
		// Try alternate structure
		return e.parseAlternateXML(data, xmlPath)
	}
	
	patent := &Patent{
		RawXMLPath: xmlPath,
	}
	
	// Extract patent number
	if doc.PublicationReference.DocumentID.DocNumber != "" {
		patent.PubNumber = doc.PublicationReference.DocumentID.DocNumber
	} else if pubNumber != "" {
		patent.PubNumber = pubNumber
	} else {
		return nil // No patent number, skip
	}
	
	// Extract title
	patent.Title = strings.TrimSpace(doc.Title)
	if len(patent.Title) > 500 {
		patent.Title = patent.Title[:500]
	}
	
	// Extract abstract
	patent.AbstractText = cleanXMLText(doc.Abstract.Text)
	if len(patent.AbstractText) > 5000 {
		patent.AbstractText = patent.AbstractText[:5000]
	}
	
	// Extract claims
	for _, claim := range doc.Claims.Claim {
		claimText := cleanXMLText(claim.Text)
		if claimText != "" {
			patent.Claims = append(patent.Claims, claimText)
		}
	}
	
    // Build description with synthesized paragraph markers
    description := ""
    if len(patent.Claims) > 0 {
        description = "CLAIMS:\n"
        for i, claim := range patent.Claims {
            if i >= 10 { break }
            description += fmt.Sprintf("%s\n\n", claim)
        }
    }
    descText := synthesizeDescription(data)
    if descText != "" {
        if description != "" { description += "DESCRIPTION:\n" }
        description += descText
    }
	
	if len(description) > 150000 {
		description = description[:150000]
	}
	patent.DescriptionText = description
	
	// Parse dates
	if doc.PublicationReference.DocumentID.Date != "" {
		if t, err := parseDate(doc.PublicationReference.DocumentID.Date); err == nil {
			patent.PubDate = &t
			patent.Year = t.Year()
		}
	}
	
	if doc.ApplicationReference.DocumentID.Date != "" {
		if t, err := parseDate(doc.ApplicationReference.DocumentID.Date); err == nil {
			patent.FilingDate = &t
		}
	}

	// Extract application number using dual schema extraction
	patent.ApplicationNumber = extractAppNumber(data)

	// Extract inventors
	var inventors []Inventor
	for _, inv := range doc.Inventors.Inventor {
		inventor := Inventor{
			Type: "individual",
		}
		
		if inv.Name.GivenName != "" && inv.Name.FamilyName != "" {
			inventor.Name = fmt.Sprintf("%s %s", inv.Name.GivenName, inv.Name.FamilyName)
		}
		
		if inventor.Name != "" {
			if inv.Address.City != "" || inv.Address.Country != "" {
				inventor.Address = map[string]string{
					"city":    inv.Address.City,
					"country": inv.Address.Country,
				}
			}
			inventors = append(inventors, inventor)
		}
	}
	
	if len(inventors) > 0 {
		if data, err := json.Marshal(inventors); err == nil {
			patent.Inventors = json.RawMessage(data)
		}
	}
	
	// Extract assignees
	var assignees []Assignee
	for _, ass := range doc.Assignees.Assignee {
		assignee := Assignee{}
		
		if ass.OrgName != "" {
			assignee.Name = ass.OrgName
			assignee.Type = "organization"
		} else if ass.Name.GivenName != "" && ass.Name.FamilyName != "" {
			assignee.Name = fmt.Sprintf("%s %s", ass.Name.GivenName, ass.Name.FamilyName)
			assignee.Type = "individual"
		}
		
		if assignee.Name != "" {
			if ass.Address.City != "" || ass.Address.Country != "" {
				assignee.Address = map[string]string{
					"city":    ass.Address.City,
					"country": ass.Address.Country,
				}
			}
			assignees = append(assignees, assignee)
		}
	}
	
	if len(assignees) > 0 {
		if data, err := json.Marshal(assignees); err == nil {
			patent.Assignees = json.RawMessage(data)
		}
	}
	
	return patent
}

func (e *Extractor) parseAlternateXML(data []byte, xmlPath string) *Patent {
    // More robust parsing for older XML structures (e.g., 2001–2005 PAP/US-PGPUB)
    patent := &Patent{
        RawXMLPath: xmlPath,
    }

    // Extract patent/publication number
    if match := regexp.MustCompile(`<doc-number>([^<]+)</doc-number>`).FindSubmatch(data); len(match) > 1 {
        patent.PubNumber = strings.TrimSpace(string(match[1]))
    } else if match := regexp.MustCompile(`US(\d+)`).FindStringSubmatch(xmlPath); len(match) > 1 {
        patent.PubNumber = match[1]
    } else {
        return nil
    }

    // Title: support both <invention-title> and <title-of-invention>
    if match := regexp.MustCompile(`<invention-title[^>]*>([^<]+)</invention-title>`).FindSubmatch(data); len(match) > 1 {
        patent.Title = cleanXMLText(string(match[1]))
    } else if match := regexp.MustCompile(`<title-of-invention[^>]*>([^<]+)</title-of-invention>`).FindSubmatch(data); len(match) > 1 {
        patent.Title = cleanXMLText(string(match[1]))
    }
    if len(patent.Title) > 500 {
        patent.Title = patent.Title[:500]
    }

    // Abstract: try standard <abstract>, else older <subdoc-abstract>
    abs := ""
    if match := regexp.MustCompile(`(?is)<abstract[^>]*>(.*?)</abstract>`).FindSubmatch(data); len(match) > 1 {
        abs = string(match[1])
    } else if match := regexp.MustCompile(`(?is)<subdoc-abstract[^>]*>(.*?)</subdoc-abstract>`).FindSubmatch(data); len(match) > 1 {
        abs = string(match[1])
    }
    if abs != "" {
        patent.AbstractText = cleanXMLText(abs)
        if len(patent.AbstractText) > 5000 { patent.AbstractText = patent.AbstractText[:5000] }
    }

    // Claims: collect <claim-text> blocks (namespace-agnostic)
    var claims []string
    claimRe := regexp.MustCompile(`(?is)<claim-text[^>]*>(.*?)</claim-text>`)
    for _, m := range claimRe.FindAllSubmatch(data, -1) {
        ct := cleanXMLText(string(m[1]))
        if ct != "" { claims = append(claims, ct) }
        if len(claims) >= 50 { break } // cap to avoid extreme documents
    }
    if len(claims) > 0 {
        patent.Claims = claims
    }

    // Description: build combined text with synthesized paragraph markers
    var description strings.Builder
    if len(patent.Claims) > 0 {
        description.WriteString("CLAIMS:\n")
        max := len(patent.Claims)
        if max > 10 { max = 10 }
        for i := 0; i < max; i++ {
            description.WriteString(patent.Claims[i])
            description.WriteString("\n\n")
        }
    }
    if descSynth := synthesizeDescription(data); descSynth != "" {
        if description.Len() > 0 { description.WriteString("DESCRIPTION:\n") }
        description.WriteString(descSynth)
    }
    desc := description.String()
    if len(desc) > 150000 { desc = desc[:150000] }
    patent.DescriptionText = desc

    // Dates/year: use any YYYY in doc-number or document-date
    if match := regexp.MustCompile(`(20\d{2})`).FindStringSubmatch(patent.PubNumber); len(match) > 1 {
        if y, err := strconv.Atoi(match[1]); err == nil && y >= 2000 && y <= 2100 {
            patent.Year = y
        }
    }
    if patent.Year == 0 {
        if match := regexp.MustCompile(`<document-date>(\d{8})</document-date>`).FindSubmatch(data); len(match) > 1 {
            if t, err := parseDate(string(match[1])); err == nil {
                patent.PubDate = &t
                patent.Year = t.Year()
            }
        }
    }

    // Extract application number using dual schema extraction
    patent.ApplicationNumber = extractAppNumber(data)

    // Inventors: support multiple older patterns
    // Pattern 1: explicit inventor blocks with given/family names
    invBlockRe := regexp.MustCompile(`(?is)<inventor[^>]*>(.*?)</inventor>`)
    nameGivenRe := regexp.MustCompile(`(?is)<given-name[^>]*>([^<]+)</given-name>`) 
    nameFamilyRe := regexp.MustCompile(`(?is)<family-name[^>]*>([^<]+)</family-name>`) 
    // Pattern 2: name-1/name-2
    name1Re := regexp.MustCompile(`(?is)<name-1[^>]*>([^<]+)</name-1>`) 
    name2Re := regexp.MustCompile(`(?is)<name-2[^>]*>([^<]+)</name-2>`) 
    cityRe := regexp.MustCompile(`(?is)<city[^>]*>([^<]+)</city>`) 
    countryRe := regexp.MustCompile(`(?is)<country[^>]*>([^<]+)</country>`) 
    var inventors []Inventor
    for _, blk := range invBlockRe.FindAllSubmatch(data, -1) {
        seg := blk[1]
        g := nameGivenRe.FindSubmatch(seg)
        f := nameFamilyRe.FindSubmatch(seg)
        var full string
        if len(g) > 1 && len(f) > 1 {
            full = strings.TrimSpace(string(g[1]) + " " + string(f[1]))
        } else {
            // fallback name-1/name-2 inside block
            n1 := name1Re.FindSubmatch(seg)
            n2 := name2Re.FindSubmatch(seg)
            if len(n1) > 1 || len(n2) > 1 {
                parts := make([]string, 0, 2)
                if len(n1) > 1 { parts = append(parts, string(n1[1])) }
                if len(n2) > 1 { parts = append(parts, string(n2[1])) }
                full = strings.TrimSpace(strings.Join(parts, " "))
            }
        }
        if full != "" {
            inv := Inventor{Name: cleanXMLText(full), Type: "individual"}
            city := cityRe.FindSubmatch(seg)
            country := countryRe.FindSubmatch(seg)
            if len(city) > 1 || len(country) > 1 {
                addr := make(map[string]string)
                if len(city) > 1 { addr["city"] = strings.TrimSpace(string(city[1])) }
                if len(country) > 1 { addr["country"] = strings.TrimSpace(string(country[1])) }
                if len(addr) > 0 { inv.Address = addr }
            }
            inventors = append(inventors, inv)
        }
        if len(inventors) >= 50 { break }
    }
    if len(inventors) > 0 {
        if b, err := json.Marshal(inventors); err == nil { patent.Inventors = json.RawMessage(b) }
    }

    // Assignees: prefer organization orgname; fallback to name-1/name-2
    assBlockRe := regexp.MustCompile(`(?is)<assignee[^>]*>(.*?)</assignee>`)
    orgRe := regexp.MustCompile(`(?is)<orgname[^>]*>([^<]+)</orgname>`) 
    var assignees []Assignee
    for _, blk := range assBlockRe.FindAllSubmatch(data, -1) {
        seg := blk[1]
        var nm string
        var typ string
        if m := orgRe.FindSubmatch(seg); len(m) > 1 {
            nm = strings.TrimSpace(string(m[1]))
            typ = "organization"
        } else {
            n1 := name1Re.FindSubmatch(seg)
            n2 := name2Re.FindSubmatch(seg)
            if len(n1) > 1 || len(n2) > 1 {
                parts := make([]string, 0, 2)
                if len(n1) > 1 { parts = append(parts, string(n1[1])) }
                if len(n2) > 1 { parts = append(parts, string(n2[1])) }
                nm = strings.TrimSpace(strings.Join(parts, " "))
                typ = "individual"
            }
        }
        if nm != "" {
            a := Assignee{Name: cleanXMLText(nm), Type: typ}
            city := cityRe.FindSubmatch(seg)
            country := countryRe.FindSubmatch(seg)
            if len(city) > 1 || len(country) > 1 {
                addr := make(map[string]string)
                if len(city) > 1 { addr["city"] = strings.TrimSpace(string(city[1])) }
                if len(country) > 1 { addr["country"] = strings.TrimSpace(string(country[1])) }
                if len(addr) > 0 { a.Address = addr }
            }
            assignees = append(assignees, a)
        }
        if len(assignees) >= 50 { break }
    }
    if len(assignees) > 0 {
        if b, err := json.Marshal(assignees); err == nil { patent.Assignees = json.RawMessage(b) }
    }

    return patent
}

func (e *Extractor) insertPatents(patents []Patent) int {
	if len(patents) == 0 {
		return 0
	}

	tx, err := e.db.Begin()
	if err != nil {
		log.Printf("Error starting transaction: %v", err)
		return 0
	}
	defer tx.Rollback()

    // Build UPSERT SQL, with optional forced overwrite of description/claims fields
    updateDesc := "description_text = CASE WHEN patent_data_unified.description_text IS NULL OR btrim(patent_data_unified.description_text) = '' THEN EXCLUDED.description_text ELSE patent_data_unified.description_text END,\n            claims_text = CASE WHEN patent_data_unified.claims_text IS NULL OR btrim(patent_data_unified.claims_text) = '' THEN EXCLUDED.claims_text ELSE patent_data_unified.claims_text END,\n            description_body = CASE WHEN patent_data_unified.description_body IS NULL OR btrim(patent_data_unified.description_body) = '' THEN EXCLUDED.description_body ELSE patent_data_unified.description_body END,"
    if cfg.ForceOverwrite {
        updateDesc = "description_text = EXCLUDED.description_text,\n            claims_text = EXCLUDED.claims_text,\n            description_body = EXCLUDED.description_body,"
    }

    upsertSQL := fmt.Sprintf(`
        INSERT INTO patent_data_unified (
            pub_number, title, abstract_text, description_text,
            claims_text, description_body,
            filing_date, pub_date, inventors, assignees,
            raw_xml_path, year, application_number
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb, $11, $12, $13)
        ON CONFLICT (pub_number) DO UPDATE SET
            title = CASE WHEN patent_data_unified.title IS NULL OR btrim(patent_data_unified.title) = '' THEN EXCLUDED.title ELSE patent_data_unified.title END,
            abstract_text = CASE WHEN patent_data_unified.abstract_text IS NULL OR btrim(patent_data_unified.abstract_text) = '' THEN EXCLUDED.abstract_text ELSE patent_data_unified.abstract_text END,
            %s
            inventors = CASE WHEN patent_data_unified.inventors IS NULL THEN EXCLUDED.inventors ELSE patent_data_unified.inventors END,
            assignees = CASE WHEN patent_data_unified.assignees IS NULL THEN EXCLUDED.assignees ELSE patent_data_unified.assignees END,
            raw_xml_path = COALESCE(patent_data_unified.raw_xml_path, EXCLUDED.raw_xml_path),
            filing_date = CASE WHEN patent_data_unified.filing_date IS NULL THEN EXCLUDED.filing_date ELSE patent_data_unified.filing_date END,
            pub_date = CASE WHEN patent_data_unified.pub_date IS NULL THEN EXCLUDED.pub_date ELSE patent_data_unified.pub_date END,
            year = CASE WHEN patent_data_unified.year IS NULL THEN EXCLUDED.year ELSE patent_data_unified.year END,
            application_number = CASE WHEN patent_data_unified.application_number IS NULL OR btrim(patent_data_unified.application_number) = '' THEN EXCLUDED.application_number ELSE patent_data_unified.application_number END
    `, updateDesc)

    stmt, err := tx.Prepare(upsertSQL)
	if err != nil {
		log.Printf("Error preparing statement: %v", err)
		return 0
	}
	defer stmt.Close()

	inserted := 0
	for _, patent := range patents {
		// Convert JSON fields to proper format or NULL
		var inventorsJSON interface{}
		var assigneesJSON interface{}

		if patent.Inventors != nil && len(patent.Inventors) > 0 {
			inventorsJSON = string(patent.Inventors)
		} else {
			inventorsJSON = nil
		}

		if patent.Assignees != nil && len(patent.Assignees) > 0 {
			assigneesJSON = string(patent.Assignees)
		} else {
			assigneesJSON = nil
		}

		// Derive claims_text and description_body
		claimsText := ""
		descriptionBody := patent.DescriptionText
		if len(patent.Claims) > 0 {
			maxClaims := len(patent.Claims)
			if maxClaims > 10 { maxClaims = 10 }
			var sb strings.Builder
			for i := 0; i < maxClaims; i++ {
				ct := strings.TrimSpace(patent.Claims[i])
				if ct == "" { continue }
				if sb.Len() > 0 { sb.WriteString("\n\n") }
				sb.WriteString(ct)
			}
			claimsText = sb.String()
			marker := "\n\nDESCRIPTION:"
			if idx := strings.Index(patent.DescriptionText, marker); idx > 0 {
				descriptionBody = patent.DescriptionText[idx+len(marker):]
			}
		} else if strings.HasPrefix(patent.DescriptionText, "CLAIMS:") {
			marker := "\n\nDESCRIPTION:"
			if idx := strings.Index(patent.DescriptionText, marker); idx > 0 {
				claimsText = strings.TrimSpace(patent.DescriptionText[len("CLAIMS:"):idx])
				descriptionBody = patent.DescriptionText[idx+len(marker):]
			} else {
				claimsText = strings.TrimSpace(patent.DescriptionText[len("CLAIMS:"):])
			}
		}

		_, err := stmt.Exec(
			patent.PubNumber,
			patent.Title,
			patent.AbstractText,
			patent.DescriptionText,
			claimsText,
			descriptionBody,
			patent.FilingDate,
			patent.PubDate,
			inventorsJSON,
			assigneesJSON,
			patent.RawXMLPath,
			patent.Year,
			patent.ApplicationNumber,
		)
		if err != nil {
			log.Printf("Error inserting patent %s: %v", patent.PubNumber, err)
			// Don't fail the whole batch for one error
			continue
		}
		inserted++
	}

	if err := tx.Commit(); err != nil {
		log.Printf("Error committing transaction: %v", err)
		return 0
	}

	log.Printf("Successfully inserted %d out of %d patents", inserted, len(patents))
	return inserted
}
func (e *Extractor) worker(id int) {
	defer e.wg.Done()
	
	for archivePath := range e.workChan {
		log.Printf("Worker %d processing: %s", id, filepath.Base(archivePath))
		
        var patents []Patent
        var err error

        lower := strings.ToLower(archivePath)
        if strings.HasSuffix(lower, ".zip") || sniffZip(archivePath) {
            patents, err = e.extractFromZIP(archivePath)
        } else if strings.Contains(lower, ".tar") || sniffTar(archivePath) {
            patents, err = e.extractFromTAR(archivePath)
        } else {
            // Unknown type; skip
            err = fmt.Errorf("unknown archive type")
        }
		
		if err != nil {
			log.Printf("Worker %d error processing %s: %v", id, filepath.Base(archivePath), err)
			atomic.AddInt64(&e.stats.Errors, 1)
		} else {
			atomic.AddInt64(&e.stats.PatentsExtracted, int64(len(patents)))
			
			if len(patents) > 0 {
				e.resultChan <- patents
			}
		}
		
        e.markProcessed(archivePath)
        e.moveToOriginals(archivePath)
        atomic.AddInt64(&e.stats.ArchivesProcessed, 1)
    }
}

func (e *Extractor) inserter() {
    defer e.insWG.Done()
    for patents := range e.resultChan {
        inserted := e.insertPatents(patents)
        atomic.AddInt64(&e.stats.PatentsInserted, int64(inserted))
    }
}

func (e *Extractor) Run() {
    archives := e.getArchives()
	
	// Get initial patent count
	var initialCount int64
	e.db.QueryRow("SELECT COUNT(*) FROM patent_data_unified").Scan(&initialCount)
	log.Printf("Starting extraction. Current patents: %d", initialCount)
	
    // Start workers
    for i := 0; i < cfg.Workers; i++ {
        e.wg.Add(1)
        go e.worker(i)
    }
	
    // Start inserter
    e.insWG.Add(1)
    go e.inserter()
	
	// Send work to workers
	go func() {
		for _, archive := range archives {
			e.workChan <- archive
		}
		close(e.workChan)
	}()
	
	// Monitor progress
	ticker := time.NewTicker(30 * time.Second)
	go func() {
		for range ticker.C {
			e.printStats()
			
			// Show current database count
			var count int64
			e.db.QueryRow("SELECT COUNT(*) FROM patent_data_unified").Scan(&count)
			log.Printf("Current total patents in database: %d", count)
		}
	}()
	
    // Wait for workers to finish
    e.wg.Wait()
    // Close results and wait for inserter to drain all pending batches
    close(e.resultChan)
    e.insWG.Wait()
	
	// Final stats
	var finalCount int64
	e.db.QueryRow("SELECT COUNT(*) FROM patent_data_unified").Scan(&finalCount)
	
	log.Printf("\nExtraction Complete!")
	log.Printf("Initial patents: %d", initialCount)
	log.Printf("Final patents: %d", finalCount)
	log.Printf("Patents added: %d", finalCount-initialCount)
	
	e.printStats()
}

func (e *Extractor) printStats() {
	elapsed := time.Since(e.stats.StartTime)
	
	log.Printf("========== STATISTICS ==========")
	log.Printf("Archives processed: %d", atomic.LoadInt64(&e.stats.ArchivesProcessed))
	log.Printf("Patents extracted: %d", atomic.LoadInt64(&e.stats.PatentsExtracted))
	log.Printf("Patents inserted: %d", atomic.LoadInt64(&e.stats.PatentsInserted))
	log.Printf("Errors: %d", atomic.LoadInt64(&e.stats.Errors))
	log.Printf("Time elapsed: %.2f hours", elapsed.Hours())
	log.Printf("Rate: %.0f patents/hour", float64(atomic.LoadInt64(&e.stats.PatentsExtracted))/elapsed.Hours())
	log.Printf("================================")
}

func cleanXMLText(s string) string {
	// Remove XML tags
	re := regexp.MustCompile(`<[^>]+>`)
	s = re.ReplaceAllString(s, " ")
	
	// Clean whitespace
	s = strings.TrimSpace(s)
	s = regexp.MustCompile(`\s+`).ReplaceAllString(s, " ")
	
	return s
}

// synthesizeDescription builds a bracket-numbered description body from common
// USPTO structures across vintages, preferring paragraph-level segmentation.
func synthesizeDescription(data []byte) string {
    // Try to locate description block variants, namespace aware
    var block []byte
    // Accept optional namespace prefixes like <us-patent-grant:description>
    nsDesc := regexp.MustCompile(`(?is)<([a-zA-Z0-9_:-]*:)?description[^>]*>(.*?)</([a-zA-Z0-9_:-]*:)?description>`) // group 2 is content
    nsSubDesc := regexp.MustCompile(`(?is)<([a-zA-Z0-9_:-]*:)?subdoc-description[^>]*>(.*?)</([a-zA-Z0-9_:-]*:)?subdoc-description>`)
    if m := nsSubDesc.FindSubmatch(data); len(m) > 2 {
        block = m[2]
    } else if m := nsDesc.FindSubmatch(data); len(m) > 2 {
        block = m[2]
    }
    if len(block) == 0 {
        return ""
    }

    // Paragraph patterns (namespace aware)
    // Capture opening tag (with attributes) and inner content so we can inspect id/num attrs
    paraReParagraph := regexp.MustCompile(`(?is)<([a-zA-Z0-9_:-]*:)?paragraph([^>]*)>(.*?)</([a-zA-Z0-9_:-]*:)?paragraph>`) // PAP
    paraReP := regexp.MustCompile(`(?is)<([a-zA-Z0-9_:-]*:)?p([^>]*)>(.*?)</([a-zA-Z0-9_:-]*:)?p>`)                          // ST.36/96
    paraRePara := regexp.MustCompile(`(?is)<([a-zA-Z0-9_:-]*:)?para([^>]*)>(.*?)</([a-zA-Z0-9_:-]*:)?para>`)                 // generic para
    idRe := regexp.MustCompile(`(?i)id\s*=\s*"[^"]*?(\d{3,5})"`)
    numAttrRe := regexp.MustCompile(`(?i)\bnum\s*=\s*"(\d{3,5})"`)
    // Strip explicit number nodes to avoid duplication
    stripNumRe1 := regexp.MustCompile(`(?is)<([a-zA-Z0-9_:-]*:)?number[^>]*>.*?</([a-zA-Z0-9_:-]*:)?number>`) // numbering nodes
    stripNumRe2 := regexp.MustCompile(`(?is)<([a-zA-Z0-9_:-]*:)?num[^>]*>.*?</([a-zA-Z0-9_:-]*:)?num>`)       // alt numbering

    // Try to capture explicit paragraph elements
    type paraSeg struct { attrs string; content []byte }
    var paraList []paraSeg
    if ms := paraReParagraph.FindAllSubmatch(block, -1); len(ms) > 0 {
        for _, m := range ms { paraList = append(paraList, paraSeg{attrs: string(m[2]), content: m[3]}) }
    } else if ms := paraReP.FindAllSubmatch(block, -1); len(ms) > 0 {
        for _, m := range ms { paraList = append(paraList, paraSeg{attrs: string(m[2]), content: m[3]}) }
    } else if ms := paraRePara.FindAllSubmatch(block, -1); len(ms) > 0 {
        for _, m := range ms { paraList = append(paraList, paraSeg{attrs: string(m[2]), content: m[3]}) }
    }

    // If still no segmented paragraphs, build them heuristically from raw block
    if len(paraList) == 0 {
        // Normalize some tags to newlines for better splitting
        txt := string(block)
        nlTags := []string{"</p>", "</paragraph>", "<br>", "<br/>", "</br>", "</para>"}
        for _, t := range nlTags { txt = strings.ReplaceAll(txt, t, "\n\n") }
        // Remove other tags
        txt = regexp.MustCompile(`(?is)<[^>]+>`).ReplaceAllString(txt, " ")
        // Collapse whitespace
        txt = regexp.MustCompile(`\s+`).ReplaceAllString(txt, " ")
        // Introduce paragraph splits on sentence endings followed by uppercase/digit
        // Go regexp does not support lookbehind; emulate by capturing the next token
        sentRe := regexp.MustCompile(`\.(\s+)([A-Z0-9])`)
        txt = sentRe.ReplaceAllString(txt, ".\n\n$2")
        // Split on blank lines
        chunks := regexp.MustCompile(`\n{2,}`).Split(txt, -1)
        for _, c := range chunks {
            c = strings.TrimSpace(c)
            if c == "" { continue }
            // Keep reasonable length to avoid extremely long paragraphs
            paraList = append(paraList, paraSeg{"", []byte(c)})
        }
    }

    if len(paraList) == 0 {
        // As a last resort, return cleaned block (still number it as a single para)
        return "[0001] " + cleanXMLText(string(block))
    }

    out := make([]string, 0, len(paraList))
    seq := 1
    for _, seg := range paraList {
        // Determine paragraph number from id if present
        n := 0
        if id := idRe.FindStringSubmatch(seg.attrs); len(id) > 1 {
            if v, err := strconv.Atoi(string(id[1])); err == nil { n = v }
        } else if na := numAttrRe.FindStringSubmatch(seg.attrs); len(na) > 1 {
            if v, err := strconv.Atoi(na[1]); err == nil { n = v }
        }
        if n == 0 { n = seq }
        seq++

        // Remove explicit numbering elements
        content := stripNumRe1.ReplaceAll(seg.content, nil)
        content = stripNumRe2.ReplaceAll(content, nil)

        txt := cleanXMLText(string(content))
        if txt == "" { continue }
        prefix := fmt.Sprintf("[%04d] ", n)
        out = append(out, prefix+txt)
    }

    return strings.Join(out, "\n\n")
}

func parseDate(dateStr string) (time.Time, error) {
	dateStr = strings.TrimSpace(dateStr)

	// Try different date formats
	formats := []string{
		"20060102",
		"2006-01-02",
		"01/02/2006",
		"2006",
	}

	for _, format := range formats {
		if t, err := time.Parse(format, dateStr); err == nil {
			return t, nil
		}
	}

	return time.Time{}, fmt.Errorf("unable to parse date: %s", dateStr)
}

// extractAppNumber extracts application number from patent XML data
// Supports both old format (2001-2004) and new format (2005+)
func extractAppNumber(data []byte) string {
	// Try new format first (2005+): <application-reference><document-id><doc-number>
	newFormatRe := regexp.MustCompile(`(?is)<application-reference[^>]*>.*?<doc-number>(\d+)</doc-number>`)
	if match := newFormatRe.FindSubmatch(data); len(match) > 1 {
		return strings.TrimSpace(string(match[1]))
	}

	// Try old format (2001-2004): <domestic-filing-data><application-number><doc-number>
	oldFormatRe := regexp.MustCompile(`(?is)<domestic-filing-data>.*?<application-number>.*?<doc-number>(\d+)</doc-number>`)
	if match := oldFormatRe.FindSubmatch(data); len(match) > 1 {
		return strings.TrimSpace(string(match[1]))
	}

	return ""
}

func main() {
    runtime.GOMAXPROCS(runtime.NumCPU())
    
    loadConfig()
    
    log.SetOutput(os.Stdout)
    log.Printf("metadata-fill-fs starting; workers=%d scan_new=%t recursive=%t min_mb=%d", cfg.Workers, cfg.ScanNewOnly, cfg.Recursive, cfg.MinArchiveSizeMB)
    log.Printf("roots=[%s]", cfg.FilesRoot)
	
	extractor, err := NewExtractor()
	if err != nil {
		log.Fatalf("Failed to create extractor: %v", err)
	}
	defer extractor.db.Close()
	
    if cfg.TestConfig {
        log.Println("---------------------------------------------------")
        log.Println("CONFIG TEST PASSED")
        log.Println("---------------------------------------------------")
        log.Println("1. Configuration loaded successfully.")
        log.Printf("   - Scan New Only: %v", cfg.ScanNewOnly)
        log.Printf("   - Files Root:    %s", cfg.FilesRoot)
        log.Printf("   - DB Host:       %s", cfg.DBHost)
        log.Println("2. Database connection established and pinged successfully.")
        log.Println("---------------------------------------------------")
        return
    }

	extractor.Run()
}
func (e *Extractor) moveToOriginals(archivePath string) {
    // Only move back if it originated from NewFiles under FilesRoot
    newFilesDir := filepath.Join(cfg.FilesRoot, "NewFiles") + string(os.PathSeparator)
    ap := archivePath
    // Normalize to absolute for safety
    if !filepath.IsAbs(ap) {
        if abs, err := filepath.Abs(ap); err == nil { ap = abs }
    }
    if strings.HasPrefix(ap, newFilesDir) {
        base := filepath.Base(archivePath)
        dest := filepath.Join(cfg.FilesRoot, base)
        if _, err := os.Stat(dest); err == nil {
            dest = filepath.Join(cfg.FilesRoot, fmt.Sprintf("%s.%d", base, time.Now().Unix()))
        }
        if err := os.Rename(archivePath, dest); err != nil {
            log.Printf("Failed to move %s to originals: %v", archivePath, err)
            return
        }
        log.Printf("Moved %s back to originals: %s", filepath.Base(archivePath), dest)
    }
}
