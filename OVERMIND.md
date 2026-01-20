# Overmind Process Management

## Overview

Overmind orchestrates all long-running patent system services, providing:
- Unified process management
- Centralized logging
- Easy start/stop/restart
- Process monitoring
- Individual service control

## Quick Start

```bash
cd /home/mark/projects/patent_extractor

# Start all web services
./scripts/start.sh

# Check status
./scripts/status.sh

# Stop all services
./scripts/stop.sh
```

## Services

### Active Services (started by default)

| Service | Port | Description |
|---------|------|-------------|
| `web` | 8093 | AI-powered patent search |
| `search_claims` | 8094 | Enhanced search with claims extraction |

### Manual Services (commented in Procfile)

| Service | Description | Start Command |
|---------|-------------|---------------|
| `extract_historical` | Historical patent extraction | `overmind start -l extract_historical` |
| `extract_grants` | Grant data extraction | `overmind start -l extract_grants` |
| `monitor` | File monitoring/watcher | `overmind start -l monitor` |
| `batch` | Batch processing | `overmind start -l batch` |

## Usage

### Start Services

```bash
# Start all default services (web, search_claims)
cd /home/mark/projects/patent_extractor
./scripts/start.sh

# Or use overmind directly
overmind start

# Start specific services only
overmind start -l web
overmind start -l web,search_claims
```

### Monitor Services

```bash
# View status
./scripts/status.sh

# Connect to a service's output (live logs)
overmind connect web
overmind connect search_claims

# Exit: Ctrl+C (doesn't stop the service)
```

### Control Services

```bash
# Restart a service
overmind restart web

# Stop a specific service
overmind stop search_claims

# Stop all services
overmind quit
# Or
./scripts/stop.sh
```

### View Logs

```bash
# Live logs for specific service
overmind connect web

# All logs in one view
cd /home/mark/projects/patent_extractor
tail -f logs/*.log

# Specific service logs
tail -f .overmind.sock  # Overmind's own logs
```

## Configuration

### Procfile

Located at `/home/mark/projects/patent_extractor/Procfile`

```procfile
# Web Applications (active by default)
web: cd patent_search && python3.11 patent_search_ai_fixed.py
search_claims: cd patent_search && python3.11 patent_search_ai_with_claims.py

# Manual services (uncomment to enable)
# extract_historical: ./patent_extractor 2>&1 | tee logs/extractor_historical.log
# extract_grants: ./grant_extractor 2>&1 | tee logs/extractor_grants.log
```

### Environment Variables

Overmind respects `.env` files. Create one if needed:

```bash
# .env
DB_HOST=localhost
DB_PORT=5432
DB_NAME=companies_db
DB_USER=mark
DB_PASSWORD=mark123
```

## Common Tasks

### Running Extractors

To run the patent extractors (long-running processes):

1. **Edit Procfile** - Uncomment the extractor you want
2. **Start it**: `overmind start -l extract_historical`
3. **Monitor**: `overmind connect extract_historical`

### Adding New Services

1. Edit `Procfile`
2. Add line: `service_name: command to run`
3. Restart overmind

Example:
```procfile
sync: ./scripts/sync/patent_data_sync.sh
```

Then: `overmind restart`

## Troubleshooting

### Services won't start

```bash
# Check for port conflicts
netstat -tln | grep -E ":(8093|8094)"

# Kill any existing processes
pkill -f patent_search_ai_fixed.py
pkill -f patent_search_ai_with_claims.py

# Try again
./scripts/start.sh
```

### Can't connect to Overmind

```bash
# Check if overmind is running
pgrep overmind

# Check socket file
ls -la .overmind.sock

# Restart overmind
./scripts/stop.sh
./scripts/start.sh
```

### Service keeps crashing

```bash
# Check logs
overmind connect <service_name>

# Or check application logs
tail -f logs/*.log

# Run service manually to see errors
cd patent_search
python3.11 patent_search_ai_fixed.py
```

## Keyboard Shortcuts (in overmind console)

- `Ctrl+C` - Stop all services and exit Overmind
- `Ctrl+B` then `?` - Show help
- `Ctrl+B` then `c` - Connect to service
- `Ctrl+B` then `k` - Kill service
- `Ctrl+B` then `r` - Restart service

## Advanced Usage

### Running in Background (tmux)

```bash
# Start in detached tmux session
tmux new-session -d -s patent_services 'cd /home/mark/projects/patent_extractor && overmind start'

# Attach to session
tmux attach -t patent_services

# Detach: Ctrl+B then D
```

### Custom Procfile

```bash
# Use different Procfile
overmind start -f Procfile.prod

# Example Procfile.prod
web: cd patent_search && python3.11 patent_search_ai_fixed.py --port 9000
```

## Files Created by Overmind

| File | Purpose |
|------|---------|
| `.overmind.sock` | Unix socket for IPC |
| `.overmind.env` | Environment variables |
| `logs/*.log` | Application logs (if configured) |

## Best Practices

1. **Always use start.sh** for consistency
2. **Check status.sh** before debugging
3. **Use overmind connect** to view live logs
4. **Don't run services manually** if overmind is active
5. **Stop overmind** before manual testing

## Migration from Manual Processes

Old way:
```bash
cd patent_search
python3.11 patent_search_ai_fixed.py > ../logs/app.log 2>&1 &
python3.11 patent_search_ai_with_claims.py > ../logs/claims.log 2>&1 &
```

New way:
```bash
cd /home/mark/projects/patent_extractor
./scripts/start.sh
```

## References

- Overmind Documentation: https://github.com/DarthSim/overmind
- Procfile Format: https://devcenter.heroku.com/articles/procfile

---

Last Updated: November 26, 2025
