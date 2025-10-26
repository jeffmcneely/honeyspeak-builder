"""
Celery tasks for honeyspeak-builder.
All tasks are granular and write to structured log files.
"""

import os
import sys
import logging
from pathlib import Path
from typing import Dict, List, Optional
from celery import Celery, Task
from celery.utils.log import get_task_logger
from datetime import datetime
import re

# Add scripts directory to path so we can import libs
script_dir = Path(__file__).parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

# Import from libs directory
from libs.dictionary_ops import (
    fetch_word_from_api,
    process_api_entry,
    increment_api_usage,
    get_word_count
)
from libs.asset_ops import (
    generate_word_audio,
    generate_definition_audio,
    generate_definition_image
)
from libs.package_ops import (
    encode_audio_file,
    encode_image_file,
    add_file_to_package,
    store_asset_metadata,
    clean_packages,
    delete_all_assets
)
from libs.dictionary import Dictionary

# Setup logging directory
LOGS_DIR = Path(__file__).parent.parent / "logs"
LOGS_DIR.mkdir(exist_ok=True)

logger = get_task_logger(__name__)


class LoggingTask(Task):
    """Base task class that adds file logging."""
    
    def __call__(self, *args, **kwargs):
        # Setup task-specific log file
        task_name = self.name.split('.')[-1]
        log_file = LOGS_DIR / f"{task_name}_{datetime.now().strftime('%Y%m%d')}.log"
        
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(
            logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        )
        logger.addHandler(file_handler)
        
        try:
            return super().__call__(*args, **kwargs)
        finally:
            logger.removeHandler(file_handler)


# Initialize Celery app
app = Celery(
    "honeyspeak_tasks",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)


# ===== Dictionary Tasks =====

@app.task(base=LoggingTask, bind=True)
def fetch_and_process_word(
    self,
    word: str,
    function_label: str,
    level: str,
    db_path: str,
    api_key: str,
    usage_file: Optional[str] = None
) -> Dict:
    """
    Fetch a word from the dictionary API and process all entries.
    
    Args:
        word: Word to fetch
        db_path: Path to SQLite database
        api_key: Dictionary API key
        usage_file: API usage tracking file (defaults to STORAGE_DIRECTORY/api_usage.txt)
        
    Returns:
        Dict with processing results
    """
    logger.info(f"Fetching word: {word}")
    logger.info(f"[CELERY DEBUG] Received db_path: {db_path}")
    try:
        is_abs = os.path.isabs(db_path) if db_path is not None else False
    except Exception:
        is_abs = False
    logger.info(f"[CELERY DEBUG] db_path is absolute: {is_abs} (db_path set: {db_path is not None})")
    logger.info(f"[CELERY DEBUG] STORAGE_DIRECTORY env: {os.getenv('STORAGE_DIRECTORY', 'NOT SET')}")
    
    data = fetch_word_from_api(word, api_key)
    if not data:
        logger.error(f"Failed to fetch word: {word}")
        return {"status": "error", "word": word, "error": "API fetch failed"}
    
    # Increment API usage
    new_count = increment_api_usage(usage_file)
    logger.info(f"API usage count: {new_count}")
    
    # Process each entry
    results = []
    for entry in data:
        if isinstance(entry, dict):
            success, message = process_api_entry(entry, function_label, level, db_path)
            results.append({"success": success, "message": message})
            logger.info(f"Entry result: {message}")
    
    success_count = sum(1 for r in results if r["success"])
    
    return {
        "status": "success",
        "word": word,
        "entries_processed": len(results),
        "entries_success": success_count,
        "api_usage": new_count,
        "results": results
    }


