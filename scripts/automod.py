"""
Automated image moderation system using Ollama vision API.

This module provides:
- Celery tasks for batch image moderation
- Ollama vision API integration with retry logic
- Flask blueprint for real-time WebSocket dashboard
- Redis caching for efficient filesystem scanning
"""

import os
import re
import time
import base64
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Set, List, Dict
import requests

from dotenv import load_dotenv
from flask import Blueprint, render_template, jsonify, current_app
from flask_socketio import SocketIO, emit

# Import Celery app and LoggingTask from celery_tasks
from celery_tasks import app, LoggingTask

load_dotenv()

# Configuration
STORAGE_DIRECTORY = os.getenv("STORAGE_DIRECTORY", "/data/honeyspeak")
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "stryker:11434")
if not LOCAL_LLM_URL.startswith("http"):
    LOCAL_LLM_URL = f"http://{LOCAL_LLM_URL}"

# Allowed image extensions and safe filename pattern (from moderator.py)
ALLOWED_EXTS = {".png", ".jpg", ".heic"}
SAFE_IMAGE_RE = re.compile(r"^image_([0-9a-fA-F\-]+)_(\d+)_(\d+)\.(?:png|jpg|heic)$")

# Flask-SocketIO instance (will be initialized in app.py)
socketio = SocketIO()

# Flask blueprint for automod dashboard
automod_bp = Blueprint("automod", __name__, template_folder="templates")

# Logger
logger = logging.getLogger(__name__)


# SocketIO event handlers for /automod namespace
@socketio.on('connect', namespace='/automod')
def handle_connect():
    """Handle client connection to /automod namespace."""
    logger.info("[automod] Client connected to /automod namespace")
    emit('connection_response', {'status': 'connected'})


@socketio.on('disconnect', namespace='/automod')
def handle_disconnect():
    """Handle client disconnection from /automod namespace."""
    logger.info("[automod] Client disconnected from /automod namespace")


def start_redis_listener():
    """
    Start Redis pub/sub listener in a background thread.
    This forwards messages from Celery workers to WebSocket clients.
    """
    import json
    import threading
    
    def redis_listener():
        redis = get_redis_client()
        if not redis:
            logger.error("[redis_listener] Redis not available, cannot start listener")
            return
        
        logger.info("[redis_listener] Starting Redis pub/sub listener...")
        pubsub = redis.pubsub()
        pubsub.subscribe('automod:updates')
        
        for message in pubsub.listen():
            if message['type'] == 'message':
                try:
                    data = json.loads(message['data'])
                    logger.info(f"[redis_listener] Received update for {data.get('filename')}")
                    
                    # Emit to all connected WebSocket clients
                    socketio.emit('moderation_update', data, namespace='/automod')
                    logger.info(f"[redis_listener] Forwarded to WebSocket clients")
                except Exception as e:
                    logger.error(f"[redis_listener] Error processing message: {e}")
    
    # Start listener in background thread
    thread = threading.Thread(target=redis_listener, daemon=True)
    thread.start()
    logger.info("[start_redis_listener] Redis listener thread started")


def get_redis_client():
    """Get Redis client for caching (lazy connection)."""
    try:
        import redis as redis_module
        broker_url = os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0")
        if broker_url.startswith("redis://"):
            client = redis_module.from_url(broker_url, decode_responses=True)
        else:
            client = redis_module.Redis(
                host=os.getenv("REDIS_HOST", "redis"),
                port=int(os.getenv("REDIS_PORT", "6379")),
                db=int(os.getenv("REDIS_DB", "0")),
                decode_responses=True
            )
        client.ping()
        return client
    except Exception as e:
        logger.warning(f"[automod] Redis not available: {e}")
        return None


