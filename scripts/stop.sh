#!/bin/bash

#############################################
# Stop Patent Extractor Services
#############################################

echo "Stopping Patent Extractor Services..."

# Stop overmind
overmind quit 2>/dev/null

# Also kill any stray processes
pkill -f patent_search_ai_fixed.py
pkill -f patent_search_ai_with_claims.py

echo "All services stopped."
