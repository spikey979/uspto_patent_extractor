package main

import (
	"fmt"
	"strings"
)

func main() {
	archiveFile := "20030313/UTIL0046/US20030046754A1-20030313.ZIP"
	targetZip := "US20030046754A1-20030313.ZIP"

	upperName := strings.ToUpper(archiveFile)

	fmt.Printf("Archive file: %s\n", archiveFile)
	fmt.Printf("Target ZIP: %s\n", targetZip)
	fmt.Printf("Upper name: %s\n", upperName)
	fmt.Printf("HasSuffix result: %v\n", strings.HasSuffix(upperName, targetZip))
}
