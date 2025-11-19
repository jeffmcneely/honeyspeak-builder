import os
import zipfile
import logging
from pathlib import Path
from flask import Flask, request, render_template, redirect, url_for, send_from_directory, flash, jsonify, send_file
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Import celery app from celery_tasks
from celery_tasks import celery_app as celery

# Use templates and static folders
TEMPLATE_DIR = os.path.join(os.path.dirname(__file__), "templates")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
STORAGE_DIRECTORY_PATH = os.environ.get("STORAGE_DIRECTORY", str(Path(__file__).parent.parent))
LOGS_DIR = Path(STORAGE_DIRECTORY_PATH) / "logs"

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
    # Set the asset directory config for moderator
    app.config["ASSET_DIRECTORY"] = ASSET_DIR
except Exception as e:
    print(f"[APP DEBUG] Could not register moderator blueprint: {e}")
    import traceback
    traceback.print_exc()

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
    level = request.form.get("level", "a1").strip().lower()
    if not prompt:
        return jsonify(success=False, error="No prompt provided.")
    if not test_id:
        return jsonify(success=False, error="No test selected.")
    try:
        with PostgresTestDatabase() as testdb:
            qid = testdb.create_question(int(test_id), prompt, level=level)
        return jsonify(success=True, question_id=qid)
    except Exception as e:
        return jsonify(success=False, error=str(e))

