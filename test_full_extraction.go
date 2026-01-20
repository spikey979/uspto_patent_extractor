package main

import (
	"archive/zip"
	"bytes"
	"fmt"
	"io/ioutil"
	"log"
	"path/filepath"
	"regexp"
	"strings"
)

func extractAppNumber(data []byte) string {
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

func extractFromArchive(archiveData []byte, xmlPath string) string {
	zr, err := zip.NewReader(bytes.NewReader(archiveData), int64(len(archiveData)))
	if err != nil {
		fmt.Printf("[ERROR] Failed to open archive as ZIP: %v\n", err)
		return ""
	}

	targetFile := filepath.Base(xmlPath)
	targetDir := filepath.Dir(xmlPath)
	targetZip := targetDir + ".ZIP"

	fmt.Printf("Looking for:\n")
	fmt.Printf("  Target file: %s\n", targetFile)
	fmt.Printf("  Target dir: %s\n", targetDir)
	fmt.Printf("  Target ZIP: %s\n", targetZip)
	fmt.Printf("  Archive contains: %d files\n\n", len(zr.File))

	for _, f := range zr.File {
		upperName := strings.ToUpper(f.Name)
		if strings.HasSuffix(upperName, targetZip) {
			fmt.Printf("Found nested ZIP: %s\n", f.Name)

			rc, err := f.Open()
			if err != nil {
				fmt.Printf("  ERROR opening: %v\n", err)
				continue
			}
			nestedData, err := ioutil.ReadAll(rc)
			rc.Close()
			if err != nil {
				fmt.Printf("  ERROR reading: %v\n", err)
				continue
			}

			fmt.Printf("  Nested ZIP size: %d bytes\n", len(nestedData))

			nestedZr, err := zip.NewReader(bytes.NewReader(nestedData), int64(len(nestedData)))
			if err != nil {
				fmt.Printf("  ERROR: not a valid ZIP: %v\n", err)
				continue
			}

			fmt.Printf("  Nested ZIP contains: %d files\n", len(nestedZr.File))

			for _, nf := range nestedZr.File {
				if strings.HasSuffix(nf.Name, targetFile) {
					fmt.Printf("  Found target file: %s\n", nf.Name)

					nrc, err := nf.Open()
					if err != nil {
						fmt.Printf("    ERROR opening XML: %v\n", err)
						continue
					}
					xmlData, err := ioutil.ReadAll(nrc)
					nrc.Close()
					if err != nil {
						fmt.Printf("    ERROR reading XML: %v\n", err)
						continue
					}

					fmt.Printf("    XML size: %d bytes\n", len(xmlData))
					appNum := extractAppNumber(xmlData)
					fmt.Printf("    Application number: %s\n", appNum)
					return appNum
				}
			}
		}
	}

	fmt.Println("No match found!")
	return ""
}

func main() {
	archivePath := "/mnt/patents/originals/20030313B.ZIP"
	xmlPath := "US20030046754A1-20030313/US20030046754A1-20030313.XML"

	fmt.Printf("Testing extraction for: %s\n", xmlPath)
	fmt.Printf("From archive: %s\n\n", archivePath)

	data, err := ioutil.ReadFile(archivePath)
	if err != nil {
		log.Fatalf("Failed to read archive: %v", err)
	}

	result := extractFromArchive(data, xmlPath)
	fmt.Printf("\n=== RESULT: %s ===\n", result)
}
