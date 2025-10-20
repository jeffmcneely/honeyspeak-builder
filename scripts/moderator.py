import os
import re
from pathlib import Path
from typing import List, Dict

from dotenv import load_dotenv
from flask import Flask, request, jsonify, url_for, send_from_directory, render_template_string, abort

# Project DB API
try:
  from libs.sqlite_dictionary import SQLiteDictionary
except ModuleNotFoundError:
  # Fallback for alternate layouts (e.g., scripts/libs)
  import sys

  here = Path(__file__).parent
  # Add project root and potential scripts path
  sys.path.extend([str(here), str(here / "scripts"), str(here.parent)])
  try:
    from libs.sqlite_dictionary import SQLiteDictionary  # type: ignore
  except ModuleNotFoundError:
    from scripts.libs.sqlite_dictionary import SQLiteDictionary  # type: ignore


load_dotenv()

ASSET_DIRECTORY = os.getenv("ASSET_DIRECTORY", "assets_hires")
PORT = int(os.getenv("PORT", "5001"))
DEBUG = os.getenv("FLASK_DEBUG", "0") in ("1", "true", "True")

# Allowed image extensions and safe filename pattern
ALLOWED_EXTS = {".png", ".jpg", ".heic"}
SAFE_IMAGE_RE = re.compile(r"^image_[0-9a-fA-F\-]+_\d+\.(?:png|jpg|heic)$")

app = Flask(__name__)


def list_images_for(uuid: str, sid: int, asset_dir: str) -> List[str]:
    """Return filenames in asset_dir matching image_{uuid}_{sid}.* with allowed extensions."""
    files: List[str] = []
    base = f"image_{uuid}_{sid}"
    p = Path(asset_dir)
    if not p.exists():
        return files
    for ext in ALLOWED_EXTS:
        candidate = p / f"{base}{ext}"
        if candidate.exists():
            files.append(candidate.name)
    # Also include any additional numbered variants e.g., image_uuid_id_1.png
    for child in p.glob(f"{base}_*.*"):
        name = child.name
        if SAFE_IMAGE_RE.match(name) and child.suffix.lower() in ALLOWED_EXTS:
            files.append(name)
    return sorted(set(files))


def collect_rows(asset_dir: str) -> List[Dict]:
    db = SQLiteDictionary()
    rows: List[Dict] = []
    try:
        words = db.get_all_words()
        for w in words:
            for sd in db.get_shortdefs(w.uuid):
                rows.append(
                    {
                        "uuid": sd.uuid,
                        "id": sd.id,
                        "definition": sd.definition,
                        "images": list_images_for(sd.uuid, sd.id, asset_dir),
                    }
                )
    finally:
        db.close()
    return rows


@app.route("/")
def index():
    asset_dir = ASSET_DIRECTORY
    rows = collect_rows(asset_dir)
    return render_template_string(
        TEMPLATE,
        rows=rows,
        asset_dir=asset_dir,
    )


@app.route("/asset/<path:filename>", methods=["GET"])  # serve images from ASSET_DIRECTORY
def serve_asset(filename: str):
    # Prevent directory traversal and enforce naming/extension
    if not SAFE_IMAGE_RE.match(filename):
        abort(400, description="Invalid filename")
    full = Path(ASSET_DIRECTORY) / filename
    if not full.exists():
        abort(404)
    return send_from_directory(ASSET_DIRECTORY, filename)


@app.route("/asset/<path:filename>", methods=["DELETE"])  # delete an image
def delete_asset(filename: str):
    # Validate filename strictly
    if not SAFE_IMAGE_RE.match(filename):
        return jsonify({"ok": False, "error": "invalid filename"}), 400

    target = (Path(ASSET_DIRECTORY) / filename).resolve()
    assets_root = Path(ASSET_DIRECTORY).resolve()
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


TEMPLATE = r"""
<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Asset Moderator</title>
    <style>
      :root { --thumb-w: 90px; --thumb-h: 160px; --gap: 8px; }
      body { font-family: system-ui, -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 16px; }
      header { display: flex; align-items: baseline; gap: 8px; margin-bottom: 12px; }
      .rows { display: grid; grid-template-columns: 1fr; gap: 14px; }
      .row { border: 1px solid #e2e2e2; border-radius: 8px; padding: 12px; }
      .meta { font-size: 12px; color: #444; margin-bottom: 6px; display: flex; gap: 12px; flex-wrap: wrap; }
      .def { font-size: 14px; margin-bottom: 8px; }
      .images { display: flex; flex-wrap: wrap; gap: var(--gap); }
      .imgwrap { position: relative; width: var(--thumb-w); height: var(--thumb-h); overflow: hidden; border-radius: 6px; border: 1px solid #ddd; background: #fafafa; transition: opacity .2s ease, transform .2s ease; }
      .imgwrap.removing { opacity: 0.2; transform: scale(0.95); }
      img.thumb { width: var(--thumb-w); height: var(--thumb-h); object-fit: cover; display: block; }
      .empty { color: #888; font-size: 12px; }
      .pill { background: #f1f3f5; border-radius: 999px; padding: 2px 8px; font-size: 11px; }
      .actions { font-size: 12px; color: #666; }
      @media (min-width: 900px) { .rows { grid-template-columns: 1fr 1fr; } }
      @media (min-width: 1400px) { .rows { grid-template-columns: 1fr 1fr 1fr; } }
    </style>
  </head>
  <body>
    <header>
      <h2>Asset Moderator</h2>
      <span class="pill">assets: {{ asset_dir }}</span>
    </header>
    <div class="rows">
      {% for r in rows %}
        <div class="row" data-uuid="{{ r.uuid }}" data-id="{{ r.id }}">
          <div class="meta">
            <div><strong>uuid</strong>: {{ r.uuid }}</div>
            <div><strong>id</strong>: {{ r.id }}</div>
            <div class="actions">click an image to delete</div>
          </div>
          <div class="def">{{ r.definition }}</div>
          <div class="images">
            {% if r.images %}
              {% for f in r.images %}
                <div class="imgwrap" data-filename="{{ f }}">
                  <img class="thumb" src="{{ url_for('serve_asset', filename=f) }}" alt="{{ f }}" title="{{ f }}"/>
                </div>
              {% endfor %}
            {% else %}
              <div class="empty">No images found</div>
            {% endif %}
          </div>
        </div>
      {% endfor %}
    </div>
    <script>
      async function deleteImage(el) {
        const wrap = el.closest('.imgwrap');
        if (!wrap) return;
        const file = wrap.dataset.filename;
        if (!file) return;
        try {
          wrap.classList.add('removing');
          const resp = await fetch(`/asset/${encodeURIComponent(file)}`, { method: 'DELETE' });
          const data = await resp.json().catch(() => ({}));
          if (!resp.ok || !data.ok) {
            console.error('Delete failed', data);
            wrap.classList.remove('removing');
            return;
          }
          // Remove after transition
          setTimeout(() => wrap.remove(), 220);
        } catch (e) {
          console.error('Error deleting', e);
          wrap.classList.remove('removing');
        }
      }

      document.addEventListener('click', (e) => {
        const img = e.target.closest('img.thumb');
        if (img) {
          e.preventDefault();
          deleteImage(img);
        }
      });
    </script>
  </body>
</html>
"""


if __name__ == "__main__":
    Path(ASSET_DIRECTORY).mkdir(parents=True, exist_ok=True)
    app.run(host="0.0.0.0", port=PORT, debug=DEBUG)
