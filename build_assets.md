# Asset Generation with Celery & Redis

This guide explains how to use `build_assets.py` with Celery and Redis to efficiently generate audio and image assets for your ESL dictionary project.

## Overview

- **Celery** is used to queue and process asset generation tasks (audio/image) in parallel.
- **Redis** acts as the message broker for Celery.
- All asset generation jobs are enqueued up front with the `--enqueue` flag and processed by worker processes (up to 5 concurrent tasks).
- Without `--enqueue`, the script runs synchronously (useful for debugging).

## Setup

### 1. Install Dependencies

Dependencies are in `requirements.txt`:
```bash
pip install -r requirements.txt
```

### 2. Start Redis Server

If you don't have Redis installed:
```bash
brew install redis  # macOS
sudo apt-get install redis-server  # Ubuntu/Debian
```
Start Redis:
```bash
redis-server
```

### 3. Start Celery Worker

From your project directory:
```bash
celery -A build_assets worker --loglevel=info --concurrency=5
```
- `-A build_assets` tells Celery to use the tasks defined in `build_assets.py`.
- `--concurrency=5` allows up to 5 tasks to run concurrently (adjustable based on your system).

### 4. Enqueue All Jobs

To enqueue all audio/image generation jobs:
```bash
python build_assets.py --enqueue
```
- This will queue all jobs for your dictionary.
- You can monitor progress in the Celery worker terminal.

## Example Workflow

1. **Start Redis server** (in terminal 1):
   ```bash
   redis-server
   ```

2. **Start Celery worker** (in terminal 2):
   ```bash
   celery -A build_assets worker --loglevel=info --concurrency=5
   ```

3. **Enqueue all jobs** (in terminal 3):
   ```bash
   python build_assets.py --enqueue
   ```

4. **Monitor progress**: Watch the Celery worker terminal for real-time updates.

## Usage Options

### Synchronous Mode (Without Celery)

For debugging or small batches:
```bash
python build_assets.py
```
This processes jobs sequentially without using Celery.

### Common Options

```bash
python build_assets.py --enqueue \
  --audio_model gpt-4o-mini-tts \
  --audio_voice alloy \
  --image_model gpt-image-1 \
  --image_size vertical \
  --outdir assets_hires \
  --verbosity 1
```

- `--no_audio`: Skip audio generation
- `--no_images`: Skip image generation
- `--audio_model`: Choose TTS model (gpt-4o-mini-tts, tts-1, tts-1-hd)
- `--audio_voice`: Choose voice (alloy, ash, ballad, coral, echo, fable, onyx, nova, sage, shimmer, verse)
- `--image_model`: Choose image model (gpt-image-1, dall-e-3, all-e-2)
- `--image_size`: Choose aspect ratio (square, vertical, horizontal)
- `--verbosity`: 0=silent, 1=progress bars, 2=detailed logs
- `--dryrun`: Show what would be done without actually doing it
- `--outdir`: Output directory (default: assets_hires)

## Advanced Usage

### Scaling Workers

Run multiple workers or increase concurrency:
```bash
# Run 2 workers with 5 concurrent tasks each (10 total)
celery -A build_assets worker --loglevel=info --concurrency=5 &
celery -A build_assets worker --loglevel=info --concurrency=5 &
```

### Monitor with Flower

Install and run Flower for a web dashboard:
```bash
pip install flower
celery -A build_assets flower
```
Then visit http://localhost:5555 for a web UI.

### Task Status

Check Celery task status:
```bash
celery -A build_assets inspect active
celery -A build_assets inspect scheduled
celery -A build_assets inspect stats
```

## Task Details

The script defines two Celery tasks:

1. **`generate_audio_task`**: Creates audio files using OpenAI TTS
   - Supports multiple models and voices
   - Skips existing files automatically
   - Returns status dict: `{"status": "success|skipped|error|dryrun", "file": "path"}`

2. **`generate_image_task`**: Creates images using OpenAI Image API
   - Supports multiple models and aspect ratios
   - Skips existing files automatically
   - Returns status dict: `{"status": "success|skipped|error|dryrun", "file": "path"}`

## Troubleshooting

### Redis Connection Error
```
Error: Connection refused to redis://localhost:6379
```
**Solution**: Make sure Redis is running (`redis-server`)

### No Workers Available
```
WARNING/MainProcess: Received unregistered task...
```
**Solution**: Start a Celery worker (`celery -A build_assets worker`)

### Rate Limiting
If you hit OpenAI API rate limits, tasks will fail. Consider:
- Reducing concurrency: `--concurrency=2`
- Adding retry logic (tasks will retry automatically on transient errors)
- Spreading jobs over time

## Notes

- All asset generation logic (audio/image) is handled by Celery tasks.
- The main script with `--enqueue` only enqueues jobs; workers do the actual processing.
- You can still run asset generation synchronously for debugging by omitting `--enqueue`.
- Workers load environment variables from `.env` automatically.
- Existing files are skipped to avoid re-generating assets.

## References
- [Celery Documentation](https://docs.celeryq.dev/en/stable/)
- [Redis Documentation](https://redis.io/)
- [OpenAI API Documentation](https://platform.openai.com/docs/)
