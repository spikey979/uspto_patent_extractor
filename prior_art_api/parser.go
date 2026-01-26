package main

import (
	"encoding/xml"
	"fmt"
	"regexp"
	"strconv"
	"strings"
)

// parsePatentXML parses USPTO XML and builds the patent document response
func parsePatentXML(data []byte, extracted *ExtractedFiles, lookup *PatentLookup) (*PatentDoc, error) {
	var patent USPatentApplication
	if err := xml.Unmarshal(data, &patent); err != nil {
		return nil, fmt.Errorf("XML parse error: %w", err)
	}

	doc := &PatentDoc{}

	// Build document sections
	buildPublicationInfo(doc, &patent)
	buildApplicationInfo(doc, &patent)
	buildApplicantInfo(doc, &patent)
	buildInventorsInfo(doc, &patent)
	buildClassifications(doc, &patent)
	buildRelatedApps(doc, &patent)
	buildAbstract(doc, &patent)
	buildDrawings(doc, &patent, extracted)
	buildDescription(doc, &patent)
	buildClaims(doc, &patent)
	buildSourceInfo(doc, lookup)

	return doc, nil
}

// buildPublicationInfo extracts publication information
func buildPublicationInfo(doc *PatentDoc, patent *USPatentApplication) {
	doc.PubNumber = patent.BibData.PublicationRef.DocID.DocNumber
	doc.Kind = patent.BibData.PublicationRef.DocID.Kind
	doc.Title = patent.BibData.InventionTitle

	pubDate, pubDateFmt := formatDate(patent.BibData.PublicationRef.DocID.Date)
	doc.Publication = DateInfo{Date: pubDate, Formatted: pubDateFmt}
}

// buildApplicationInfo extracts application information
func buildApplicationInfo(doc *PatentDoc, patent *USPatentApplication) {
	appDate, appDateFmt := formatDate(patent.BibData.ApplicationRef.DocID.Date)
	doc.Application = AppInfo{
		Number:    patent.BibData.ApplicationRef.DocID.DocNumber,
		Date:      appDate,
		Formatted: appDateFmt,
	}
}

// buildApplicantInfo extracts applicant information
func buildApplicantInfo(doc *PatentDoc, patent *USPatentApplication) {
	if len(patent.BibData.USParties.Applicants) == 0 {
		return
	}

	app := patent.BibData.USParties.Applicants[0]
	name := app.OrgName
	if name == "" {
		name = strings.TrimSpace(app.FirstName + " " + app.LastName)
	}

	doc.Applicant = &ApplicantInfo{
		Name:     name,
		Location: formatLocation(app.City, app.State, app.Country),
	}
}

// buildInventorsInfo extracts inventors information
func buildInventorsInfo(doc *PatentDoc, patent *USPatentApplication) {
	for _, inv := range patent.BibData.USParties.Inventors {
		name := strings.TrimSpace(inv.FirstName + " " + inv.LastName)
		doc.Inventors = append(doc.Inventors, InventorInfo{
			Name:     name,
			Location: formatLocation(inv.City, inv.State, inv.Country),
		})
	}
}

// buildClassifications extracts IPC and CPC classifications
func buildClassifications(doc *PatentDoc, patent *USPatentApplication) {
	doc.Classifications.IPC = []string{}
	doc.Classifications.CPC = []string{}

	// IPC classifications
	for _, ipc := range patent.BibData.Classifications.Items {
		cls := formatClassification(ipc.Section, ipc.Class, ipc.Subclass, ipc.MainGroup, ipc.Subgroup)
		doc.Classifications.IPC = append(doc.Classifications.IPC, cls)
	}

	// CPC classifications (main + other)
	for _, cpc := range patent.BibData.CPCClassifications.Main {
		cls := formatClassification(cpc.Section, cpc.Class, cpc.Subclass, cpc.MainGroup, cpc.Subgroup)
		doc.Classifications.CPC = append(doc.Classifications.CPC, cls)
	}
	for _, cpc := range patent.BibData.CPCClassifications.Other {
		cls := formatClassification(cpc.Section, cpc.Class, cpc.Subclass, cpc.MainGroup, cpc.Subgroup)
		doc.Classifications.CPC = append(doc.Classifications.CPC, cls)
	}
}