@app.task(base=LoggingTask, bind=True)
def process_wordlist(
    self,
    wordlist: List[str],
    db_path: str,
    api_key: str,
    level: str = "A1"
) -> Dict:
    """
    Process a list of words.
    
    Args:
        wordlist: List of words to process
        db_path: Path to SQLite database
        api_key: Dictionary API key
        
    Returns:
        Dict with overall results
    """
    logger.info(f"Processing {len(wordlist)} words")
    
    results = []
    for i, line in enumerate(wordlist):
        word = line.strip()
        match = re.match(r"^([a-zA-Z ]+) ([a-z./, ]+)$", word)
        if not match:
            continue
        word = match.group(1)
        for function_label_abbreviation in match.group(2).split(","):
            match function_label_abbreviation:
                case 'n.':
                    fun_label = 'noun'
                case 'v.':
                    fun_label = 'verb'
                case 'adj.':
                    fun_label = 'adjective'
                case 'adv.':
                    fun_label = 'adverb'
                case 'prep.':
                    fun_label = 'preposition'
                case 'conj.':
                    fun_label = 'conjunction'
                case 'interj.':
                    fun_label = 'interjection'
                case 'pron.':
                    fun_label = 'pronoun'
                case _:
                    fun_label = function_label_abbreviation
            logger.info(f"Progress: {i+1}/{len(wordlist)} - {word}")
            result = fetch_and_process_word(word, fun_label, level, db_path, api_key)
            results.append(result)

            # Update task progress
            self.update_state(
                state='PROGRESS',
                meta={'current': i+1, 'total': len(wordlist), 'word': word}
            )
    
    total_count = get_word_count(db_path)
    
    return {
        "status": "success",
        "words_processed": len(wordlist),
        "total_words_in_db": total_count,
        "results": results
    }


# ===== Asset Generation Tasks =====

@app.task(base=LoggingTask, bind=True)
def generate_word_audio_task(
    self,
    word: str,
    uuid: str,
    output_dir: str,
    audio_model: str = "gpt-4o-mini-tts",
    audio_voice: str = "alloy"
) -> Dict:
    """Generate audio for a word."""
    logger.info(f"Generating word audio: {word} ({uuid})")
    logger.info(f"[CELERY DEBUG] Word audio output_dir: {output_dir}")
    logger.info(f"[CELERY DEBUG] output_dir exists: {os.path.exists(output_dir)}")
    
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)
    logger.info(f"[CELERY DEBUG] Created/verified output_dir: {os.path.exists(output_dir)}")
    
    result = generate_word_audio(word, uuid, output_dir, audio_model, audio_voice)
    logger.info(f"Word audio result: {result['status']}")
    
    if result.get('file'):
        logger.info(f"[CELERY DEBUG] Generated file: {result['file']}")
        logger.info(f"[CELERY DEBUG] File exists: {os.path.exists(result['file'])}")
    
    return result


@app.task(base=LoggingTask, bind=True)
def generate_definition_audio_task(
    self,
    definition: str,
    uuid: str,
    def_id: int,
    output_dir: str,
    i: int = 0,
    audio_model: str = "gpt-4o-mini-tts",
    audio_voice: str = "alloy"
) -> Dict:
    """Generate audio for a definition."""
    import time
    start_time = time.time()
    
    logger.info(f"Generating definition audio: {uuid}_{def_id}_{i}")
    result = generate_definition_audio(definition, uuid, def_id, output_dir, i, audio_model, audio_voice)
    
    elapsed_time = time.time() - start_time
    result['elapsed_time'] = elapsed_time
    logger.info(f"Definition audio result: {result['status']} (took {elapsed_time:.2f}s)")
    
    # Store timing in Redis for estimations
    try:
        from celery import current_app
        redis_client = current_app.broker_connection().channel().client
        redis_client.lpush('task_times:generate_definition_audio', elapsed_time)
        redis_client.ltrim('task_times:generate_definition_audio', 0, 99)  # Keep last 100
    except Exception as e:
        logger.debug(f"Could not store timing: {e}")
    
    return result


@app.task(base=LoggingTask, bind=True)
def generate_definition_image_task(
    self,
    definition: str,
    uuid: str,
    def_id: int,
    output_dir: str,
    word: str = "",
    i: int = 0,
    image_model: str = "gpt-image-1",
    image_size: str = "vertical"
) -> Dict:
    """Generate image for a definition."""
    import time
    start_time = time.time()
    
    logger.info(f"Generating definition image: {uuid}_{def_id}_{i}")
    result = generate_definition_image(definition, uuid, def_id, output_dir, word, i, image_model, image_size)
    
    elapsed_time = time.time() - start_time
    result['elapsed_time'] = elapsed_time
    logger.info(f"Definition image result: {result['status']} (took {elapsed_time:.2f}s)")
    
    # Store timing in Redis for estimations
    try:
        from celery import current_app
        redis_client = current_app.broker_connection().channel().client
        redis_client.lpush('task_times:generate_definition_image', elapsed_time)
        redis_client.ltrim('task_times:generate_definition_image', 0, 99)  # Keep last 100
    except Exception as e:
        logger.debug(f"Could not store timing: {e}")
    
    return result


