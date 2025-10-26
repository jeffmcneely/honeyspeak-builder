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
# For PostgreSQL, DICT_PATH is only used as fallback for SQLite
POSTGRES_CONN = os.environ.get("POSTGRES_CONNECTION")
DICT_PATH = os.environ.get("DATABASE_PATH", str(Path(STORAGE_DIRECTORY) / "Dictionary.sqlite")) if not POSTGRES_CONN else None
ASSET_DIR = os.environ.get("ASSET_DIRECTORY", str(Path(STORAGE_DIRECTORY) / "assets_hires"))
PACKAGE_DIR = os.environ.get("PACKAGE_DIRECTORY", str(Path(STORAGE_DIRECTORY) / "assets"))
WORDLIST_DIR = BASE_DIR

# Debug output for paths
print(f"[APP DEBUG] BASE_DIR: {BASE_DIR}")
print(f"[APP DEBUG] STORAGE_HOME: {STORAGE_HOME}")
print(f"[APP DEBUG] STORAGE_DIRECTORY: {STORAGE_DIRECTORY}")
print(f"[APP DEBUG] DICT_PATH: {DICT_PATH}")
print(f"[APP DEBUG] ASSET_DIR: {ASSET_DIR}")
print(f"[APP DEBUG] PACKAGE_DIR: {PACKAGE_DIR}")

# Ensure required directories exist
LOGS_DIR.mkdir(exist_ok=True)
Path(STORAGE_DIRECTORY).mkdir(parents=True, exist_ok=True)
Path(ASSET_DIR).mkdir(parents=True, exist_ok=True)
Path(PACKAGE_DIR).mkdir(parents=True, exist_ok=True)

print(f"[APP DEBUG] STORAGE_DIRECTORY exists: {Path(STORAGE_DIRECTORY).exists()}")
print(f"[APP DEBUG] ASSET_DIR exists: {Path(ASSET_DIR).exists()}")
print(f"[APP DEBUG] PACKAGE_DIR exists: {Path(PACKAGE_DIR).exists()}")

# Register moderator blueprint if available
try:
    # moderator.py lives next to this file in the scripts/ folder
    from moderator import moderator_bp  # type: ignore
    app.register_blueprint(moderator_bp, url_prefix="/moderator")
    print("[APP DEBUG] Moderator blueprint registered at /moderator")
except Exception as e:
    print(f"[APP DEBUG] Could not register moderator blueprint: {e}")

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
    return [f.name for f in pkg_dir.iterdir() if f.is_file()]
    

# === Build Tests Page and AJAX Endpoints ===
from libs.pg_test import PostgresTestDatabase
from libs.pg_dictionary import PostgresDictionary
import random

@app.route("/build_tests")
def build_tests():
    return render_template("build_tests.html")

@app.route("/build_tests/get_tests")
def build_tests_get_tests():
    try:
        with PostgresTestDatabase() as testdb:
            tests = testdb.get_all_tests()
            # If no tests exist, create a default one
            if not tests:
                test_id = testdb.create_test("sentence grammar")
                tests = testdb.get_all_tests()
            test_list = [{"id": t.id, "name": t.name} for t in tests]
        return jsonify(success=True, tests=test_list)
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"[build_tests_get_tests ERROR] {error_details}")
        return jsonify(success=False, error=str(e))

@app.route("/build_tests/add_question", methods=["POST"])
def build_tests_add_question():
    prompt = request.form.get("prompt", "").strip()
    test_id = request.form.get("test_id")
    if not prompt:
        return jsonify(success=False, error="No prompt provided.")
    if not test_id:
        return jsonify(success=False, error="No test selected.")
    try:
        with PostgresTestDatabase() as testdb:
            qid = testdb.create_question(int(test_id), prompt)
        return jsonify(success=True, question_id=qid)
    except Exception as e:
        return jsonify(success=False, error=str(e))