@app.route("/build_tests/get_words")
def build_tests_get_words():
    label = request.args.get("label", "")
    count = int(request.args.get("count", 100))
    level = request.args.get("level", "").strip().lower()
    try:
        db = PostgresDictionary()
        if label == "proper noun":
            # function_label == 'noun' and first letter capitalized (uppercase), flags == 0
            if level:
                rows = db.execute_fetchall(
                    "SELECT word FROM words WHERE functional_label = 'noun' AND word ~ '^[A-Z]' AND flags = 0 AND level = %s ORDER BY random() LIMIT %s",
                    (level, count)
                )
            else:
                rows = db.execute_fetchall(
                    "SELECT word FROM words WHERE functional_label = 'noun' AND word ~ '^[A-Z]' AND flags = 0 ORDER BY random() LIMIT %s",
                    (count,)
                )
        elif label == "noun":
            # function_label == 'noun' and first letter lowercase, starts with a letter, flags == 0
            if level:
                rows = db.execute_fetchall(
                    "SELECT word FROM words WHERE functional_label = 'noun' AND word ~ '^[a-z]' AND flags = 0 AND level = %s ORDER BY random() LIMIT %s",
                    (level, count)
                )
            else:
                rows = db.execute_fetchall(
                    "SELECT word FROM words WHERE functional_label = 'noun' AND word ~ '^[a-z]' AND flags = 0 ORDER BY random() LIMIT %s",
                    (count,)
                )
        elif label in ["verb", "adjective", "adverb"]:
            # Exclude words that do not start with a letter, flags == 0
            if level:
                rows = db.execute_fetchall(
                    "SELECT word FROM words WHERE functional_label = %s AND word ~ '^[a-zA-Z]' AND flags = 0 AND level = %s ORDER BY random() LIMIT %s",
                    (label, level, count)
                )
            else:
                rows = db.execute_fetchall(
                    "SELECT word FROM words WHERE functional_label = %s AND word ~ '^[a-zA-Z]' AND flags = 0 ORDER BY random() LIMIT %s",
                    (label, count)
                )
        else:
            if level:
                rows = db.execute_fetchall(
                    "SELECT word FROM words WHERE functional_label = %s AND flags = 0 AND level = %s ORDER BY random() LIMIT %s",
                    (label, level, count)
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
        # Look up the word UUID from the dictionary
        from libs.sqlite_dictionary import SQLiteDictionary
        with SQLiteDictionary(DICT_PATH) as dict_db:
            word_uuids = dict_db.get_uuids(word)
            if not word_uuids:
                return jsonify(success=False, error=f"Word '{word}' not found in dictionary.")
            # Use the first UUID if multiple entries exist for the same word
            word_uuid = word_uuids[0]
        
        # Insert answer with word UUID
        with PostgresTestDatabase() as testdb:
            try:
                testdb.create_answer(int(question_id), word_uuid, bool(is_correct))
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
        # Import dictionary to look up words
        from libs.sqlite_dictionary import SQLiteDictionary
        with SQLiteDictionary(DICT_PATH) as dict_db:
            with PostgresTestDatabase() as testdb:
                tests = testdb.get_all_tests()
                result = []
                for test in tests:
                    questions = testdb.get_questions_for_test(test.id)
                    questions_data = []
                    for question in questions:
                        answers = testdb.get_answers_for_question(question.id)
                        # Look up word text from UUIDs
                        answers_data = []
                        for a in answers:
                            word_obj = dict_db.get_word_by_uuid(a.body_uuid)
                            word_text = word_obj.word if word_obj else f"[UUID: {a.body_uuid}]"
                            answers_data.append({
                                "id": a.id,
                                "body": word_text,
                                "is_correct": a.is_correct,
                                "weight": a.weight
                            })
                        questions_data.append({
                            "id": question.id,
                            "prompt": question.prompt,
                            "explanation": question.explanation,
                            "answers": answers_data
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
    """List SQLite database files from PACKAGE_DIR (assets directory)."""
    pkg_dir = Path(PACKAGE_DIR)
    if not pkg_dir.exists():
        return []
    # Look for db.sqlite in the package directory
    db_files = [f for f in pkg_dir.glob("*.sqlite") if f.is_file()]
    return db_files

def list_log_files():
    """List all log files in logs directory."""
    if not LOGS_DIR.exists():
        return []
    # Include both .log and .txt files
    log_files = [f for f in LOGS_DIR.glob("*.log") if f.is_file()]
    txt_files = [f for f in LOGS_DIR.glob("*.txt") if f.is_file()]
    return sorted(log_files + txt_files, key=lambda x: x.stat().st_mtime, reverse=True)

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
    
    # GET request - handle word search if query provided
    backend = "PostgreSQL" if POSTGRES_CONN else "SQLite"
    query = request.args.get("query", "").strip()
    word_data = None
    tables_exist = False
    
    try:
        if not POSTGRES_CONN:
            flash("Word search is only available when using PostgreSQL backend.", "warning")
        from libs.pg_dictionary import PostgresDictionary
        from libs.sqlite_dictionary import Flags
        pg_dict = PostgresDictionary()
        tables_exist = True  # PostgresDictionary ensures schema on init
        if query:
            word = pg_dict.get_word_by_text(query)
            if word:
                # Build complete word data with definitions and assets
                word_data = {
                    "word": word.word,
                    "fl": word.functional_label,
                    "uuid": word.uuid,
                    "flags": word.flags,
                    "level": word.level,
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
                
                # Get definitions with sid
                shortdefs = pg_dict.get_shortdefs(word.uuid)
                for sd in shortdefs:
                    word_data["definitions"].append({
                        "sid": sd.id,
                        "definition": sd.definition
                    })
                
                # Check filesystem for generated assets
                try:
                    audio_dir = os.path.join(ASSET_DIR, "audio")
                    image_dir = os.path.join(ASSET_DIR, "image")
                    
                    # Check for word audio
                    word_audio = f"word_{word.uuid}_0.aac"
                    if os.path.exists(os.path.join(audio_dir, word_audio)):
                        # Check if not already in assets from DB
                        if not any(a["filename"] == word_audio for a in word_data["assets"]):
                            word_data["assets"].append({
                                "assetgroup": "word",
                                "sid": 0,
                                "definition_id": 0,
                                "variant": 0,
                                "package": None,
                                "filename": word_audio,
                                "source": "filesystem"
                            })
                    
                    # Check for definition audio and images
                    for sd in shortdefs:
                        # Check definition audio (variant 0)
                        def_audio = f"shortdef_{word.uuid}_{sd.id}_0.aac"
                        if os.path.exists(os.path.join(audio_dir, def_audio)):
                            if not any(a["filename"] == def_audio for a in word_data["assets"]):
                                word_data["assets"].append({
                                    "assetgroup": "shortdef",
                                    "sid": sd.id * 100,  # sid = def_id * 100 + variant
                                    "definition_id": sd.id,
                                    "variant": 0,
                                    "package": None,
                                    "filename": def_audio,
                                    "source": "filesystem"
                                })
                        
                        # Check definition images (both variants)
                        for variant in range(2):
                            def_image = f"image_{word.uuid}_{sd.id}_{variant}.png"
                            if os.path.exists(os.path.join(image_dir, def_image)):
                                if not any(a["filename"] == def_image for a in word_data["assets"]):
                                    word_data["assets"].append({
                                        "assetgroup": "image",
                                        "sid": sd.id * 100 + variant,
                                        "definition_id": sd.id,
                                        "variant": variant,
                                        "package": None,
                                        "filename": def_image,
                                        "source": "filesystem"
                                    })
                except Exception as fs_error:
                    logger.warning(f"Error checking filesystem for assets: {fs_error}")

    except Exception as e:
        flash(f"Error searching for word: {e}", "error")
        import traceback
        traceback.print_exc()
    
    return render_template("build_dictionary.html", 
                         backend=backend, 
                         query=query, 
                         word_data=word_data,
                         tables_exist=tables_exist)


@app.route("/build_dictionary/single", methods=["POST"])
def build_dictionary_single():
    """Process a single word from the dictionary API."""
    word = request.form.get("word", "").strip().lower()
    function_label = request.form.get("function_label", "noun").strip()
    level = request.form.get("level", "z1").strip()
    
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
    task = celery.send_task("scripts.celery_tasks.fetch_and_process_word", args=[word, function_label, level, db_path, api_key])
    flash(f"Fetching word '{word}' (task id: {task.id})", "info")
    return redirect(url_for("task_status", task_id=task.id))

@app.route("/build_assets", methods=["GET", "POST"])
def build_assets():
    # All options from build_assets.py
    TTS_MODELS = ["gpt-4o-mini-tts", "tts-1", "tts-1-hd", "comfy-tts"]
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
    
    backend = "PostgreSQL"
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
        return redirect(url_for("build_package"))
    
    backend = "PostgreSQL (will convert to SQLite for packaging)" if POSTGRES_CONN else "SQLite"
    return render_template("build_package.html", package_dir=PACKAGE_DIR, asset_dir=ASSET_DIR, backend=backend)

@app.route("/build_package_db_only", methods=["POST"])
def build_package_db_only():
    """Export database tables only (PostgreSQL -> SQLite) without packaging assets"""
    try:
        # For DB-only export, we just need to determine output path
        if POSTGRES_CONN:
            db_path = os.path.join(STORAGE_DIRECTORY, "Dictionary.sqlite")
        else:
            db_path = DICT_PATH
        
        # The output_dir parameter is actually ignored by export_database_tables
        # It writes to STORAGE_DIRECTORY/assets/db.sqlite
        output_dir = ASSET_DIR
        
        # Enqueue only the database export task
        task = celery.send_task(
            "scripts.celery_tasks.export_database_tables",
            args=[db_path, output_dir]
        )
        
        return jsonify({
            "status": "success",
            "message": "Database export started",
            "task_id": task.id
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "error": str(e)
        }), 500

@app.route("/api/package_results")
def get_package_results():
    """Get the overall package results from package_result.json"""
    import json
    result_file = Path(ASSET_DIR) / "package_result.json"
    if not result_file.exists():
        return jsonify({"status": "not_found", "message": "No package results found"})
    
    try:
        with open(result_file, 'r') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/api/package_results/<letter>")
def get_package_letter_results(letter):
    """Get individual letter package results from {letter}.json"""
    import json
    # Validate letter is in valid set
    if letter not in "abcdef0123456789":
        return jsonify({"status": "error", "error": "Invalid letter"}), 400
    
    result_file = Path(ASSET_DIR) / f"{letter}.json"
    if not result_file.exists():
        return jsonify({"status": "not_found", "message": f"No results found for letter '{letter}'"})
    
    try:
        with open(result_file, 'r') as f:
            data = json.load(f)
        return jsonify(data)
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/api/download_files")
def get_download_files():
    """Get list of available database and package files for download"""
    try:
        pkg_dir = Path(PACKAGE_DIR)
        db_files = []
        package_files = []
        
        if pkg_dir.exists():
            # Look for db.sqlite in package directory
            db_files = [f.name for f in pkg_dir.glob("*.sqlite") if f.is_file()]
            package_files = [f.name for f in pkg_dir.glob("package_*.zip") if f.is_file()]
        
        return jsonify({
            "status": "success",
            "db_files": sorted(db_files),
            "package_files": sorted(package_files)
        })
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/api/create_bundle", methods=["POST"])
def create_bundle():
    """Create a timestamped zip bundle of all files in PACKAGE_DIR"""
    try:
        from datetime import datetime
        import tempfile
        
        # Generate timestamped filename
        now = datetime.now()
        bundle_filename = f"bundle_{now.strftime('%Y%m%d_%H%M')}.zip"
        
        # Create temporary zip file
        temp_dir = tempfile.mkdtemp()
        temp_zip_path = os.path.join(temp_dir, bundle_filename)
        
        pkg_dir = Path(PACKAGE_DIR)
        if not pkg_dir.exists():
            return jsonify({"status": "error", "error": "Package directory does not exist"}), 404
        
        # Create zip file with all contents of PACKAGE_DIR
        with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
            file_count = 0
            for file_path in pkg_dir.rglob('*'):
                if file_path.is_file():
                    # Add file to zip with relative path
                    arcname = file_path.relative_to(pkg_dir)
                    zipf.write(file_path, arcname)
                    file_count += 1
        
        if file_count == 0:
            return jsonify({"status": "error", "error": "No files found in package directory"}), 404
        
        # Move temp zip to package directory
        final_zip_path = pkg_dir / bundle_filename
        if final_zip_path.exists():
            final_zip_path.unlink()
        
        import shutil
        shutil.move(temp_zip_path, final_zip_path)
        
        # Clean up temp directory
        try:
            os.rmdir(temp_dir)
        except:
            pass
        
        return jsonify({
            "status": "success",
            "filename": bundle_filename,
            "file_count": file_count,
            "size": final_zip_path.stat().st_size
        })
    except Exception as e:
        logger.error(f"Error creating bundle: {e}", exc_info=True)
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/download")
def download():
    db_files = list_db_files()
    pkg_files = list_package_files()
    return render_template("download.html", db_files=db_files, pkg_files=pkg_files, package_dir=PACKAGE_DIR)

@app.route("/download_file/<path:filename>")
def download_file(filename):
    # Serve from package dir first (where db.sqlite and package zips are)
    pkg_path = Path(PACKAGE_DIR) / filename
    if pkg_path.exists():
        return send_from_directory(PACKAGE_DIR, filename, as_attachment=True)
    # Fallback to base dir for legacy files
    fpath = BASE_DIR / filename
    if fpath.exists():
        return send_from_directory(BASE_DIR, filename, as_attachment=True)
    flash("File not found", "error")
    return redirect(url_for("download"))

@app.route("/asset/<path:filename>")
def serve_asset(filename):
    """Serve asset files (audio/images) for preview."""
    # Check audio directory
    audio_path = Path(ASSET_DIR) / "audio" / filename
    if audio_path.exists():
        return send_from_directory(Path(ASSET_DIR) / "audio", filename)
    
    # Check image directory
    image_path = Path(ASSET_DIR) / "image" / filename
    if image_path.exists():
        return send_from_directory(Path(ASSET_DIR) / "image", filename)
    
    # Check base asset directory
    base_path = Path(ASSET_DIR) / filename
    if base_path.exists():
        return send_from_directory(ASSET_DIR, filename)
    
    return "Asset not found", 404

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


@app.route("/logs/<filename>/content")
def get_log_content(filename):
    """AJAX endpoint to get log file content."""
    log_path = LOGS_DIR / secure_filename(filename)
    
    if not log_path.exists() or not log_path.is_file():
        return jsonify({"error": "Log file not found"}), 404
    
    try:
        with open(log_path, "r") as f:
            content = f.read()
        return jsonify({"content": content, "filename": filename})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


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
                        "level": word.level,
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
                        # Include both definition text and sid
                        word_data["definitions"].append({
                            "sid": sd.id,
                            "definition": sd.definition
                        })

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
        
        # Get actual pending tasks count from broker (RabbitMQ or Redis)
        # Reserved tasks are limited by prefetch, so we need to check the broker queue
        pending_count = 0
        redis_client = None
        
        try:
            broker_url = celery.conf.broker_url
            
            # Check if using RabbitMQ
            if broker_url and 'amqp://' in broker_url:
                import pika
                from urllib.parse import urlparse
                
                # Parse RabbitMQ URL
                parsed = urlparse(broker_url)
                credentials = pika.PlainCredentials(
                    parsed.username or 'guest',
                    parsed.password or 'guest'
                )
                parameters = pika.ConnectionParameters(
                    host=parsed.hostname or 'localhost',
                    port=parsed.port or 5672,
                    virtual_host=parsed.path.lstrip('/') or '/',
                    credentials=credentials
                )
                
                connection = pika.BlockingConnection(parameters)
                channel = connection.channel()
                
                # Check the main 'celery' queue
                queue_name = 'celery'
                method = channel.queue_declare(queue=queue_name, durable=True, passive=True)
                pending_count = method.method.message_count
                
                connection.close()
                        
            # Check if using Redis
            elif broker_url and 'redis' in broker_url:
                import redis
                # Parse Redis URL
                redis_client = redis.from_url(broker_url)
                # Default Celery queue name is 'celery'
                queue_name = 'celery'
                # Get length of the queue in Redis
                pending_count = redis_client.llen(queue_name)
                        
        except Exception as broker_error:
            # If broker inspection fails, fall back to reserved count
            print(f"[api_celery_status] Broker queue inspection failed: {broker_error}")
            import traceback
            traceback.print_exc()
            pending_count = reserved_count
        
        # Get timing stats for later use
        avg_audio_time = 0
        avg_image_time = 0
        
        # Try to get timing from Redis result backend
        try:
            import redis
            result_backend = celery.conf.result_backend
            if result_backend and 'redis' in result_backend:
                redis_client = redis.from_url(result_backend)
                # Get average times from stored timings
                audio_times = redis_client.lrange('task_times:generate_definition_audio', 0, -1)
                if audio_times:
                    avg_audio_time = sum(float(t) for t in audio_times) / len(audio_times)
                
                image_times = redis_client.lrange('task_times:generate_definition_image', 0, -1)
                if image_times:
                    avg_image_time = sum(float(t) for t in image_times) / len(image_times)
                redis_client.close()
        except Exception as timing_error:
            print(f"[api_celery_status] Error fetching timing stats: {timing_error}")
        
        # Format active tasks for display
        formatted_active = []
        for worker, tasks in active_tasks.items():
            for task in tasks:
                task_id = task.get("id", "unknown")
                task_info = {
                    "worker": worker,
                    "name": task.get("name", "unknown"),
                    "id": task_id,
                    "args": str(task.get("args", [])),
                    "kwargs": str(task.get("kwargs", {})),
                    "time_start": task.get("time_start", 0),
                    "progress": None
                }
                
                # Try to get progress info for this task
                try:
                    if task_id != "unknown":
                        res = celery.AsyncResult(task_id)
                        if res.state == 'PROGRESS' and res.info:
                            task_info["progress"] = {
                                "current": res.info.get("current", 0),
                                "total": res.info.get("total", 0),
                                "percent": int((res.info.get("current", 0) / res.info.get("total", 1)) * 100) if res.info.get("total", 0) > 0 else 0,
                                "word": res.info.get("word", "")
                            }
                except Exception as progress_error:
                    # If we can't get progress, just continue without it
                    pass
                
                formatted_active.append(task_info)
        
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
        
        # Calculate estimate time remaining
        estimated_time_remaining = 0
        task_breakdown = {"audio": 0, "image": 0, "other": 0}
        
        try:
            # Count task types in pending + reserved
            all_waiting_tasks = []
            for tasks in reserved_tasks.values():
                all_waiting_tasks.extend(tasks)
            
            # Use task names from active/reserved to estimate distribution
            for task in all_waiting_tasks:
                task_name = task.get('name', '')
                if 'audio' in task_name.lower():
                    task_breakdown['audio'] += 1
                elif 'image' in task_name.lower():
                    task_breakdown['image'] += 1
                else:
                    task_breakdown['other'] += 1
            
            # Estimate remaining time based on pending count and task distribution
            if pending_count > 0:
                # If we have task breakdown, use weighted average
                if task_breakdown['audio'] + task_breakdown['image'] > 0:
                    total_tasks = task_breakdown['audio'] + task_breakdown['image'] + task_breakdown['other']
                    if total_tasks > 0:
                        audio_ratio = task_breakdown['audio'] / total_tasks
                        image_ratio = task_breakdown['image'] / total_tasks
                        other_ratio = task_breakdown['other'] / total_tasks
                        
                        # Estimate average time per task
                        avg_task_time = (
                            audio_ratio * (avg_audio_time if avg_audio_time > 0 else 5) +
                            image_ratio * (avg_image_time if avg_image_time > 0 else 10) +
                            other_ratio * 3  # Default 3s for other tasks
                        )
                    else:
                        avg_task_time = 5  # Default fallback
                else:
                    # No breakdown available, use simple average
                    if avg_audio_time > 0 and avg_image_time > 0:
                        avg_task_time = (avg_audio_time + avg_image_time) / 2
                    elif avg_audio_time > 0:
                        avg_task_time = avg_audio_time
                    elif avg_image_time > 0:
                        avg_task_time = avg_image_time
                    else:
                        avg_task_time = 5  # Default fallback
                
                # Calculate estimated time for pending tasks
                # Adjust for concurrent workers
                worker_count = len(workers) if workers else 1
                max_concurrency = sum(w.get('max_concurrency', 1) for w in workers) if workers else 1
                
                # Time = (pending tasks / worker concurrency) * avg time per task
                estimated_time_remaining = (pending_count / max_concurrency) * avg_task_time
            
        except Exception as timing_error:
            print(f"[api_celery_status] Error calculating timing: {timing_error}")
        
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
            "timing": {
                "avg_audio_time": round(avg_audio_time, 2),
                "avg_image_time": round(avg_image_time, 2),
                "estimated_time_remaining": round(estimated_time_remaining, 1),
                "task_breakdown": task_breakdown
            }
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


@app.route("/api/celery_clear_queues", methods=["POST"])
def api_celery_clear_queues():
    """API endpoint to clear all pending tasks from Celery queues."""
    try:
        broker_url = celery.conf.broker_url
        purged_count = 0
        
        # Check if using RabbitMQ
        if broker_url and 'amqp://' in broker_url:
            try:
                import pika
                from urllib.parse import urlparse
                
                # Parse RabbitMQ URL
                parsed = urlparse(broker_url)
                credentials = pika.PlainCredentials(
                    parsed.username or 'guest',
                    parsed.password or 'guest'
                )
                parameters = pika.ConnectionParameters(
                    host=parsed.hostname or 'localhost',
                    port=parsed.port or 5672,
                    virtual_host=parsed.path.lstrip('/') or '/',
                    credentials=credentials
                )
                
                connection = pika.BlockingConnection(parameters)
                channel = connection.channel()
                
                # Purge the main 'celery' queue
                queue_name = 'celery'
                method = channel.queue_purge(queue=queue_name)
                purged_count = method.method.message_count
                
                connection.close()
                
                return jsonify({
                    "success": True,
                    "purged_count": purged_count,
                    "message": f"Purged {purged_count} tasks from RabbitMQ queue"
                })
            except ImportError:
                return jsonify({
                    "success": False,
                    "error": "pika library not installed. Install with: pip install pika"
                }), 500
            except Exception as rmq_error:
                return jsonify({
                    "success": False,
                    "error": f"Failed to purge RabbitMQ queue: {str(rmq_error)}"
                }), 500
                
        # Check if using Redis
        elif broker_url and 'redis' in broker_url:
            import redis
            redis_client = redis.from_url(broker_url)
            queue_name = 'celery'
            
            # Get count before deleting
            purged_count = redis_client.llen(queue_name)
            
            # Delete the queue
            redis_client.delete(queue_name)
            redis_client.close()
            
            return jsonify({
                "success": True,
                "purged_count": purged_count,
                "message": f"Purged {purged_count} tasks from Redis queue"
            })
        else:
            return jsonify({
                "success": False,
                "error": "Unsupported broker type. Only RabbitMQ (amqp://) and Redis are supported."
            }), 400
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


# === Build Stories Page and API Endpoints ===
@app.route("/build_stories")
def build_stories():
    return render_template("build_stories.html")

@app.route("/view_stories")
def view_stories():
    """View existing stories page"""
    return render_template("view_stories.html")

@app.route("/api/stories")
def api_get_stories():
    """Get all stories from database"""
    try:
        from libs.pg_dictionary import PostgresDictionary
        db = PostgresDictionary()
        
        stories = db.get_all_stories()
        
        return jsonify({
            "status": "success",
            "stories": [
                {
                    "uuid": story.uuid,
                    "title": story.title,
                    "style": story.style,
                    "grouping": story.grouping,
                    "difficulty": story.difficulty
                }
                for story in stories
            ]
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/api/stories/<story_uuid>")
def api_get_story_detail(story_uuid):
    """Get detailed story information including paragraphs and words"""
    try:
        from libs.pg_dictionary import PostgresDictionary
        db = PostgresDictionary()
        
        # Get story
        story = db.get_story(story_uuid)
        if not story:
            return jsonify({"status": "error", "error": "Story not found"}), 404
        
        # Get paragraphs
        paragraphs = db.get_story_paragraphs(story_uuid)
        
        # Get word associations
        story_words = db.get_story_words(story_uuid)
        
        # Fetch word details for each word_uuid
        words_with_details = []
        for sw in story_words:
            word = db.get_word_by_uuid(sw["word_uuid"])
            if word:
                words_with_details.append({
                    "word": {
                        "word": word.word,
                        "uuid": word.uuid,
                        "level": word.level,
                        "functional_label": word.functional_label
                    },
                    "paragraph_index": sw["paragraph_index"]
                })
        
        return jsonify({
            "status": "success",
            "story": {
                "uuid": story.uuid,
                "title": story.title,
                "style": story.style,
                "grouping": story.grouping,
                "difficulty": story.difficulty
            },
            "paragraphs": [
                {
                    "paragraph_index": p.paragraph_index,
                    "paragraph_title": p.paragraph_title,
                    "content": p.content
                }
                for p in paragraphs
            ],
            "words": words_with_details
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/api/stories/<story_uuid>", methods=["DELETE"])
def api_delete_story(story_uuid):
    """Delete a story and all associated data"""
    try:
        from libs.pg_dictionary import PostgresDictionary
        db = PostgresDictionary()
        
        success = db.delete_story(story_uuid)
        
        if success:
            return jsonify({
                "status": "success",
                "message": "Story deleted successfully"
            })
        else:
            return jsonify({
                "status": "error",
                "error": "Story not found"
            }), 404
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"status": "error", "error": str(e)}), 500

@app.route("/api/choose_words", methods=["POST"])
def api_choose_words():
    """Fetch random nouns and verbs by level"""
    try:
        data = request.get_json()
        level = data.get("level", "a1")
        num_words = data.get("num_words", 4)
        
        from libs.dictionary import Dictionary
        db = Dictionary()
        
        try:
            # Fetch random nouns
            nouns_query = """
                SELECT word, uuid, functional_label, level 
                FROM words 
                WHERE functional_label = %s AND level = %s
                ORDER BY RANDOM() 
                LIMIT %s
            """
            nouns_rows = db.execute_fetchall(nouns_query, ('noun', level, num_words))
            nouns = [{"word": row['word'], "uuid": row['uuid'], 
                     "functional_label": row['functional_label'], "level": row['level']}
                    for row in nouns_rows]
            
            # Fetch random verbs
            verbs_query = """
                SELECT word, uuid, functional_label, level 
                FROM words 
                WHERE functional_label = %s AND level = %s
                ORDER BY RANDOM() 
                LIMIT %s
            """
            verbs_rows = db.execute_fetchall(verbs_query, ('verb', level, num_words))
            verbs = [{"word": row['word'], "uuid": row['uuid'], 
                     "functional_label": row['functional_label'], "level": row['level']}
                    for row in verbs_rows]
            
            return jsonify({
                "nouns": nouns,
                "verbs": verbs
            })
        finally:
            if hasattr(db, 'close'):
                db.close()
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/replace_word", methods=["POST"])
def api_replace_word():
    """Fetch a single replacement word, excluding already selected UUIDs"""
    try:
        data = request.get_json()
        level = data.get("level", "a1")
        functional_label = data.get("functional_label", "noun")
        exclude_uuids = data.get("exclude_uuids", [])
        
        from libs.dictionary import Dictionary
        db = Dictionary()
        
        try:
            # Build query with exclusions
            if exclude_uuids:
                placeholders = ",".join(["%s" for _ in exclude_uuids])
                query = f"""
                    SELECT word, uuid, functional_label, level 
                    FROM words 
                    WHERE functional_label = %s AND level = %s AND uuid NOT IN ({placeholders})
                    ORDER BY RANDOM() 
                    LIMIT 1
                """
                params = [functional_label, level] + exclude_uuids
            else:
                query = """
                    SELECT word, uuid, functional_label, level 
                    FROM words 
                    WHERE functional_label = %s AND level = %s
                    ORDER BY RANDOM() 
                    LIMIT 1
                """
                params = [functional_label, level]
            
            row = db.execute_fetchone(query, params)
            
            if row:
                return jsonify({
                    "word": {
                        "word": row['word'],
                        "uuid": row['uuid'],
                        "functional_label": row['functional_label'],
                        "level": row['level']
                    }
                })
            else:
                return jsonify({"word": None})
                
        finally:
            if hasattr(db, 'close'):
                db.close()
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500

@app.route("/api/story_build_llm", methods=["POST"])
def api_story_build_llm():
    """Send story generation request to LLM (OpenAI or Ollama)"""
    try:
        data = request.get_json()
        model = data.get("model", "llama3.1:8b-instruct-q5_K_M")
        level = data.get("level", "a1").lower()
        nouns = data.get("nouns", [])
        verbs = data.get("verbs", [])
        
        # Determine word count range based on level
        level_ranges = {
            "a1": "150-250",
            "a2": "150-250",
            "b1": "200-300",
            "b2": "200-300",
            "c1": "300-400",
            "c2": "300-400"
        }
        word_range = level_ranges.get(level, "150-250")
        
        # Combine all required words for validation
        all_required_words = nouns + verbs
        
        # Build prompt
        prompt = f"""Write a short story suitable for CEFR level {level.upper()} English learners.

The story MUST incorporate ALL of the following words:

Nouns: {", ".join(nouns)}
Verbs: {", ".join(verbs)}

Requirements:
- Keep sentences simple and appropriate for {level.upper()} level
- Use all listed words naturally in the story
- Make the story engaging and coherent
- Length: {word_range} words
- Include a clear beginning, middle, and end
- No offensive language or content

Write only the story, no additional commentary."""

        # Check if this is an OpenAI model
        openai_models = ["gpt-5", "gpt-4.1", "gpt-4", "gpt-3.5-turbo"]
        is_openai = any(model.startswith(om) for om in openai_models)
        
        import requests
        
        if is_openai:
            # Call OpenAI API
            openai_api_key = os.getenv("OPENAI_API_KEY")
            if not openai_api_key:
                return jsonify({"success": False, "error": "OPENAI_API_KEY not configured"}), 500
            
            # Build request payload
            request_payload = {
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are a helpful assistant that writes educational stories for English language learners."},
                    {"role": "user", "content": prompt}
                ]
            }
            
            # Only add temperature for models that support it (not gpt-5)
            if not model.startswith("gpt-5"):
                request_payload["temperature"] = 0.7
            
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {openai_api_key}",
                    "Content-Type": "application/json"
                },
                json=request_payload,
                timeout=120
            )
            
            if response.status_code == 200:
                result = response.json()
                story = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            else:
                return jsonify({"success": False, "error": f"OpenAI API error: {response.status_code} - {response.text}"}), 500
        else:
            # Call Ollama API
            ollama_url = os.getenv("LOCAL_LLM_URL", "localhost:11434")
            if not ollama_url.startswith("http"):
                ollama_url = f"http://{ollama_url}"
            
            response = requests.post(
                f"{ollama_url}/api/generate",
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False
                },
                timeout=120
            )
            
            if response.status_code == 200:
                result = response.json()
                story = result.get("response", "")
            else:
                return jsonify({"success": False, "error": f"Ollama API error: {response.status_code}"}), 500
        
        # Validate that all required words are used
        story_lower = story.lower()
        missing_words = []
        for word in all_required_words:
            if word.lower() not in story_lower:
                missing_words.append(word)
        
        return jsonify({
            "success": True,
            "story": story,
            "missing_words": missing_words
        })
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/approve_story", methods=["POST"])
def api_approve_story():
    """Save approved story to PostgreSQL database with word UUIDs"""
    try:
        data = request.get_json()
        story_text = data.get("story", "").strip()
        level = data.get("level", "a1").lower()
        model = data.get("model", "")
        word_uuids = data.get("word_uuids", [])  # List of word UUIDs
        
        if not story_text:
            return jsonify({"success": False, "error": "No story content provided"}), 400
        
        if not word_uuids:
            return jsonify({"success": False, "error": "No word UUIDs provided"}), 400
        
        from libs.pg_dictionary import PostgresDictionary
        import uuid as uuid_lib
        
        # Generate UUID for this story
        story_uuid = str(uuid_lib.uuid4())
        
        # Extract title from first line or use default
        lines = story_text.split('\n')
        title = lines[0][:50] if lines else "Untitled Story"
        if len(title) == 50:
            title += "..."
        
        db = PostgresDictionary()
        
        try:
            # Add story to database
            db.add_story(
                story_uuid=story_uuid,
                title=title,
                style=model,  # Store the model used as 'style'
                grouping=level,  # Store CEFR level as 'grouping'
                difficulty=level  # Also store as difficulty
            )
            
            # Split story into paragraphs on line breaks
            paragraphs = [p.strip() for p in story_text.split('\n') if p.strip()]
            
            # Add each paragraph
            for idx, paragraph_text in enumerate(paragraphs):
                db.add_story_paragraph(
                    story_uuid=story_uuid,
                    paragraph_index=idx,
                    paragraph_title="",
                    content=paragraph_text
                )
            
            # Add word associations (distribute across all paragraphs)
            # For simplicity, associate all words with all paragraphs
            story_words = []
            for paragraph_idx in range(len(paragraphs)):
                story_words.extend([(story_uuid, word_uuid, paragraph_idx) for word_uuid in word_uuids])
            words_added = db.batch_add_story_words(story_words)
            
            return jsonify({
                "success": True,
                "story_uuid": story_uuid,
                "words_added": words_added,
                "message": f"Story saved successfully with {words_added} word associations"
            })
            
        except Exception as db_error:
            import traceback
            traceback.print_exc()
            return jsonify({"success": False, "error": f"Database error: {str(db_error)}"}), 500
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"success": False, "error": str(e)}), 500


