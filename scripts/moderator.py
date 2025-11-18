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
redis_connection_attempted = False  # Track if we've already tried to connect

def get_redis_client():
    """Get or create Redis client lazily. Only logs connection failure once."""
    global redis_client, redis_connection_attempted
    
    # If we've already tried and failed, return None immediately
    if redis_connection_attempted and redis_client is None:
        return None
    
    if redis_client is None and not redis_connection_attempted:
        redis_connection_attempted = True  # Mark that we've tried
        try:
            import redis as redis_module
            
            # Try to use CELERY_BROKER_URL if available (from Kubernetes/Docker env)
            broker_url = os.getenv("CELERY_BROKER_URL")
            if broker_url and broker_url.startswith("redis://"):
                # Parse redis://host:port/db format
                redis_client = redis_module.from_url(broker_url, decode_responses=True)
            else:
                # Fall back to individual env vars with robust parsing
                redis_host = os.getenv("REDIS_HOST", "redis")
                redis_port = os.getenv("REDIS_PORT", "6379")
                redis_db = os.getenv("REDIS_DB", "0")
                
                # Handle cases where port/db might be URLs or invalid values
                try:
                    # Extract port number if it's a URL (e.g., tcp://host:port)
                    if "://" in redis_port:
                        # Extract port from URL format
                        import re
                        port_match = re.search(r':(\d+)$', redis_port)
                        if port_match:
                            redis_port = port_match.group(1)
                        else:
                            redis_port = "6379"  # Default fallback
                    
                    port_int = int(redis_port)
                    db_int = int(redis_db)
                except (ValueError, TypeError):
                    print(f"[MODERATOR] Invalid Redis port/db values: port={redis_port}, db={redis_db}, using defaults")
                    port_int = 6379
                    db_int = 0
                
                redis_client = redis_module.Redis(
                    host=redis_host,
                    port=port_int,
                    db=db_int,
                    decode_responses=True
                )
            
            # Test connection
            redis_client.ping()
            print("[MODERATOR] Redis connection established")
        except Exception as e:
            # Log once, then use filesystem fallback silently
            print(f"[MODERATOR] Redis not available, using filesystem fallback for image lookups")
            if DEBUG_TIMING:
                print(f"[MODERATOR DEBUG] Redis error details: {e}")
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
    
    # Find all image files matching the pattern (recursively scan subdirectories)
    image_files = set()
    for ext in ALLOWED_EXTS:
        for img_path in p.rglob(f"image_*{ext}"):
            if SAFE_IMAGE_RE.match(img_path.name):
                # Store relative path from asset_dir to support subdirectories
                rel_path = str(img_path.relative_to(p))
                image_files.add(rel_path)
    
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
    """Return filenames matching image_{uuid}_{sid}.* from Redis cache or filesystem.

    Matches both image_{uuid}_{sid}.ext and image_{uuid}_{sid}_N.ext variants.
    
    Args:
        uuid: Word UUID
        sid: Definition ID
        asset_dir: Asset directory path (used for filesystem fallback)
    """
    t0 = time.time() if DEBUG_TIMING else None
    
    # DEBUG: Always log what we're searching for
    print(f"[MODERATOR DEBUG] list_images_for: uuid={uuid}, sid={sid}, asset_dir={asset_dir}")
    
    # Try to get all images from Redis cache first
    all_images = get_cached_images()
    
    # If Redis cache is empty, fall back to filesystem scan
    if not all_images:
        if DEBUG_TIMING:
            print(f"[TIMING] list_images_for({uuid[:8]}, {sid}): Redis cache empty, falling back to filesystem")
        
        # Need asset_dir for filesystem fallback
        if not asset_dir:
            asset_dir = current_app.config.get("ASSET_DIRECTORY") or os.getenv("ASSET_DIRECTORY", "assets_hires")
        
        print(f"[MODERATOR DEBUG] Filesystem fallback: asset_dir={asset_dir}")
        
        # Direct filesystem check for this specific uuid/sid
        p = Path(asset_dir)
        if not p.exists():
            print(f"[MODERATOR DEBUG] Asset directory does not exist: {asset_dir}")
            return []
        
        print(f"[MODERATOR DEBUG] Asset directory exists, searching for image_{uuid}_{sid}.*")
        
        files = []
        base = f"image_{uuid}_{sid}"
        
        # Check exact matches (search recursively in subdirectories)
        for ext in ALLOWED_EXTS:
            fname = f"{base}{ext}"
            for img_path in p.rglob(fname):
                if SAFE_IMAGE_RE.match(img_path.name):
                    rel_path = str(img_path.relative_to(p))
                    files.append(rel_path)
        
        # Check numbered variants (e.g., image_uuid_sid_1.png)
        prefix = f"{base}_"
        for img_path in p.rglob(f"{prefix}*"):
            if SAFE_IMAGE_RE.match(img_path.name):
                rel_path = str(img_path.relative_to(p))
                if rel_path not in files:
                    files.append(rel_path)
        
        print(f"[MODERATOR DEBUG] Filesystem scan found {len(files)} images for {uuid}_{sid}")
        if files:
            print(f"[MODERATOR DEBUG] Found files: {files}")
        
        if DEBUG_TIMING:
            total_time = time.time() - t0
            print(f"[TIMING] list_images_for({uuid[:8]}, {sid}): found {len(files)} images in {total_time:.4f}s (filesystem fallback)")
        
        return sorted(files)
    
    # Redis cache available - use it for fast lookups
    base = f"image_{uuid}_{sid}"
    files = []
    
    # Check all cached paths (could be just filename or path with subdirs)
    for cached_path in all_images:
        # Extract just the filename from the path
        cached_filename = Path(cached_path).name
        
        # Exact matches
        for ext in ALLOWED_EXTS:
            target_fname = f"{base}{ext}"
            if cached_filename == target_fname and cached_path not in files:
                files.append(cached_path)
        
        # Numbered variants
        prefix = f"{base}_"
        if cached_filename.startswith(prefix) and SAFE_IMAGE_RE.match(cached_filename) and cached_path not in files:
            files.append(cached_path)
    
    if DEBUG_TIMING:
        total_time = time.time() - t0
        print(f"[TIMING] list_images_for({uuid[:8]}, {sid}): found {len(files)} images in {total_time:.4f}s (Redis lookup)")
    
    return sorted(files)


