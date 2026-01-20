#!/bin/bash

#############################################
# Smart Bidirectional Patent Data Sync
# Syncs local organized structure with Hetzner flat structure
# Supports dry-run mode for testing
#############################################

# Configuration
HETZNER_USER="u506059"
HETZNER_PASS="adh9mym@bdw.ukm9YXZ"
HETZNER_HOST="u506059.your-storagebox.de"
HETZNER_PORT="23"
REMOTE_BASE="uspto_downloads"

# Local paths (organized by type)
LOCAL_BASE="/mnt/patents/data"
LOCAL_GRANTS_XML="$LOCAL_BASE/grants/xml"
LOCAL_GRANTS_PDF="$LOCAL_BASE/grants/pdf"
LOCAL_APPLICATIONS="$LOCAL_BASE/applications/office_actions"
LOCAL_HISTORICAL="$LOCAL_BASE/historical"

# Log file
LOG_FILE="/home/mark/projects/patent_extractor/logs/sync_$(date +%Y%m%d_%H%M%S).log"
mkdir -p "$(dirname "$LOG_FILE")"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Dry-run mode (set via --dry-run flag)
DRY_RUN=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --help|-h)
      cat << EOF
Smart Bidirectional Patent Data Sync

Usage: $0 [OPTIONS]

Options:
  --dry-run    Test mode - show what would be synced without making changes
  --help, -h   Show this help message

Description:
  Syncs patent data between local organized structure and Hetzner storage.

  Local Structure (organized by type):
    /mnt/patents/data/historical/YYYY/       - IPG XML & I-prefix TAR files
    /mnt/patents/data/grants/pdf/YYYY/       - Grant PDF files
    /mnt/patents/data/applications/office_actions/YYYY/ - BDR files

  Remote Structure (flat by year):
    uspto_downloads/YYYY/  - All file types mixed

  Sync Logic:
    1. PULL: Download missing files from remote (IPG, I-TAR, BDR, PDF)
    2. PUSH: Upload missing files to remote (IPG, I-TAR, BDR, PDF)
    3. Auto-organize locally by file type based on filename patterns

Examples:
  $0 --dry-run    # Test what would be synced
  $0              # Actually perform sync

EOF
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

# Log function
log() {
  local level=$1
  shift
  local msg="$@"
  echo -e "$(date '+%Y-%m-%d %H:%M:%S') [$level] $msg" | tee -a "$LOG_FILE"
}

log_info() {
  echo -e "${BLUE}[INFO]${NC} $1" | tee -a "$LOG_FILE"
}

log_success() {
  echo -e "${GREEN}[SUCCESS]${NC} $1" | tee -a "$LOG_FILE"
}

log_warning() {
  echo -e "${YELLOW}[WARNING]${NC} $1" | tee -a "$LOG_FILE"
}

log_error() {
  echo -e "${RED}[ERROR]${NC} $1" | tee -a "$LOG_FILE"
}

log_step() {
  echo -e "${CYAN}[STEP]${NC} $1" | tee -a "$LOG_FILE"
}

# Check dependencies
if ! command -v rsync &> /dev/null; then
  log_error "rsync is not installed"
  exit 1
fi

if ! command -v sshpass &> /dev/null; then
  log_error "sshpass is not installed"
  exit 1
fi

# Export password for sshpass
export SSHPASS="$HETZNER_PASS"

# Dry-run indicator
if [ "$DRY_RUN" = true ]; then
  RSYNC_DRY_RUN="--dry-run"
  log_warning "DRY-RUN MODE - No files will be modified"
else
  RSYNC_DRY_RUN=""
  log_info "LIVE MODE - Files will be synced"
fi

echo ""
echo "=========================================="
log_info "Smart Bidirectional Patent Data Sync"
echo "=========================================="
log_info "Remote: sftp://$HETZNER_HOST/$REMOTE_BASE/"
log_info "Local:  $LOCAL_BASE/"
log_info "Log:    $LOG_FILE"
echo ""