# === Migration Routes ===

@app.route("/migration")
def migration():
    """Migration tools page for updating word levels."""
    backend = "PostgreSQL" if POSTGRES_CONN else "SQLite"
    return render_template("migration.html", backend=backend)


@app.route("/migration/mark_unknown", methods=["POST"])
def migration_mark_unknown():
    """Mark all words as level='z1'."""
    try:
        # Use default database (PostgreSQL or SQLite based on config)
        db_path = None  # Let Dictionary class decide based on environment
        
        # Enqueue task
        task = celery.send_task("scripts.celery_tasks.mark_all_words_unknown", args=[db_path])
        
        return jsonify({
            "ok": True,
            "task_id": task.id,
            "message": "Task started to mark all words as 'z1'"
        })
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


@app.route("/migration/update_levels", methods=["POST"])
def migration_update_levels():
    """Update word levels from uploaded wordlist."""
    try:
        wordlist_file = request.files.get("wordlist")
        level = request.form.get("level", "a1").lower()
        
        if not wordlist_file:
            return jsonify({
                "ok": False,
                "error": "No wordlist file uploaded"
            }), 400
        
        # Read wordlist
        try:
            wordlist_content = wordlist_file.read().decode('utf-8')
            words = [w.strip() for w in wordlist_content.splitlines() if w.strip()]
        except Exception as e:
            return jsonify({
                "ok": False,
                "error": f"Error reading wordlist: {e}"
            }), 400
        
        if not words:
            return jsonify({
                "ok": False,
                "error": "Wordlist is empty"
            }), 400
        
        # Use default database (PostgreSQL or SQLite based on config)
        db_path = None  # Let Dictionary class decide based on environment
        
        # Enqueue task
        task = celery.send_task(
            "scripts.celery_tasks.update_word_levels_from_list",
            args=[words, db_path, level]
        )
        
        return jsonify({
            "ok": True,
            "task_id": task.id,
            "words_count": len(words),
            "level": level,
            "message": f"Task started to update {len(words)} words to level '{level}'"
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500


# For Celery CLI discovery
celery_app = celery

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5002")), debug=True)
