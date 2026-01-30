# Database Sync Ideas

## Overview

Notes on keeping the Compilatio SQLite database in sync between the serving server (user: rabota) and local laptop.

## Recommended Approach: rsync with Primary/Replica Model

Designate one machine as the write primary (serving if it's the production dev server).

### Option A: Laptop pulls from server (simplest)

```bash
# On laptop - pull latest database
rsync -avz serving:/path/to/compilatio/database/compilatio.db ./database/compilatio.db
```

### Option B: Bidirectional with manual control

```bash
# Push local changes to server
rsync -avz ./database/compilatio.db serving:/path/to/compilatio/database/

# Pull server changes to laptop
rsync -avz serving:/path/to/compilatio/database/compilatio.db ./database/
```

## Key Rules

1. **Never write on both machines simultaneously** - SQLite doesn't handle merge conflicts
2. **Stop the server before syncing** if it's actively serving (or use `-wal` mode and sync all 3 files: `.db`, `.db-wal`, `.db-shm`)
3. **Backup before overwriting** - keep a dated copy

## Makefile Targets

```makefile
db-pull:
	rsync -avz serving:/path/to/database/compilatio.db ./database/

db-push:
	rsync -avz ./database/compilatio.db serving:/path/to/database/
```

## Alternative: Litestream

For continuous replication to S3/cloud storage, [Litestream](https://litestream.io/) provides streaming backup and point-in-time recovery. More infrastructure, but zero-touch once configured.

## Step-by-Step: Setting Up rsync from Laptop to serving

### 1. Ensure SSH access to serving

First, verify you can SSH to serving:

```bash
ssh serving
```

If this doesn't work, set up an SSH config entry. Edit `~/.ssh/config`:

```
Host serving
    HostName serving
    User rabota
```

### 2. Set up SSH key authentication (if not already done)

```bash
# Generate key if you don't have one
ssh-keygen -t ed25519 -C "laptop"

# Copy public key to serving
ssh-copy-id serving
```

### 3. Verify the database path on serving

SSH to serving and confirm the path:

```bash
ssh serving
ls -la /Users/rabota/Geekery/Compilatio/database/compilatio.db
```

Note the exact path for use in rsync commands.

### 4. Pull database from serving to laptop

From the laptop, in the Compilatio project directory:

```bash
cd ~/Geekery/Compilatio

# Dry run first (shows what would happen)
rsync -avz --dry-run serving:/Users/rabota/Geekery/Compilatio/database/compilatio.db ./database/

# If it looks correct, run for real
rsync -avz serving:/Users/rabota/Geekery/Compilatio/database/compilatio.db ./database/
```

### 5. Push database from laptop to serving

```bash
cd ~/Geekery/Compilatio

# Dry run first
rsync -avz --dry-run ./database/compilatio.db serving:/Users/rabota/Geekery/Compilatio/database/

# Run for real
rsync -avz ./database/compilatio.db serving:/Users/rabota/Geekery/Compilatio/database/
```

### 6. Handle WAL mode (if applicable)

If SQLite is in WAL mode, sync all three files:

```bash
# Pull all database files
rsync -avz serving:/Users/rabota/Geekery/Compilatio/database/compilatio.db* ./database/

# Push all database files
rsync -avz ./database/compilatio.db* serving:/Users/rabota/Geekery/Compilatio/database/
```

### 7. Add to Makefile (optional)

Create or edit `Makefile` in the project root:

```makefile
SERVING_DB = serving:/Users/rabota/Geekery/Compilatio/database/compilatio.db
LOCAL_DB = ./database/compilatio.db

db-pull:
	rsync -avz $(SERVING_DB) $(LOCAL_DB)

db-push:
	rsync -avz $(LOCAL_DB) $(SERVING_DB)

db-backup:
	cp $(LOCAL_DB) ./database/compilatio-$(shell date +%Y%m%d).db
```

Then use:
- `make db-pull` to get latest from serving
- `make db-push` to send local changes to serving
- `make db-backup` to create a dated local backup before pulling

## Recommendation

Start with Option A (laptop pulls from server). It's the simplest, and complexity can be added later if needed.

## Quick Reference: Option A Setup

### 1. Verify SSH access
```bash
ssh serving
```
If this works, you're good. If not, add an entry to `~/.ssh/config`.

### 2. Find the database path on serving
While SSH'd into serving:
```bash
find ~ -name "compilatio.db" 2>/dev/null
```
Note the exact path.

### 3. Test with a dry run
Back on laptop, from the Compilatio directory:
```bash
rsync -avz --dry-run serving:/path/to/compilatio/database/compilatio.db ./database/
```
Replace `/path/to/compilatio/` with the actual path from step 2.

### 4. Pull the database
If the dry run looks correct:
```bash
rsync -avz serving:/path/to/compilatio/database/compilatio.db ./database/
```

### 5. (Optional) Add Makefile targets
Makes future syncs easy with `make db-pull`:
```makefile
SERVING_DB = serving:/actual/path/database/compilatio.db
LOCAL_DB = ./database/compilatio.db

db-pull:
	rsync -avz $(SERVING_DB) $(LOCAL_DB)

db-backup:
	cp $(LOCAL_DB) ./database/compilatio-$(shell date +%Y%m%d).db
```

### Key safety rules
- Always backup before overwriting: `make db-backup` or `cp database/compilatio.db database/compilatio-backup.db`
- Don't write to the database on both machines simultaneously
- If serving's server is running, stop it before syncing (or sync WAL files too: `compilatio.db*`)
