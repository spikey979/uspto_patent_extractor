#!/bin/bash

#############################################
# Check Status of Patent Extractor Services
#############################################

echo "==========================================  "
echo "Patent Extractor Services Status"
echo "=========================================="
echo ""

# Check if overmind is running
if pgrep -f "overmind" > /dev/null; then
    echo "✅ Overmind is RUNNING"
    echo ""
    echo "Active services:"
    ps aux | grep -E "(patent_search_ai|overmind)" | grep -v grep | awk '{print "  - " $11 " " $12 " " $13}'
else
    echo "❌ Overmind is NOT running"
fi

echo ""
echo "Ports:"
netstat -tln | grep -E ":(8093|8094)" || echo "  No services listening on ports 8093/8094"

echo ""
echo "Recent logs:"
echo "  $(ls -t logs/*.log 2>/dev/null | head -1 || echo 'No logs found')"
