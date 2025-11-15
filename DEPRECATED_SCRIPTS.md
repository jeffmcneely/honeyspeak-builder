# Deprecated Scripts

As of the Kubernetes/Flask/Celery migration, the following Python CLI scripts are **deprecated** and should not be used. All functionality is now available through the Flask web service at `http://localhost:5002` (or your Kubernetes service endpoint).

## ❌ Deprecated CLI Scripts

### 1. `scripts/build_dictionary.py` - DEPRECATED
**Status:** Do not use  
**Replacement:** Flask API `/build_dictionary` route + Celery task `fetch_and_process_word`

**Why deprecated:**
- Processes words synchronously (slow for large word lists)
- No progress visibility or monitoring
- Cannot be paused/resumed
- No concurrent processing

**Use instead:**
- Web interface: Navigate to `http://localhost:5002/build_dictionary`
- Upload word list file via form
- Or POST to `/build_dictionary/single` with JSON: `{"word": "example", "function_label": "verb", "level": "a1"}`
- Tasks automatically enqueued to Celery workers
- Monitor progress in real-time via web interface

**Flask routes:**
- `GET/POST /build_dictionary` - Upload word list and enqueue tasks
- `POST /build_dictionary/single` - Process single word
- `GET /celery_status` - Monitor task progress

**Celery tasks:**
- `fetch_and_process_word(word, function_label, level, db_path, api_key, usage_file)` - Fetches word from API and stores in database

---

### 2. `scripts/build_assets.py` - DEPRECATED
**Status:** Do not use  
**Replacement:** Flask API `/build_assets` route + Celery tasks for audio/image generation

**Why deprecated:**
- Even with `--enqueue` flag, still requires CLI invocation
- No web-based progress monitoring
- Harder to configure asset types/models via command line
- No visual interface for selecting asset generation options

**Use instead:**
- Web interface: Navigate to `http://localhost:5002/build_assets`
- Select asset types (word audio, definition audio, definition images)
- Choose OpenAI models and voices from dropdown menus
- All generation runs as Celery tasks automatically
- Monitor progress via web interface

**Flask routes:**
- `GET/POST /build_assets` - Configure and enqueue asset generation tasks
- `GET /celery_status` - Monitor task progress

**Celery tasks:**
- `generate_word_audio_task(word, uuid, db_path, asset_dir, model, voice)` - Generate word pronunciation audio
- `generate_definition_audio_task(definition, uuid, def_id, db_path, asset_dir, model, voice)` - Generate definition audio
- `generate_definition_image_task(definition, uuid, def_id, db_path, asset_dir, model, size)` - Generate definition images

---

### 3. `scripts/build_package.py` - DEPRECATED
**Status:** Do not use  
**Replacement:** Flask API `/build_package` route + Celery task `package_all_assets`

**Why deprecated:**
- Processes assets sequentially (slow for large databases)
- No parallel encoding/packaging
- Manual invocation required
- No web-based download interface

**Use instead:**
- Web interface: Navigate to `http://localhost:5002/build_package`
- Click "Start Packaging" button
- Tasks automatically transcode/downscale assets (ffmpeg/ImageMagick)
- Creates zip packages (16 parallel tasks for a-f, 0-9)
- Download SQLite DB + zip packages from `/download` page

**Flask routes:**
- `GET/POST /build_package` - Start packaging process
- `GET /download` - List and download packaged files
- `GET /download_file/<filename>` - Download specific file

**Celery tasks:**
- `package_all_assets(db_path, asset_dir, package_dir)` - Orchestrates packaging (launches 16 parallel tasks)
- `package_asset_group(letter, db_path, asset_dir, package_dir)` - Packages all assets for specific letter/number

---

### 4. `scripts/build_icons.py` - DEPRECATED (partially)
**Status:** Not integrated into web service yet  
**Replacement:** None currently

**Why deprecated:**
- Very specialized utility for icon generation
- Not part of standard workflow
- Uses ImageMagick to generate icons from images

**Status:** This script is not currently integrated into the Flask/Celery system. If icon generation is needed:
1. Integrate into web service as new route (e.g., `/build_icons`)
2. Create Celery task for parallel icon generation
3. Or keep as standalone utility if rarely used

---

### 5. `scripts/build_stories.py` - DEPRECATED
**Status:** Empty file (placeholder)  
**Replacement:** Flask API `/build_stories` route exists (check `app.py`)