@app.task(base=LoggingTask, bind=True)
def generate_assets_for_word(
    self,
    word: str,
    uuid: str,
    db_path: str,
    output_dir: str,
    generate_audio: bool = True,
    generate_images: bool = True,
    audio_model: str = "gpt-4o-mini-tts",
    audio_voice: str = "alloy",
    image_model: str = "gpt-image-1",
    image_size: str = "vertical"
) -> Dict:
    """
    Generate all assets (audio and images) for a word and its definitions.
    
    Returns:
        Dict with generation results
    """
    if not generate_audio and not generate_images:
        logger.warning(f"No audio or image generation requested for {word}")
        return {"status": "skipped", "word": word, "uuid": uuid}

    logger.info(f"Generating assets for word: {word} ({uuid})")
    logger.debug(f"[CELERY DEBUG] Asset output_dir: {output_dir}")
    logger.debug(f"[CELERY DEBUG] output_dir is absolute: {os.path.isabs(output_dir)}")
    logger.debug(f"[CELERY DEBUG] output_dir exists: {os.path.exists(output_dir)}")

    results = {"word": word, "uuid": uuid, "word_audio": None, "definitions": []}
    
    
    # Get definitions
    db = Dictionary(db_path)
    definitions = db.get_shortdefs(uuid)
    db.close()
    
    # Generate assets for each definition
    for defn in definitions:
        def_results = {"id": defn.id, "audio_tasks": [], "image_tasks": []}
        
        # Generate 2 variants of each asset (i=0, i=1)
        for i in range(2):
            if generate_audio:
                audio_task = generate_definition_audio_task.delay(
                    defn.definition, uuid, defn.id, output_dir, i, audio_model, audio_voice
                )
                def_results["audio_tasks"].append({"i": i, "task_id": audio_task.id})
            
            if generate_images:
                image_task = generate_definition_image_task.delay(
                    defn.definition, uuid, defn.id, output_dir, word, i, image_model, image_size
                )
                def_results["image_tasks"].append({"i": i, "task_id": image_task.id})
        
        results["definitions"].append(def_results)
    
    logger.info(f"Completed assets for {word}: {len(definitions)} definitions")
    return results