def call_ollama_vision(image_b64: str, prompt: str, max_retries: int = 3, timeout: int = 120) -> Optional[bool]:
    """
    Call Ollama vision API with exponential backoff retry logic.
    
    Args:
        image_b64: Base64-encoded image data
        prompt: Text prompt for the vision model
        max_retries: Maximum number of retry attempts
        timeout: Request timeout in seconds
        
    Returns:
        Boolean response or None if all retries fail
    """
    url = f"{LOCAL_LLM_URL}/api/chat"
    
    payload = {
        "model": "qwen3-vl:4b",
        "messages": [
            {
                "role": "system",
                "content": "You are a binary classifier. Answer ONLY with the word 'true' or 'false', nothing else."
            },
            {
                "role": "user",
                "content": prompt,
                "images": [image_b64]
            }
        ],
        "stream": False
    }
    
    for attempt in range(max_retries):
        try:
            logger.info(f"[call_ollama_vision] Attempt {attempt + 1}/{max_retries}")
            response = requests.post(url, json=payload, timeout=timeout)
            
            if response.status_code == 200:
                result = response.json()
                content = result.get("message", {}).get("content", "")
                logger.info(f"[call_ollama_vision] Response: {content}")
                
                # Parse boolean from response using regex
                match = re.search(r'\b(true|false)\b', content, re.IGNORECASE)
                if match:
                    return match.group(1).lower() == "true"
                else:
                    logger.warning(f"[call_ollama_vision] Could not parse boolean from: {content}")
                    return None
            else:
                logger.error(f"[call_ollama_vision] API error {response.status_code}: {response.text}")
                
        except requests.exceptions.Timeout:
            logger.warning(f"[call_ollama_vision] Timeout on attempt {attempt + 1}")
        except Exception as e:
            logger.error(f"[call_ollama_vision] Exception on attempt {attempt + 1}: {e}")
        
        # Exponential backoff: 2s, 4s, 8s
        if attempt < max_retries - 1:
            delay = 2 ** (attempt + 1)
            logger.info(f"[call_ollama_vision] Retrying in {delay}s...")
            time.sleep(delay)
    
    logger.error(f"[call_ollama_vision] All {max_retries} attempts failed")
    return None


def get_unmoderated_images(asset_dir: str) -> Set[str]:
    """
    Get set of image filenames that haven't been moderated yet.
    Uses Redis caching for filesystem scan and database query for moderated images.
    
    Args:
        asset_dir: Asset directory path
        
    Returns:
        Set of unmoderated image filenames
    """
    logger.info(f"[get_unmoderated_images] Scanning {asset_dir}")
    
    # Step 1: Get all image files from filesystem (with Redis caching)
    redis = get_redis_client()
    cache_key = "automod:all_images"
    
    if redis:
        try:
            # Try to get from cache
            cached = redis.smembers(cache_key)
            if cached:
                logger.info(f"[get_unmoderated_images] Using cached filesystem scan ({len(cached)} images)")
                all_images = cached
            else:
                # Cache miss, scan filesystem
                logger.info(f"[get_unmoderated_images] Cache miss, scanning filesystem...")
                all_images = scan_image_files(asset_dir)
                if all_images:
                    redis.sadd(cache_key, *all_images)
                    redis.expire(cache_key, 3600)  # 1 hour TTL
                    logger.info(f"[get_unmoderated_images] Cached {len(all_images)} images")
        except Exception as e:
            logger.warning(f"[get_unmoderated_images] Redis error: {e}, falling back to direct scan")
            all_images = scan_image_files(asset_dir)
    else:
        # No Redis, direct filesystem scan
        all_images = scan_image_files(asset_dir)
    
    logger.info(f"[get_unmoderated_images] Total images: {len(all_images)}")
    
    # Step 2: Get already moderated images from database
    from libs.pg_dictionary import PostgresDictionary
    db = PostgresDictionary()
    try:
        rows = db.execute_fetchall("SELECT word_uuid, sid, variant FROM moderation_results")
        moderated = set()
        for row in rows:
            # Reconstruct filename pattern (try all extensions)
            for ext in ["png", "jpg", "heic"]:
                filename = f"image_{row['word_uuid']}_{row['sid']}_{row['variant']}.{ext}"
                moderated.add(filename)
        logger.info(f"[get_unmoderated_images] Already moderated: {len(moderated)}")
    finally:
        db.close()
    
    # Step 3: Return set difference
    unmoderated = all_images - moderated
    logger.info(f"[get_unmoderated_images] Unmoderated images: {len(unmoderated)}")
    return unmoderated


