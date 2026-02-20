package main

import (
	"os"
	"strconv"
)

// Configuration holds all application settings
type Config struct {
	DBHost      string
	DBPort      int
	DBName      string
	DBUser      string
	DBPassword  string
	ServerPort  int
	ArchiveBase string
}

// Default configuration - can be overridden via environment variables
var cfg = Config{
	DBHost:      getEnv("DB_HOST", "localhost"),
	DBPort:      getEnvInt("DB_PORT", 5432),
	DBName:      getEnv("DB_NAME", "companies_db"),
	DBUser:      getEnv("DB_USER", "mark"),
	DBPassword:  getEnv("DB_PASSWORD", "mark123"),
	ServerPort:  getEnvInt("SERVER_PORT", 8096),
	ArchiveBase: getEnv("ARCHIVE_BASE", "/mnt/patents/data/historical"),
}

// getEnv returns environment variable value or default
func getEnv(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}

// getEnvInt returns environment variable as int or default
func getEnvInt(key string, def int) int {
	if v := os.Getenv(key); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			return n
		}
	}
	return def
}