// buildRelatedApps extracts related application references
func buildRelatedApps(doc *PatentDoc, patent *USPatentApplication) {
	for _, prov := range patent.BibData.RelatedDocs.Provisionals {
		date, _ := formatDate(prov.DocID.Date)
		doc.RelatedApps = append(doc.RelatedApps, RelatedApp{
			Type:   "provisional",
			Number: prov.DocID.DocNumber,
			Date:   date,
		})
	}
}

// buildAbstract extracts abstract text
func buildAbstract(doc *PatentDoc, patent *USPatentApplication) {
	var abstractParts []string
	for _, p := range patent.Abstract.Paragraphs {
		text := cleanXMLText(p.Text)
		if text != "" {
			abstractParts = append(abstractParts, text)
		}
	}
	doc.Abstract = strings.Join(abstractParts, " ")
}

// buildDrawings extracts drawing/figure information
func buildDrawings(doc *PatentDoc, patent *USPatentApplication, extracted *ExtractedFiles) {
	for _, fig := range patent.Drawings.Figures {
		num := 0
		if fig.Num != "" {
			num, _ = strconv.Atoi(fig.Num)
		}

		drawing := DrawingInfo{
			Num:  num,
			ID:   fig.ID,
			File: fig.Img.File,
		}

		// Set full path from extracted files
		if path, ok := extracted.TIFFiles[fig.Img.File]; ok {
			drawing.Path = path
		}

		doc.Drawings = append(doc.Drawings, drawing)
	}
}

// buildDescription parses and extracts description content
func buildDescription(doc *PatentDoc, patent *USPatentApplication) {
	content := string(patent.Description.Content)
	doc.Description = parseDescriptionContent(content)
}

// descMatch holds match information for description parsing
type descMatch struct {
	pos    int
	isHead bool
	num    int
	text   string
}

// parseDescriptionContent parses description XML content into structured paragraphs
func parseDescriptionContent(content string) []DescPara {
	var result []DescPara

	// Regex patterns for headings and paragraphs
	headingRe := regexp.MustCompile(`<heading[^>]*>([^<]*)</heading>`)
	paraRe := regexp.MustCompile(`<p[^>]*num="(\d+)"[^>]*>(.*?)</p>`)

	// Collect matches with positions for sorting
	var matches []descMatch

	// Find headings
	for _, m := range headingRe.FindAllStringSubmatchIndex(content, -1) {
		text := content[m[2]:m[3]]
		matches = append(matches, descMatch{
			pos:    m[0],
			isHead: true,
			text:   strings.TrimSpace(text),
		})
	}

	// Find paragraphs with num attribute
	for _, m := range paraRe.FindAllStringSubmatchIndex(content, -1) {
		numStr := content[m[2]:m[3]]
		text := content[m[4]:m[5]]
		num, _ := strconv.Atoi(numStr)
		cleanText := cleanXMLText([]byte(text))
		if cleanText != "" {
			matches = append(matches, descMatch{
				pos:    m[0],
				isHead: false,
				num:    num,
				text:   cleanText,
			})
		}
	}

	// Sort by position in document
	sortDescMatches(matches)

	// Build result
	for _, m := range matches {
		if m.isHead {
			result = append(result, DescPara{Type: "heading", Text: m.text})
		} else {
			result = append(result, DescPara{Type: "paragraph", Num: m.num, Text: m.text})
		}
	}

	return result
}

// sortDescMatches sorts description matches by position using simple bubble sort
func sortDescMatches(matches []descMatch) {
	for i := 0; i < len(matches)-1; i++ {
		for j := i + 1; j < len(matches); j++ {
			if matches[j].pos < matches[i].pos {
				matches[i], matches[j] = matches[j], matches[i]
			}
		}
	}
}

// buildClaims extracts patent claims
func buildClaims(doc *PatentDoc, patent *USPatentApplication) {
	for _, claim := range patent.Claims.Items {
		num, _ := strconv.Atoi(claim.Num)
		text := cleanXMLText(claim.Text)
		doc.Claims = append(doc.Claims, ClaimInfo{Num: num, Text: text})
	}
}

// buildSourceInfo adds source file information
func buildSourceInfo(doc *PatentDoc, lookup *PatentLookup) {
	parts := strings.Split(lookup.RawXMLPath, "/")
	doc.Source = SourceInfo{
		Archive: parts[0],
		XMLPath: lookup.RawXMLPath,
	}
}
