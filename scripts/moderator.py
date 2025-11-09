import os
import re
import time
import json
from pathlib import Path
from typing import List, Dict, Set

from dotenv import load_dotenv
from flask import Blueprint, Flask, jsonify, url_for, send_from_directory, render_template, abort, current_app

load_dotenv()

# Performance debugging flag
DEBUG_TIMING = os.getenv("DEBUG_TIMING", "0") in ("1", "true", "True")

# Redis connection - make it lazy to avoid import-time errors
redis_client = None

def get_redis_client():
    """Get or create Redis client lazily."""
    global redis_client
    if redis_client is None:
        try:
            import redis as redis_module
            
            # Try to use CELERY_BROKER_URL if available (from Kubernetes/Docker env)
            broker_url = os.getenv("CELERY_BROKER_URL")
            if broker_url and broker_url.startswith("redis://"):
                # Parse redis://host:port/db format
                redis_client = redis_module.from_url(broker_url, decode_responses=True)
            else:
                # Fall back to individual env vars
                redis_client = redis_module.Redis(
                    host=os.getenv("REDIS_HOST", "localhost"),
                    port=int(os.getenv("REDIS_PORT", "6379")),
                    db=int(os.getenv("REDIS_DB", "0")),
                    decode_responses=True
                )
            
            # Test connection
            redis_client.ping()
            print("[MODERATOR] Redis connection established")
        except Exception as e:
            print(f"[MODERATOR WARNING] Redis not available: {e}")
            redis_client = None
    return redis_client

# Redis key for the image cache
REDIS_IMAGES_KEY = "moderator:images:all"

# Allowed image extensions and safe filename pattern
ALLOWED_EXTS = {".png", ".jpg", ".heic"}
SAFE_IMAGE_RE = re.compile(r"^image_[0-9a-fA-F\-]+_\d+(?:_\d+)?\.(?:png|jpg|heic)$")

# Blueprint used by the main Flask app
moderator_bp = Blueprint("moderator", __name__, template_folder="templates")


def scan_asset_directory_to_redis(asset_dir: str) -> int:
    """Scan asset directory and populate Redis cache with all image filenames.
    
    Returns:
        Number of image files found and cached
    """
    t0 = time.time() if DEBUG_TIMING else None
    
    redis = get_redis_client()
    if not redis:
        if DEBUG_TIMING:
            print(f"[TIMING] scan_asset_directory_to_redis: Redis not available, skipping cache")
        return 0
    
    p = Path(asset_dir)
    if not p.exists():
        if DEBUG_TIMING:
            print(f"[TIMING] scan_asset_directory_to_redis: asset_dir not found: {asset_dir}")
        return 0
    
    # Find all image files matching the pattern
    image_files = set()
    for ext in ALLOWED_EXTS:
        for img_path in p.glob(f"image_*{ext}"):
            if SAFE_IMAGE_RE.match(img_path.name):
                image_files.add(img_path.name)
    
    # Store as a Redis set for O(1) membership checks
    if image_files:
        redis.delete(REDIS_IMAGES_KEY)  # Clear existing
        redis.sadd(REDIS_IMAGES_KEY, *image_files)
        # Set expiry to 1 hour
        redis.expire(REDIS_IMAGES_KEY, 3600)
    
    if DEBUG_TIMING:
        scan_time = time.time() - t0
        print(f"[TIMING] scan_asset_directory_to_redis: found {len(image_files)} images in {scan_time:.4f}s")
    
    return len(image_files)


def get_cached_images() -> Set[str]:
    """Get all image filenames from Redis cache.
    
    Returns:
        Set of image filenames, or empty set if cache is empty or Redis unavailable
    """
    redis = get_redis_client()
    if not redis:
        return set()
    try:
        return redis.smembers(REDIS_IMAGES_KEY)
    except Exception as e:
        if DEBUG_TIMING:
            print(f"[TIMING] get_cached_images: Redis error: {e}")
        return set()


