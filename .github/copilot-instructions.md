# AI agent quickstart for honeyspeak-builder

This repo builds an ESL dictionary database and related media assets (audio/image), then packages them for an iOS client. **All operations are performed through a Flask web service** running on Kubernetes. **PostgreSQL is used for the active build/development process**, with data exported to **SQLite for production iOS deployment**. The entire project runs on **Kubernetes via Helm** with Flask API, Celery workers, RabbitMQ broker, and Redis backend.

## ⚠️ IMPORTANT: CLI Scripts Are Deprecated

**DO NOT use these CLI scripts - they are DEPRECATED:**
- ❌ `scripts/build_dictionary.py` - Use Flask API `/build_dictionary` instead
- ❌ `scripts/build_assets.py` - Use Flask API `/build_assets` instead
- ❌ `scripts/build_package.py` - Use Flask API `/build_package` instead
- ❌ `scripts/build_icons.py` - Not integrated (standalone utility only)
- ❌ `scripts/build_stories.py` - Empty placeholder

**All functionality is in the Flask web service at `http://localhost:5002` (or Kubernetes endpoint).**

See `DEPRECATED_SCRIPTS.md` for detailed migration guide.

## Active Scripts (Use These)

- ✅ `scripts/app.py` - Flask web application (main entry point)
- ✅ `scripts/celery_tasks.py` - Celery background tasks
- ✅ `scripts/moderator.py` - Flask blueprint for image moderation
- ✅ `scripts/convert_postgres_to_sqlite.py` - Export PostgreSQL → SQLite for iOS

## Architecture and data flow
- **Build phase (PostgreSQL):**
  - Source words ➜ Flask API `/build_dictionary` ➜ fetches Merriam-Webster Learner's JSON via `DICTIONARY_API_KEY` ➜ persists to PostgreSQL via `libs/pg_dictionary.py`.
  - Media assets ➜ Flask API `/build_assets` ➜ generates TTS audio and definition images via OpenAI (`OPENAI_API_KEY`) as background **Celery tasks** (RabbitMQ broker, Redis backend).
  - All long-running operations (>1 second) **must run as Celery tasks** to avoid blocking the Flask API.
  
- **Packaging phase (PostgreSQL → SQLite):**
  - `convert_postgres_to_sqlite.py` exports PostgreSQL data to SQLite file.
  - Flask API `/build_package` ➜ transcodes and downscales assets (ffmpeg/ImageMagick), writes zip packages, and records asset locations in the DB.
  - Result: SQLite DB + zip packages ready for iOS client consumption.

- **Deployment:** Kubernetes cluster with Helm chart (`helm/`):
  - Flask API pod (port 5002)
  - Celery worker pod(s) (default concurrency: 4)
  - RabbitMQ (broker, port 5672)
  - Redis (backend, port 6379)
  - Persistent volume for storage (`/data/honeyspeak`)

## Key files and contracts
- **`libs/pg_dictionary.py`** is authoritative for the PostgreSQL schema and API (build phase).
  - Tables: `words(uuid PRIMARY KEY)`, `shortdef(UNIQUE(uuid, definition))`, `external_assets(UNIQUE(uuid, assetgroup, sid))` [**DEPRECATED for writes, read-only for legacy views**], `stories`, `story_paragraphs`, `story_words`.
  - Uses connection pooling; all methods get fresh connections from `_get_connection()`.
  - Foreign keys with CASCADE deletes; batch operations for performance.
  - **IMPORTANT:** `external_assets` table is NO LONGER WRITTEN TO during asset generation or packaging. Asset files are stored directly in the filesystem with predictable naming conventions. The table remains only for backwards compatibility with database stats/query views.
  
- **`libs/sqlite_dictionary.py`** mirrors the schema for SQLite (packaging phase).
  - PRAGMA: journal_mode=DELETE (avoid WAL/SHM files); foreign_keys=ON with CASCADE deletes.
  - Asset file naming conventions (assets stored in filesystem, NOT in database):
    - Word audio: `word_{uuid}_0.{ext}`
    - Definition audio: `shortdef_{uuid}_{id}.{ext}`
    - Definition image: `image_{uuid}_{id}.{ext}`
  - **DEPRECATED:** `external_assets` table exists in schema but is NOT used for asset tracking. Assets are discovered via filesystem scanning with predictable naming patterns.