def scan_image_files(asset_dir: str) -> Set[str]:
    """
    Scan asset directory for all image files matching the pattern.
    
    Args:
        asset_dir: Asset directory path
        
    Returns:
        Set of image filenames (just filename, not full path)
    """
    p = Path(asset_dir)
    if not p.exists():
        logger.warning(f"[scan_image_files] Directory does not exist: {asset_dir}")
        return set()
    
    image_files = set()
    for ext in ALLOWED_EXTS:
        pattern = f"image_*{ext}"
        for img_path in p.rglob(pattern):
            if SAFE_IMAGE_RE.match(img_path.name):
                image_files.add(img_path.name)
    
    logger.info(f"[scan_image_files] Found {len(image_files)} matching images")
    return image_files


def emit_moderation_update(filename: str, word_uuid: str, sid: int, variant: int,
                           word: str, functional_label: str, definition: str,
                           represents: Optional[bool], multiple: Optional[bool],
                           offensive: Optional[bool]):
    """
    Emit WebSocket update for moderation result via Redis pub/sub.
    This is called from Celery tasks, which run in separate processes.
    
    Args:
        filename: Image filename
        word_uuid: Word UUID
        sid: Definition ID
        variant: Image variant number
        word: The word being defined
        functional_label: Part of speech
        definition: Definition text
        represents: Does image represent the word/definition?
        multiple: Does image have multiple objects?
        offensive: Is image offensive?
    """
    try:
        import json
        redis = get_redis_client()
        if not redis:
            logger.warning(f"[emit_moderation_update] Redis not available, skipping WebSocket update")
            return
        
        # Publish message to Redis channel
        # Ensure filename includes subdirectory for proper asset serving
        display_filename = f"image/{filename}" if not filename.startswith("image/") else filename
        message = {
            'filename': display_filename,
            'uuid': word_uuid,
            'sid': sid,
            'variant': variant,
            'word': word,
            'functional_label': functional_label,
            'definition': definition,
            'represents_word_def': represents,
            'has_multiple_objects': multiple,
            'is_offensive': offensive,
            'analyzed_at': datetime.now().isoformat()
        }
        
        redis.publish('automod:updates', json.dumps(message))
        logger.info(f"[emit_moderation_update] Published update to Redis for {filename}")
    except Exception as e:
        logger.warning(f"[emit_moderation_update] Failed to publish update: {e}")


@app.task(base=LoggingTask, bind=True, task_ignore_result=True)
def moderate_all_images(self, max_images: int = 0):
    """
    Spawn individual moderation tasks for all unmoderated images.
    
    Args:
        max_images: Maximum number of images to process (0 = no limit)
    """
    logger.info(f"[moderate_all_images] Starting with max_images={max_images}")
    
    # Get unmoderated images
    asset_dir = os.path.join(STORAGE_DIRECTORY, "assets_hires", "image")
    unmoderated = get_unmoderated_images(asset_dir)
    
    # Convert to list and limit if needed
    files = sorted(list(unmoderated))
    if max_images > 0:
        files = files[:max_images]
    
    total = len(files)
    logger.info(f"[moderate_all_images] Spawning {total} tasks...")
    
    # Spawn individual tasks with delay
    for i, filename in enumerate(files):
        automod_image.delay(filename)
        time.sleep(0.01)  # Small delay to avoid overwhelming broker
        
        # Update progress every 100 tasks
        if (i + 1) % 100 == 0:
            self.update_state(
                state='PROGRESS',
                meta={
                    'spawned': i + 1,
                    'total': total,
                    'filename': filename
                }
            )
            logger.info(f"[moderate_all_images] Spawned {i + 1}/{total} tasks")
    
    logger.info(f"[moderate_all_images] Completed spawning {total} tasks")


