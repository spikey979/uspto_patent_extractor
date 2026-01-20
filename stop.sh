#!/bin/bash

# Stop Patent Extractor

if [ -f "patent_extractor.pid" ]; then
    PID=$(cat patent_extractor.pid)
    if ps -p $PID > /dev/null 2>&1; then
        echo "Stopping Patent Extractor (PID: $PID)..."
        kill $PID
        rm patent_extractor.pid
        echo "Patent Extractor stopped."
    else
        echo "Process not running (PID: $PID)"
        rm patent_extractor.pid
    fi
else
    echo "No PID file found. Trying to find process..."
    pkill -f patent_extractor && echo "Patent Extractor stopped." || echo "Patent Extractor not running."
fi