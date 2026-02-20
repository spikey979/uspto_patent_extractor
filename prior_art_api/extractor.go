package main

import (
	"archive/tar"
	"archive/zip"
	"bytes"
	"fmt"
	"io"
	"log"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"sync"
	"time"
)

// ExtractedFiles holds the extracted patent files from archive
type ExtractedFiles struct {
	XMLData  []byte
	TIFFiles map[string]string // filename -> full archive path
	XMLPath  string
}

// ============================================================================
// ZIP Cache - avoids re-opening TAR archives for the same patent
// ============================================================================

type zipCacheEntry struct {
	data       []byte
	memberName string
	accessedAt time.Time
}

var (
	zipCache    = make(map[string]*zipCacheEntry)
	zipCacheMu  sync.RWMutex
	zipCacheTTL = 5 * time.Minute
)

func init() {
	go zipCacheCleanup()
}

// zipCacheCleanup removes expired entries every minute
func zipCacheCleanup() {
	ticker := time.NewTicker(1 * time.Minute)
	for range ticker.C {
		zipCacheMu.Lock()
		now := time.Now()
		for key, entry := range zipCache {
			if now.Sub(entry.accessedAt) > zipCacheTTL {
				log.Printf("Cache evict: %s", key)
				delete(zipCache, key)
			}
		}
		zipCacheMu.Unlock()
	}
}

// getCachedZIP returns ZIP data from cache or extracts from TAR and caches it
func getCachedZIP(tarPath, patentDir string) ([]byte, string, error) {
	key := tarPath + ":" + patentDir

	// Check cache
	zipCacheMu.RLock()
	entry, ok := zipCache[key]
	zipCacheMu.RUnlock()

	if ok {
		// Update access time
		zipCacheMu.Lock()
		entry.accessedAt = time.Now()
		zipCacheMu.Unlock()
		log.Printf("Cache hit: %s", patentDir)
		return entry.data, entry.memberName, nil
	}

	// Cache miss - extract from TAR
	log.Printf("Cache miss: %s — extracting from TAR", patentDir)
	data, memberName, err := extractZIPFromTAR(tarPath, patentDir)
	if err != nil {
		return nil, "", err
	}

	// Store in cache
	zipCacheMu.Lock()
	zipCache[key] = &zipCacheEntry{
		data:       data,
		memberName: memberName,
		accessedAt: time.Now(),
	}
	zipCacheMu.Unlock()

	return data, memberName, nil
}

// ============================================================================
// Archive Extraction
// ============================================================================

// parseArchivePath extracts tarPath and patentDir from a PatentLookup
func parseArchivePath(lookup *PatentLookup) (tarPath, patentDir string, err error) {
	if lookup.RawXMLPath == "" {
		return "", "", fmt.Errorf("no raw_xml_path in database")
	}

	parts := strings.Split(lookup.RawXMLPath, "/")
	if len(parts) < 2 {
		return "", "", fmt.Errorf("invalid raw_xml_path format: %s", lookup.RawXMLPath)
	}

	tarFilename := parts[0]
	patentDir = parts[1]
	tarPath = filepath.Join(cfg.ArchiveBase, strconv.Itoa(lookup.Year), tarFilename)

	if _, err := os.Stat(tarPath); os.IsNotExist(err) {
		return "", "", fmt.Errorf("TAR file not found: %s", tarPath)
	}

	return tarPath, patentDir, nil
}

// extractFromArchive extracts patent files from TAR/ZIP archive
func extractFromArchive(lookup *PatentLookup) (*ExtractedFiles, error) {
	tarPath, patentDir, err := parseArchivePath(lookup)
	if err != nil {
		return nil, err
	}

	log.Printf("Extracting from: %s", tarPath)

	zipData, zipMemberName, err := getCachedZIP(tarPath, patentDir)
	if err != nil {
		return nil, err
	}

	log.Printf("Found ZIP: %s", zipMemberName)

	result, err := extractFilesFromZIP(zipData, tarPath, patentDir)
	if err != nil {
		return nil, err
	}

	result.XMLPath = lookup.RawXMLPath
	return result, nil
}