@app.task(base=LoggingTask, task_ignore_result=True)
def automod_image(filename: str):
    """
    Moderate a single image with three validation prompts.
    
    Args:
        filename: Image filename (e.g., image_uuid_sid_variant.ext)
    """
    logger.info(f"[automod_image] Processing {filename}")
    
    # Parse filename
    match = SAFE_IMAGE_RE.match(filename)
    if not match:
        logger.error(f"[automod_image] Invalid filename pattern: {filename}")
        return
    
    word_uuid = match.group(1)
    sid = int(match.group(2))
    variant = int(match.group(3))
    
    logger.info(f"[automod_image] Parsed: uuid={word_uuid}, sid={sid}, variant={variant}")
    
    # Load word and definition from database
    from libs.pg_dictionary import PostgresDictionary
    db = PostgresDictionary()
    try:
        word_data = db.get_word_by_uuid(word_uuid)
        if not word_data:
            logger.error(f"[automod_image] Word not found: {word_uuid}")
            return
        
        shortdefs = db.get_shortdefs(word_uuid)
        if not shortdefs:
            logger.error(f"[automod_image] Definition not found: {word_uuid}, sid={sid}")
            return
        
        # Find the shortdef with matching id
        definition = None
        for sd in shortdefs:
            if sd.id == sid:
                definition = sd.definition
                break
        
        if not definition:
            logger.error(f"[automod_image] Definition id mismatch: {word_uuid}, sid={sid}")
            return
        
        logger.info(f"[automod_image] Word: {word_data.word}, Definition: {definition}")
        
        # Load and encode image
        asset_dir = os.path.join(STORAGE_DIRECTORY, "assets_hires", "image")
        image_path = Path(asset_dir) / filename
        
        if not image_path.exists():
            logger.error(f"[automod_image] Image file not found: {image_path}")
            return
        
        with open(image_path, "rb") as f:
            image_b64 = base64.b64encode(f.read()).decode("utf-8")
        
        logger.info(f"[automod_image] Image loaded and encoded ({len(image_b64)} bytes)")
        
        # Prompt 1: Does this image represent the word/definition? (desired: true)
        prompt1 = f"Does this image represent {word_data.word} {definition}? Answer true or false"
        logger.info(f"[automod_image] Prompt 1: {prompt1}")
        represents = call_ollama_vision(image_b64, prompt1)
        logger.info(f"[automod_image] Prompt 1 result: {represents}")
        
        db.upsert_moderation_result(word_uuid, sid, variant, represents=represents)
        
        # Prompt 2: Does this image have more than 1 object? (desired: false)
        prompt2 = f"Does this image have more than 1 {word_data.word}? Answer true or false"
        logger.info(f"[automod_image] Prompt 2: {prompt2}")
        multiple = call_ollama_vision(image_b64, prompt2)
        logger.info(f"[automod_image] Prompt 2 result: {multiple}")
        
        db.upsert_moderation_result(word_uuid, sid, variant, multiple=multiple)
        
        # Prompt 3: Is this image offensive? (desired: false)
        prompt3 = f"Is this image offensive? Answer true or false"
        logger.info(f"[automod_image] Prompt 3: {prompt3}")
        offensive = call_ollama_vision(image_b64, prompt3)
        logger.info(f"[automod_image] Prompt 3 result: {offensive}")
        
        db.upsert_moderation_result(word_uuid, sid, variant, offensive=offensive)
        
        logger.info(f"[automod_image] Completed {filename}")
        
        # Emit WebSocket update
        emit_moderation_update(
            filename=filename,
            word_uuid=word_uuid,
            sid=sid,
            variant=variant,
            word=word_data.word,
            functional_label=word_data.functional_label,
            definition=definition,
            represents=represents,
            multiple=multiple,
            offensive=offensive
        )
        
    finally:
        db.close()


# Flask routes
@automod_bp.route("/")
def index():
    """Render automod dashboard."""
    return render_template("automod.html")


@automod_bp.route("/api/status")
def get_status():
    """Get recent moderation results."""
    from libs.pg_dictionary import PostgresDictionary
    db = PostgresDictionary()
    try:
        results = db.get_recent_moderation_results(limit=100)
        return jsonify(results)
    finally:
        db.close()
