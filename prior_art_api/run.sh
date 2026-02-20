#!/bin/bash
# Prior Art API - Run Script

cd "$(dirname "$0")"

# Kill any existing instance
pkill -f "prior_art_api" 2>/dev/null

# Build if needed (check all .go files for changes)
NEEDS_BUILD=false
if [ ! -f prior_art_api ]; then
    NEEDS_BUILD=true
else
    for f in *.go; do
        if [ "$f" -nt prior_art_api ]; then
            NEEDS_BUILD=true
            break
        fi
    done
fi

if [ "$NEEDS_BUILD" = true ]; then
    echo "Building..."
    go build -o prior_art_api . || exit 1
fi

# Run
echo "Starting Prior Art API on port 8095..."
./prior_art_api
