import os
import zipfile
from pathlib import Path
from flask import Flask, request, render_template, redirect, url_for, send_from_directory, flash, jsonify, send_file
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Import celery app from celery_tasks
from celery_tasks import celery_app as celery

# Use templates and static folders
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
LOGS_DIR = Path(__file__).parent.parent / "logs"

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)

app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersecret")

# Paths
BASE_DIR = Path(__file__).parent.parent
STORAGE_HOME = os.environ.get("STORAGE_HOME", str(BASE_DIR))
STORAGE_DIRECTORY = os.environ.get("STORAGE_DIRECTORY", str(BASE_DIR / "honeyspeak"))
DICT_PATH = os.environ.get("DATABASE_PATH", str(Path(STORAGE_DIRECTORY) / "Dictionary.sqlite"))
ASSET_DIR = os.environ.get("ASSET_DIRECTORY", str(Path(STORAGE_DIRECTORY) / "assets_hires"))
PACKAGE_DIR = os.environ.get("PACKAGE_DIRECTORY", str(Path(STORAGE_DIRECTORY) / "assets"))
WORDLIST_DIR = BASE_DIR

# Ensure required directories exist
LOGS_DIR.mkdir(exist_ok=True)
Path(STORAGE_DIRECTORY).mkdir(parents=True, exist_ok=True)
Path(ASSET_DIR).mkdir(parents=True, exist_ok=True)
Path(PACKAGE_DIR).mkdir(parents=True, exist_ok=True)

