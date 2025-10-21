# Quick Start Guide - Restructured Flask App

## 🚀 Quick Start (Local Development)

### Prerequisites
- Python 3.13+
- Redis server
- FFmpeg and ImageMagick
- Environment variables set in `.env`

### 1. Install Dependencies
```bash
pip install -r requirements.txt
```

### 2. Start Redis
```bash
redis-server
```

### 3. Start Celery Worker (Terminal 1)
```bash
cd scripts
celery -A celery_tasks.celery_app worker --loglevel=info --concurrency=4
```

### 4. Start Flask App (Terminal 2)
```bash
cd scripts
python app.py
```

### 5. Access Web UI
Open browser to: http://localhost:5002

## 📋 Using the Web Interface

### Build Dictionary
1. Go to **Build Dictionary**
2. Upload a `.txt` file with one word per line
3. Submit - task starts in background
4. View progress on task status page

### Generate Assets
1. Go to **Build Assets**
2. Choose options (audio model, voice, image settings)
3. Submit - task starts in background
4. Monitor in **View Logs**

### Package Assets
1. Go to **Build Package**
2. Submit - packages all assets into zips
3. Download from **Download** page

### View Logs
1. Go to **📋 View Logs**
2. Click any log file to view contents
3. Download logs if needed

## 🐳 Docker/Kubernetes Deployment

### Build and Deploy
```bash
./upstart.sh
```

### Access in Cluster
```bash
# Get service info
kubectl get svc honeyspeak-builder

# Access via NodePort
http://<node-ip>:32003
```

### View Pod Logs
```bash
# Flask app logs
kubectl logs <pod-name> -c honeyspeak-builder

# Celery worker logs
kubectl logs <pod-name> -c celery-worker

# Follow logs
kubectl logs -f <pod-name> -c celery-worker
```

## 📊 Monitoring Tasks

### Task Status
- Each task returns a task ID
- Visit `/task_status/<task_id>` to see:
  - Status (PENDING, PROGRESS, SUCCESS, FAILURE)
  - Progress info (if available)
  - Results (when complete)

### Log Files
All tasks write to `logs/` directory:
- Format: `<task_name>_YYYYMMDD.log`
- View through web UI at `/logs`
- Download for offline analysis

### Example Log Names
- `fetch_and_process_word_20251020.log`
- `generate_all_assets_20251020.log`
- `package_all_assets_20251020.log`

## 🔧 Common Operations

### Process a Word List
```python
# Through web UI
1. Upload wordlist.txt
2. Submit
3. Monitor at /task_status/<task_id>

# Via Python (for testing)
from celery_tasks import process_wordlist
task = process_wordlist.delay(
    ['hello', 'world'],
    'Dictionary.sqlite',
    'your-api-key'
)
print(task.id)
```

### Generate All Assets
```python
from celery_tasks import generate_all_assets
task = generate_all_assets.delay(
    db_path='Dictionary.sqlite',
    output_dir='assets_hires',
    generate_audio=True,
    generate_images=True,
    audio_model='gpt-4o-mini-tts',
    audio_voice='alloy'
)
```

### Package Everything
```python
from celery_tasks import package_all_assets
task = package_all_assets.delay(
    db_path='Dictionary.sqlite',
    asset_dir='assets_hires',
    package_dir='assets'
)
```

## 🐛 Troubleshooting

### Celery Worker Won't Start
```bash
# Check Redis
redis-cli ping
# Should return PONG

# Check Python path
cd scripts
python -c "from celery_tasks import celery_app; print('OK')"

# Start with verbose logging
celery -A celery_tasks.celery_app worker --loglevel=debug
```

### Tasks Not Executing
1. Check Celery worker is running
2. Check Redis connection
3. View worker logs for errors
4. Check task-specific log files in `logs/`

### Import Errors
```bash
# Ensure you're in the right directory
cd /path/to/honeyspeak-builder/scripts

# Or set PYTHONPATH
export PYTHONPATH=$PYTHONPATH:/path/to/honeyspeak-builder/scripts
```

### No Logs Appearing
1. Check `logs/` directory exists
2. Check write permissions
3. Check task is actually running (not queued)
4. Look for errors in Celery worker output

## 📁 Directory Structure
```
honeyspeak-builder/
├── scripts/
│   ├── app.py              # Flask app
│   ├── celery_tasks.py     # Celery tasks
│   ├── libs/               # Library modules
│   ├── templates/          # HTML templates
│   └── static/             # CSS/JS
├── logs/                   # Task logs (auto-created)
├── Dictionary.sqlite       # Database
├── assets_hires/           # High-res assets
├── assets/                 # Packaged assets
├── Dockerfile
├── requirements.txt
└── helm/                   # Kubernetes deployment
```

## 🔑 Environment Variables

Required in `.env`:
```bash
DICTIONARY_API_KEY=your_merriam_webster_key
OPENAI_API_KEY=your_openai_key
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/0
DATABASE_PATH=Dictionary.sqlite
ASSET_DIRECTORY=assets_hires
PACKAGE_DIRECTORY=assets
FLASK_SECRET_KEY=your_secret_key
```

## 📚 Additional Resources

- Full Documentation: `docs/RESTRUCTURE_README.md`
- Changes Summary: `docs/CHANGES_SUMMARY.md`
- Original Instructions: `.github/copilot-instructions.md`

## 🎯 Next Steps

1. ✅ Start Redis and Celery worker
2. ✅ Start Flask app
3. ✅ Upload a small wordlist to test
4. ✅ Monitor logs and task status
5. ✅ Generate assets for test words
6. ✅ Package and download results
7. 🚀 Deploy to production

## 💡 Tips

- Start with a small wordlist (5-10 words) to test
- Use dryrun mode for testing without API calls
- Monitor Redis memory usage in production
- Set up log rotation for long-running deployments
- Use Flower for advanced Celery monitoring:
  ```bash
  pip install flower
  celery -A celery_tasks.celery_app flower
  # Visit http://localhost:5555
  ```

## 🆘 Getting Help

1. Check logs in `/logs` directory
2. Check Celery worker output
3. Review `docs/RESTRUCTURE_README.md`
4. Check task status at `/task_status/<task_id>`
5. Use verbose logging: `--loglevel=debug`
