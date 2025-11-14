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

# Use RabbitMQ for broker, Redis for result backend
app = Celery(
    "honeyspeak_tasks",
    broker=os.getenv("CELERY_BROKER_URL", "amqp://guest:guest@localhost:5672//"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://redis:6379/0"),
)

app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    broker_transport_options={
        'priority_steps': list(range(6)),  # 0-5
        'queue_order_strategy': 'priority',
        'max_priority': 5,
        'visibility_timeout': 3600,
        'queue_arguments': {'x-max-priority': 5},
    },
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
    audio_model: str = "comfy-tts",
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
    audio_model: str = "comfy-tts",
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
    audio_model: str = "comfy-tts",
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
                    audio_task = generate_definition_audio_task.apply_async(
                        args=(defn.definition, uuid, defn.id, output_dir, i, audio_model, audio_voice),
                        priority=5
                    )
                    def_results["audio_tasks"].append({"i": i, "task_id": audio_task.id})
            
                if generate_images:
                    image_task = generate_definition_image_task.apply_async(
                        args=(defn.definition, uuid, defn.id, output_dir, word, i, image_model, image_size),
                        priority=4
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
    audio_model: str = "comfy-tts",
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
                    word.word, uuid, os.path.join(output_dir,"audio"), audio_model, audio_voice
                )
                word_result["word_audio"] = {"task_id": audio_task.id, "status": "queued"}
                tasks_queued += 1
            else:
                word_result["word_audio"] = {"status": "skipped", "reason": "exists"}
                tasks_skipped += 1
            
            # Check definition assets
            for defn in definitions:
                def_results = {"id": defn.id, "audio_tasks": [], "image_tasks": []}

                    # Check definition audio - 1 variant only
                def_audio_file = f"shortdef_{uuid}_{defn.id}_0.aac"
                if def_audio_file not in existing_files and generate_audio:
                    audio_task = generate_definition_audio_task.delay(
                        defn.definition, uuid, defn.id, os.path.join(output_dir,"audio"), 0, audio_model, audio_voice
                    )
                    def_results["audio_tasks"].append({"i": 0, "task_id": audio_task.id, "status": "queued"})
                    tasks_queued += 1
                else:
                    def_results["audio_tasks"].append({"i": 0, "status": "skipped", "reason": "exists"})
                    tasks_skipped += 1

                # Check 2 variants of each asset (i=0, i=1)
                for variant_i in range(2):

                    # Only generate images for nouns and verbs
                    if word.functional_label not in ["noun", "verb"]:
                        continue
                    # Check definition image
                    def_image_file = f"image_{uuid}_{defn.id}_{variant_i}.png"
                    if def_image_file not in existing_files and generate_images:
                        image_task = generate_definition_image_task.delay(
                            defn.definition, uuid, defn.id, os.path.join(output_dir,"image"), word.word, variant_i, image_model, image_size
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
def package_asset_group(
    self,
    letter: str,
    asset_dir: str,
    package_dir: str,
    db_path: str
) -> Dict:
    """
    Package all assets for a specific letter group (a-f, 0-9).
    Finds hires files matching the letter pattern, encodes them, and packages them.
    Does NOT write to external_assets table - that table is deprecated.
    
    Args:
        letter: Single character (a-f, 0-9) to filter files by UUID first letter
        asset_dir: Directory containing hires assets (expects audio/ and image/ subdirs)
        package_dir: Directory for output package files
        db_path: Path to database (passed to encoding functions)
    
    Returns:
        Dict with packaging results
    """
    import glob
    import re
    
    logger.info(f"Starting asset packaging for letter group: {letter}")
    
    # Create package directory if needed
    os.makedirs(package_dir, exist_ok=True)
    
    # Collect all hires files that match the letter pattern from audio/ and image/
    hires_audio_dir = os.path.join(asset_dir, "audio")
    hires_image_dir = os.path.join(asset_dir, "image")
    
    files_to_process = []
    
    # Find audio files in audio/ that start with letter
    if os.path.exists(hires_audio_dir):
        # Pattern: word_{uuid}_0.aac where uuid starts with letter
        word_pattern = os.path.join(hires_audio_dir, f"word_{letter}*.aac")
        word_files = glob.glob(word_pattern)
        
        # Pattern: shortdef_{uuid}_{def_id}_{variant}.aac where uuid starts with letter
        shortdef_pattern = os.path.join(hires_audio_dir, f"shortdef_{letter}*.aac")
        shortdef_files = glob.glob(shortdef_pattern)
        
        files_to_process.extend([("audio", f) for f in word_files + shortdef_files])
        logger.info(f"Found {len(word_files)} word audio files, {len(shortdef_files)} shortdef audio files")
    
    # Find image files in image/ that start with letter
    if os.path.exists(hires_image_dir):
        # Pattern: image_{uuid}_{def_id}_{variant}.png where uuid starts with letter
        image_pattern = os.path.join(hires_image_dir, f"image_{letter}*.png")
        image_files = glob.glob(image_pattern)
        files_to_process.extend([("image", f) for f in image_files])
        logger.info(f"Found {len(image_files)} image files")
    
    logger.info(f"Total files to process for '{letter}': {len(files_to_process)}")
    
    # Process each file
    results = {
        "letter": letter,
        "total_files": len(files_to_process),
        "audio_encoded": 0,
        "audio_failed": 0,
        "images_encoded": 0,
        "images_failed": 0,
        "files_packaged": 0,
        "files_skipped": 0
    }
    
    # Temp output directory for encoded files
    temp_output_dir = os.path.join(asset_dir, "temp")
    # Ensure temp/{letter}/audio and temp/{letter}/image directories exist
    temp_audio_dir = os.path.join(temp_output_dir, letter, "audio")
    temp_image_dir = os.path.join(temp_output_dir, letter, "image")
    os.makedirs(temp_audio_dir, exist_ok=True)
    os.makedirs(temp_image_dir, exist_ok=True)
    
    for i, (asset_type, filepath) in enumerate(files_to_process):
        filename = os.path.basename(filepath)
        
        # Parse filename to extract uuid and other metadata
        # Patterns: word_{uuid}_0.aac, shortdef_{uuid}_{def_id}_{variant}.aac, image_{uuid}_{def_id}_{variant}.png
        
        if asset_type == "audio":
            if filename.startswith("word_"):
                # word_{uuid}_0.aac
                match = re.match(r"word_([a-f0-9-]+)_0\.aac", filename)
                if match:
                    uuid = match.group(1)
                    assetgroup = "word"
                    defn_id = 0
                    variant = 0
                else:
                    logger.warning(f"Failed to parse word audio filename: {filename}")
                    results["audio_failed"] += 1
                    continue
            else:
                # Accept both shortdef_{uuid}_{def_id}_{variant}.aac and shortdef_{uuid}_{id}.aac
                match = re.match(r"shortdef_([a-f0-9-]+)_(\d+)_(\d+)\.aac", filename)
                if match:
                    uuid = match.group(1)
                    assetgroup = "shortdef"
                    defn_id = int(match.group(2))
                    variant = int(match.group(3))
                else:
                    # Try shortdef_{uuid}_{id}.aac (no variant)
                    match2 = re.match(r"shortdef_([a-f0-9-]+)_(\d+)\.aac", filename)
                    if match2:
                        uuid = match2.group(1)
                        assetgroup = "shortdef"
                        defn_id = int(match2.group(2))
                        variant = 0
                    else:
                        logger.warning(f"Failed to parse shortdef audio filename: {filename}")
                        results["audio_failed"] += 1
                        continue
            
            # Call encode_and_package_audio
            logger.debug(f"Encoding audio: {filepath}")
            result = encode_and_package_audio(
                input_file=filepath,
                output_dir=temp_output_dir,
                package_dir=package_dir,
                db_path=db_path,
                uuid=uuid,
                assetgroup=assetgroup,
                defn_id=defn_id,
                variant=variant
            )
            
            if result["status"] == "success":
                results["audio_encoded"] += 1
                results["files_packaged"] += 1
                logger.debug(f"Encoded and packaged {filename}")
            elif result["status"] == "skipped":
                results["files_skipped"] += 1
                logger.debug(f"Skipped already-encoded audio {filename}")
            else:
                results["audio_failed"] += 1
                logger.warning(f"Failed to encode audio {filename}: {result.get('error', 'unknown')}")
        
        elif asset_type == "image":
            # image_{uuid}_{def_id}_{variant}.png
            match = re.match(r"image_([a-f0-9-]+)_(\d+)_(\d+)\.png", filename)
            if match:
                uuid = match.group(1)
                assetgroup = "image"
                defn_id = int(match.group(2))
                variant = int(match.group(3))
            else:
                logger.warning(f"Failed to parse image filename: {filename}")
                results["images_failed"] += 1
                continue
            
            # Call encode_and_package_image
            logger.debug(f"Encoding image: {filepath}")
            result = encode_and_package_image(
                input_file=filepath,
                output_dir=temp_output_dir,
                package_dir=package_dir,
                db_path=db_path,
                uuid=uuid,
                assetgroup=assetgroup,
                defn_id=defn_id,
                variant=variant
            )
            
            if result["status"] == "success":
                results["images_encoded"] += 1
                results["files_packaged"] += 1
                logger.debug(f"Encoded and packaged {filename}")
            elif result["status"] == "skipped":
                results["files_skipped"] += 1
                logger.debug(f"Skipped already-encoded image {filename}")
            else:
                results["images_failed"] += 1
                logger.warning(f"Failed to encode image {filename}: {result.get('error', 'unknown')}")
        
        # Update progress
        if i % 50 == 0:
            self.update_state(
                state='PROGRESS',
                meta={
                    'letter': letter,
                    'current': i+1,
                    'total': len(files_to_process),
                    'audio_encoded': results["audio_encoded"],
                    'images_encoded': results["images_encoded"]
                }
            )
    
    logger.info(f"Packaging complete for '{letter}': {results}")
    
    # Save results to {letter}.json in asset_dir
    try:
        import json
        result_file = os.path.join(asset_dir, f"{letter}.json")
        final_result = {
            "status": "success",
            **results
        }
        with open(result_file, 'w') as f:
            json.dump(final_result, f, indent=2)
        logger.info(f"Saved results to {result_file}")
    except Exception as e:
        logger.warning(f"Failed to save results to JSON: {e}")
    
    return {
        "status": "success",
        **results
    }


@app.task(base=LoggingTask, bind=True)
def encode_and_package_audio(
    self,
    input_file: str,
    output_dir: str,
    package_dir: str,
    db_path: str,
    uuid: str,
    assetgroup: str,
    defn_id: int,
    variant: int,
    bitrate: int = 32
) -> Dict:
    """
    Encode an audio file and add it to a package.
    Does NOT store metadata - caller is responsible for batching metadata storage.
    
    Args:
        output_dir: Base temp directory (will create subdirs by UUID first letter)
        defn_id: Definition ID (0 for word audio)
        variant: Variant number (0 or 1)
    
    Returns:
        Dict with encoding and packaging results
    """
    # Compute sid from defn_id and variant: sid = defn_id * 100 + variant
    sid = defn_id * 100 + variant
    
    logger.debug(f"[encode_and_package_audio] Starting for: {input_file}")
    logger.debug(f"[encode_and_package_audio] uuid={uuid}, assetgroup={assetgroup}, defn_id={defn_id}, variant={variant}, sid={sid}")
    logger.debug(f"[encode_and_package_audio] output_dir={output_dir}")
    logger.debug(f"[encode_and_package_audio] package_dir={package_dir}")
    logger.debug(f"[encode_and_package_audio] input_file exists: {os.path.exists(input_file)}")
    
    # Create output directory: temp/{first_letter_of_uuid}/audio/
    first_letter = uuid[0] if uuid else "0"
    specific_output_dir = os.path.join(output_dir, first_letter, "audio")
    os.makedirs(specific_output_dir, exist_ok=True)
    logger.debug(f"[encode_and_package_audio] specific_output_dir={specific_output_dir}")
    
    # Encode - pass the full input path and the base output directory
    logger.debug(f"[encode_and_package_audio] Calling encode_audio_file with input_file={input_file}, output_dir={output_dir}")
    encode_result = encode_audio_file(input_file, output_dir, bitrate)
    logger.debug(f"[encode_and_package_audio] encode_result={encode_result}")

    # Extra debugging for skipped or failed encoding
    if encode_result["status"] not in ["success", "skipped"]:
        logger.warning(f"[encode_and_package_audio] Encoding failed: {encode_result}")
        logger.debug(f"[encode_and_package_audio] input_file exists: {os.path.exists(input_file)} size: {os.path.getsize(input_file) if os.path.exists(input_file) else 'N/A'}")
        output_file = encode_result.get("output_file")
        if output_file:
            logger.debug(f"[encode_and_package_audio] output_file exists: {os.path.exists(output_file)} size: {os.path.getsize(output_file) if os.path.exists(output_file) else 'N/A'}")
        logger.debug(f"[encode_and_package_audio] Parameters: input_file={input_file}, output_dir={output_dir}, bitrate={bitrate}")
        return encode_result
    
    # If skipped, log that we're continuing to package the existing file
    if encode_result["status"] == "skipped":
        logger.debug(f"[encode_and_package_audio] File already encoded, continuing to package: {encode_result['output_file']}")
    
    # Package
    logger.debug(f"[encode_and_package_audio] Calling add_file_to_package with file={encode_result['output_file']}")
    package_id = add_file_to_package(encode_result["output_file"], package_dir)
    logger.debug(f"[encode_and_package_audio] package_id={package_id}")
    
    if not package_id:
        logger.error(f"[encode_and_package_audio] Failed to add to package")
        return {"status": "error", "error": "Failed to add to package"}
    
    # Return package info (don't store metadata - caller will batch it)
    filename = os.path.basename(encode_result["output_file"])
    logger.debug(f"[encode_and_package_audio] Success: {filename} -> {package_id}")
    
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
    defn_id: int,
    variant: int,
    quality: int = 25
) -> Dict:
    """
    Encode an image file and add it to a package.
    Does NOT store metadata - caller is responsible for batching metadata storage.
    
    Args:
        output_dir: Base temp directory (will create subdirs by UUID first letter)
        defn_id: Definition ID (0 for word images)
        variant: Variant number (0 or 1)
    
    Returns:
        Dict with encoding and packaging results
    """
    # Compute sid from defn_id and variant: sid = defn_id * 100 + variant
    sid = defn_id * 100 + variant
    
    logger.debug(f"[encode_and_package_image] Starting for: {input_file}")
    logger.debug(f"[encode_and_package_image] uuid={uuid}, assetgroup={assetgroup}, defn_id={defn_id}, variant={variant}, sid={sid}")
    logger.debug(f"[encode_and_package_image] output_dir={output_dir}")
    logger.debug(f"[encode_and_package_image] package_dir={package_dir}")
    logger.debug(f"[encode_and_package_image] input_file exists: {os.path.exists(input_file)}")
    
    # Create output directory: temp/{first_letter_of_uuid}/image/
    first_letter = uuid[0] if uuid else "0"
    specific_output_dir = os.path.join(output_dir, first_letter, "image")
    os.makedirs(specific_output_dir, exist_ok=True)
    logger.debug(f"[encode_and_package_image] specific_output_dir={specific_output_dir}")
    
    # Encode - pass the full input path and the base output directory
    logger.debug(f"[encode_and_package_image] Calling encode_image_file with input_file={input_file}, output_dir={output_dir}")
    encode_result = encode_image_file(input_file, output_dir, quality)
    logger.debug(f"[encode_and_package_image] encode_result={encode_result}")
    
    # Extra debugging for skipped or failed encoding
    if encode_result["status"] not in ["success", "skipped"]:
        logger.warning(f"[encode_and_package_image] Encoding failed: {encode_result}")
        logger.debug(f"[encode_and_package_image] input_file exists: {os.path.exists(input_file)} size: {os.path.getsize(input_file) if os.path.exists(input_file) else 'N/A'}")
        output_file = encode_result.get("output_file")
        if output_file:
            logger.debug(f"[encode_and_package_image] output_file exists: {os.path.exists(output_file)} size: {os.path.getsize(output_file) if os.path.exists(output_file) else 'N/A'}")
        logger.debug(f"[encode_and_package_image] Parameters: input_file={input_file}, output_dir={output_dir}, quality={quality}")
        return encode_result
    
    # If skipped, log that we're continuing to package the existing file
    if encode_result["status"] == "skipped":
        logger.debug(f"[encode_and_package_image] File already encoded, continuing to package: {encode_result['output_file']}")
    
    # Package
    logger.debug(f"[encode_and_package_image] Calling add_file_to_package with file={encode_result['output_file']}")
    package_id = add_file_to_package(encode_result["output_file"], package_dir)
    logger.debug(f"[encode_and_package_image] package_id={package_id}")
    
    if not package_id:
        logger.error(f"[encode_and_package_image] Failed to add to package")
        return {"status": "error", "error": "Failed to add to package"}
    
    # Return package info (don't store metadata - caller will batch it)
    filename = os.path.basename(encode_result["output_file"])
    logger.debug(f"[encode_and_package_image] Success: {filename} -> {package_id}")
    
    return {
        "status": "success",
        "input_file": input_file,
        "output_file": encode_result["output_file"],
        "package_id": package_id,
        "filename": filename
    }


@app.task(base=LoggingTask, bind=True)
def relocate_files(
    self,
    asset_dir: str
) -> Dict:
    """
    Relocate files in asset directory into organized subdirectories.
    
    Creates subdirectories: image/, audio/, temp/
    Moves image_* files to image/
    Moves *.aac files to audio/
    Deletes low_* files
    
    Args:
        asset_dir: Path to asset directory
    
    Returns:
        Dict with counts of files moved/deleted
    """
    logger.info(f"Starting file relocation in: {asset_dir}")
    
    try:
        asset_path = Path(asset_dir)
        if not asset_path.exists():
            error_msg = f"Asset directory does not exist: {asset_dir}"
            logger.error(error_msg)
            return {"status": "error", "error": error_msg}
        
        # Create subdirectories
        image_dir = asset_path / "image"
        audio_dir = asset_path / "audio"
        temp_dir = asset_path / "temp"
        
        image_dir.mkdir(exist_ok=True)
        audio_dir.mkdir(exist_ok=True)
        temp_dir.mkdir(exist_ok=True)
        
        logger.info("Created subdirectories: image/, audio/, temp/")
        
        images_moved = 0
        audio_moved = 0
        
        # Process files in the asset directory (not subdirectories)
        for item in asset_path.iterdir():
            if not item.is_file():
                continue
            
            filename = item.name
            
            # Move image_* files to image/
            if filename.startswith("image_"):
                target = image_dir / filename
                if not target.exists():  # Don't overwrite existing files
                    item.rename(target)
                    images_moved += 1
                    logger.debug(f"Moved to image/: {filename}")
                continue
            
            # Move *.aac files to audio/
            if filename.endswith(".aac"):
                target = audio_dir / filename
                if not target.exists():  # Don't overwrite existing files
                    item.rename(target)
                    audio_moved += 1
                    logger.debug(f"Moved to audio/: {filename}")
                continue
        
        logger.info(f"Relocation complete: {images_moved} images, {audio_moved} audio")
        
        return {
            "status": "success",
            "images_moved": images_moved,
            "audio_moved": audio_moved
        }
        
    except Exception as e:
        logger.error(f"Error in relocate_files: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "status": "error",
            "error": str(e)
        }


@app.task(base=LoggingTask, bind=True)
def delete_conceptual_images(
    self,
    db_path: str,
    asset_dir: str
) -> Dict:
    """
    Delete image assets where functional_label is NOT 'noun' or 'verb'.
    These are conceptual images (for adjectives, adverbs, etc.) that shouldn't have visual representations.
    
    Args:
        db_path: Path to database
        asset_dir: Directory containing image assets
    
    Returns:
        Dict with deletion results
    """
    logger.info("Starting deletion of conceptual images (non-noun/verb)")
    
    try:
        # Import dictionary at runtime
        from libs.dictionary import Dictionary
        import redis as redis_module
        
        # Setup Redis for cache invalidation
        redis_client = None
        try:
            broker_url = os.getenv("CELERY_BROKER_URL")
            if broker_url and broker_url.startswith("redis://"):
                redis_client = redis_module.from_url(broker_url, decode_responses=True)
            else:
                redis_client = redis_module.Redis(
                    host=os.getenv("REDIS_HOST", "localhost"),
                    port=int(os.getenv("REDIS_PORT", "6379")),
                    db=int(os.getenv("REDIS_DB", "0")),
                    decode_responses=True
                )
            redis_client.ping()
        except Exception as e:
            logger.warning(f"Redis not available for cache invalidation: {e}")
            redis_client = None
        
        db = Dictionary(db_path)
        
        # Get all definitions with words, filtering for non-noun/verb
        all_definitions = db.get_all_definitions_with_words()
        
        # Filter to only non-noun and non-verb entries
        conceptual_defs = [
            d for d in all_definitions 
            if d['functional_label'] not in ['noun', 'verb']
        ]
        
        logger.info(f"Found {len(conceptual_defs)} definitions with non-noun/verb functional labels")
        
        deleted_files = 0
        deleted_db_records = 0
        errors = []
        
        for i, defn in enumerate(conceptual_defs):
            uuid = defn['uuid']
            def_id = defn['def_id']
            word = defn['word']
            functional_label = defn['functional_label']
            
            # Check for image files matching this definition (both variants: 0 and 1)
            for variant in range(2):
                # Pattern: image_{uuid}_{def_id}_{variant}.{ext}
                for ext in ['png', 'jpg', 'heic']:
                    filename = f"image_{uuid}_{def_id}_{variant}.{ext}"
                    file_path = Path(asset_dir) / filename
                    
                    if file_path.exists():
                        try:
                            # Delete the file
                            file_path.unlink()
                            deleted_files += 1
                            logger.info(f"Deleted file: {filename} (word={word}, label={functional_label})")
                            
                            # Delete from Redis cache
                            if redis_client:
                                try:
                                    redis_client.srem("moderator:images:all", filename)
                                except Exception as e:
                                    logger.warning(f"Failed to remove from Redis cache: {e}")
                            
                        except Exception as e:
                            error_msg = f"Failed to delete {filename}: {e}"
                            logger.error(error_msg)
                            errors.append(error_msg)
                
                # Delete from database (variant is combined with def_id in sid: sid = def_id * 100 + variant)
                # try:
                #     sid = def_id * 100 + variant
                #     db.delete_asset(uuid, 'image', sid)
                #     deleted_db_records += 1
                #     logger.debug(f"Deleted DB record: uuid={uuid}, assetgroup=image, sid={sid}")
                # except Exception as e:
                #     error_msg = f"Failed to delete DB record for {word} (uuid={uuid}, sid={sid}): {e}"
                #     logger.error(error_msg)
                #     errors.append(error_msg)
            
            # Update progress
            if i % 100 == 0:
                self.update_state(
                    state='PROGRESS',
                    meta={
                        'current': i+1, 
                        'total': len(conceptual_defs), 
                        'deleted_files': deleted_files,
                        'deleted_db_records': deleted_db_records
                    }
                )
        
        db.close()
        
        logger.info(f"Deletion complete: {deleted_files} files, {deleted_db_records} DB records")
        
        return {
            "status": "success",
            "definitions_processed": len(conceptual_defs),
            "deleted_files": deleted_files,
            "deleted_db_records": deleted_db_records,
            "errors": errors[:100]  # Limit error list to first 100
        }
        
    except Exception as e:
        logger.error(f"Error in delete_conceptual_images: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "status": "error",
            "error": str(e)
        }


@app.task(base=LoggingTask, bind=True)
def package_all_assets(
    self,
    db_path: str,
    asset_dir: str,
    package_dir: str
) -> Dict:
    """
    Package all assets by launching 16 parallel tasks for letter groups [a-f, 0-9].
    Waits for all tasks to complete, tracks timing, and saves aggregate results.
    Does NOT use external_assets table - that table is deprecated.
    
    Returns:
        Dict with task IDs for each letter group and aggregate results
    """
    import glob
    import json
    import time
    from celery.result import AsyncResult
    
    start_time = time.time()
    logger.info("Starting parallel asset packaging for all letter groups")
    
    # Clean package directory - remove all existing package files
    logger.info(f"Cleaning package directory: {package_dir}")
    if os.path.exists(package_dir):
        for file in os.listdir(package_dir):
            file_path = os.path.join(package_dir, file)
            if os.path.isfile(file_path):
                try:
                    os.remove(file_path)
                    logger.debug(f"Removed package file: {file}")
                except Exception as e:
                    logger.warning(f"Failed to remove {file}: {e}")
    
    # Launch 16 parallel tasks for [a-f, 0-9]
    letter_groups = list("abcdef0123456789")
    tasks = {}
    
    logger.info(f"Launching {len(letter_groups)} parallel packaging tasks")
    
    for letter in letter_groups:
        task = package_asset_group.delay(letter, asset_dir, package_dir, db_path)
        tasks[letter] = task.id
        logger.info(f"Launched task for letter '{letter}': {task.id}")
    
    logger.info(f"All {len(letter_groups)} packaging tasks launched, waiting for completion...")
    
    # Wait for all tasks to complete and collect results
    aggregate_results = {
        "total_files": 0,
        "audio_encoded": 0,
        "audio_failed": 0,
        "images_encoded": 0,
        "images_failed": 0,
        "files_packaged": 0,
        "files_skipped": 0,
        "tasks_completed": 0,
        "tasks_failed": 0
    }
    
    task_results = {}
    
    for letter, task_id in tasks.items():
        try:
            result = AsyncResult(task_id, app=app)
            # Wait for task to complete (timeout after 1 hour)
            task_result = result.get(timeout=3600)
            
            if task_result.get("status") == "success":
                aggregate_results["tasks_completed"] += 1
                aggregate_results["total_files"] += task_result.get("total_files", 0)
                aggregate_results["audio_encoded"] += task_result.get("audio_encoded", 0)
                aggregate_results["audio_failed"] += task_result.get("audio_failed", 0)
                aggregate_results["images_encoded"] += task_result.get("images_encoded", 0)
                aggregate_results["images_failed"] += task_result.get("images_failed", 0)
                aggregate_results["files_packaged"] += task_result.get("files_packaged", 0)
                aggregate_results["files_skipped"] += task_result.get("files_skipped", 0)
            else:
                aggregate_results["tasks_failed"] += 1
            
            task_results[letter] = {
                "task_id": task_id,
                "status": task_result.get("status", "unknown"),
                "result": task_result
            }
            
            logger.info(f"Task for letter '{letter}' completed: {task_result.get('status')}")
        except Exception as e:
            aggregate_results["tasks_failed"] += 1
            task_results[letter] = {
                "task_id": task_id,
                "status": "error",
                "error": str(e)
            }
            logger.error(f"Task for letter '{letter}' failed: {e}")
    
    end_time = time.time()
    total_time = end_time - start_time
    
    logger.info(f"All packaging tasks completed in {total_time:.2f} seconds")
    logger.info(f"Aggregate results: {aggregate_results}")
    
    # Save aggregate results to package_result.json
    try:
        result_file = os.path.join(asset_dir, "package_result.json")
        final_result = {
            "status": "success",
            "start_time": start_time,
            "end_time": end_time,
            "total_time_seconds": total_time,
            "letter_groups": letter_groups,
            "aggregate_results": aggregate_results,
            "task_results": task_results
        }
        with open(result_file, 'w') as f:
            json.dump(final_result, f, indent=2)
        logger.info(f"Saved aggregate results to {result_file}")
    except Exception as e:
        logger.error(f"Failed to save aggregate results to JSON: {e}")
    
    return {
        "status": "success",
        "message": f"Completed {len(letter_groups)} packaging tasks in {total_time:.2f}s",
        "total_time_seconds": total_time,
        "letter_groups": letter_groups,
        "tasks": tasks,
        "aggregate_results": aggregate_results
    }


@app.task(base=LoggingTask, bind=True)
def clean_packages(
    self,
    asset_dir: str,
    package_dir: str
) -> Dict:
    """
    Clean up packaging artifacts:
    - Delete all package* files in asset_dir
    - Delete db.sqlite in asset_dir
    - Delete all files in asset_dir/temp/*
    
    Args:
        asset_dir: Base asset directory (e.g., 'assets')
        package_dir: Package directory to clean
    
    Returns:
        Dict with cleanup results
    """
    import glob
    import shutil
    
    logger.info(f"Starting package cleanup in {asset_dir}")
    
    results = {
        "package_files_deleted": 0,
        "db_deleted": False,
        "temp_files_deleted": 0,
        "errors": []
    }
    
    try:
        # Delete package* files in asset_dir
        package_pattern = os.path.join(asset_dir, "package*")
        for package_file in glob.glob(package_pattern):
            try:
                if os.path.isfile(package_file):
                    os.remove(package_file)
                    results["package_files_deleted"] += 1
                    logger.info(f"Deleted package file: {package_file}")
            except Exception as e:
                error_msg = f"Failed to delete {package_file}: {e}"
                logger.error(error_msg)
                results["errors"].append(error_msg)
        
        # Delete db.sqlite in asset_dir
        db_sqlite_path = os.path.join(asset_dir, "db.sqlite")
        if os.path.exists(db_sqlite_path):
            try:
                os.remove(db_sqlite_path)
                results["db_deleted"] = True
                logger.info(f"Deleted db.sqlite: {db_sqlite_path}")
            except Exception as e:
                error_msg = f"Failed to delete db.sqlite: {e}"
                logger.error(error_msg)
                results["errors"].append(error_msg)
        
        # Delete all files in asset_dir/temp/*
        temp_dir = os.path.join(asset_dir, "temp")
        if os.path.exists(temp_dir):
            # Recursively delete all subdirectories and files in temp/
            for item in os.listdir(temp_dir):
                item_path = os.path.join(temp_dir, item)
                try:
                    if os.path.isfile(item_path):
                        os.remove(item_path)
                        results["temp_files_deleted"] += 1
                    elif os.path.isdir(item_path):
                        # Count files before deletion
                        for root, dirs, files in os.walk(item_path):
                            results["temp_files_deleted"] += len(files)
                        shutil.rmtree(item_path)
                    logger.debug(f"Deleted temp item: {item_path}")
                except Exception as e:
                    error_msg = f"Failed to delete {item_path}: {e}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)
        
        # Also clean package_dir if specified
        if package_dir and os.path.exists(package_dir):
            for package_file in os.listdir(package_dir):
                file_path = os.path.join(package_dir, package_file)
                try:
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                        results["package_files_deleted"] += 1
                        logger.info(f"Deleted package file: {file_path}")
                except Exception as e:
                    error_msg = f"Failed to delete {file_path}: {e}"
                    logger.error(error_msg)
                    results["errors"].append(error_msg)
        
        logger.info(f"Package cleanup complete: {results}")
        
        return {
            "status": "success",
            **results
        }
        
    except Exception as e:
        logger.error(f"Error in clean_packages: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            "status": "error",
            "error": str(e)
        }


@app.task(base=LoggingTask, bind=True)
def export_database_tables(
    self,
    db_path: str,
    output_dir: str
) -> Dict:
    """
    Export words and shortdef tables to output_dir/db.sqlite.
    This creates a lightweight database containing only the dictionary data
    without assets or other tables.
    
    Args:
        db_path: Path to source database
        output_dir: Directory where db.sqlite will be created (typically 'assets')
    
    Returns:
        Dict with export results
    """
    import sqlite3
    
    logger.info(f"Exporting database tables from {db_path} to {output_dir}/db.sqlite")
    
    # Create output directory if needed
    os.makedirs(output_dir, exist_ok=True)
    
    # Path for the exported db
    export_db_path = os.path.join(output_dir, "db.sqlite")
    
    try:
        # Remove existing db.sqlite if it exists
        if os.path.exists(export_db_path):
            os.remove(export_db_path)
            logger.info(f"Removed existing {export_db_path}")
        
        # Connect to source and export databases
        source_conn = sqlite3.connect(db_path)
        export_conn = sqlite3.connect(export_db_path)
        
        # Create the tables in the export database
        export_conn.execute("""CREATE TABLE words (
            word TEXT NOT NULL,
            functional_label TEXT,
            uuid TEXT PRIMARY KEY,
            flags INTEGER DEFAULT 0,
            level TEXT
        )""")
        export_conn.execute("""CREATE INDEX idx_words_word ON words(word)""")
        export_conn.execute("""CREATE INDEX idx_words_level ON words(level)""")
        
        export_conn.execute("""CREATE TABLE shortdef (
            uuid TEXT,
            definition TEXT,
            id INTEGER PRIMARY KEY,
            FOREIGN KEY (uuid) REFERENCES words(uuid) ON DELETE CASCADE,
            UNIQUE(uuid, definition)
        )""")
        export_conn.execute("""CREATE INDEX idx_shortdef_uuid ON shortdef(uuid)""")
        
        # Copy data from source to export
        source_cursor = source_conn.cursor()
        export_cursor = export_conn.cursor()
        
        # Copy words table
        source_cursor.execute("SELECT word, functional_label, uuid, flags, level FROM words")
        words_data = source_cursor.fetchall()
        export_cursor.executemany(
            "INSERT INTO words (word, functional_label, uuid, flags, level) VALUES (?, ?, ?, ?, ?)",
            words_data
        )
        logger.info(f"Copied {len(words_data)} words")
        
        # Copy shortdef table
        source_cursor.execute("SELECT uuid, definition, id FROM shortdef")
        shortdef_data = source_cursor.fetchall()
        export_cursor.executemany(
            "INSERT INTO shortdef (uuid, definition, id) VALUES (?, ?, ?)",
            shortdef_data
        )
        logger.info(f"Copied {len(shortdef_data)} definitions")
        
        # Commit and close
        export_conn.commit()
        source_conn.close()
        export_conn.close()
        
        export_size = os.path.getsize(export_db_path)
        logger.info(f"Successfully exported to {export_db_path} ({export_size:,} bytes)")
        
        return {
            "status": "success",
            "export_path": export_db_path,
            "words_count": len(words_data),
            "definitions_count": len(shortdef_data),
            "file_size": export_size
        }
    except Exception as e:
        logger.error(f"Error exporting database tables: {e}", exc_info=True)
        return {
            "status": "error",
            "error": str(e)
        }


@app.task(base=LoggingTask, bind=True)
def rename_image_variant(self, asset_dir: str, uuid: str, def_id: int) -> Dict:
    """
    Rename image variant 1 to variant 0 after a delay.
    Used when variant 0 is deleted - promotes variant 1 to primary.
    Fails silently if variant 1 does not exist.
    
    Args:
        asset_dir: Directory containing image assets
        uuid: Word UUID
        def_id: Definition ID
    
    Returns:
        Dict with rename results
    """
    logger.info(f"Attempting to rename image variant 1 to 0: {uuid}_{def_id}")
    
    try:
        import redis as redis_module
        
        # Setup Redis for cache updates
        redis_client = None
        try:
            broker_url = os.getenv("CELERY_BROKER_URL")
            if broker_url and broker_url.startswith("redis://"):
                redis_client = redis_module.from_url(broker_url, decode_responses=True)
            else:
                redis_client = redis_module.Redis(
                    host=os.getenv("REDIS_HOST", "localhost"),
                    port=int(os.getenv("REDIS_PORT", "6379")),
                    db=int(os.getenv("REDIS_DB", "0")),
                    decode_responses=True
                )
            redis_client.ping()
        except Exception as e:
            logger.warning(f"Redis not available for cache updates: {e}")
            redis_client = None
        
        # Try all allowed extensions
        allowed_exts = [".png", ".jpg", ".heic"]
        renamed = False
        
        for ext in allowed_exts:
            variant_1_name = f"image_{uuid}_{def_id}_1{ext}"
            variant_0_name = f"image_{uuid}_{def_id}_0{ext}"
            
            variant_1_path = Path(asset_dir) / variant_1_name
            variant_0_path = Path(asset_dir) / variant_0_name
            
            if variant_1_path.exists():
                # Rename variant 1 to variant 0
                variant_1_path.rename(variant_0_path)
                logger.info(f"Renamed {variant_1_name} to {variant_0_name}")
                
                # Update Redis cache
                if redis_client:
                    try:
                        redis_client.srem("moderator:images:all", variant_1_name)
                        redis_client.sadd("moderator:images:all", variant_0_name)
                        logger.debug(f"Updated Redis cache: removed {variant_1_name}, added {variant_0_name}")
                    except Exception as e:
                        logger.warning(f"Failed to update Redis cache: {e}")
                
                renamed = True
                break
        
        if not renamed:
            logger.info(f"No variant 1 found for {uuid}_{def_id} (silent failure as expected)")
            return {
                "status": "skipped",
                "message": "Variant 1 does not exist"
            }
        
        return {
            "status": "success",
            "renamed_from": variant_1_name,
            "renamed_to": variant_0_name
        }
        
    except Exception as e:
        logger.error(f"Error renaming image variant: {e}")
        import traceback
        logger.error(traceback.format_exc())
        # Fail silently - return success status to avoid alerting
        return {
            "status": "error",
            "error": str(e),
            "silent_failure": True
        }


# Expose celery app for CLI
celery_app = app
