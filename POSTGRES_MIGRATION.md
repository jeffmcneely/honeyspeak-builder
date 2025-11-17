# PostgreSQL Migration Guide

This project now supports both PostgreSQL (for development) and SQLite (for production). The system automatically selects the appropriate backend based on environment configuration.

## Overview

- **Development**: Use PostgreSQL for better concurrent access and performance during development
- **Production**: Convert to SQLite for iOS app deployment (single-file, no server required)

## Setup PostgreSQL for Development

### 1. Install PostgreSQL

```bash
# macOS with Homebrew
brew install postgresql
brew services start postgresql

# Ubuntu/Debian
sudo apt-get install postgresql postgresql-client
sudo systemctl start postgresql

# Create database and user
createdb honeyspeak_dev
createuser honeyspeak
psql -d honeyspeak_dev -c "ALTER USER honeyspeak WITH PASSWORD 'yourpassword';"
psql -d honeyspeak_dev -c "GRANT ALL PRIVILEGES ON DATABASE honeyspeak_dev TO honeyspeak;"
```

### 2. Configure Environment

Copy the example configuration:
```bash
cp .env.postgres.example .env
```

Edit `.env` and set your PostgreSQL connection:
```
POSTGRES_CONNECTION=postgresql://honeyspeak:yourpassword@localhost:5432/honeyspeak_dev
```

### 3. Install Python Dependencies

```bash
pip install -r requirements.txt
```

The `psycopg2-binary` package provides PostgreSQL support for Python.

### 4. Initialize Database

The database schema will be automatically created when you first use it:

```bash
# Through Flask web interface
curl http://localhost:5002/init_database

# Or run build_dictionary.py
python scripts/build_dictionary.py noun1.txt
```

## Database Backend Selection

The system automatically chooses the backend based on the `POSTGRES_CONNECTION` environment variable:

- **If `POSTGRES_CONNECTION` is set**: Uses PostgreSQL
- **If `POSTGRES_CONNECTION` is not set**: Falls back to SQLite

All Python scripts use the unified `Dictionary` interface from `libs/dictionary.py`:

```python
from libs.dictionary import Dictionary

# Automatically uses PostgreSQL or SQLite based on environment
db = Dictionary()
words = db.get_all_words()
```

## Converting PostgreSQL to SQLite for Production

When ready to deploy to iOS, convert your PostgreSQL database to SQLite:

```bash
# Basic conversion
python scripts/convert_postgres_to_sqlite.py

# Specify output path
python scripts/convert_postgres_to_sqlite.py -o production.sqlite

# Copy directly to iOS app bundle
python scripts/convert_postgres_to_sqlite.py --ios-path /path/to/ios/app
```

The converter:
- Creates a production-ready SQLite database (no WAL mode)
- Transfers all data: words, definitions, assets, stories
- Optimizes the database with VACUUM
- Verifies data integrity

## API Compatibility

Both `PostgresDictionary` and `SQLiteDictionary` implement the same interface:

### Core Methods
- `add_word(word, functional_label, flags)` - Add a word
- `add_shortdef(uuid, definition)` - Add a definition
- ~~`add_external_asset(uuid, assetgroup, sid, package, filename)`~~ - **DEPRECATED** - Add asset metadata (generates warning)
- `get_word_by_uuid(uuid)` - Get word by UUID
- `get_word_by_text(word)` - Get word by text
- `get_shortdefs(uuid)` - Get definitions for a word
- `get_external_assets(uuid, assetgroup)` - Get assets for a word (read-only, for legacy views)
- `get_all_words(limit)` - Get all words
- `get_word_count()` - Count words
- `get_shortdef_count()` - Count definitions
- `get_asset_count()` - Count assets (read-only, for legacy views)

> **⚠️ NOTE:** The `external_assets` table and its write methods (`add_external_asset`, `add_asset`, `delete_asset`, `delete_assets`) are **deprecated**. Assets are now stored in the filesystem with predictable naming conventions (`word_{uuid}_0.ext`, `shortdef_{uuid}_{id}.ext`, `image_{uuid}_{id}.ext`). Read-only methods like `get_external_assets()` and `get_asset_count()` remain for backwards compatibility with database stats views.

### Transaction Methods
- `begin_immediate()` - Start transaction (returns connection for PostgreSQL)
- `commit(conn)` - Commit transaction
- `rollback(conn)` - Rollback transaction

### Query Methods
- `execute_fetchall(query, params)` - Execute and fetch all results
- `execute_fetchone(query, params)` - Execute and fetch one result
- `execute(query, params)` - Execute without results

## Docker Support

The Dockerfile includes PostgreSQL client libraries:

```dockerfile
RUN apt-get update && apt-get install -y \
    postgresql-client \
    libpq-dev \
    ...
```

## Kubernetes Deployment

For Kubernetes, you can either:

1. **Use PostgreSQL in development, convert to SQLite for deployment**
   - Develop with PostgreSQL locally
   - Convert to SQLite before building Docker image
   - Deploy SQLite-based image to Kubernetes

2. **Run PostgreSQL in Kubernetes** (not recommended for this project)
   - Deploy PostgreSQL as a separate service
   - Configure connection string in ConfigMap
   - More complex, requires persistent volumes

## Migration from Existing SQLite

If you have an existing SQLite database, you can continue using it:

1. **Keep using SQLite**: Just don't set `POSTGRES_CONNECTION` in your environment
2. **Migrate to PostgreSQL**: Write a migration script (reverse of convert_postgres_to_sqlite.py)

## Troubleshooting

### Connection Errors

If you get connection errors, check:
- PostgreSQL is running: `pg_isready`
- Connection string format is correct
- Database and user exist
- Password is correct

### Performance Issues

PostgreSQL should handle concurrent access better than SQLite. If you see issues:
- Check connection pooling settings
- Ensure indexes are created (they're in the schema)
- Run `ANALYZE` on PostgreSQL tables

### Data Integrity

The converter validates record counts. If mismatches occur:
- Check for unique constraint violations
- Ensure all foreign keys are valid
- Look for transaction rollbacks in logs

## Benefits of This Approach

1. **Development Speed**: PostgreSQL handles concurrent Celery workers better
2. **Production Simplicity**: SQLite is perfect for iOS deployment
3. **Code Reuse**: Same API for both backends
4. **Easy Migration**: Simple conversion script for production
5. **Flexibility**: Can switch backends by changing environment variable