@app.route("/build_tests/get_words")
def build_tests_get_words():
    label = request.args.get("label", "")
    count = int(request.args.get("count", 100))
    try:
        db = PostgresDictionary()
        if label == "proper noun":
            # function_label == 'noun' and first letter capitalized (uppercase), flags == 0
            rows = db.execute_fetchall(
                "SELECT word FROM words WHERE functional_label = 'noun' AND word ~ '^[A-Z]' AND flags = 0 ORDER BY random() LIMIT %s",
                (count,)
            )
        elif label == "noun":
            # function_label == 'noun' and first letter lowercase, starts with a letter, flags == 0
            rows = db.execute_fetchall(
                "SELECT word FROM words WHERE functional_label = 'noun' AND word ~ '^[a-z]' AND flags = 0 ORDER BY random() LIMIT %s",
                (count,)
            )
        elif label in ["verb", "adjective", "adverb"]:
            # Exclude words that do not start with a letter, flags == 0
            rows = db.execute_fetchall(
                "SELECT word FROM words WHERE functional_label = %s AND word ~ '^[a-zA-Z]' AND flags = 0 ORDER BY random() LIMIT %s",
                (label, count)
            )
        else:
            rows = db.execute_fetchall(
                "SELECT word FROM words WHERE functional_label = %s AND flags = 0 ORDER BY random() LIMIT %s",
                (label, count)
            )
        words = [r["word"] for r in rows]
        return jsonify(success=True, words=words)
    except Exception as e:
        return jsonify(success=False, error=str(e))

@app.route("/build_tests/add_answer", methods=["POST"])
def build_tests_add_answer():
    question_id = request.form.get("question_id")
    word = request.form.get("word", "")
    is_correct = int(request.form.get("is_correct", 0))
    if not question_id or not word:
        return jsonify(success=False, error="Missing question_id or word.")
    try:
        # Insert answer (body=word)
        with PostgresTestDatabase() as testdb:
            try:
                testdb.create_answer(int(question_id), word, bool(is_correct))
            except Exception as e:
                # Check for unique constraint violation (duplicate answer)
                if 'duplicate key value violates unique constraint' in str(e):
                    return jsonify(success=True)
                raise
        return jsonify(success=True)
    except Exception as e:
        return jsonify(success=False, error=str(e))

# === View Tests Page ===
@app.route("/view_tests")
def view_tests():
    return render_template("view_tests.html")

@app.route("/view_tests/get_data")
def view_tests_get_data():
    try:
        with PostgresTestDatabase() as testdb:
            tests = testdb.get_all_tests()
            result = []
            for test in tests:
                questions = testdb.get_questions_for_test(test.id)
                questions_data = []
                for question in questions:
                    answers = testdb.get_answers_for_question(question.id)
                    questions_data.append({
                        "id": question.id,
                        "prompt": question.prompt,
                        "explanation": question.explanation,
                        "answers": [{"id": a.id, "body": a.body, "is_correct": a.is_correct, "weight": a.weight} for a in answers]
                    })
                result.append({
                    "id": test.id,
                    "name": test.name,
                    "version": test.version,
                    "created_at": test.created_at.isoformat(),
                    "questions": questions_data
                })
        return jsonify(success=True, tests=result)
    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"[view_tests_get_data ERROR] {error_details}")
        return jsonify(success=False, error=str(e))

@app.route("/view_tests/delete_question", methods=["POST"])
def view_tests_delete_question():
    question_id = request.form.get("question_id")
    if not question_id:
        return jsonify(success=False, error="No question_id provided.")
    try:
        with PostgresTestDatabase() as testdb:
            success = testdb.delete_question(int(question_id))
        return jsonify(success=success)
    except Exception as e:
        return jsonify(success=False, error=str(e))

@app.route("/view_tests/delete_answer", methods=["POST"])
def view_tests_delete_answer():
    answer_id = request.form.get("answer_id")
    if not answer_id:
        return jsonify(success=False, error="No answer_id provided.")
    try:
        with PostgresTestDatabase() as testdb:
            success = testdb.delete_answer(int(answer_id))
        return jsonify(success=success)
    except Exception as e:
        return jsonify(success=False, error=str(e))
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

