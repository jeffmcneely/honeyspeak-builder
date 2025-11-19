# Honeyspeak Builder

**Web service** for creating an ESL dictionary SQLite database with media assets for iOS deployment. All operations are performed through a Flask web interface with Celery background workers.

## Features

- 🌐 **Web-based interface** - All operations via browser at `http://localhost:5002`
- 📖 **Dictionary building** - Fetches word definitions from Merriam-Webster Learner's Dictionary API
- 🎵 **Audio generation** - Creates pronunciation audio using OpenAI TTS
- 🖼️ **Image generation** - Generates definition images using OpenAI/DALL-E
- 📦 **Asset packaging** - Packages assets for efficient iOS app consumption
- 🗄️ **Dual database support** - PostgreSQL (development) and SQLite (production)
- ⚡ **Concurrent processing** - Celery workers with RabbitMQ broker and Redis backend
- 📊 **Real-time monitoring** - Track task progress and view logs via web interface

## Architecture

- **Flask API** - Web interface for all operations (port 5002)
- **Celery Workers** - Background task processing (configurable concurrency)
- **RabbitMQ** - Task queue broker (port 5672)
- **Redis** - Result backend and caching (port 6379)
- **PostgreSQL** - Development database (better concurrency)
- **SQLite** - Production database (iOS deployment)

## Database Support

### PostgreSQL for Development
Use PostgreSQL during development for better concurrent access with multiple Celery workers. See [POSTGRES_MIGRATION.md](POSTGRES_MIGRATION.md) for setup instructions.

### SQLite for Production
Convert to SQLite for iOS deployment (single-file database with no WAL files).

### Backend Selection
- Always use PostgreSQL for user interaction and then repackage to SQLite for production.

## Quick Start

### Local Development (macOS)

1. **Setup environment**:
```bash
cp .env.example .env
# Edit .env with your API keys (DICTIONARY_API_KEY, OPENAI_API_KEY)
```

2. **Install dependencies**:
```bash
pip install -r requirements.txt
brew install ffmpeg imagemagick redis  # macOS
```

3. **Start services**:
```bash
# Start Redis
redis-server &

# Start Celery worker
celery -A scripts.celery_tasks worker --loglevel=info --concurrency=4 &

# Start Flask web service
python scripts/app.py
```

4. **Access web interface**:
```bash
# Open browser to http://localhost:5002
```

### Kubernetes Deployment (Production)

1. **Build and deploy**:
```bash
./upstart.sh build   # Build Docker image
./upstart.sh deploy  # Deploy to Kubernetes

# Port-forward to access locally
kubectl port-forward svc/honeyspeak-flask 5002:5002
```

2. **Access web interface**:
```bash
# Open browser to http://localhost:5002
```

## Web Interface Usage

All operations are performed through the web interface:

### 1. Build Dictionary
Navigate to `http://localhost:5002/build_dictionary`
- Upload word list file (e.g., `ae-3000-a1.txt`)
- Or POST single words to `/build_dictionary/single`
- Tasks automatically enqueued to Celery workers
- Monitor progress in real-time

### 2. Generate Assets
Navigate to `http://localhost:5002/build_assets`
- Select asset types (word audio, definition audio, definition images)
- Choose OpenAI models and voices from dropdown menus
- Click "Generate Assets"
- All generation runs as Celery tasks

### 3. Package for iOS
Navigate to `http://localhost:5002/build_package`
- Click "Start Packaging"
- Assets are transcoded/downscaled (ffmpeg/ImageMagick)
- Packaged into zip files via 16 parallel tasks [a-f, 0-9]
- Download SQLite DB + packages from `/download` page

### 4. Monitor Progress
Navigate to `http://localhost:5002/celery_status`
- View real-time task status
- See task logs and results
- Track API usage

### 5. Moderate Images
Navigate to `http://localhost:5002/moderator`
- Review definition images
- Mark conceptual vs. literal images
- Delete inappropriate images in batch

## Convert to Production SQLite

For iOS deployment, convert PostgreSQL to SQLite:
```bash
python scripts/convert_postgres_to_sqlite.py -o production.sqlite
```

This creates a clean SQLite file with no WAL/SHM files, suitable for iOS deployment.

## Project Structure

```
├── scripts/
│   ├── app.py                    # ✅ Flask web interface (ACTIVE)
│   ├── celery_tasks.py          # ✅ Celery task definitions (ACTIVE)
│   ├── moderator.py             # ✅ Asset moderation blueprint (ACTIVE)
│   ├── convert_postgres_to_sqlite.py  # ✅ Convert DB for production (ACTIVE)
│   │
│   ├── build_dictionary.py      # ❌ DEPRECATED - Use /build_dictionary web route
│   ├── build_assets.py          # ❌ DEPRECATED - Use /build_assets web route
│   ├── build_package.py         # ❌ DEPRECATED - Use /build_package web route
│   ├── build_icons.py           # ❌ DEPRECATED - Not integrated
│   ├── build_stories.py         # ❌ DEPRECATED - Empty placeholder
│   │
│   └── libs/
│       ├── dictionary.py        # Unified database interface
│       ├── sqlite_dictionary.py # SQLite implementation
│       ├── pg_dictionary.py     # PostgreSQL implementation
│       ├── dictionary_ops.py    # Dictionary operations (used by Celery tasks)
│       ├── asset_ops.py         # Asset generation (used by Celery tasks)
│       ├── package_ops.py       # Packaging operations (used by Celery tasks)
│       └── openai_helpers.py    # OpenAI API wrappers
├── helm/                         # Kubernetes Helm charts
├── Dockerfile                    # Container image
├── requirements.txt              # Python dependencies
├── DEPRECATED_SCRIPTS.md         # ⚠️ CLI script deprecation guide
└── POSTGRES_MIGRATION.md         # PostgreSQL setup guide
```

## ⚠️ Important: CLI Scripts Are Deprecated

**Do NOT use** the following CLI scripts:
- ❌ `build_dictionary.py` - Use `/build_dictionary` web route instead
- ❌ `build_assets.py` - Use `/build_assets` web route instead  
- ❌ `build_package.py` - Use `/build_package` web route instead
- ❌ `build_icons.py` - Not integrated into web service
- ❌ `build_stories.py` - Empty placeholder

**All functionality is now in the Flask web service.**

See [DEPRECATED_SCRIPTS.md](DEPRECATED_SCRIPTS.md) for detailed migration guide and rationale.

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