@app.task(base=LoggingTask, bind=True)
def generate_all_assets(
    self,
    db_path: str,
    output_dir: str,
    generate_audio: bool = True,
    generate_images: bool = True,
    audio_model: str = "gpt-4o-mini-tts",
    audio_voice: str = "alloy",
    image_model: str = "gpt-image-1",
    image_size: str = "vertical",
    limit: int = 0
) -> Dict:
    """
    Generate all assets for all words in database.
    
    Args:
        limit: Number of words to process (0 = unlimited)
    
    Returns:
        Dict with overall results
    """
    logger.info("Starting asset generation for all words")
    logger.info(f"Generate audio: {generate_audio}, Generate images: {generate_images}")
    
    db = Dictionary(db_path)
    words = db.get_all_words()
    db.close()
    
    # Apply limit if specified
    total_words = len(words)
    if limit > 0 and limit < total_words:
        words = words[:limit]
        logger.info(f"Limited to {limit} words (total available: {total_words})")
    
    logger.info(f"Processing {len(words)} words")
    
    # Create output directory
    logger.info(f"[CELERY DEBUG] Creating output directory: {output_dir}")
    logger.info(f"[CELERY DEBUG] output_dir is absolute: {os.path.isabs(output_dir)}")
    Path(output_dir).mkdir(exist_ok=True, parents=True)
    logger.info(f"[CELERY DEBUG] Output directory exists: {Path(output_dir).exists()}")
    logger.info(f"[CELERY DEBUG] Absolute output path: {Path(output_dir).resolve()}")
    
    # Load existing filenames once at the start
    logger.info("Scanning output directory for existing assets...")
    existing_files = set()
    try:
        if os.path.exists(output_dir):
            existing_files = {f for f in os.listdir(output_dir) if os.path.isfile(os.path.join(output_dir, f))}
            logger.info(f"Found {len(existing_files)} existing asset files")
        else:
            logger.info("Output directory does not exist yet, no existing files")
    except Exception as e:
        logger.warning(f"Error scanning output directory: {e}")
    
    results = []
    tasks_queued = 0
    tasks_skipped = 0
    
    for i, word in enumerate(words):
        logger.info(f"Progress: {i+1}/{len(words)} - {word.word}")
        
        # Get UUIDs for this word
        db = Dictionary(db_path)
        uuids = db.get_uuids(word.word)
        db.close()
        
        for uuid in uuids:
            # Get definitions to check which assets would be generated
            db = Dictionary(db_path)
            definitions = db.get_shortdefs(uuid)
            db.close()
            
            word_result = {"word": word.word, "uuid": uuid, "word_audio": None, "definitions": []}
            
            # Check word audio
            word_audio_file = f"word_{uuid}_0.aac"
            if word_audio_file not in existing_files and generate_audio:
                audio_task = generate_word_audio_task.delay(
                    word.word, uuid, output_dir, audio_model, audio_voice
                )
                word_result["word_audio"] = {"task_id": audio_task.id, "status": "queued"}
                tasks_queued += 1
            else:
                word_result["word_audio"] = {"status": "skipped", "reason": "exists"}
                tasks_skipped += 1
            
            # Check definition assets
            for defn in definitions:
                def_results = {"id": defn.id, "audio_tasks": [], "image_tasks": []}
                
                # Check 2 variants of each asset (i=0, i=1)
                for variant_i in range(2):
                    # Check definition audio
                    def_audio_file = f"shortdef_{uuid}_{defn.id}_{variant_i}.aac"
                    if def_audio_file not in existing_files and generate_audio:
                        audio_task = generate_definition_audio_task.delay(
                            defn.definition, uuid, defn.id, output_dir, variant_i, audio_model, audio_voice
                        )
                        def_results["audio_tasks"].append({"i": variant_i, "task_id": audio_task.id, "status": "queued"})
                        tasks_queued += 1
                    else:
                        def_results["audio_tasks"].append({"i": variant_i, "status": "skipped", "reason": "exists"})
                        tasks_skipped += 1
                    
                    # Check definition image
                    def_image_file = f"image_{uuid}_{defn.id}_{variant_i}.png"
                    if def_image_file not in existing_files and generate_images:
                        image_task = generate_definition_image_task.delay(
                            defn.definition, uuid, defn.id, output_dir, word.word, variant_i, image_model, image_size
                        )
                        def_results["image_tasks"].append({"i": variant_i, "task_id": image_task.id, "status": "queued"})
                        tasks_queued += 1
                    else:
                        def_results["image_tasks"].append({"i": variant_i, "status": "skipped", "reason": "exists"})
                        tasks_skipped += 1
                
                word_result["definitions"].append(def_results)
            
            results.append(word_result)
        
        # Update task progress
        self.update_state(
            state='PROGRESS',
            meta={'current': i+1, 'total': len(words), 'word': word.word}
        )
    
    logger.info(f"Asset generation complete: {len(results)} word entries processed")
    logger.info(f"Tasks queued: {tasks_queued}, Tasks skipped (existing): {tasks_skipped}")
    
    return {
        "status": "success",
        "words_processed": len(words),
        "entries_processed": len(results),
        "tasks_queued": tasks_queued,
        "tasks_skipped": tasks_skipped,
        "output_dir": output_dir
    }


# ===== Packaging Tasks =====

@app.task(base=LoggingTask, bind=True)
def encode_and_package_audio(
    self,
    input_file: str,
    output_dir: str,
    package_dir: str,
    db_path: str,
    uuid: str,
    assetgroup: str,
    sid: int,
    bitrate: int = 32
) -> Dict:
    """
    Encode an audio file and add it to a package.
    
    Returns:
        Dict with encoding and packaging results
    """
    logger.info(f"Encoding and packaging audio: {input_file}")
    
    # Encode
    encode_result = encode_audio_file(input_file, output_dir, bitrate)
    if encode_result["status"] != "success":
        return encode_result
    
    # Package
    package_id = add_file_to_package(encode_result["output_file"], package_dir)
    if not package_id:
        return {"status": "error", "error": "Failed to add to package"}
    
    # Store metadata
    filename = os.path.basename(encode_result["output_file"])
    metadata_result = store_asset_metadata(db_path, uuid, assetgroup, sid, package_id, filename)
    
    logger.info(f"Audio packaged: {filename} -> {package_id}")
    
    return {
        "status": "success",
        "input_file": input_file,
        "output_file": encode_result["output_file"],
        "package_id": package_id,
        "filename": filename
    }