@app.route("/init_database")
def init_database():
    """Initialize the database with tables (PostgreSQL or SQLite)."""
    import sqlite3
    import time
    import tempfile
    import shutil
    from libs.sqlite_dictionary import SQLITE_SCHEMA
    from libs.pg_dictionary import POSTGRES_SCHEMA, PostgresDictionary
    
    # Check if we should use PostgreSQL
    postgres_conn = os.environ.get("POSTGRES_CONNECTION")
    if postgres_conn:
        try:
            print(f"[init_database] Initializing PostgreSQL database...")
            db = PostgresDictionary(postgres_conn)
            
            # Get stats to confirm it works
            word_count = db.get_word_count()
            
            return jsonify({
                "status": "success",
                "message": f"PostgreSQL database initialized successfully",
                "backend": "PostgreSQL",
                "word_count": word_count
            })
        except Exception as e:
            print(f"[init_database ERROR] PostgreSQL init failed: {e}")
            import traceback
            traceback.print_exc()
            return jsonify({
                "status": "error",
                "message": str(e),
                "backend": "PostgreSQL"
            }), 500
    
    # Otherwise use SQLite
    db_path = DICT_PATH
    conn = None
    
    try:
        print(f"[init_database] Initializing SQLite: {db_path}...")
        
        # Check if database already exists and is valid
        if Path(db_path).exists():
            existing_size = Path(db_path).stat().st_size
            if existing_size > 0:
                return jsonify({
                    "status": "already_exists",
                    "message": f"Database already initialized ({existing_size} bytes)",
                    "path": db_path
                })
            else:
                # Remove 0-byte file
                print(f"[init_database] Removing 0-byte database file...")
                Path(db_path).unlink()
        
        # Ensure directory exists
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # WORKAROUND for network filesystem locking issues:
        # Create database in /tmp first, then move to final location
        print(f"[init_database] Creating database in temp directory to avoid network FS locking...")
        
        with tempfile.NamedTemporaryFile(suffix='.sqlite', delete=False, dir='/tmp') as tmp_file:
            temp_db_path = tmp_file.name
        
        print(f"[init_database] Temp database path: {temp_db_path}")
        
        # Create connection to temp database (local filesystem, no locking issues)
        conn = sqlite3.connect(temp_db_path, timeout=5.0)
        
        try:
            # Set pragmas (use DELETE mode for initial creation)
            print(f"[init_database] Setting pragmas...")
            conn.execute("PRAGMA journal_mode = DELETE")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA foreign_keys = ON")
            
            # Create all tables in a single transaction
            print(f"[init_database] Creating tables...")
            conn.execute("BEGIN")
            cursor = conn.cursor()
            for i, stmt in enumerate(SQLITE_SCHEMA):
                print(f"[init_database] Executing statement {i+1}/{len(SQLITE_SCHEMA)}: {stmt[:50]}...")
                cursor.execute(stmt)
            conn.commit()
            
            # Get size of temp database
            temp_size = Path(temp_db_path).stat().st_size
            print(f"[init_database] Temp database created successfully ({temp_size} bytes)")
            
            # Close connection before moving file
            conn.close()
            conn = None
            
            # Move temp database to final location
            print(f"[init_database] Moving database to final location: {db_path}")
            shutil.move(temp_db_path, db_path)
            
            # Small delay to ensure filesystem sync
            time.sleep(0.5)
            
            # Now open the database and convert to WAL mode if possible
            print(f"[init_database] Opening database to enable WAL mode...")
            conn = sqlite3.connect(db_path, timeout=5.0)
            
            try:
                # Try to convert to WAL mode (might fail on some network filesystems)
                print(f"[init_database] Attempting to enable WAL mode...")
                result = conn.execute("PRAGMA journal_mode = WAL").fetchone()
                print(f"[init_database] Journal mode result: {result}")
                
                if result and result[0].upper() == 'WAL':
                    conn.execute("PRAGMA wal_autocheckpoint = 1000")
                    conn.commit()
                    mode_message = "WAL mode enabled"
                else:
                    print(f"[init_database WARNING] Could not enable WAL mode, using DELETE mode")
                    mode_message = "DELETE mode (WAL not available on this filesystem)"
            except Exception as wal_e:
                print(f"[init_database WARNING] WAL mode failed: {wal_e}, continuing with DELETE mode")
                mode_message = "DELETE mode (WAL failed)"
            
            conn.close()
            conn = None
            
            db_size = Path(db_path).stat().st_size
            print(f"[init_database] Database initialized successfully ({db_size} bytes, {mode_message})")
            
            return jsonify({
                "status": "success",
                "message": f"Database initialized successfully ({db_size} bytes, {mode_message})",
                "path": db_path,
                "size": db_size
            })
            
        except Exception as inner_e:
            print(f"[init_database ERROR] Transaction failed: {inner_e}")
            # Clean up temp file if it exists
            if Path(temp_db_path).exists():
                try:
                    Path(temp_db_path).unlink()
                except:
                    pass
            try:
                if conn:
                    conn.rollback()
            except:
                pass
            raise
        
    except Exception as e:
        print(f"[init_database ERROR] {e}")
        import traceback
        traceback.print_exc()
        
        # Clean up partial database file
        try:
            if Path(db_path).exists():
                print(f"[init_database] Cleaning up failed database file...")
                Path(db_path).unlink()
                # Also remove WAL/SHM files if they exist
                for suffix in ['-wal', '-shm']:
                    wal_file = Path(f"{db_path}{suffix}")
                    if wal_file.exists():
                        wal_file.unlink()
        except Exception as cleanup_e:
            print(f"[init_database] Cleanup error: {cleanup_e}")
        
        return jsonify({
            "status": "error",
            "message": str(e),
            "path": db_path
        }), 500
        
    finally:
        # Always close the connection
        if conn:
            try:
                print(f"[init_database] Closing connection...")
                conn.close()
            except Exception as close_e:
                print(f"[init_database] Error closing connection: {close_e}")

