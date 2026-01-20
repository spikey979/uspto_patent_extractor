# Patent Extractor Auto-Batch Problem

## Date
2025-11-23 15:20

## Problem Statement
The auto-batch downloads monitoring script keeps launching the patent extractor, but the extractor immediately exits after finding 0 archives to process, creating an infinite restart loop.

## Symptoms
1. Extractor launches every 60 seconds
2. Each run reports: `scan_new=false` (should be `true`)
3. Each run reports: `Found 0 unprocessed archives`
4. Extractor completes in 1 second with 0 patents processed
5. Loop repeats indefinitely

## Evidence from Logs

### Extraction Log
```
2025/11/23 15:20:03 metadata-fill-fs starting; workers=8 scan_new=false recursive=true min_mb=1
2025/11/23 15:20:03 roots=[/mnt/patents/originals]
2025/11/23 15:20:03 Loaded 3021 processed archives
2025/11/23 15:20:03 Found 0 unprocessed archives under /mnt/patents/originals
```

### NewFiles Directory Status
```
$ ls -lah /mnt/patents/originals/NewFiles/ | head -5
total 185G
-rwxrwxr-x 1 mark mark  327M Sep  8 16:15 20010927.ZIP
-rwxrwxr-x 1 mark mark  348M Sep  8 16:15 20011004.ZIP
-rwxrwxr-x 1 mark mark  412M Sep  8 16:15 20011011.ZIP
...
```
**Files ARE present in NewFiles/** (~317 files, ~185GB total)

## Root Cause

The environment variable `SCAN_NEW` is NOT being passed to the patent_extractor process despite multiple attempts:

1. **Attempt 1**: `export SCAN_NEW=true` before `nohup` - FAILED (nohup doesn't preserve exports)
2. **Attempt 2**: `SCAN_NEW=true nohup ...` - FAILED (inline vars before nohup don't work)
3. **Attempt 3**: `nohup env SCAN_NEW=true ...` - FAILED (still not working)
4. **Attempt 4**: Created wrapper script - FAILED (added complexity)
5. **Attempt 5**: Removed nohup, direct background execution - FAILED (still showing scan_new=false)

## Current Code (auto_batch_downloads.sh line 193-194)
```bash
SCAN_NEW=true WORKERS=8 DB_PASSWORD=qwklmn711 \
    ./patent_extractor >> "$PROJ/logs/extraction.log" 2>&1 &
```

## Expected Behavior
- `SCAN_NEW=true` should be read by extractor
- Extractor should scan `/mnt/patents/originals/NewFiles/` directory
- Should find ~317 ZIP files
- Should process them

## Actual Behavior
- `scan_new=false` is being used (default value)
- Extractor scans `/mnt/patents/originals/` (not NewFiles subdirectory)
- Finds 0 unprocessed files (all 3021 already in processed_archives.txt)
- Exits immediately

## Environment Variable Reading Code (patent_extractor.go:155)
```go
cfg.ScanNewOnly = getEnvBool("SCAN_NEW", cfg.ScanNewOnly)
```

The `getEnvBool` function:
```go
func getEnvBool(key string, def bool) bool {
    if v := strings.TrimSpace(os.Getenv(key)); v != "" {
        v = strings.ToLower(v)
        return v == "1" || v == "true" || v == "yes"
    }
    return def
}
```

## Question
Why is the environment variable NOT being passed from the bash script to the Go binary when launched with:
```bash
SCAN_NEW=true ./patent_extractor &
```

## Possibilities to Investigate
1. Is bash stripping environment variables when backgrounding with `&`?
2. Is the Go binary being launched in a different shell context?
3. Is there something about how the auto-batch script itself is launched that prevents env var inheritance?
4. Does the `cd "$PROJ"` command affect environment variable passing?
5. Is there a shell option (like `set -a`) that needs to be enabled?