# Jinja2 custom filters
@app.template_filter('filesizeformat')
def filesizeformat(num):
    """Format file size in human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if abs(num) < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"

@app.template_filter('timestamp_to_datetime')
def timestamp_to_datetime(timestamp):
    """Convert Unix timestamp to readable datetime."""
    from datetime import datetime
    return datetime.fromtimestamp(timestamp).strftime('%Y-%m-%d %H:%M:%S')

# Utility: List package files
def list_package_files():
    pkg_dir = BASE_DIR / PACKAGE_DIR
    if not pkg_dir.exists():
        return []
    return [f for f in pkg_dir.glob("package_*.zip") if f.is_file()]

def list_db_files():
    return [f for f in BASE_DIR.glob("*.sqlite") if f.is_file()]

def list_log_files():
    """List all log files in logs directory."""
    if not LOGS_DIR.exists():
        return []
    return sorted([f for f in LOGS_DIR.glob("*.log") if f.is_file()], key=lambda x: x.stat().st_mtime, reverse=True)

# Routes
@app.route("/")
def index():
    return render_template("index.html")

@app.route("/build_dictionary", methods=["GET", "POST"])
def build_dictionary():
    if request.method == "POST":
        wordlist = request.files.get("wordlist")
        db_path = request.form.get("db_path", DICT_PATH)
        
        if not wordlist:
            flash("No wordlist uploaded", "error")
            return redirect(url_for("build_dictionary"))
        
        # Read wordlist
        wl_path = BASE_DIR / secure_filename(wordlist.filename)
        wordlist.save(wl_path)
        
        try:
            with open(wl_path, "r") as f:
                words = [w.strip() for w in f.read().splitlines() if w.strip()]
        except Exception as e:
            flash(f"Error reading wordlist: {e}", "error")
            return redirect(url_for("build_dictionary"))
        
        # Get API key
        api_key = os.getenv("DICTIONARY_API_KEY")
        if not api_key:
            flash("DICTIONARY_API_KEY not set in environment", "error")
            return redirect(url_for("build_dictionary"))
        
        # Enqueue task using send_task with full task name
        task = celery.send_task("scripts.celery_tasks.process_wordlist", args=[words, db_path, api_key])
        flash(f"Dictionary build started with {len(words)} words (task id: {task.id})", "info")
        return redirect(url_for("task_status", task_id=task.id))
    
    return render_template("build_dictionary.html", db_path=DICT_PATH)


@app.route("/build_dictionary/single", methods=["POST"])
def build_dictionary_single():
    """Process a single word from the dictionary API."""
    word = request.form.get("word", "").strip().lower()
    db_path = request.form.get("db_path", DICT_PATH)
    
    if not word:
        flash("Please enter a word", "error")
        return redirect(url_for("build_dictionary"))
    
    # Get API key
    api_key = os.getenv("DICTIONARY_API_KEY")
    if not api_key:
        flash("DICTIONARY_API_KEY not set in environment", "error")
        return redirect(url_for("build_dictionary"))
    
    # Enqueue task for single word using send_task with full task name
    task = celery.send_task("scripts.celery_tasks.fetch_and_process_word", args=[word, db_path, api_key])
    flash(f"Fetching word '{word}' (task id: {task.id})", "info")
    return redirect(url_for("task_status", task_id=task.id))

@app.route("/build_assets", methods=["GET", "POST"])
def build_assets():
    # All options from build_assets.py
    TTS_MODELS = ["gpt-4o-mini-tts", "tts-1", "tts-1-hd"]
    VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse"]
    IMAGE_MODELS = ["dall-e-2", "dall-e-3", "gpt-image-1"]
    IMAGE_SIZES = ["square", "vertical", "horizontal"]
    
    if request.method == "POST":
        # Parse options
        generate_audio = request.form.get("generate_audio", "on") == "on"
        generate_images = request.form.get("generate_images", "on") == "on"
        audio_model = request.form.get("audio_model", "gpt-4o-mini-tts")
        audio_voice = request.form.get("audio_voice", "alloy")
        image_model = request.form.get("image_model", "gpt-image-1")
        image_size = request.form.get("image_size", "vertical")
        output_dir = request.form.get("outdir", ASSET_DIR)
        db_path = request.form.get("db_path", DICT_PATH)
        
        # Enqueue task using send_task with full task name
        task = celery.send_task(
            "scripts.celery_tasks.generate_all_assets",
            kwargs={
                "db_path": db_path,
                "output_dir": output_dir,
                "generate_audio": generate_audio,
                "generate_images": generate_images,
                "audio_model": audio_model,
                "audio_voice": audio_voice,
                "image_model": image_model,
                "image_size": image_size
            }
        )
        flash(f"Assets build started (task id: {task.id})", "info")
        return redirect(url_for("task_status", task_id=task.id))
    
    return render_template(
        "build_assets.html",
        tts_models=TTS_MODELS,
        voices=VOICES,
        image_models=IMAGE_MODELS,
        image_sizes=IMAGE_SIZES,
        outdir=ASSET_DIR
    )

@app.route("/build_package", methods=["GET", "POST"])
def build_package():
    if request.method == "POST":
        asset_dir = request.form.get("asset_dir", ASSET_DIR)
        package_dir = request.form.get("packagedir", PACKAGE_DIR)
        db_path = request.form.get("db_path", DICT_PATH)
        
        # Enqueue task using send_task with full task name
        task = celery.send_task(
            "scripts.celery_tasks.package_all_assets",
            args=[db_path, asset_dir, package_dir]
        )
        flash(f"Packaging started (task id: {task.id})", "info")
        return redirect(url_for("task_status", task_id=task.id))
    
    return render_template("build_package.html", outdir=PACKAGE_DIR, asset_dir=ASSET_DIR)

@app.route("/download")
def download():
    db_files = list_db_files()
    pkg_files = list_package_files()
    return render_template("download.html", db_files=db_files, pkg_files=pkg_files, package_dir=PACKAGE_DIR)

@app.route("/download_file/<path:filename>")
def download_file(filename):
    # Serve from base dir or package dir
    fpath = BASE_DIR / filename
    if fpath.exists():
        return send_from_directory(BASE_DIR, filename, as_attachment=True)
    pkg_path = BASE_DIR / PACKAGE_DIR / filename
    if pkg_path.exists():
        return send_from_directory(BASE_DIR / PACKAGE_DIR, filename, as_attachment=True)
    flash("File not found", "error")
    return redirect(url_for("download"))

@app.route("/task_status/<task_id>")
def task_status(task_id):
    res = celery.AsyncResult(task_id)
    status = res.status
    result = res.result if res.ready() else None
    
    # Get task progress if available
    progress = None
    if res.state == 'PROGRESS':
        progress = res.info
    
    return render_template("task_status.html", task_id=task_id, status=status, result=result, progress=progress)


@app.route("/logs")
def logs():
    """Display list of log files."""
    log_files = list_log_files()
    return render_template("logs.html", log_files=log_files)


@app.route("/logs/<filename>")
def view_log(filename):
    """View a specific log file."""
    log_path = LOGS_DIR / secure_filename(filename)
    
    if not log_path.exists() or not log_path.is_file():
        flash("Log file not found", "error")
        return redirect(url_for("logs"))
    
    try:
        with open(log_path, "r") as f:
            content = f.read()
        return render_template("log_viewer.html", filename=filename, content=content)
    except Exception as e:
        flash(f"Error reading log file: {e}", "error")
        return redirect(url_for("logs"))


@app.route("/logs/<filename>/download")
def download_log(filename):
    """Download a log file."""
    log_path = LOGS_DIR / secure_filename(filename)
    
    if not log_path.exists() or not log_path.is_file():
        flash("Log file not found", "error")
        return redirect(url_for("logs"))
    
    return send_file(log_path, as_attachment=True, download_name=filename)


@app.route("/db_stats", methods=["GET", "POST"])
def db_stats():
    """Show database statistics and allow querying by word."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent / "libs"))
    from sqlite_dictionary import SQLiteDictionary
    
    db_path = request.args.get("db_path", DICT_PATH)
    query_word = request.args.get("word", "").strip().lower()
    
    stats = {}
    word_data = None
    
    try:
        db = SQLiteDictionary(db_path)
        
        # Get row counts for each table
        cursor = db.connection.cursor()
        
        # Words count
        cursor.execute("SELECT COUNT(*) FROM words")
        stats["words"] = cursor.fetchone()[0]
        
        # Shortdef count
        cursor.execute("SELECT COUNT(*) FROM shortdef")
        stats["shortdef"] = cursor.fetchone()[0]
        
        # External assets count
        cursor.execute("SELECT COUNT(*) FROM external_assets")
        stats["external_assets"] = cursor.fetchone()[0]
        
        # Stories count (if exists)
        try:
            cursor.execute("SELECT COUNT(*) FROM stories")
            stats["stories"] = cursor.fetchone()[0]
        except:
            stats["stories"] = 0
        
        # Story paragraphs count (if exists)
        try:
            cursor.execute("SELECT COUNT(*) FROM story_paragraphs")
            stats["story_paragraphs"] = cursor.fetchone()[0]
        except:
            stats["story_paragraphs"] = 0
        
        # If querying a specific word
        if query_word:
            # Get word(s) matching the query
            cursor.execute("SELECT word, functional_label, uuid, flags FROM words WHERE word = ?", (query_word,))
            words_rows = cursor.fetchall()
            
            if words_rows:
                word_data = []
                for word_row in words_rows:
                    word_info = {
                        "word": word_row[0],
                        "functional_label": word_row[1],
                        "uuid": word_row[2],
                        "flags": word_row[3],
                        "shortdefs": [],
                        "external_assets": []
                    }
                    
                    # Get shortdefs for this UUID
                    cursor.execute("SELECT id, definition FROM shortdef WHERE uuid = ? ORDER BY id", (word_row[2],))
                    shortdef_rows = cursor.fetchall()
                    for sd in shortdef_rows:
                        word_info["shortdefs"].append({"id": sd[0], "definition": sd[1]})
                    
                    # Get external assets for this UUID
                    cursor.execute(
                        "SELECT assetgroup, sid, package, filename FROM external_assets WHERE uuid = ? ORDER BY assetgroup, sid",
                        (word_row[2],)
                    )
                    asset_rows = cursor.fetchall()
                    for asset in asset_rows:
                        word_info["external_assets"].append({
                            "assetgroup": asset[0],
                            "sid": asset[1],
                            "package": asset[2],
                            "filename": asset[3]
                        })
                    
                    word_data.append(word_info)
        
        db.close()
        
    except Exception as e:
        flash(f"Error accessing database: {e}", "error")
        return redirect(url_for("index"))
    
    return render_template("db_stats.html", 
                          stats=stats, 
                          word_data=word_data, 
                          query_word=query_word,
                          db_path=db_path)


# For Celery CLI discovery
celery_app = celery

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5002")), debug=True)
