# Remaining Application Number Gaps - Root Cause Analysis

## Current Status: 99.58% Coverage

**Missing**: 34,022 patents (0.42%)
- 2003: 16,237 (6.85% of year)
- 2010: 17,783 (5.09% of year)
- 2002: 1
- Other: 1

## Root Cause Identified: Archive Loading Logic Bug

### The Problem

The backfill script was only loading ONE archive per date, but patents from the same date are split across multiple archives (A and B).

**Original buggy logic**:
```go
for _, path := range archivePaths {
    archiveData, err = e.loadArchive(path)
    if err == nil {
        foundPath = path
        break  // ❌ STOPS after finding first archive (usually A)
    }
}

// Process all patents using ONLY the first archive found
for _, patent := range group {
    appNum := e.extractFromArchive(archiveData, patent.RawPath)
    // ...
}
```

### Example: Patent 20030046754

**Database path**: `US20030046754A1-20030313/US20030046754A1-20030313.XML`
**Actual location**: Archive B at `20030313/UTIL0046/US20030046754A1-20030313.ZIP`

**What was happening**:
1. Script grouped all patents from 2003-03-13 together
2. Tried to load archive → found `20030313A.ZIP` first
3. Used ONLY archive A for all patents from that date
4. Patent 20030046754 is in archive B → not found!

### The Fix

Load ALL available archives (A, B, etc.) for each date, then try each archive for each patent:

```go
// Load all available archives for this date
var availableArchives [][]byte
for _, path := range archivePaths {
    archiveData, err := e.loadArchive(path)
    if err == nil {
        availableArchives = append(availableArchives, archiveData)
    }
}

// Try each patent against all archives
for _, patent := range group {
    var appNum string
    for _, archiveData := range availableArchives {
        appNum = e.extractFromArchive(archiveData, patent.RawPath)
        if appNum != "" {
            break // Found it!
        }
    }
}
```

## Archive Structure Details

### Nested ZIP Organization

Archives contain subdirectories with nested ZIPs:
```
20030313A.ZIP/
├── 20030313/DTDS/
├── 20030313/ENTITIES/
├── 20030313/UTIL0050/
│   ├── US20030050000A1-20030313.ZIP
│   ├── US20030050001A1-20030313.ZIP
│   └── ...
├── 20030313/UTIL0051/
│   └── ...

20030313B.ZIP/
├── 20030313/UTIL0046/
│   ├── US20030046754A1-20030313.ZIP
│   ├── US20030046755A1-20030313.ZIP
│   └── ...
├── 20030313/UTIL0047/
│   └── ...
```

### Why the suffix matching works

The code looks for files ending with `US20030046754A1-20030313.ZIP`:
- File in archive: `20030313/UTIL0046/US20030046754A1-20030313.ZIP`
- Suffix match: ✅ Works correctly
- The nested ZIP path includes subdirectories, but suffix matching handles this

## Expected Impact

This fix should recover most or all of the remaining 16,237 patents from 2003.

## 2010 Issues

Separate investigation still needed - likely different XML schema or archive structure.

**Remaining after 2003 fix**: ~17,784 patents (~0.22% of total)