def collect_rows_with_images(asset_dir: str, starting_letter: str = None, function_label: str = None) -> List[Dict]:
    """Collect definitions that have images from the database and Redis cache (or filesystem fallback).
    
    Args:
        asset_dir: Directory containing image assets (used for cache warming and filesystem fallback)
        starting_letter: Filter words by starting letter (case-insensitive). Use '-' for non-alphabetic.
    """
    overall_start = time.time() if DEBUG_TIMING else None
    
    print(f"[MODERATOR DEBUG] collect_rows_with_images: asset_dir={asset_dir}, starting_letter={starting_letter}, function_label={function_label}")
    
    # Try to ensure Redis cache is populated (if Redis is available)
    redis = get_redis_client()
    cache_size = 0
    using_redis = False
    
    if redis:
        try:
            cache_size = redis.scard(REDIS_IMAGES_KEY)
        except Exception:
            cache_size = 0
            
        if cache_size == 0:
            if DEBUG_TIMING:
                print(f"[TIMING] Redis cache empty, scanning asset directory...")
            scan_asset_directory_to_redis(asset_dir)
            try:
                cache_size = redis.scard(REDIS_IMAGES_KEY)
                using_redis = cache_size > 0
            except Exception:
                cache_size = 0
            if DEBUG_TIMING:
                print(f"[TIMING] Cache populated with {cache_size} images")
        else:
            using_redis = True
            if DEBUG_TIMING:
                print(f"[TIMING] Using Redis cache ({cache_size} files)")
    else:
        if DEBUG_TIMING:
            print(f"[TIMING] Redis not available, will use filesystem fallback for each definition")
        using_redis = False
    
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
        print(f"[MODERATOR DEBUG] SQL query returned {len(results)} definitions")
        if results and len(results) > 0:
            print(f"[MODERATOR DEBUG] First result: word={results[0]['word']}, uuid={results[0]['uuid']}, def_id={results[0]['def_id']}")
        if DEBUG_TIMING:
            print(f"[TIMING] SQL query returned {len(results)} definitions in {query_time:.4f}s")
        lookup_start = time.time() if DEBUG_TIMING else None
        lookup_count = 0
        image_found_count = 0
        for r in results:
            lookup_count += 1
            # Pass asset_dir for filesystem fallback
            images = list_images_for(r['uuid'], r['def_id'], asset_dir)
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
            mode = "Redis" if using_redis else "filesystem"
            print(f"[TIMING] Image lookups: {lookup_count} definitions checked, {image_found_count} with images, took {lookup_time:.4f}s ({mode})")
            print(f"[TIMING] Total collect_rows_with_images: {total_time:.4f}s (query={query_time:.4f}s, lookups={lookup_time:.4f}s)")
            print(f"[TIMING] Breakdown: SQL={query_time/total_time*100:.1f}%, Lookups={lookup_time/total_time*100:.1f}%")
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