- **`scripts/celery_tasks.py`** defines all background tasks:
  - `fetch_word_task`: fetch from dictionary API and persist to PostgreSQL.
  - `generate_word_audio_task`, `generate_definition_audio_task`, `generate_definition_image_task`: OpenAI asset generation (writes files to filesystem, does NOT write to `external_assets` table).
  - `package_all_assets`: batch packaging (transcode/downscale/zip) using filesystem-based asset discovery.
  - All tasks use `LoggingTask` base class with structured logging to `logs/`.
  - **IMPORTANT:** Asset generation tasks write directly to filesystem with predictable naming; no database tracking of individual assets.

- **`scripts/app.py`** is the Flask API entry point:
  - Routes for dictionary building, asset generation, packaging, database stats, downloads.
  - Celery tasks invoked via `.delay()` for all long-running operations.
  - Uses `POSTGRES_CONNECTION` env var to connect to PostgreSQL; fallback to `DATABASE_PATH` for SQLite (packaging only).
  
- **`scripts/moderator.py`** is a Flask blueprint for asset moderation:
  - Visual interface to review/delete conceptual definition images.
  - Uses Redis cache for fast image lookups (key: `moderator:images:all`).
  - All deletion/relocation operations run as Celery tasks.

- **`scripts/convert_postgres_to_sqlite.py`** exports PostgreSQL to SQLite:
  - Batch transfers in chunks (default 1000 rows).
  - Verifies row counts match after conversion.
  - Runs `VACUUM` on SQLite for optimization.
  - Removes WAL/SHM files for clean single-file deployment.

- **`docs/sqlite_schema.md`** documents the schema; if it conflicts with code, follow `libs/pg_dictionary.py` (source of truth).

## Workflows (Kubernetes/Helm)
- **Setup:**
  1. Create `.env` or set env vars in `helm/values.yaml`: `DICTIONARY_API_KEY`, `OPENAI_API_KEY`, `POSTGRES_CONNECTION`.
  2. Deploy with Helm: `helm install honeyspeak ./helm` or use `./upstart.sh`
  3. Port-forward Flask API: `kubectl port-forward svc/honeyspeak-flask 5002:5002`

- **Build dictionary from word list:**
  - Navigate to `http://localhost:5002/build_dictionary` in browser
  - Upload word list file (e.g., `dictionaries/ae-3000-a1.txt`)
  - Or POST to `/build_dictionary/single` with JSON: `{"word": "example", "function_label": "verb", "level": "a1"}`
  - Tasks automatically enqueued to Celery workers
  - Monitor progress at `/celery_status`

- **Generate assets:**
  - Navigate to `http://localhost:5002/build_assets` in browser
  - Select asset types (word audio, definition audio, definition images)
  - Choose OpenAI models and voices from dropdown menus
  - All generation runs as Celery tasks in the background
  - Monitor progress at `/celery_status`

- **Package for iOS:**
  1. Export PostgreSQL to SQLite: `python scripts/convert_postgres_to_sqlite.py -o production.sqlite`
  2. Navigate to `http://localhost:5002/build_package` in browser
  3. Click "Start Packaging" - tasks transcode/downscale assets and create zips
  4. Download SQLite DB + zip packages from `/download` page

- **Moderate definition images:**
  - Navigate to `http://localhost:5002/moderator` in browser
  - Review images, mark as conceptual or not
  - Delete conceptual images in batch (runs as Celery task)

