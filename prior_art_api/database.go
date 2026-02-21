package main

import (
	"database/sql"
	"fmt"
	"time"

	_ "github.com/lib/pq"
)

var db *sql.DB

// initDB establishes database connection
func initDB() error {
	connStr := fmt.Sprintf(
		"host=%s port=%d user=%s password=%s dbname=%s sslmode=disable",
		cfg.DBHost, cfg.DBPort, cfg.DBUser, cfg.DBPassword, cfg.DBName,
	)

	var err error
	db, err = sql.Open("postgres", connStr)
	if err != nil {
		return fmt.Errorf("failed to open database: %w", err)
	}

	// Connection pool settings
	db.SetMaxOpenConns(10)
	db.SetMaxIdleConns(5)

	// Verify connection
	if err := db.Ping(); err != nil {
		return fmt.Errorf("failed to ping database: %w", err)
	}

	return nil
}

// lookupPatent retrieves patent information from database by publication number
func lookupPatent(pubNumber string) (*PatentLookup, error) {
	normalized := normalizePubNumber(pubNumber)

	var patent PatentLookup
	var pubDate sql.NullTime
	var rawPath sql.NullString
	var title sql.NullString

	err := db.QueryRow(`
		SELECT pub_number, pub_date, raw_xml_path, year, title
		FROM patent_data_unified
		WHERE pub_number = $1
	`, normalized).Scan(&patent.PubNumber, &pubDate, &rawPath, &patent.Year, &title)

	if err != nil {
		return nil, err
	}

	if pubDate.Valid {
		patent.PubDate = &pubDate.Time
	}
	if rawPath.Valid {
		patent.RawXMLPath = rawPath.String
	}
	if title.Valid {
		patent.Title = title.String
	}

	return &patent, nil
}

// saveFigureDescription saves a figure description with auto-incrementing version
func saveFigureDescription(pubNumber string, fig FigureDescriptionInput) (int, error) {
	var version int
	err := db.QueryRow(`
		INSERT INTO figure_descriptions (pub_number, figure_num, figure_file, description, model, prompt_hash, version)
		SELECT $1::varchar, $2::integer, $3::varchar, $4::text, $5::varchar, $6::varchar,
		       COALESCE(MAX(version), 0) + 1
		FROM figure_descriptions
		WHERE pub_number = $1 AND figure_num = $2
		RETURNING version
	`, pubNumber, fig.FigureNum, fig.FigureFile, fig.Desc, fig.Model, fig.PromptHash).Scan(&version)
	if err != nil {
		return 0, fmt.Errorf("failed to save figure description: %w", err)
	}
	return version, nil
}

// getLatestFigureDescriptions returns the latest version of each figure's description
func getLatestFigureDescriptions(pubNumber string) ([]FigureDescriptionRecord, error) {
	rows, err := db.Query(`
		SELECT DISTINCT ON (figure_num)
			id, pub_number, figure_num, figure_file, description, model, prompt_hash, version, created_at
		FROM figure_descriptions
		WHERE pub_number = $1
		ORDER BY figure_num, version DESC
	`, pubNumber)
	if err != nil {
		return nil, fmt.Errorf("failed to query figure descriptions: %w", err)
	}
	defer rows.Close()

	return scanFigureDescriptions(rows)
}

// getFigureVersions returns all versions of a specific figure's description
func getFigureVersions(pubNumber string, figureNum int) ([]FigureDescriptionRecord, error) {
	rows, err := db.Query(`
		SELECT id, pub_number, figure_num, figure_file, description, model, prompt_hash, version, created_at
		FROM figure_descriptions
		WHERE pub_number = $1 AND figure_num = $2
		ORDER BY version DESC
	`, pubNumber, figureNum)
	if err != nil {
		return nil, fmt.Errorf("failed to query figure versions: %w", err)
	}
	defer rows.Close()

	return scanFigureDescriptions(rows)
}

// getFigureDescriptionStatus returns a summary of all figure descriptions for a patent
func getFigureDescriptionStatus(pubNumber string) ([]FigureStatusSummary, int, error) {
	rows, err := db.Query(`
		SELECT figure_num,
		       MAX(figure_file) AS figure_file,
		       COUNT(*) AS version_count,
		       MAX(version) AS latest_version,
		       (array_agg(model ORDER BY version DESC))[1] AS latest_model,
		       MAX(created_at) AS latest_date,
		       LENGTH((array_agg(description ORDER BY version DESC))[1]) AS desc_len
		FROM figure_descriptions
		WHERE pub_number = $1
		GROUP BY figure_num
		ORDER BY figure_num
	`, pubNumber)
	if err != nil {
		return nil, 0, fmt.Errorf("failed to query figure status: %w", err)
	}
	defer rows.Close()

	var summaries []FigureStatusSummary
	totalVersions := 0
	for rows.Next() {
		var s FigureStatusSummary
		var figureFile, model sql.NullString
		var latestDate time.Time

		err := rows.Scan(&s.FigureNum, &figureFile, &s.VersionCount, &s.LatestVersion, &model, &latestDate, &s.DescriptionLen)
		if err != nil {
			return nil, 0, fmt.Errorf("failed to scan status row: %w", err)
		}
		if figureFile.Valid {
			s.FigureFile = figureFile.String
		}
		if model.Valid {
			s.LatestModel = model.String
		}
		s.LatestDate = latestDate.Format(time.RFC3339)
		totalVersions += s.VersionCount
		summaries = append(summaries, s)
	}
	return summaries, totalVersions, nil
}

// deleteFigureDescriptions removes all figure descriptions for a patent, returns count deleted
func deleteFigureDescriptions(pubNumber string) (int, error) {
	result, err := db.Exec(`DELETE FROM figure_descriptions WHERE pub_number = $1`, pubNumber)
	if err != nil {
		return 0, fmt.Errorf("failed to delete figure descriptions: %w", err)
	}
	count, err := result.RowsAffected()
	if err != nil {
		return 0, fmt.Errorf("failed to get rows affected: %w", err)
	}
	return int(count), nil
}

// scanFigureDescriptions scans rows into FigureDescriptionRecord slices
func scanFigureDescriptions(rows *sql.Rows) ([]FigureDescriptionRecord, error) {
	var records []FigureDescriptionRecord
	for rows.Next() {
		var r FigureDescriptionRecord
		var figureFile, model, promptHash sql.NullString
		var createdAt time.Time

		err := rows.Scan(&r.ID, &r.PubNumber, &r.FigureNum, &figureFile,
			&r.Desc, &model, &promptHash, &r.Version, &createdAt)
		if err != nil {
			return nil, fmt.Errorf("failed to scan row: %w", err)
		}

		if figureFile.Valid {
			r.FigureFile = figureFile.String
		}
		if model.Valid {
			r.Model = model.String
		}
		if promptHash.Valid {
			r.PromptHash = promptHash.String
		}
		r.CreatedAt = createdAt.Format(time.RFC3339)

		records = append(records, r)
	}
	return records, nil
}