@moderator_bp.route("/migration")
def migration():
    """Migration tools page for file reorganization."""
    return render_template("migration.html")


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
        from scripts.celery_tasks import delete_conceptual_images
        
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


@moderator_bp.route("/api/relocate-files", methods=["POST"])
def relocate_files_endpoint():
    """Trigger async file relocation task."""
    try:
        # Import Celery task
        from scripts.celery_tasks import relocate_files as relocate_files_task
        
        # Get asset directory from config/env
        asset_dir = current_app.config.get("ASSET_DIRECTORY") or os.getenv("ASSET_DIRECTORY", "assets_hires")
        
        # Queue the task
        task = relocate_files_task.delay(asset_dir)
        
        return jsonify({
            "ok": True,
            "task_id": task.id,
            "message": "File relocation task queued"
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@moderator_bp.route("/api/clean-packages", methods=["POST"])
def clean_packages_endpoint():
    """Trigger async package cleanup task."""
    try:
        # Import Celery task
        from scripts.celery_tasks import clean_packages
        
        # Get directories from config/env
        asset_dir = os.getenv("STORAGE_DIRECTORY", "asset_library")
        package_dir = os.path.join(asset_dir, "packages")
        
        # Queue the task
        task = clean_packages.delay(asset_dir, package_dir)
        
        return jsonify({
            "ok": True,
            "task_id": task.id,
            "message": "Package cleanup task queued"
        })
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@moderator_bp.route("/asset/<path:filename>", methods=["GET"])  # serve images from ASSET_DIRECTORY
def serve_asset(filename: str):
    # Extract just the filename from the path for validation
    base_filename = Path(filename).name
    
    # Prevent directory traversal and enforce naming/extension on the actual filename
    if not SAFE_IMAGE_RE.match(base_filename):
        abort(400, description="Invalid filename")
    
    asset_dir = current_app.config.get("ASSET_DIRECTORY") or os.getenv("ASSET_DIRECTORY", "assets_hires")
    full = Path(asset_dir) / filename
    
    # Ensure the resolved path is within asset_dir (prevent directory traversal)
    try:
        full.resolve().relative_to(Path(asset_dir).resolve())
    except ValueError:
        abort(400, description="Invalid path")
    
    if not full.exists():
        abort(404)
    
    # Serve from the parent directory, with the relative path
    return send_from_directory(asset_dir, filename)


@moderator_bp.route("/asset/<path:filename>", methods=["DELETE"])  # delete an image
def delete_asset(filename: str):
    """Delete an image asset and optionally queue rename task for variant 1->0."""
    print(f"[DELETE_ASSET] Starting deletion for: {filename}")
    
    # Extract just the filename from the path for validation (handle subdirectories)
    base_filename = Path(filename).name
    print(f"[DELETE_ASSET] Base filename: {base_filename}")
    
    # Validate the actual filename strictly
    if not SAFE_IMAGE_RE.match(base_filename):
        print(f"[DELETE_ASSET] Invalid filename pattern: {base_filename}")
        return jsonify({"ok": False, "error": "invalid filename"}), 400

    asset_dir = current_app.config.get("ASSET_DIRECTORY") or os.getenv("ASSET_DIRECTORY", "assets_hires")
    print(f"[DELETE_ASSET] Asset directory: {asset_dir}")
    
    target = (Path(asset_dir) / filename).resolve()
    assets_root = Path(asset_dir).resolve()
    print(f"[DELETE_ASSET] Target path: {target}")
    print(f"[DELETE_ASSET] Assets root: {assets_root}")
    
    try:
        # Ensure target is within assets_root
        target.relative_to(assets_root)
        print(f"[DELETE_ASSET] Path validation passed")
    except Exception as e:
        print(f"[DELETE_ASSET] Path validation failed: {e}")
        return jsonify({"ok": False, "error": "unsafe path"}), 400

    if not target.exists():
        print(f"[DELETE_ASSET] File does not exist: {target}")
        return jsonify({"ok": False, "missing": True}), 404

    try:
        # Check if this is a variant 0 image before deletion
        # Pattern: image_{uuid}_{def_id}_0.{ext}
        variant_0_match = re.match(r"^image_([0-9a-fA-F\-]+)_(\d+)_0\.(?:png|jpg|heic)$", base_filename)
        
        if variant_0_match:
            print(f"[DELETE_ASSET] Detected variant 0 image: uuid={variant_0_match.group(1)}, def_id={variant_0_match.group(2)}")
        else:
            print(f"[DELETE_ASSET] Not a variant 0 image (or different pattern)")
        
        # Remove from Redis cache FIRST (assume cache is correct)
        redis = get_redis_client()
        if redis:
            try:
                removed_from_cache = redis.srem(REDIS_IMAGES_KEY, filename)
                print(f"[DELETE_ASSET] Removed from Redis cache: {removed_from_cache > 0}")
            except Exception as e:
                print(f"[DELETE_ASSET] Redis error during cache removal: {e}")
        else:
            print(f"[DELETE_ASSET] Redis not available, skipping cache removal")
        
        # Then delete the file
        print(f"[DELETE_ASSET] Deleting file: {target}")
        target.unlink()
        print(f"[DELETE_ASSET] File deleted successfully")
        
        # If variant 0 was deleted, queue task to rename variant 1 to variant 0 after 30 seconds
        if variant_0_match:
            uuid = variant_0_match.group(1)
            def_id = int(variant_0_match.group(2))
            
            print(f"[DELETE_ASSET] Queueing rename task for uuid={uuid}, def_id={def_id}")
            
            try:
                from scripts.celery_tasks import rename_image_variant
                # Queue task with 30 second countdown
                task = rename_image_variant.apply_async(
                    args=(asset_dir, uuid, def_id),
                    countdown=30
                )
                print(f"[DELETE_ASSET] Rename task queued successfully: task_id={task.id}, countdown=30s")
                print(f"[DELETE_ASSET] Task args: asset_dir={asset_dir}, uuid={uuid}, def_id={def_id}")
            except Exception as e:
                # Fail silently - don't block the delete operation
                print(f"[DELETE_ASSET] ERROR: Failed to queue rename task: {e}")
                import traceback
                print(f"[DELETE_ASSET] Traceback: {traceback.format_exc()}")
        
        print(f"[DELETE_ASSET] Deletion completed successfully")
        return jsonify({"ok": True})
    except Exception as e:
        print(f"[DELETE_ASSET] ERROR during deletion: {e}")
        import traceback
        print(f"[DELETE_ASSET] Traceback: {traceback.format_exc()}")
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    # Allow running this module standalone for development
    temp_app = Flask(__name__)
    temp_app.register_blueprint(moderator_bp, url_prefix="/moderator")
    asset_dir = os.getenv("ASSET_DIRECTORY", "assets_hires")
    Path(asset_dir).mkdir(parents=True, exist_ok=True)
    temp_app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5001")), debug=os.getenv("FLASK_DEBUG", "0") in ("1", "true", "True"))