@app.route("/reset_database")
def reset_database():
    """Remove database file and all WAL/SHM files to start fresh."""
    db_path = DICT_PATH
    
    try:
        removed_files = []
        
        # Remove main database file
        if Path(db_path).exists():
            Path(db_path).unlink()
            removed_files.append(db_path)
        
        # Remove WAL and SHM files
        for suffix in ['-wal', '-shm', '.init.lock']:
            extra_file = Path(f"{db_path}{suffix}")
            if extra_file.exists():
                extra_file.unlink()
                removed_files.append(str(extra_file))
        
        if removed_files:
            return jsonify({
                "status": "success",
                "message": f"Removed {len(removed_files)} file(s)",
                "files": removed_files
            })
        else:
            return jsonify({
                "status": "success",
                "message": "No database files found to remove"
            })
            
    except Exception as e:
        print(f"[reset_database ERROR] {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500

@app.route("/database_status")
def database_status():
    """Check database file status."""
    db_path = DICT_PATH
    
    status = {
        "path": db_path,
        "exists": Path(db_path).exists(),
        "size": 0,
        "wal_exists": False,
        "shm_exists": False,
        "lock_exists": False
    }
    
    if status["exists"]:
        status["size"] = Path(db_path).stat().st_size
    
    wal_file = Path(f"{db_path}-wal")
    if wal_file.exists():
        status["wal_exists"] = True
        status["wal_size"] = wal_file.stat().st_size
    
    shm_file = Path(f"{db_path}-shm")
    if shm_file.exists():
        status["shm_exists"] = True
        status["shm_size"] = shm_file.stat().st_size
    
    lock_file = Path(f"{db_path}.init.lock")
    if lock_file.exists():
        status["lock_exists"] = True
    
    return jsonify(status)

@app.route("/build_dictionary", methods=["GET", "POST"])
def build_dictionary():
    if request.method == "POST":
        wordlist = request.files.get("wordlist")
        level = request.form.get("level", "none")
        
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
        
        # Use default database (PostgreSQL or SQLite based on config)
        db_path = None  # Let Dictionary class decide based on environment
        
        # Enqueue task using send_task with full task name
        task = celery.send_task("scripts.celery_tasks.process_wordlist", args=[words, db_path, api_key, level])
        level_msg = f" (level: {level.upper()})" if level != "none" else ""
        flash(f"Dictionary build started with {len(words)} words{level_msg} (task id: {task.id})", "info")
        return redirect(url_for("task_status", task_id=task.id))
    
    backend = "PostgreSQL" if POSTGRES_CONN else "SQLite"
    return render_template("build_dictionary.html", backend=backend)


@app.route("/build_dictionary/single", methods=["POST"])
def build_dictionary_single():
    """Process a single word from the dictionary API."""
    word = request.form.get("word", "").strip().lower()
    
    print(f"[APP DEBUG] Single word request: {word}")
    print(f"[APP DEBUG] Database backend: {'PostgreSQL' if POSTGRES_CONN else 'SQLite'}")
    
    if not word:
        flash("Please enter a word", "error")
        return redirect(url_for("build_dictionary"))
    
    # Get API key
    api_key = os.getenv("DICTIONARY_API_KEY")
    if not api_key:
        flash("DICTIONARY_API_KEY not set in environment", "error")
        return redirect(url_for("build_dictionary"))
    
    # Use default database (PostgreSQL or SQLite based on config)
    db_path = None  # Let Dictionary class decide based on environment
    
    # Enqueue task for single word using send_task with full task name
    task = celery.send_task("scripts.celery_tasks.fetch_and_process_word", args=[word, db_path, api_key])
    flash(f"Fetching word '{word}' (task id: {task.id})", "info")
    return redirect(url_for("task_status", task_id=task.id))

@app.route("/build_assets", methods=["GET", "POST"])
def build_assets():
    # All options from build_assets.py
    TTS_MODELS = ["gpt-4o-mini-tts", "tts-1", "tts-1-hd"]
    VOICES = ["alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse"]
    IMAGE_MODELS = ["dall-e-2", "dall-e-3", "gpt-image-1", "sdxl_turbo"]
    IMAGE_SIZES = ["square", "vertical", "horizontal"]
    
    if request.method == "POST":
        # Parse options - checkboxes only send value if checked
        generate_audio = request.form.get("generate_audio") == "1"
        generate_images = request.form.get("generate_images") == "1"
        audio_model = request.form.get("audio_model", "gpt-4o-mini-tts")
        audio_voice = request.form.get("audio_voice", "alloy")
        image_model = request.form.get("image_model", "sdxl_turbo")
        image_size = request.form.get("image_size", "vertical")
        output_dir = request.form.get("outdir", ASSET_DIR)
        
        # Parse limit (0 = unlimited)
        try:
            limit = int(request.form.get("limit", "0"))
            if limit < 0:
                limit = 0
        except (ValueError, TypeError):
            limit = 0
        
        # Use default database (PostgreSQL or SQLite based on config)
        db_path = None  # Let Dictionary class decide based on environment
        
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
                "image_size": image_size,
                "limit": limit
            }
        )
        limit_msg = f" (limited to {limit} word{'s' if limit != 1 else ''})" if limit > 0 else ""
        flash(f"Assets build started{limit_msg} (task id: {task.id})", "info")
        return redirect(url_for("task_status", task_id=task.id))
    
    backend = "PostgreSQL" if POSTGRES_CONN else "SQLite"
    return render_template(
        "build_assets.html",
        tts_models=TTS_MODELS,
        voices=VOICES,
        image_models=IMAGE_MODELS,
        image_sizes=IMAGE_SIZES,
        outdir=ASSET_DIR,
        backend=backend
    )