**Why deprecated:**
- File is currently empty
- Functionality likely intended for future story/paragraph system
- Any story-related features should be implemented via Flask API + Celery tasks

---

## ✅ Scripts Still in Use

### `scripts/app.py` - **ACTIVE**
Flask web application - main entry point for all operations.

**Start with:**
```bash
python scripts/app.py
# Or via Kubernetes: kubectl port-forward svc/honeyspeak-flask 5002:5002
```

### `scripts/celery_tasks.py` - **ACTIVE**
Defines all Celery background tasks for dictionary building, asset generation, and packaging.

**Start workers with:**
```bash
celery -A scripts.celery_tasks worker --loglevel=info --concurrency=4
# Or via Kubernetes: Celery workers run automatically in separate pods
```

### `scripts/moderator.py` - **ACTIVE**
Flask blueprint for asset moderation (review/delete conceptual images).

**Access via:**
```bash
http://localhost:5002/moderator
```

### `scripts/convert_postgres_to_sqlite.py` - **ACTIVE**
Exports PostgreSQL database to SQLite for iOS deployment.

**Usage:**
```bash
python scripts/convert_postgres_to_sqlite.py -o production.sqlite
```

**Important:** This script is essential for production deployment. PostgreSQL is used during build/development; SQLite is required for iOS client.

---

## Migration Guide

### Old Workflow (CLI - DEPRECATED):
```bash
# ❌ Don't do this anymore
python scripts/build_dictionary.py dictionaries/ae-3000-a1.txt
python scripts/build_assets.py --enqueue --outdir assets_hires
python scripts/build_package.py --outdir assets_hires
```

### New Workflow (Web Service):
```bash
# ✅ Do this instead

# 1. Start services (one-time setup)
./upstart.sh  # Starts Flask, Celery, RabbitMQ, Redis via Kubernetes
kubectl port-forward svc/honeyspeak-flask 5002:5002

# 2. Use web interface
# Navigate to http://localhost:5002

# 3. Build dictionary
#    → Go to /build_dictionary
#    → Upload word list file (e.g., ae-3000-a1.txt)
#    → Tasks enqueued automatically

# 4. Generate assets
#    → Go to /build_assets
#    → Select asset types and models
#    → Click "Generate Assets"

# 5. Package for iOS
#    → Go to /build_package
#    → Click "Start Packaging"
#    → Download files from /download

# 6. Monitor progress
#    → Go to /celery_status
#    → View real-time task status and logs
```

---

## Why This Migration Happened

The CLI scripts were deprecated because:

1. **No concurrency control:** Each script ran independently with no coordination
2. **Poor visibility:** No way to monitor progress or view logs without tailing files
3. **No fault tolerance:** If a script crashed, you lost all progress
4. **Hard to deploy:** Required manual invocation on server
5. **No web interface:** Not user-friendly for non-developers
6. **Resource inefficiency:** No way to limit concurrent API calls or workers

The Flask/Celery architecture provides:

1. **Web-based interface:** Accessible from any browser
2. **Task queuing:** Celery manages all background jobs with priorities
3. **Concurrent processing:** Multiple workers process tasks in parallel
4. **Progress monitoring:** Real-time status updates via web interface
5. **Fault tolerance:** Failed tasks can be retried automatically
6. **Structured logging:** All tasks log to `logs/` directory with timestamps
7. **Resource management:** Control worker concurrency, memory limits, etc.
8. **Kubernetes deployment:** Scales horizontally, health checks, rolling updates

---

## For AI Agents

When asked to:
- "Build a dictionary" → Use Flask API `/build_dictionary`, NOT `build_dictionary.py`
- "Generate audio/images" → Use Flask API `/build_assets`, NOT `build_assets.py`
- "Package assets" → Use Flask API `/build_package`, NOT `build_package.py`
- "Run the moderator" → Use Flask API at `/moderator`, NOT standalone script
- "Check task status" → Use Flask API `/celery_status`, NOT log files directly

**The only valid standalone script invocations are:**
- `python scripts/app.py` - Start Flask web service
- `python scripts/convert_postgres_to_sqlite.py -o production.sqlite` - Export to SQLite for iOS
- `celery -A scripts.celery_tasks worker` - Start Celery workers (or use Kubernetes deployment)

Everything else should go through the Flask web interface.
