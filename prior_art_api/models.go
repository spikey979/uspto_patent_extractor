package main

import (
	"encoding/xml"
	"time"
)

// ============================================================================
// Database Models
// ============================================================================

// PatentLookup represents a patent record from the database
type PatentLookup struct {
	PubNumber  string
	PubDate    *time.Time
	RawXMLPath string
	Year       int
	Title      string
}

// ============================================================================
// XML Structures for USPTO Patent Application
// ============================================================================

// USPatentApplication is the root element of USPTO patent XML
type USPatentApplication struct {
	XMLName     xml.Name    `xml:"us-patent-application"`
	BibData     BibData     `xml:"us-bibliographic-data-application"`
	Abstract    Abstract    `xml:"abstract"`
	Drawings    Drawings    `xml:"drawings"`
	Description Description `xml:"description"`
	Claims      Claims      `xml:"claims"`
}

// BibData contains bibliographic information
type BibData struct {
	PublicationRef     PublicationRef     `xml:"publication-reference"`
	ApplicationRef     ApplicationRef     `xml:"application-reference"`
	InventionTitle     string             `xml:"invention-title"`
	Classifications    Classifications    `xml:"classifications-ipcr"`
	CPCClassifications CPCClassifications `xml:"classifications-cpc"`
	USParties          USParties          `xml:"us-parties"`
	RelatedDocs        RelatedDocs        `xml:"us-related-documents"`
}

// PublicationRef contains publication reference info
type PublicationRef struct {
	DocID DocID `xml:"document-id"`
}

// ApplicationRef contains application reference info
type ApplicationRef struct {
	DocID DocID `xml:"document-id"`
}

// DocID represents a document identifier
type DocID struct {
	Country   string `xml:"country"`
	DocNumber string `xml:"doc-number"`
	Kind      string `xml:"kind"`
	Date      string `xml:"date"`
}

// Classifications contains IPC classifications
type Classifications struct {
	Items []ClassificationIPCR `xml:"classification-ipcr"`
}

// ClassificationIPCR represents an IPC classification
type ClassificationIPCR struct {
	Section   string `xml:"section"`
	Class     string `xml:"class"`
	Subclass  string `xml:"subclass"`
	MainGroup string `xml:"main-group"`
	Subgroup  string `xml:"subgroup"`
}

// CPCClassifications contains CPC classifications
type CPCClassifications struct {
	Main  []ClassificationCPC `xml:"main-cpc>classification-cpc"`
	Other []ClassificationCPC `xml:"further-cpc>classification-cpc"`
}

// ClassificationCPC represents a CPC classification
type ClassificationCPC struct {
	Section   string `xml:"section"`
	Class     string `xml:"class"`
	Subclass  string `xml:"subclass"`
	MainGroup string `xml:"main-group"`
	Subgroup  string `xml:"subgroup"`
}

// USParties contains applicants and inventors
type USParties struct {
	Applicants []Applicant `xml:"us-applicants>us-applicant"`
	Inventors  []Inventor  `xml:"inventors>inventor"`
}

// Applicant represents a patent applicant
type Applicant struct {
	OrgName   string `xml:"addressbook>orgname"`
	FirstName string `xml:"addressbook>first-name"`
	LastName  string `xml:"addressbook>last-name"`
	City      string `xml:"addressbook>address>city"`
	State     string `xml:"addressbook>address>state"`
	Country   string `xml:"addressbook>address>country"`
}

// Inventor represents a patent inventor
type Inventor struct {
	FirstName string `xml:"addressbook>first-name"`
	LastName  string `xml:"addressbook>last-name"`
	City      string `xml:"addressbook>address>city"`
	State     string `xml:"addressbook>address>state"`
	Country   string `xml:"addressbook>address>country"`
}

// RelatedDocs contains related document references
type RelatedDocs struct {
	Provisionals []ProvisionalApp `xml:"us-provisional-application"`
}

