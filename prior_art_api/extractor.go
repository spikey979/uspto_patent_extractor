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
)

// ExtractedFiles holds the extracted patent files from archive
type ExtractedFiles struct {
	XMLData  []byte
	TIFFiles map[string]string // filename -> full archive path
	XMLPath  string
}

// extractFromArchive extracts patent files from TAR/ZIP archive
func extractFromArchive(lookup *PatentLookup) (*ExtractedFiles, error) {
	if lookup.RawXMLPath == "" {
		return nil, fmt.Errorf("no raw_xml_path in database")
	}

	// Parse raw_xml_path: "I20160526.tar/US20160148332A1-20160526/US20160148332A1-20160526.XML"
	parts := strings.Split(lookup.RawXMLPath, "/")
	if len(parts) < 2 {
		return nil, fmt.Errorf("invalid raw_xml_path format: %s", lookup.RawXMLPath)
	}

	tarFilename := parts[0]
	patentDir := parts[1] // e.g., "US20160148332A1-20160526"

	// Build full TAR path
	tarPath := filepath.Join(cfg.ArchiveBase, strconv.Itoa(lookup.Year), tarFilename)

	if _, err := os.Stat(tarPath); os.IsNotExist(err) {
		return nil, fmt.Errorf("TAR file not found: %s", tarPath)
	}

	log.Printf("Extracting from: %s", tarPath)

	// Extract ZIP from TAR
	zipData, zipMemberName, err := extractZIPFromTAR(tarPath, patentDir)
	if err != nil {
		return nil, err
	}

	log.Printf("Found ZIP: %s", zipMemberName)

	// Extract files from ZIP
	result, err := extractFilesFromZIP(zipData, tarPath, patentDir)
	if err != nil {
		return nil, err
	}

	result.XMLPath = lookup.RawXMLPath
	return result, nil
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
			// Store the full path for the TIF file (archive:internal_path format)
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
