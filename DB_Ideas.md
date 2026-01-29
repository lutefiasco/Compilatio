# Database Sync Ideas

## Overview

Notes on keeping the Compilatio SQLite database in sync between the rabota server and local laptop.

## Recommended Approach: rsync with Primary/Replica Model

Designate one machine as the write primary (rabota if it's the production dev server).

### Option A: Laptop pulls from server (simplest)

```bash
# On laptop - pull latest database
rsync -avz rabota:/path/to/compilatio/database/compilatio.db ./database/compilatio.db
```

### Option B: Bidirectional with manual control

```bash
# Push local changes to server
rsync -avz ./database/compilatio.db rabota:/path/to/compilatio/database/

# Pull server changes to laptop
rsync -avz rabota:/path/to/compilatio/database/compilatio.db ./database/
```

## Key Rules

1. **Never write on both machines simultaneously** - SQLite doesn't handle merge conflicts
2. **Stop the server before syncing** if it's actively serving (or use `-wal` mode and sync all 3 files: `.db`, `.db-wal`, `.db-shm`)
3. **Backup before overwriting** - keep a dated copy

## Makefile Targets

```makefile
db-pull:
	rsync -avz rabota:/path/to/database/compilatio.db ./database/

db-push:
	rsync -avz ./database/compilatio.db rabota:/path/to/database/
```

## Alternative: Litestream

For continuous replication to S3/cloud storage, [Litestream](https://litestream.io/) provides streaming backup and point-in-time recovery. More infrastructure, but zero-touch once configured.

## Step-by-Step: Setting Up rsync from Laptop to rabota

### 1. Ensure SSH access to rabota

First, verify you can SSH to rabota:

```bash
ssh rabota
```

If this doesn't work, set up an SSH config entry. Edit `~/.ssh/config`:

```
Host rabota
    HostName rabota.local    # or IP address
    User your_username
    IdentityFile ~/.ssh/id_ed25519
```

### 2. Set up SSH key authentication (if not already done)

```bash
# Generate key if you don't have one
ssh-keygen -t ed25519 -C "laptop"

# Copy public key to rabota
ssh-copy-id rabota
```

### 3. Verify the database path on rabota

SSH to rabota and confirm the path:

```bash
ssh rabota
ls -la /Users/rabota/Geekery/Compilatio/database/compilatio.db
```

Note the exact path for use in rsync commands.

### 4. Pull database from rabota to laptop

From the laptop, in the Compilatio project directory:

```bash
cd ~/Geekery/Compilatio

# Dry run first (shows what would happen)
rsync -avz --dry-run rabota:/Users/rabota/Geekery/Compilatio/database/compilatio.db ./database/

# If it looks correct, run for real
rsync -avz rabota:/Users/rabota/Geekery/Compilatio/database/compilatio.db ./database/
```

### 5. Push database from laptop to rabota

```bash
cd ~/Geekery/Compilatio

# Dry run first
rsync -avz --dry-run ./database/compilatio.db rabota:/Users/rabota/Geekery/Compilatio/database/

# Run for real
rsync -avz ./database/compilatio.db rabota:/Users/rabota/Geekery/Compilatio/database/
```

### 6. Handle WAL mode (if applicable)

If SQLite is in WAL mode, sync all three files:

```bash
# Pull all database files
rsync -avz rabota:/Users/rabota/Geekery/Compilatio/database/compilatio.db* ./database/

# Push all database files
rsync -avz ./database/compilatio.db* rabota:/Users/rabota/Geekery/Compilatio/database/
```

### 7. Add to Makefile (optional)

Create or edit `Makefile` in the project root:

```makefile
RABOTA_DB = rabota:/Users/rabota/Geekery/Compilatio/database/compilatio.db
LOCAL_DB = ./database/compilatio.db

db-pull:
	rsync -avz $(RABOTA_DB) $(LOCAL_DB)

db-push:
	rsync -avz $(LOCAL_DB) $(RABOTA_DB)

db-backup:
	cp $(LOCAL_DB) ./database/compilatio-$(shell date +%Y%m%d).db
```

Then use:
- `make db-pull` to get latest from rabota
- `make db-push` to send local changes to rabota
- `make db-backup` to create a dated local backup before pulling

## Recommendation

Start with Option A (laptop pulls from server). It's the simplest, and complexity can be added later if needed.
