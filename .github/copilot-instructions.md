# AI agent quickstart for honeyspeak-builder

This repo builds an ESL dictionary SQLite DB and related media assets (audio/image), then packages them for an iOS client. Core concerns: SQLite schema and helpers, batch API ingestion, asset generation via OpenAI, background processing with Celery/Redis, and packaging rules.

## Architecture and data flow
- Source words ➜ `build_dictionary.py` fetches Merriam-Webster Learner’s JSON via `DICTIONARY_API_KEY` ➜ persists to SQLite via `libs/sqlite_dictionary.py`.
- Media assets ➜ `build_assets.py` generates TTS audio and definition images via OpenAI (`OPENAI_API_KEY`), either synchronously or via Celery/Redis workers.
- Packaging ➜ `build_package.py` transcodes and downscales assets (ffmpeg/ImageMagick), writes zip packages, and records asset locations in the DB for the app to consume.

## Key files and contracts
- `libs/sqlite_dictionary.py` is authoritative for the schema and DB API.
  - PRAGMA: journal_mode=DELETE (avoid WAL/SHM files); foreign_keys=ON with CASCADE deletes.
  - Tables: `words(uuid PRIMARY KEY)`, `shortdef(UNIQUE(uuid, definition))`, `external_assets(UNIQUE(uuid, assetgroup, sid))`.
  - Asset conventions:
    - Word audio: `word_{uuid}_0.{ext}` with `assetgroup="word"`, `sid=0`.
    - Definition audio: `shortdef_{uuid}_{id}.{ext}` with `assetgroup="shortdef"`, `sid={id}`.
    - Definition image: `image_{uuid}_{id}.{ext}` with `assetgroup="image"`, `sid={id}`.
- `sqlite_schema.md` documents the schema; if it conflicts with code, follow `libs/sqlite_dictionary.py`.
  - Note: code stores `external_assets.package` as a two-character text id (e.g., `a0`); packaging may exceed two chars if counts grow.
- `build_assets.py` patterns:
  - Strip brace-tagged markup before generation (`strip_tags` removes `{...}`).
  - Skips existing files; supports `--dryrun` and verbosity 0/1/2. 400 errors log to `errors.txt` with input context.
  - TTS models: `gpt-4o-mini-tts|tts-1|tts-1-hd`; voices: alloy|ash|…|verse. Images: `gpt-image-1|dall-e-3|all-e-2` with square/vertical/horizontal sizes.
- `build_package.py`:
  - Audio ➜ low-bitrate mono AAC via ffmpeg; Images ➜ downscale/HEIF via ImageMagick. Result files prefixed with `low_`.
  - Zips split by size (~100MB). `store_file` returns a package id like `{first_letter}{n}` and records it in DB.

## Workflows (commands assume macOS zsh)
- Env: copy `.env.example` ➜ `.env`; set `DICTIONARY_API_KEY`, `OPENAI_API_KEY`.
- Install deps: `pip install -r requirements.txt` plus system: `brew install ffmpeg imagemagick redis`.
- Build DB from a word list:
  ```bash
  python build_dictionary.py noun10.txt Dictionary.sqlite
  ```
- Generate assets synchronously (debug-friendly):
  ```bash
  python build_assets.py --verbosity 1 --outdir assets_hires
  ```
- Use Celery/Redis for parallel jobs (see `build_assets.md`):
  ```bash
  redis-server &
  celery -A build_assets worker --loglevel=info --concurrency=5
  python build_assets.py --enqueue --outdir assets_hires
  ```
- Package for app consumption and record assets into DB:
  ```bash
  python build_package.py --outdir assets_hires --packagedir packages --dictionary Dictionary.sqlite
  ```
  Optional copy to iOS bundle via `IOS_PATH` env.

## Conventions and gotchas
- Always use `SQLiteDictionary` methods (do not hand-roll SQL) to preserve constraints/uniques.
- `add_shortdef` dedupes on `(uuid, definition)`; avoid re-adding identical defs.
- Asset id mapping is strict: use the correct `assetgroup` and `sid` or packaging lookups will fail.
- `errors.txt` captures OpenAI 400s with the exact input—use it to prune/clean problematic definitions.
- Large media folders (`assets_hires`, `assets`, `icons`, `.heif`) are git-ignored by design.
- `build_icons.py` mass-generates square app icons from `assets_hires` originals using ImageMagick.
- AWS helpers in `libs/helper.py` (S3, Polly) exist but aren’t wired into main flows; treat them as optional utilities.

## When extending
- New asset types: mirror the patterns above and extend `external_assets` consumers; keep filename and `(assetgroup, sid)` consistent.
- Schema changes: update `libs/sqlite_dictionary.py` first; keep `sqlite_schema.md` in sync.

If anything here seems off or incomplete (e.g., package id length expectations, additional iOS export steps), tell me and I’ll refine this doc.