@app.route("/build_package", methods=["GET", "POST"])
def build_package():
    if request.method == "POST":
        asset_dir = request.form.get("asset_dir", ASSET_DIR)
        package_dir = request.form.get("packagedir", PACKAGE_DIR)
        
        # For packaging, always use SQLite (production format)
        # If using PostgreSQL for development, convert first
        if POSTGRES_CONN:
            # When using PostgreSQL as the authoritative source, packaging
            # should convert Postgres -> SQLite into the shared storage
            # directory so packaging writes to that SQLite file.
            db_path = os.path.join(STORAGE_DIRECTORY, "Dictionary.sqlite")
            # Note: Conversion would happen in the celery task
        else:
            db_path = DICT_PATH
        
        # Enqueue task using send_task with full task name
        task = celery.send_task(
            "scripts.celery_tasks.package_all_assets",
            args=[db_path, asset_dir, package_dir]
        )
        flash(f"Packaging started (task id: {task.id})", "info")
        return redirect(url_for("task_status", task_id=task.id))
    
    backend = "PostgreSQL (will convert to SQLite for packaging)" if POSTGRES_CONN else "SQLite"
    return render_template("build_package.html", outdir=PACKAGE_DIR, asset_dir=ASSET_DIR, backend=backend)

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


@app.route("/database", methods=["GET", "POST"])
def database_management():
    """Unified database management page with init/stats/status/reset."""
    from libs.dictionary import Dictionary
    
    # Determine backend type
    backend = "PostgreSQL" if POSTGRES_CONN else "SQLite"
    connection_string = POSTGRES_CONN if POSTGRES_CONN else DICT_PATH
    
    # Handle different actions (accept from querystring or form)
    action = request.values.get("action", "status")
    # Accept either 'query' (template) or legacy 'word' parameter
    query_input = request.values.get("query") or request.values.get("word") or ""
    query_word = query_input.strip().lower()
    
    # Initialize response data
    response_data = {
        "backend": backend,
        "connection": connection_string,
        "status": {},
        "stats": {},
        "tables_exist": False,
        "word_data": None,
        "query_word": query_word,
        # Expose the original query text (used by the template)
        "query": query_input
    }

    # If this is a POST, handle init/reset actions immediately and redirect
    if request.method == "POST":
        # Re-read action from form first
        action = request.form.get("action", action)

        def _parse_view_result(view_res):
            """Parse a Flask view return value (Response or (body, status)).
            Returns (data_dict_or_none, status_code).
            """
            data = None
            status_code = 200
            try:
                if isinstance(view_res, tuple):
                    # view functions sometimes return (response, status)
                    body = view_res[0]
                    if len(view_res) > 1 and isinstance(view_res[1], int):
                        status_code = view_res[1]
                    if hasattr(body, "get_json"):
                        data = body.get_json()
                    elif isinstance(body, (dict, list)):
                        data = body
                else:
                    # Likely a Response object
                    status_code = getattr(view_res, "status_code", 200)
                    if hasattr(view_res, "get_json"):
                        try:
                            data = view_res.get_json()
                        except Exception:
                            data = None
                    elif isinstance(view_res, (dict, list)):
                        data = view_res
            except Exception:
                data = None
            return data, status_code

        # Initialize database
        if action == "init":
            # If caller requested AJAX, return the init_database JSON directly
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return init_database()

            try:
                view_res = init_database()
                data, code = _parse_view_result(view_res)
                if code >= 400 or (data and data.get("status") == "error"):
                    msg = (data.get("message") if data else "Initialization failed")
                    flash(msg, "error")
                else:
                    # success / informational statuses
                    if data and data.get("status") == "already_exists":
                        flash(data.get("message", "Database already exists"), "info")
                    else:
                        flash(data.get("message", "Database initialized"), "success")
            except Exception as e:
                flash(f"Initialization exception: {e}", "error")
            return redirect(url_for("database_management"))

        # Reset database
        if action == "reset":
            if request.headers.get("X-Requested-With") == "XMLHttpRequest":
                return reset_database()

            try:
                view_res = reset_database()
                data, code = _parse_view_result(view_res)
                if code >= 400 or (data and data.get("status") == "error"):
                    flash((data.get("message") if data else "Reset failed"), "error")
                else:
                    flash((data.get("message") if data else "Reset completed"), "success")
            except Exception as e:
                flash(f"Reset exception: {e}", "error")
            return redirect(url_for("database_management"))
    
    # Check database status
    try:
        if backend == "PostgreSQL":
            # Check PostgreSQL connection
            from libs.pg_dictionary import PostgresDictionary
            try:
                db = PostgresDictionary(POSTGRES_CONN)
                # Try to get a count to verify tables exist
                word_count = db.get_word_count()
                response_data["status"] = {
                    "connected": True,
                    "tables_exist": True,
                    "message": "PostgreSQL connected and tables exist"
                }
                response_data["tables_exist"] = True
            except Exception as e:
                if "does not exist" in str(e).lower() or "relation" in str(e).lower():
                    response_data["status"] = {
                        "connected": True,
                        "tables_exist": False,
                        "message": "PostgreSQL connected but tables need initialization"
                    }
                else:
                    response_data["status"] = {
                        "connected": False,
                        "tables_exist": False,
                        "message": f"PostgreSQL connection error: {e}"
                    }
        else:
            # Check SQLite status
            if Path(DICT_PATH).exists():
                size = Path(DICT_PATH).stat().st_size
                if size > 0:
                    try:
                        db = Dictionary()
                        word_count = db.get_word_count()
                        response_data["status"] = {
                            "connected": True,
                            "tables_exist": True,
                            "message": f"SQLite database exists ({size:,} bytes)",
                            "size": size,
                            "path": DICT_PATH
                        }
                        response_data["tables_exist"] = True
                        db.close()
                    except:
                        response_data["status"] = {
                            "connected": True,
                            "tables_exist": False,
                            "message": f"SQLite file exists but tables need initialization",
                            "size": size,
                            "path": DICT_PATH
                        }
                else:
                    response_data["status"] = {
                        "connected": False,
                        "tables_exist": False,
                        "message": "Empty SQLite file",
                        "path": DICT_PATH
                    }
            else:
                response_data["status"] = {
                    "connected": False,
                    "tables_exist": False,
                    "message": "SQLite database does not exist",
                    "path": DICT_PATH
                }
    except Exception as e:
        response_data["status"] = {
            "connected": False,
            "tables_exist": False,
            "message": f"Error checking database: {e}"
        }

    # Expose some top-level helpers for the template
    response_data["connected"] = response_data.get("status", {}).get("connected", False)
    # SQLite helper values
    try:
        response_data["db_path"] = DICT_PATH
        response_data["db_exists"] = Path(DICT_PATH).exists()
        response_data["db_size"] = Path(DICT_PATH).stat().st_size if response_data["db_exists"] else 0
    except Exception:
        response_data["db_path"] = DICT_PATH
        response_data["db_exists"] = False
        response_data["db_size"] = 0
    
    # Get statistics if tables exist
    if response_data["tables_exist"]:
        try:
            db = Dictionary()
            
            response_data["stats"] = {
                "words": db.get_word_count(),
                "definitions": db.get_shortdef_count(),
                "assets": db.get_asset_count()
            }
            
            # Try to get story counts
            try:
                result = db.execute_fetchone("SELECT COUNT(*) as count FROM stories")
                response_data["stats"]["stories"] = result['count'] if result else 0
            except:
                response_data["stats"]["stories"] = 0
            
            try:
                result = db.execute_fetchone("SELECT COUNT(*) as count FROM story_paragraphs")
                response_data["stats"]["story_paragraphs"] = result['count'] if result else 0
            except:
                response_data["stats"]["story_paragraphs"] = 0
            
            # Get asset breakdown
            try:
                # Counts per package (package id -> count)
                response_data["stats"]["by_package"] = (
                    db.get_asset_count_by_package()
                    if hasattr(db, "get_asset_count_by_package")
                    else {}
                )
            except:
                response_data["stats"]["by_package"] = {}

            try:
                # Counts per asset type/group (e.g., 'word', 'shortdef')
                response_data["stats"]["by_type"] = (
                    db.get_asset_count_by_group()
                    if hasattr(db, "get_asset_count_by_group")
                    else {}
                )
            except:
                response_data["stats"]["by_type"] = {}
            
            # Query specific word if requested
            if query_word:
                word = db.get_word_by_text(query_word)
                if word:
                    from libs.sqlite_dictionary import Flags

                    word_data = {
                        "word": word.word,
                        "fl": word.functional_label,
                        "uuid": word.uuid,
                        "flags": word.flags,
                        "definitions": [],
                        "assets": []
                    }

                    # Compute human-readable flag names
                    try:
                        flags_obj = Flags.from_int(word.flags or 0)
                        flags_list = []
                        if flags_obj.offensive:
                            flags_list.append("Offensive")
                        if flags_obj.british:
                            flags_list.append("British")
                        if flags_obj.us:
                            flags_list.append("US")
                        if flags_obj.old_fashioned:
                            flags_list.append("Old-fashioned")
                        if flags_obj.informal:
                            flags_list.append("Informal")
                        word_data["flags_list"] = flags_list
                    except Exception:
                        word_data["flags_list"] = []

                    shortdefs = db.get_shortdefs(word.uuid)
                    for sd in shortdefs:
                        # Template expects a list of definition strings
                        word_data["definitions"].append(sd.definition)

                    assets = db.get_external_assets(word.uuid)
                    for asset in assets:
                        word_data["assets"].append({
                            "assetgroup": asset.assetgroup,
                            "sid": asset.sid,
                            "package": asset.package,
                            "filename": asset.filename,
                        })

                    # Template expects a single object (not a list)
                    response_data["word_data"] = word_data
            
            db.close()
        except Exception as e:
            response_data["stats_error"] = str(e)
    
    # Handle AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify(response_data)
    
    # Render template for regular requests
    return render_template("database.html", **response_data)

