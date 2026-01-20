#!/bin/bash
# Start the auto-batch downloads monitor

PROJ_DIR=/home/mark/projects/patent_extractor
SCRIPT=$PROJ_DIR/scripts/auto_batch_downloads.sh
PID_FILE=$PROJ_DIR/auto_batch_downloads.pid
LOG_FILE=$PROJ_DIR/logs/auto_batch_downloads.log

# Check if already running
if [ -f "$PID_FILE" ]; then
    pid=$(cat "$PID_FILE")
    if ps -p "$pid" > /dev/null 2>&1; then
        echo "Auto-batch monitor already running (PID: $pid)"
        echo "Log: tail -f $LOG_FILE"
        exit 0
    else
        echo "Removing stale PID file"
        rm -f "$PID_FILE"
    fi
fi

# Start the monitor in background
echo "Starting auto-batch downloads monitor..."
nohup "$SCRIPT" >> "$LOG_FILE" 2>&1 &
pid=$!
echo $pid > "$PID_FILE"

echo "Auto-batch monitor started (PID: $pid)"
echo ""
echo "Commands:"
echo "  View log:  tail -f $LOG_FILE"
echo "  Stop:      ./stop_auto_monitor.sh"
echo "  Status:    ps -p $pid"
echo ""

# Show initial output
sleep 2
tail -20 "$LOG_FILE"
