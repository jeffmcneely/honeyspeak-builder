# Honeyspeak Builder

Build system for creating an ESL dictionary SQLite database with media assets for iOS deployment.

## Features

- Fetches word definitions from Merriam-Webster Learner's Dictionary API
- Generates audio pronunciations and definition images using OpenAI
- Packages assets for efficient iOS app consumption
- Supports both PostgreSQL (development) and SQLite (production) backends
- Concurrent processing with Celery/Redis workers

## Database Support

### New: PostgreSQL for Development
The system now supports PostgreSQL for development, providing better concurrent access for multiple Celery workers. See [POSTGRES_MIGRATION.md](POSTGRES_MIGRATION.md) for setup instructions.

- **Development**: Use PostgreSQL for better concurrency
- **Production**: Convert to SQLite for iOS deployment

### Backend Selection
The system automatically selects the database backend:
- If `POSTGRES_CONNECTION` is set → uses PostgreSQL
- Otherwise → uses SQLite

## Quick Start

1. **Setup environment**:
```bash
cp .env.example .env
# Edit .env with your API keys

# For PostgreSQL development (optional):
cp .env.postgres.example .env
# Set POSTGRES_CONNECTION in .env
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
brew install ffmpeg imagemagick redis  # macOS
```

3. **Build dictionary**:
```bash
# Initialize database (PostgreSQL or SQLite based on config)
python scripts/build_dictionary.py noun10.txt Dictionary.sqlite
```

4. **Generate assets**:
```bash
# Synchronous (for debugging)
python scripts/build_assets.py --verbosity 1 --outdir assets_hires

# Or with Celery workers (parallel)
redis-server &
celery -A scripts.build_assets worker --loglevel=info --concurrency=5
python scripts/build_assets.py --enqueue --outdir assets_hires
```

5. **Package for iOS**:
```bash
python scripts/build_package.py --outdir assets_hires --packagedir packages --dictionary Dictionary.sqlite

# Or if using PostgreSQL, convert first:
python scripts/convert_postgres_to_sqlite.py -o production.sqlite
```

## Web Interface

Run the Flask web app for monitoring and management:
```bash
python scripts/app.py
# Visit http://localhost:5002
```

Features:
- Database initialization and statistics
- Build dictionary from word lists
- Monitor Celery tasks
- View logs

## Kubernetes Deployment

For production deployment with Kubernetes:
```bash
./upstart.sh build   # Build Docker image
./upstart.sh deploy  # Deploy to Kubernetes
```

See Helm charts in `helm/` directory for configuration.

## Project Structure

```
├── scripts/
│   ├── app.py                    # Flask web interface
│   ├── celery_tasks.py          # Celery task definitions
│   ├── build_dictionary.py      # Fetch word definitions
│   ├── build_assets.py          # Generate audio/images
│   ├── build_package.py         # Package for iOS
│   ├── convert_postgres_to_sqlite.py  # Convert DB for production
│   └── libs/
│       ├── dictionary.py        # Unified database interface
│       ├── sqlite_dictionary.py # SQLite implementation
│       ├── pg_dictionary.py     # PostgreSQL implementation
│       └── ...
├── helm/                         # Kubernetes Helm charts
├── Dockerfile                    # Container image
└── requirements.txt              # Python dependencies
```

## Environment Variables

Key configuration in `.env`:
- `DICTIONARY_API_KEY` - Merriam-Webster API key
- `OPENAI_API_KEY` - OpenAI API key
- `POSTGRES_CONNECTION` - PostgreSQL connection string (optional)
- `DATABASE_PATH` - SQLite database path (fallback)
- `STORAGE_DIRECTORY` - Base storage directory

See [.env.example](.env.example) or [.env.postgres.example](.env.postgres.example) for all options.

## License

Proprietary - All rights reserved