# Function to sync a specific year
sync_year() {
  local year=$1
  local remote_path="$HETZNER_USER@$HETZNER_HOST:$REMOTE_BASE/$year/"

  log_step "Syncing year $year..."

  # Create local year directories if needed
  mkdir -p "$LOCAL_GRANTS_XML/$year"
  mkdir -p "$LOCAL_GRANTS_PDF/$year"
  mkdir -p "$LOCAL_APPLICATIONS/$year"
  mkdir -p "$LOCAL_HISTORICAL/$year"

  # Create remote year directory if needed
  sshpass -e sftp -P "$HETZNER_PORT" -o StrictHostKeyChecking=no "$HETZNER_USER@$HETZNER_HOST" << EOF >> "$LOG_FILE" 2>&1
mkdir $REMOTE_BASE 2>/dev/null
mkdir $REMOTE_BASE/$year 2>/dev/null
quit
EOF

  # PULL: Download missing files from remote to local
  # This handles all file types - rsync will download anything missing locally
  log_info "  Pulling from remote → local (year $year)..."

  # Download to temp directory first
  local temp_dir="/tmp/patent_sync_$year"
  mkdir -p "$temp_dir"

  sshpass -e rsync -avh $RSYNC_DRY_RUN --ignore-existing --progress \
    -e "ssh -p$HETZNER_PORT -o StrictHostKeyChecking=no" \
    "$remote_path" "$temp_dir/" >> "$LOG_FILE" 2>&1

  pull_result=$?

  # Organize downloaded files by type
  if [ -d "$temp_dir" ]; then
    # Move IPG files to grants/xml (issued patent grants in XML format)
    for file in "$temp_dir"/ipg*.zip; do
      [ -f "$file" ] && mv "$file" "$LOCAL_GRANTS_XML/$year/" && log_info "    → IPG: $(basename "$file")"
    done

    # Move I-prefix TAR files to historical (historical patent archives)
    for file in "$temp_dir"/I20*.tar; do
      [ -f "$file" ] && mv "$file" "$LOCAL_HISTORICAL/$year/" && log_info "    → I-TAR: $(basename "$file")"
    done

    # Skip grant_pdf_*.tar files (not used - grants already in IPG XML)
    for file in "$temp_dir"/grant_pdf_*.tar; do
      [ -f "$file" ] && rm -f "$file" && log_info "    → Skipped Grant PDF: $(basename "$file") (redundant)"
    done

    # Move BDR files to applications/office_actions
    for file in "$temp_dir"/bdr_oa_*.zip; do
      [ -f "$file" ] && mv "$file" "$LOCAL_APPLICATIONS/$year/" && log_info "    → BDR: $(basename "$file")"
    done

    # Clean up temp
    rm -rf "$temp_dir"
  fi

  if [ $pull_result -eq 0 ] || [ $pull_result -eq 23 ]; then
    log_success "  Pull completed for $year"
  else
    log_error "  Pull failed for $year (error code: $pull_result)"
  fi

  echo ""

  # PUSH: Upload missing files from local to remote
  log_info "  Pushing from local → remote (year $year)..."

  # Push IPG files from grants/xml
  if [ -d "$LOCAL_GRANTS_XML/$year" ]; then
    sshpass -e rsync -avh $RSYNC_DRY_RUN --ignore-existing --progress \
      -e "ssh -p$HETZNER_PORT -o StrictHostKeyChecking=no" \
      --include="ipg*.zip" --exclude="*" \
      "$LOCAL_GRANTS_XML/$year/" "$remote_path" >> "$LOG_FILE" 2>&1
  fi

  # Push I-prefix TAR files from historical
  if [ -d "$LOCAL_HISTORICAL/$year" ]; then
    sshpass -e rsync -avh $RSYNC_DRY_RUN --ignore-existing --progress \
      -e "ssh -p$HETZNER_PORT -o StrictHostKeyChecking=no" \
      --include="I20*.tar" --exclude="*" \
      "$LOCAL_HISTORICAL/$year/" "$remote_path" >> "$LOG_FILE" 2>&1
  fi

  # Push BDR files
  if [ -d "$LOCAL_APPLICATIONS/$year" ]; then
    sshpass -e rsync -avh $RSYNC_DRY_RUN --ignore-existing --progress \
      -e "ssh -p$HETZNER_PORT -o StrictHostKeyChecking=no" \
      --include="bdr_oa_*.zip" --exclude="*" \
      "$LOCAL_APPLICATIONS/$year/" "$remote_path" >> "$LOG_FILE" 2>&1
  fi

  push_result=$?

  if [ $push_result -eq 0 ] || [ $push_result -eq 23 ]; then
    log_success "  Push completed for $year"
  else
    log_error "  Push failed for $year (error code: $push_result)"
  fi

  echo ""
}

# Get list of years to sync (from both local and remote)
years_to_sync=()

# Add years from local directories
for dir in "$LOCAL_GRANTS_XML"/* "$LOCAL_GRANTS_PDF"/* "$LOCAL_APPLICATIONS"/*; do
  if [ -d "$dir" ]; then
    year=$(basename "$dir")
    if [[ "$year" =~ ^20[0-9]{2}$ ]]; then
      years_to_sync+=("$year")
    fi
  fi
done

# Add years from remote (query via SFTP)
remote_years=$(sshpass -e sftp -P "$HETZNER_PORT" -o StrictHostKeyChecking=no "$HETZNER_USER@$HETZNER_HOST" << 'EOF' 2>/dev/null | grep -E "^d" | awk '{print $NF}' | grep -E "^20[0-9]{2}$"
ls -1 $REMOTE_BASE
quit
EOF
)

for year in $remote_years; do
  years_to_sync+=("$year")
done

# Remove duplicates and sort
years_to_sync=($(echo "${years_to_sync[@]}" | tr ' ' '\n' | sort -u))

if [ ${#years_to_sync[@]} -eq 0 ]; then
  log_warning "No years found to sync"
  exit 0
fi

log_info "Years to sync: ${years_to_sync[*]}"
echo ""

# Sync each year
for year in "${years_to_sync[@]}"; do
  sync_year "$year"
done

# Summary
echo ""
log_step "Sync Summary"
echo ""

log_info "==== Local File Counts ===="
for year in "${years_to_sync[@]}"; do
  ipg_count=$(find "$LOCAL_GRANTS_XML/$year" -name "ipg*.zip" 2>/dev/null | wc -l)
  itar_count=$(find "$LOCAL_HISTORICAL/$year" -name "I20*.tar" 2>/dev/null | wc -l)
  bdr_count=$(find "$LOCAL_APPLICATIONS/$year" -name "bdr_oa_*.zip" 2>/dev/null | wc -l)

  if [ $ipg_count -gt 0 ] || [ $itar_count -gt 0 ] || [ $bdr_count -gt 0 ]; then
    echo "  $year: IPG=$ipg_count, I-TAR=$itar_count, BDR=$bdr_count"
  fi
done

echo ""
echo "=========================================="
if [ "$DRY_RUN" = true ]; then
  log_warning "DRY-RUN completed - no files were modified"
else
  log_success "Sync completed!"
fi
echo "=========================================="
echo ""

# Clean up
unset SSHPASS