def list_images_for(uuid: str, sid: int, asset_dir: str = None) -> List[str]:
    """Return filenames matching image_{uuid}_{sid}.* from Redis cache.

    Matches both image_{uuid}_{sid}.ext and image_{uuid}_{sid}_N.ext variants.
    
    Args:
        uuid: Word UUID
        sid: Definition ID
        asset_dir: Unused (kept for backward compatibility)
    """
    t0 = time.time() if DEBUG_TIMING else None
    
    # Get all images from cache
    all_images = get_cached_images()
    
    if not all_images:
        if DEBUG_TIMING:
            print(f"[TIMING] list_images_for({uuid[:8]}, {sid}): Redis cache is empty!")
        return []
    
    # Filter for this specific uuid/sid
    base = f"image_{uuid}_{sid}"
    files = []
    
    # Exact matches
    for ext in ALLOWED_EXTS:
        fname = f"{base}{ext}"
        if fname in all_images:
            files.append(fname)
    
    # Numbered variants
    prefix = f"{base}_"
    for fname in all_images:
        if fname.startswith(prefix) and fname not in files:
            files.append(fname)
    
    if DEBUG_TIMING:
        total_time = time.time() - t0
        print(f"[TIMING] list_images_for({uuid[:8]}, {sid}): found {len(files)} images in {total_time:.4f}s (Redis lookup)")
    
    return sorted(files)


def collect_rows_with_images(asset_dir: str, starting_letter: str = None, function_label: str = None) -> List[Dict]:
    """Collect definitions that have images from the database and Redis cache.
    
    Args:
        asset_dir: Directory containing image assets (used for cache warming only)
        starting_letter: Filter words by starting letter (case-insensitive). Use '-' for non-alphabetic.
    """
    overall_start = time.time() if DEBUG_TIMING else None
    
    # Ensure cache is populated
    redis = get_redis_client()
    cache_size = 0
    if redis:
        try:
            cache_size = redis.scard(REDIS_IMAGES_KEY)
        except Exception:
            cache_size = 0
            
    if cache_size == 0:
        if DEBUG_TIMING:
            print(f"[TIMING] Redis cache empty or unavailable, scanning asset directory...")
        scan_asset_directory_to_redis(asset_dir)
        if redis:
            try:
                cache_size = redis.scard(REDIS_IMAGES_KEY)
            except Exception:
                cache_size = 0
        if DEBUG_TIMING:
            print(f"[TIMING] Cache populated with {cache_size} images")
    elif DEBUG_TIMING:
        print(f"[TIMING] Using cached images ({cache_size} files)")
    
    # Import the unified Dictionary factory at runtime to avoid import-time side-effects
    from libs.dictionary import Dictionary
    from libs.sqlite_dictionary import Flags

    db = Dictionary()
    rows: List[Dict] = []
    try:
        # Pass function_label to DB query if provided
        query_start = time.time() if DEBUG_TIMING else None
        results = db.get_all_definitions_with_words(starting_letter=starting_letter, function_label=function_label)
        query_time = time.time() - query_start if DEBUG_TIMING else 0
        if DEBUG_TIMING:
            print(f"[TIMING] SQL query returned {len(results)} definitions in {query_time:.4f}s")
        lookup_start = time.time() if DEBUG_TIMING else None
        lookup_count = 0
        image_found_count = 0
        for r in results:
            lookup_count += 1
            images = list_images_for(r['uuid'], r['def_id'])
            if images:
                image_found_count += 1
                flags = Flags.from_int(r['flags'])
                rows.append(
                    {
                        "uuid": r['uuid'],
                        "id": r['def_id'],
                        "word": r['word'],
                        "functional_label": r['functional_label'],
                        "flags": {
                            "offensive": flags.offensive,
                            "british": flags.british,
                            "us": flags.us,
                            "old_fashioned": flags.old_fashioned,
                            "informal": flags.informal,
                        },
                        "definition": r['definition'],
                        "images": images,
                    }
                )
        if DEBUG_TIMING:
            lookup_time = time.time() - lookup_start
            total_time = time.time() - overall_start
            print(f"[TIMING] Redis lookups: {lookup_count} definitions checked, {image_found_count} with images, took {lookup_time:.4f}s")
            print(f"[TIMING] Total collect_rows_with_images: {total_time:.4f}s (query={query_time:.4f}s, redis={lookup_time:.4f}s)")
            print(f"[TIMING] Breakdown: SQL={query_time/total_time*100:.1f}%, Redis={lookup_time/total_time*100:.1f}%")
    finally:
        try:
            db.close()
        except Exception:
            pass
    return rows


@moderator_bp.route("/")
def index():
    # Just render the template without data - AJAX will load it
    return render_template("moderator.html")