// extractTIFFromArchive extracts a specific TIF file's bytes from the archive
func extractTIFFromArchive(lookup *PatentLookup, figureNum int) ([]byte, string, error) {
	tarPath, patentDir, err := parseArchivePath(lookup)
	if err != nil {
		return nil, "", err
	}

	zipData, _, err := getCachedZIP(tarPath, patentDir)
	if err != nil {
		return nil, "", err
	}

	// Find TIF in ZIP matching the figure number pattern (D00001, D00002, etc.)
	tifPattern := fmt.Sprintf("D%05d.TIF", figureNum)

	zipReader, err := zip.NewReader(bytes.NewReader(zipData), int64(len(zipData)))
	if err != nil {
		return nil, "", fmt.Errorf("error opening ZIP: %w", err)
	}

	for _, file := range zipReader.File {
		filename := filepath.Base(file.Name)
		if strings.HasSuffix(strings.ToUpper(filename), tifPattern) {
			data, err := readZIPFile(file)
			if err != nil {
				return nil, "", fmt.Errorf("error reading TIF: %w", err)
			}
			return data, filename, nil
		}
	}

	return nil, "", fmt.Errorf("figure %d (pattern *%s) not found in archive", figureNum, tifPattern)
}

// extractZIPFromTAR finds and extracts the patent ZIP file from TAR archive
func extractZIPFromTAR(tarPath, patentDir string) ([]byte, string, error) {
	tarFile, err := os.Open(tarPath)
	if err != nil {
		return nil, "", fmt.Errorf("failed to open TAR: %w", err)
	}
	defer tarFile.Close()

	tarReader := tar.NewReader(tarFile)
	zipPattern := patentDir + ".ZIP"

	for {
		header, err := tarReader.Next()
		if err == io.EOF {
			break
		}
		if err != nil {
			return nil, "", fmt.Errorf("error reading TAR: %w", err)
		}

		if strings.HasSuffix(header.Name, zipPattern) {
			zipData, err := io.ReadAll(tarReader)
			if err != nil {
				return nil, "", fmt.Errorf("error extracting ZIP from TAR: %w", err)
			}
			return zipData, header.Name, nil
		}
	}

	return nil, "", fmt.Errorf("ZIP not found in TAR for pattern: %s", zipPattern)
}

// extractFilesFromZIP extracts XML and TIF file references from ZIP data
func extractFilesFromZIP(zipData []byte, tarPath, patentDir string) (*ExtractedFiles, error) {
	zipReader, err := zip.NewReader(bytes.NewReader(zipData), int64(len(zipData)))
	if err != nil {
		return nil, fmt.Errorf("error opening ZIP: %w", err)
	}

	result := &ExtractedFiles{
		TIFFiles: make(map[string]string),
	}

	for _, file := range zipReader.File {
		filename := filepath.Base(file.Name)
		upperFilename := strings.ToUpper(filename)

		if strings.HasSuffix(upperFilename, ".XML") {
			xmlData, err := readZIPFile(file)
			if err != nil {
				return nil, fmt.Errorf("error reading XML: %w", err)
			}
			result.XMLData = xmlData
			log.Printf("Extracted XML: %s (%d bytes)", filename, len(xmlData))

		} else if strings.HasSuffix(upperFilename, ".TIF") {
			fullPath := fmt.Sprintf("%s:%s/%s", tarPath, patentDir, filename)
			result.TIFFiles[filename] = fullPath
		}
	}

	if result.XMLData == nil {
		return nil, fmt.Errorf("no XML file found in ZIP")
	}

	return result, nil
}

// readZIPFile reads content from a ZIP file entry
func readZIPFile(file *zip.File) ([]byte, error) {
	rc, err := file.Open()
	if err != nil {
		return nil, err
	}
	defer rc.Close()

	return io.ReadAll(rc)
}
