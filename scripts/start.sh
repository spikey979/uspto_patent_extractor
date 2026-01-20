#!/bin/bash

#############################################
# Start Patent Extractor Services
# Uses Overmind to orchestrate all services
#############################################

cd "$(dirname "$0")/.."

echo "Starting Patent Extractor Services with Overmind..."
echo ""
echo "Services:"
echo "  - web (Port 8093): AI-powered patent search"
echo "  - search_claims (Port 8094): Enhanced search with claims"
echo ""
echo "Controls:"
echo "  - View logs: overmind connect <service>"
echo "  - Stop all: overmind quit (or Ctrl+C)"
echo "  - Restart service: overmind restart <service>"
echo ""

# Start overmind
overmind start
