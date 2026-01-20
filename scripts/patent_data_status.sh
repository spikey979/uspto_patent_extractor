#!/bin/bash
# Patent Data Status - Shows file counts by year and type
# Usage: ./patent_data_status.sh

DATA_ROOT="/mnt/patents/data"

# Colors
B='\033[1m'
R='\033[0m'
G='\033[32m'
C='\033[36m'
D='\033[90m'
RED='\033[31m'

# Column widths
W1=6   # Year
W2=10  # Historical
W3=8   # Grants
W4=10  # OfficeAct
W5=8   # Biblio

# Count files in a directory
count_files() {
    local dir="$1" pattern="$2"
    [[ -d "$dir" ]] && find "$dir" -maxdepth 1 -type f -name "$pattern" 2>/dev/null | wc -l || echo 0
}

# Print cell with proper padding (number right-aligned)
cell() {
    local val="$1" width="$2" color="$3"
    local str
    if [[ "$val" == "0" || -z "$val" ]]; then
        str="-"
    else
        str="$val"
    fi
    local pad=$((width - ${#str}))
    printf "%${pad}s${color}%s${R}" "" "$str"
}

# Header
echo ""
echo -e "${B}PATENT DATA STATUS${R}"
echo ""

# Table header
printf "${B}%${W1}s  %${W2}s  %${W3}s  %${W4}s  %${W5}s${R}\n" \
    "Year" "Hist [1]" "Grant[2]" "OA [3]" "Bib [4]"

# Separator
printf "${D}%${W1}s  %${W2}s  %${W3}s  %${W4}s  %${W5}s${R}\n" \
    "------" "----------" "--------" "----------" "--------"

# Collect years
declare -A years
for dir in "$DATA_ROOT/historical"/* "$DATA_ROOT/grants/xml"/* "$DATA_ROOT/grants/aps"/* "$DATA_ROOT/grants/pdf"/* "$DATA_ROOT/applications/office_actions"/* "$DATA_ROOT/applications/office_actions/rejections"/* "$DATA_ROOT/applications/office_actions/all"/* "$DATA_ROOT/applications/bibliographic"/*; do
    [[ -d "$dir" ]] && year=$(basename "$dir") && [[ "$year" =~ ^[0-9]{4}$ ]] && years[$year]=1
done

# Totals
t_hist=0 t_grants=0 t_oa=0 t_bib=0

# Print rows
for year in $(echo "${!years[@]}" | tr ' ' '\n' | sort); do
    hist=$(count_files "$DATA_ROOT/historical/$year" "*.tar")
    hist=$((hist + $(count_files "$DATA_ROOT/historical/$year" "*.ZIP") + $(count_files "$DATA_ROOT/historical/$year" "*.zip")))
    # Count grants from all subdirectories (xml, aps, pdf)
    grants=0
    for subdir in xml aps pdf; do
        grants=$((grants + $(count_files "$DATA_ROOT/grants/$subdir/$year" "*.zip")))
        grants=$((grants + $(count_files "$DATA_ROOT/grants/$subdir/$year" "*.ZIP")))
        grants=$((grants + $(count_files "$DATA_ROOT/grants/$subdir/$year" "*.tar")))
        grants=$((grants + $(count_files "$DATA_ROOT/grants/$subdir/$year" "*.pdf")))
    done
    # Count Office Actions from all subdirectories (rejections + all)
    oa=$(count_files "$DATA_ROOT/applications/office_actions/$year" "*.zip")
    oa=$((oa + $(count_files "$DATA_ROOT/applications/office_actions/rejections/$year" "*.zip")))
    oa=$((oa + $(count_files "$DATA_ROOT/applications/office_actions/all/$year" "*.zip")))
    # Count Bibliographic (appblxml) files
    bib=$(count_files "$DATA_ROOT/applications/bibliographic/$year" "*.zip")

    [[ $hist -eq 0 && $grants -eq 0 && $oa -eq 0 && $bib -eq 0 ]] && continue

    t_hist=$((t_hist + hist)); t_grants=$((t_grants + grants)); t_oa=$((t_oa + oa)); t_bib=$((t_bib + bib))

    # Determine colors
    hc=$([[ $hist -gt 0 ]] && echo "$G" || echo "$D")
    gc=$([[ $grants -gt 0 ]] && echo "$G" || echo "$D")
    oc=$([[ $oa -gt 0 ]] && echo "$G" || echo "$D")
    bc=$([[ $bib -gt 0 ]] && echo "$G" || echo "$D")

    printf "%${W1}s  " "$year"
    cell "$hist" $W2 "$hc"; printf "  "
    cell "$grants" $W3 "$gc"; printf "  "
    cell "$oa" $W4 "$oc"; printf "  "
    cell "$bib" $W5 "$bc"
    printf "\n"
done

# Separator
printf "${D}%${W1}s  %${W2}s  %${W3}s  %${W4}s  %${W5}s${R}\n" \
    "------" "----------" "--------" "----------" "--------"

# Totals row
printf "${B}%${W1}s  %${W2}d  %${W3}d  %${W4}d  %${W5}d${R}\n" \
    "TOTAL" $t_hist $t_grants $t_oa $t_bib

# Legend
echo ""
echo -e "${D}Sources:${R}"
echo -e "${D}[1] Historical - Patent application full text with images (appdt dataset)${R}"
echo -e "${D}    https://data.uspto.gov/bulkdata/datasets/appdt${R}"
echo -e "${RED}[2] Grants - Weekly patent grant XML (IPG files, 2002-present) [REQUIRED - need historical data]${R}"
echo -e "${RED}    https://data.uspto.gov/bulkdata/datasets/PTGRXML${R}"
echo -e "${RED}[*] Grants APS - Green Book ASCII (1976-2001) [REQUIRED - need historical data]${R}"
echo -e "${RED}    https://data.uspto.gov/bulkdata/datasets/ptgraps${R}"
echo -e "${D}[3] Office Actions - USPTO examiner office actions (BDR files)${R}"
echo -e "${D}    https://developer.uspto.gov/data/oa-weekly-archives${R}"
echo -e "${D}[4] Bibliographic - Patent Application Bibliographic XML (front page data, 2001+)${R}"
echo -e "${D}    https://data.uspto.gov/bulkdata/datasets/appblxml${R}"
echo ""
