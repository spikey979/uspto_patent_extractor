#!/bin/bash
# Prior Art API - Run Script

cd "$(dirname "$0")"

# Kill any existing instance
pkill -f "prior_art_api" 2>/dev/null

# Build if needed
if [ ! -f prior_art_api ] || [ main.go -nt prior_art_api ]; then
    echo "Building..."
    go build -o prior_art_api . || exit 1
fi

# Run
echo "Starting Prior Art API on port 8095..."
./prior_art_api
