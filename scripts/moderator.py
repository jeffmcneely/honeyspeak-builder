import os
import re
from pathlib import Path
from typing import List, Dict

from dotenv import load_dotenv
from flask import Blueprint, Flask, jsonify, url_for, send_from_directory, render_template, abort, current_app

load_dotenv()

# Allowed image extensions and safe filename pattern
ALLOWED_EXTS = {".png", ".jpg", ".heic"}
SAFE_IMAGE_RE = re.compile(r"^image_[0-9a-fA-F\-]+_\d+(?:_\d+)?\.(?:png|jpg|heic)$")

# Blueprint used by the main Flask app
moderator_bp = Blueprint("moderator", __name__, template_folder="templates")


def list_images_for(uuid: str, sid: int, asset_dir: str) -> List[str]:
    """Return filenames in asset_dir matching image_{uuid}_{sid}.* with allowed extensions.

    Matches both image_{uuid}_{sid}.ext and image_{uuid}_{sid}_N.ext variants.
    """
    files: List[str] = []
    base = f"image_{uuid}_{sid}"
    p = Path(asset_dir)
    if not p.exists():
        return files

    # Exact matches
    for ext in ALLOWED_EXTS:
        candidate = p / f"{base}{ext}"
        if candidate.exists():
            files.append(candidate.name)

    # Numbered variants
    for child in p.glob(f"{base}_*.*"):
        name = child.name
        if SAFE_IMAGE_RE.match(name) and child.suffix.lower() in ALLOWED_EXTS:
            files.append(name)

    return sorted(set(files))


def collect_rows_with_images(asset_dir: str, starting_letter: str = None) -> List[Dict]:
    """Collect definitions that have images from the database and assets folder.
    
    Args:
        asset_dir: Directory containing image assets
        starting_letter: Filter words by starting letter (case-insensitive). Use '-' for non-alphabetic.
    """
    # Import the unified Dictionary factory at runtime to avoid import-time side-effects
    from libs.dictionary import Dictionary
    from libs.sqlite_dictionary import Flags

    db = Dictionary()
    rows: List[Dict] = []
    try:
        # OPTIMIZED: Single query with SQL-level filtering by starting letter
        # This pushes the letter filter into the database query instead of Python
        results = db.get_all_definitions_with_words(starting_letter=starting_letter)
        
        for r in results:
            images = list_images_for(r['uuid'], r['def_id'], asset_dir)
            # Only include definitions that have images
            if images:
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
    """
    from flask import request
    
    asset_dir = current_app.config.get("ASSET_DIRECTORY") or os.getenv("ASSET_DIRECTORY", "assets_hires")
    starting_letter = request.args.get("letter", None)
    rows = collect_rows_with_images(asset_dir, starting_letter)
    return jsonify({"definitions": rows})


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
        target.unlink()
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    # Allow running this module standalone for development
    temp_app = Flask(__name__)
    temp_app.register_blueprint(moderator_bp, url_prefix="/moderator")
    asset_dir = os.getenv("ASSET_DIRECTORY", "assets_hires")
    Path(asset_dir).mkdir(parents=True, exist_ok=True)
    temp_app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5001")), debug=os.getenv("FLASK_DEBUG", "0") in ("1", "true", "True"))