@app.route("/celery_status")
def celery_status_page():
    """Celery queue status page with auto-refresh."""
    return render_template("celery_status.html")


@app.route("/api/celery_status")
def api_celery_status():
    """API endpoint for Celery queue status data."""
    try:
        # Get Celery inspector
        inspect = celery.control.inspect()
        
        # Get active tasks
        active_tasks = inspect.active() or {}
        
        # Get scheduled tasks
        scheduled_tasks = inspect.scheduled() or {}
        
        # Get reserved tasks
        reserved_tasks = inspect.reserved() or {}
        
        # Get registered tasks
        registered_tasks = inspect.registered() or {}
        
        # Get stats
        stats = inspect.stats() or {}
        
        # Count tasks
        active_count = sum(len(tasks) for tasks in active_tasks.values())
        scheduled_count = sum(len(tasks) for tasks in scheduled_tasks.values())
        reserved_count = sum(len(tasks) for tasks in reserved_tasks.values())
        
        # Get actual pending tasks count from Redis broker
        # Reserved tasks are limited by prefetch, so we need to check the broker queue
        pending_count = 0
        try:
            import redis
            # Get Redis connection from Celery broker URL
            broker_url = celery.conf.broker_url
            if broker_url and 'redis' in broker_url:
                # Parse Redis URL
                redis_client = redis.from_url(broker_url)
                # Default Celery queue name is 'celery'
                queue_name = 'celery'
                # Get length of the queue in Redis
                pending_count = redis_client.llen(queue_name)
                redis_client.close()
        except Exception as redis_error:
            # If Redis inspection fails, fall back to reserved count
            print(f"[api_celery_status] Redis queue inspection failed: {redis_error}")
            pending_count = reserved_count
        
        # Format active tasks for display
        formatted_active = []
        for worker, tasks in active_tasks.items():
            for task in tasks:
                formatted_active.append({
                    "worker": worker,
                    "name": task.get("name", "unknown"),
                    "id": task.get("id", "unknown"),
                    "args": str(task.get("args", [])),
                    "kwargs": str(task.get("kwargs", {})),
                    "time_start": task.get("time_start", 0),
                })
        
        # Format scheduled tasks
        formatted_scheduled = []
        for worker, tasks in scheduled_tasks.items():
            for task in tasks:
                formatted_scheduled.append({
                    "worker": worker,
                    "name": task.get("request", {}).get("name", "unknown"),
                    "id": task.get("request", {}).get("id", "unknown"),
                    "eta": task.get("eta", "unknown"),
                })
        
        # Format reserved/pending tasks
        formatted_reserved = []
        for worker, tasks in reserved_tasks.items():
            for task in tasks:
                formatted_reserved.append({
                    "worker": worker,
                    "name": task.get("name", "unknown"),
                    "id": task.get("id", "unknown"),
                    "args": str(task.get("args", [])),
                    "kwargs": str(task.get("kwargs", {})),
                })
        
        # Get worker info
        workers = []
        for worker, worker_stats in stats.items():
            workers.append({
                "name": worker,
                "status": "online",
                "pool": worker_stats.get("pool", {}).get("implementation", "unknown"),
                "max_concurrency": worker_stats.get("pool", {}).get("max-concurrency", 0),
            })
        
        # Format registered tasks
        formatted_registered = {}
        for worker, tasks in registered_tasks.items():
            formatted_registered[worker] = sorted(tasks) if tasks else []
        
        return jsonify({
            "success": True,
            "workers": workers,
            "active_count": active_count,
            "scheduled_count": scheduled_count,
            "reserved_count": reserved_count,
            "pending_count": pending_count,
            "active_tasks": formatted_active,
            "scheduled_tasks": formatted_scheduled,
            "reserved_tasks": formatted_reserved,
            "registered_tasks": formatted_registered,
            "timestamp": __import__("time").time(),
        })
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
            "workers": [],
            "active_count": 0,
            "scheduled_count": 0,
            "reserved_count": 0,
            "pending_count": 0,
            "active_tasks": [],
            "scheduled_tasks": [],
            "reserved_tasks": [],
            "registered_tasks": {},
        }), 500


# For Celery CLI discovery
celery_app = celery

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5002")), debug=True)