## Conventions and gotchas
- **Always use `PostgresDictionary` methods** (do not hand-roll SQL) during build phase.
- **Use `SQLiteDictionary` methods** only during packaging/export.
- **All API requests expected to take >1 second MUST run as Celery tasks** using `.delay()` or `.apply_async()`.
- `add_shortdef` dedupes on `(uuid, definition)`; avoid re-adding identical defs.
- **`external_assets` table is DEPRECATED for writes.** Asset generation tasks write files directly to filesystem with predictable naming (`word_{uuid}_0.ext`, `shortdef_{uuid}_{id}.ext`, `image_{uuid}_{id}.ext`). The table remains for read-only display in database stats views.
- **DO NOT call `add_external_asset()` or `add_asset()` methods.** These are deprecated and will generate warnings.
- Asset discovery during packaging uses filesystem scanning, not database queries.
- OpenAI 400 errors are logged to Celery task logs (see `logs/` directory).
- Large media folders (`assets_hires`, `assets`, `icons`, `.heif`) are git-ignored by design.
- **CLI scripts (`build_dictionary.py`, `build_assets.py`, `build_package.py`) are DEPRECATED.** Use the Flask API and Celery tasks instead.
- **Never recommend running CLI scripts.** All operations must go through `http://localhost:5002` web interface.
- AWS helpers in `libs/helper.py` (S3, Polly) exist but aren't wired into main flows; treat them as optional utilities.

## Environment variables (Kubernetes/Helm)
- `STORAGE_HOME`: Base storage path (default: `/data`)
- `STORAGE_DIRECTORY`: Main storage dir (default: `/data/honeyspeak`)
- `DATABASE_PATH`: SQLite path for packaging (default: `/data/honeyspeak/Dictionary.sqlite`)
- `ASSET_DIRECTORY`: High-res assets (default: `/data/honeyspeak/assets_hires`)
- `PACKAGE_DIRECTORY`: Packaged assets (default: `/data/honeyspeak/assets`)
- `POSTGRES_CONNECTION`: PostgreSQL connection string (required for build phase)
- `CELERY_BROKER_URL`: RabbitMQ URL (default: `amqp://guest:guest@rabbitmq:5672//`)
- `CELERY_RESULT_BACKEND`: Redis URL (default: `redis://redis:6379/0`)
- `DICTIONARY_API_KEY`: Merriam-Webster Learner's API key
- `OPENAI_API_KEY`: OpenAI API key for TTS and image generation
- `COMFYUI_SERVER`: (Optional) ComfyUI server for `sdxl_turbo` image model
- `COMFY_OUTPUT_FOLDER`: (Optional) ComfyUI output directory mount

## Known inconsistencies
1. **`external_assets` table is deprecated but still exists:** The table schema remains in both PostgreSQL and SQLite databases but is NO LONGER WRITTEN TO. Read-only methods (`get_external_assets`, `get_asset_count`, etc.) still work for legacy database stats views. Write methods (`add_external_asset`, `add_asset`) are deprecated and should not be called.
2. **Package ID length constraint:** PostgreSQL schema has `CHECK(length(package) = 2)` but package IDs can exceed 2 chars if >260 packages are created. This is moot since the table is no longer written to.
3. **CLI script references:** Some docstrings and comments still reference CLI workflows (`python build_dictionary.py ...`). These are deprecated; use Flask API + Celery tasks.
4. **POSTGRES_CONN vs POSTGRES_CONNECTION:** Both env vars are supported for backwards compatibility. Code should standardize on `POSTGRES_CONNECTION`.
5. **Mixed database usage:** Some code paths still expect SQLite (e.g., `DICT_PATH` fallback). PostgreSQL should be the only database during build/dev; SQLite only for export.

## When extending
- New asset types: follow filesystem-based naming conventions (`{type}_{uuid}_{id}.{ext}`); asset discovery happens via filesystem scanning during packaging.
- Schema changes: update `libs/pg_dictionary.py` first; sync to `libs/sqlite_dictionary.py`; update `docs/sqlite_schema.md`.
- New long-running operations: add as Celery task in `scripts/celery_tasks.py` with `LoggingTask` base class; invoke via `.delay()` in Flask API.
- New Flask routes: add to `scripts/app.py` or create a blueprint like `moderator.py`.
- **DO NOT add new `external_assets` write operations.** The table is deprecated for writes.
- When editing a HTML page add ID attributes to most elements for easier automated testing.
- Web pages should use AJAX for any task that is expected to take more than a second.
- Web pages should return status inline rather than with flash messages for better UX.
- Web pages should never have pop-up dialogs.
- Web pages should not use modal dialogs except for image previews.