@app.task(base=LoggingTask, bind=True)
def encode_and_package_image(
    self,
    input_file: str,
    output_dir: str,
    package_dir: str,
    db_path: str,
    uuid: str,
    assetgroup: str,
    sid: int,
    quality: int = 25
) -> Dict:
    """
    Encode an image file and add it to a package.
    
    Returns:
        Dict with encoding and packaging results
    """
    logger.info(f"Encoding and packaging image: {input_file}")
    
    # Encode
    encode_result = encode_image_file(input_file, output_dir, quality)
    if encode_result["status"] != "success":
        return encode_result
    
    # Package
    package_id = add_file_to_package(encode_result["output_file"], package_dir)
    if not package_id:
        return {"status": "error", "error": "Failed to add to package"}
    
    # Store metadata
    filename = os.path.basename(encode_result["output_file"])
    metadata_result = store_asset_metadata(db_path, uuid, assetgroup, sid, package_id, filename)
    
    logger.info(f"Image packaged: {filename} -> {package_id}")
    
    return {
        "status": "success",
        "input_file": input_file,
        "output_file": encode_result["output_file"],
        "package_id": package_id,
        "filename": filename
    }


@app.task(base=LoggingTask, bind=True)
def package_all_assets(
    self,
    db_path: str,
    asset_dir: str,
    package_dir: str
) -> Dict:
    """
    Package all assets for all words in database.
    
    Returns:
        Dict with packaging results
    """
    import tempfile
    import shutil
    
    logger.info("Starting asset packaging")
    
    # Determine packaging SQLite DB path. If a PostgreSQL connection is
    # configured, convert Postgres -> SQLite for packaging so assets are
    # always written into a SQLite database.
    postgres_conn = os.getenv("POSTGRES_CONNECTION")
    packaging_db_path = None
    temp_db_path = None
    final_db_destination = None

    if postgres_conn:
        # Create temp directory for SQLite file
        temp_dir = tempfile.mkdtemp(prefix="honeyspeak_pkg_")
        temp_db_path = os.path.join(temp_dir, "Dictionary.sqlite")
        packaging_db_path = temp_db_path
        
        # Final destination will be in asset_dir
        final_db_destination = os.path.join(asset_dir, "Dictionary.sqlite")
        
        logger.info(f"[PACKAGE] Created temp directory: {temp_dir}")
        logger.info(f"[PACKAGE] Temp DB path: {temp_db_path}")
        logger.info(f"[PACKAGE] Final destination: {final_db_destination}")
        logger.info(f"Postgres detected - converting to SQLite for packaging: {packaging_db_path}")
        
        from scripts.convert_postgres_to_sqlite import convert_database
        ok = convert_database(postgres_conn, packaging_db_path)
        
        if not ok:
            logger.error("Postgres -> SQLite conversion failed, aborting packaging")
            # Clean up temp directory
            shutil.rmtree(temp_dir, ignore_errors=True)
            return {"status": "error", "message": "Postgres->SQLite conversion failed"}
    else:
        # No Postgres - ensure we have a sqlite path to operate on
        if db_path and str(db_path).lower().endswith('.sqlite'):
            # If db_path looks like it's in /data, create temp copy
            if db_path.startswith('/data'):
                temp_dir = tempfile.mkdtemp(prefix="honeyspeak_pkg_")
                temp_db_path = os.path.join(temp_dir, "Dictionary.sqlite")
                
                logger.info(f"[PACKAGE] DB path is in /data, creating temp copy")
                logger.info(f"[PACKAGE] Copying {db_path} -> {temp_db_path}")
                
                shutil.copy(db_path, temp_db_path)
                packaging_db_path = temp_db_path
                final_db_destination = os.path.join(asset_dir, "Dictionary.sqlite")
                
                logger.info(f"[PACKAGE] Temp DB created: {temp_db_path}")
                logger.info(f"[PACKAGE] Final destination: {final_db_destination}")
            else:
                packaging_db_path = db_path
        else:
            packaging_db_path = os.environ.get("DATABASE_PATH", "Dictionary.sqlite")

    logger.info(f"[PACKAGE] Using packaging DB: {packaging_db_path}")

    # Clean existing packages and metadata in the packaging DB
    clean_packages(package_dir)
    delete_all_assets(packaging_db_path)

    # Always read words from the packaging SQLite database so asset FK
    # relations are preserved when we write external_assets.
    from libs.sqlite_dictionary import SQLiteDictionary
    db = SQLiteDictionary(packaging_db_path)
    words = db.get_all_words()
    db.close()
    
    logger.info(f"Packaging assets for {len(words)} words")
    
    results = []
    for i, word in enumerate(words):
        logger.info(f"Progress: {i+1}/{len(words)} - {word.word}")

        # Get definitions from the packaging SQLite DB
        db = SQLiteDictionary(packaging_db_path)
        definitions = db.get_shortdefs(word.uuid)
        db.close()

        # Package word audio
        word_audio_file = f"word_{word.uuid}_0.aac"
        audio_result = encode_and_package_audio(
            word_audio_file, asset_dir, package_dir, packaging_db_path,
            word.uuid, "word", 0
        )
        results.append(audio_result)
        
        # Package definition assets
        for defn in definitions:
            # Package 2 variants of definition audio (i=0, i=1)
            for i in range(2):
                def_audio_file = f"shortdef_{word.uuid}_{defn.id}_{i}.aac"
                # Encode both def_id and variant i into sid: sid = def_id * 100 + i
                audio_sid = defn.id * 100 + i
                audio_result = encode_and_package_audio(
                    def_audio_file, asset_dir, package_dir, packaging_db_path,
                    word.uuid, "shortdef", audio_sid
                )
                results.append(audio_result)
            
            # Package 2 variants of definition image (i=0, i=1)
            for i in range(2):
                def_image_file = f"image_{word.uuid}_{defn.id}_{i}.png"
                # Encode both def_id and variant i into sid: sid = def_id * 100 + i
                image_sid = defn.id * 100 + i
                image_result = encode_and_package_image(
                    def_image_file, asset_dir, package_dir, packaging_db_path,
                    word.uuid, "image", image_sid
                )
                results.append(image_result)
        
        # Update task progress
        self.update_state(
            state='PROGRESS',
            meta={'current': i+1, 'total': len(words), 'word': word.word}
        )
    
    success_count = sum(1 for r in results if r.get("status") == "success")
    logger.info(f"Packaging complete: {success_count}/{len(results)} successful")
    
    # Move temp DB to final destination if needed
    if temp_db_path and final_db_destination:
        try:
            logger.info(f"[PACKAGE] Moving temp DB to final destination")
            logger.info(f"[PACKAGE] Source: {temp_db_path}")
            logger.info(f"[PACKAGE] Destination: {final_db_destination}")
            
            # Ensure destination directory exists
            os.makedirs(os.path.dirname(final_db_destination), exist_ok=True)
            
            # Move the database file
            shutil.copy(temp_db_path, final_db_destination)
            logger.info(f"[PACKAGE] ✓ Database moved to {final_db_destination}")
            
            # Clean up temp directory
            temp_dir = os.path.dirname(temp_db_path)
            shutil.rmtree(temp_dir, ignore_errors=True)
            logger.info(f"[PACKAGE] ✓ Cleaned up temp directory: {temp_dir}")
            
        except Exception as e:
            logger.error(f"[PACKAGE] Error moving database: {e}")
            return {
                "status": "error",
                "message": f"Packaging succeeded but failed to move database: {e}",
                "words_processed": len(words),
                "assets_processed": len(results),
                "assets_success": success_count
            }
    
    return {
        "status": "success",
        "words_processed": len(words),
        "assets_processed": len(results),
        "assets_success": success_count,
        "database_path": final_db_destination if final_db_destination else packaging_db_path
    }


# Expose celery app for CLI
celery_app = app