@moderator_bp.route("/api/definitions")
def get_definitions():
    """API endpoint to get definitions with images via AJAX.
    Query params:
        letter: Filter by starting letter (a-z or '-' for non-alphabetic)
        function_label: Filter by function label (noun, verb, adverb, adjective)
    """
    from flask import request
    request_start = time.time() if DEBUG_TIMING else None
    asset_dir = current_app.config.get("ASSET_DIRECTORY") or os.getenv("ASSET_DIRECTORY", "assets_hires")
    starting_letter = request.args.get("letter", None)
    function_label = request.args.get("function_label", None)
    if DEBUG_TIMING:
        print(f"\n[TIMING] ========== API REQUEST: /api/definitions?letter={starting_letter}&function_label={function_label} ==========")
    rows = collect_rows_with_images(asset_dir, starting_letter, function_label)
    if DEBUG_TIMING:
        total_time = time.time() - request_start
        print(f"[TIMING] Total API response time: {total_time:.4f}s for {len(rows)} definitions")
        print(f"[TIMING] ========== END REQUEST ==========\n")
    return jsonify({"definitions": rows})


@moderator_bp.route("/api/refresh-cache", methods=["POST"])
def refresh_cache():
    """Manually refresh the Redis cache by rescanning the asset directory."""
    try:
        asset_dir = current_app.config.get("ASSET_DIRECTORY") or os.getenv("ASSET_DIRECTORY", "assets_hires")
        count = scan_asset_directory_to_redis(asset_dir)
        return jsonify({"ok": True, "images_cached": count})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@moderator_bp.route("/api/delete-conceptual-images", methods=["POST"])
def delete_conceptual_images_endpoint():
    """Trigger async deletion of conceptual images (non-noun/verb)."""
    try:
        # Import Celery task
        from celery_tasks import delete_conceptual_images
        
        # Get paths from config/env
        db_path = current_app.config.get("DATABASE_PATH") or os.getenv("DATABASE_PATH")
        asset_dir = current_app.config.get("ASSET_DIRECTORY") or os.getenv("ASSET_DIRECTORY", "assets_hires")
        
        # Queue the task
        task = delete_conceptual_images.delay(db_path, asset_dir)
        
        return jsonify({
            "ok": True,
            "task_id": task.id,
            "message": "Deletion task queued"
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@moderator_bp.route("/asset/<path:filename>", methods=["GET"])  # serve images from ASSET_DIRECTORY
def serve_asset(filename: str):
    # Prevent directory traversal and enforce naming/extension
    if not SAFE_IMAGE_RE.match(filename):
        abort(400, description="Invalid filename")
    asset_dir = current_app.config.get("ASSET_DIRECTORY") or os.getenv("ASSET_DIRECTORY", "assets_hires")
    full = Path(asset_dir) / filename
    if not full.exists():
        abort(404)
    return send_from_directory(asset_dir, filename)


@moderator_bp.route("/asset/<path:filename>", methods=["DELETE"])  # delete an image
def delete_asset(filename: str):
    # Validate filename strictly
    if not SAFE_IMAGE_RE.match(filename):
        return jsonify({"ok": False, "error": "invalid filename"}), 400

    asset_dir = current_app.config.get("ASSET_DIRECTORY") or os.getenv("ASSET_DIRECTORY", "assets_hires")
    target = (Path(asset_dir) / filename).resolve()
    assets_root = Path(asset_dir).resolve()
    try:
        # Ensure target is within assets_root
        target.relative_to(assets_root)
    except Exception:
        return jsonify({"ok": False, "error": "unsafe path"}), 400

    if not target.exists():
        return jsonify({"ok": False, "missing": True}), 404

    try:
        # Remove from Redis cache FIRST (assume cache is correct)
        redis = get_redis_client()
        if redis:
            try:
                removed_from_cache = redis.srem(REDIS_IMAGES_KEY, filename)
                if DEBUG_TIMING:
                    print(f"[TIMING] delete_asset: removed '{filename}' from Redis cache (existed={removed_from_cache})")
            except Exception as e:
                if DEBUG_TIMING:
                    print(f"[TIMING] delete_asset: Redis error: {e}")
        
        # Then delete the file
        target.unlink()
        
        if DEBUG_TIMING:
            print(f"[TIMING] delete_asset: deleted file '{filename}'")
        
        return jsonify({"ok": True})
    except Exception as e:
        if DEBUG_TIMING:
            print(f"[TIMING] delete_asset: error deleting '{filename}': {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    # Allow running this module standalone for development
    temp_app = Flask(__name__)
    temp_app.register_blueprint(moderator_bp, url_prefix="/moderator")
    asset_dir = os.getenv("ASSET_DIRECTORY", "assets_hires")
    Path(asset_dir).mkdir(parents=True, exist_ok=True)
    temp_app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5001")), debug=os.getenv("FLASK_DEBUG", "0") in ("1", "true", "True"))