// ProvisionalApp represents a provisional application reference
type ProvisionalApp struct {
	DocID DocID `xml:"document-id"`
}

// Abstract contains patent abstract paragraphs
type Abstract struct {
	Paragraphs []Paragraph `xml:"p"`
}

// Drawings contains patent figures
type Drawings struct {
	Figures []Figure `xml:"figure"`
}

// Figure represents a patent drawing figure
type Figure struct {
	ID  string `xml:"id,attr"`
	Num string `xml:"num,attr"`
	Img Img    `xml:"img"`
}

// Img represents an image reference
type Img struct {
	File   string `xml:"file,attr"`
	Format string `xml:"img-format,attr"`
}

// Description contains patent description content
type Description struct {
	Content []byte `xml:",innerxml"`
}

// Claims contains patent claims
type Claims struct {
	Items []Claim `xml:"claim"`
}

// Claim represents a patent claim
type Claim struct {
	ID   string `xml:"id,attr"`
	Num  string `xml:"num,attr"`
	Text []byte `xml:",innerxml"`
}

// Paragraph represents a text paragraph
type Paragraph struct {
	Num  string `xml:"num,attr"`
	Text []byte `xml:",innerxml"`
}

// ============================================================================
// API Response Structures
// ============================================================================

// APIResponse is the standard API response wrapper
type APIResponse struct {
	Success bool       `json:"success"`
	Patent  *PatentDoc `json:"patent,omitempty"`
	Error   string     `json:"error,omitempty"`
}

// PatentDoc represents the full patent document for API response
type PatentDoc struct {
	PubNumber       string         `json:"pub_number"`
	Kind            string         `json:"kind"`
	Title           string         `json:"title"`
	Publication     DateInfo       `json:"publication"`
	Application     AppInfo        `json:"application"`
	Applicant       *ApplicantInfo `json:"applicant,omitempty"`
	Inventors       []InventorInfo `json:"inventors"`
	Classifications ClassInfo      `json:"classifications"`
	RelatedApps     []RelatedApp   `json:"related_applications,omitempty"`
	Abstract        string         `json:"abstract"`
	Drawings        []DrawingInfo  `json:"drawings"`
	Description     []DescPara     `json:"description"`
	Claims          []ClaimInfo    `json:"claims"`
	Source          SourceInfo     `json:"source"`
}

// DateInfo holds formatted date information
type DateInfo struct {
	Date      string `json:"date"`
	Formatted string `json:"date_formatted"`
}

// AppInfo holds application information
type AppInfo struct {
	Number    string `json:"number"`
	Date      string `json:"date"`
	Formatted string `json:"date_formatted"`
}

// ApplicantInfo holds applicant information
type ApplicantInfo struct {
	Name     string `json:"name"`
	Location string `json:"location"`
}

// InventorInfo holds inventor information
type InventorInfo struct {
	Name     string `json:"name"`
	Location string `json:"location"`
}

// ClassInfo holds classification information
type ClassInfo struct {
	IPC []string `json:"ipc"`
	CPC []string `json:"cpc"`
}

// RelatedApp holds related application information
type RelatedApp struct {
	Type   string `json:"type"`
	Number string `json:"number"`
	Date   string `json:"date"`
}

// DrawingInfo holds drawing/figure information
type DrawingInfo struct {
	Num  int    `json:"num"`
	ID   string `json:"id"`
	File string `json:"file"`
	Path string `json:"path"`
}

// DescPara holds description paragraph information
type DescPara struct {
	Type string `json:"type"`
	Num  int    `json:"num,omitempty"`
	Text string `json:"text"`
}

// ClaimInfo holds claim information
type ClaimInfo struct {
	Num  int    `json:"num"`
	Text string `json:"text"`
}

// SourceInfo holds source file information
type SourceInfo struct {
	Archive string `json:"archive"`
	XMLPath string `json:"xml_path"`
}
