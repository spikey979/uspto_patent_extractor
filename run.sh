#!/bin/bash

# Patent Extractor Run Script

echo "Starting Patent Extractor..."
echo "Archives: /mnt/patents/data/historical/"
echo "Logs: ./logs/extraction.log"
echo ""

# Check if binary exists, build if not
if [ ! -f "./patent_extractor" ]; then
    echo "Building patent_extractor..."
    if command -v go &> /dev/null; then
        go build -o patent_extractor patent_extractor.go
    elif [ -f "$HOME/go/bin/go" ]; then
        $HOME/go/bin/go build -o patent_extractor patent_extractor.go
    else
        echo "Error: Go not found. Please install Go or build manually."
        exit 1
    fi
fi

# Create directories if needed
mkdir -p logs temp

# Run extractor
nohup ./patent_extractor > logs/extraction.log 2>&1 &
PID=$!

echo "Patent Extractor started with PID: $PID"
echo "Monitor with: tail -f logs/extraction.log"
echo "Stop with: kill $PID"

# Save PID for later
echo $PID > patent_extractor.pid