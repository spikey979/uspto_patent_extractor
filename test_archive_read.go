package main

import (
	"archive/zip"
	"bytes"
	"fmt"
	"io/ioutil"
	"log"
	"strings"
)

func main() {
	// Read the outer archive
	archivePath := "/mnt/patents/originals/20030313B.ZIP"
	data, err := ioutil.ReadFile(archivePath)
	if err != nil {
		log.Fatalf("Failed to read archive: %v", err)
	}

	fmt.Printf("Archive size: %d bytes\n", len(data))

	zr, err := zip.NewReader(bytes.NewReader(data), int64(len(data)))
	if err != nil {
		log.Fatalf("Failed to open as ZIP: %v", err)
	}

	fmt.Printf("Archive contains %d files\n\n", len(zr.File))

	targetZip := "US20030046754A1-20030313.ZIP"
	fmt.Printf("Looking for nested ZIP ending with: %s\n\n", targetZip)

	found := 0
	for _, f := range zr.File {
		upperName := strings.ToUpper(f.Name)
		if strings.HasSuffix(upperName, targetZip) {
			found++
			fmt.Printf("MATCH #%d: %s\n", found, f.Name)

			// Try to open it
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

			// Try to open nested ZIP
			nestedZr, err := zip.NewReader(bytes.NewReader(nestedData), int64(len(nestedData)))
			if err != nil {
				fmt.Printf("  ERROR: not a valid ZIP: %v\n", err)
				continue
			}

			fmt.Printf("  Nested ZIP contains %d files:\n", len(nestedZr.File))
			for i, nf := range nestedZr.File {
				if i < 10 {
					fmt.Printf("    %d. %s\n", i, nf.Name)
				}
			}
		}
	}

	if found == 0 {
		fmt.Println("No matches found!")
		fmt.Println("\nShowing first 10 files in archive:")
		for i, f := range zr.File {
			if i < 10 {
				fmt.Printf("  %d. %s\n", i, f.Name)
			}
		}
	}
}
