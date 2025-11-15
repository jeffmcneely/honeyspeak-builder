# =====================================================================
# ⚠️  DEPRECATED SCRIPT - DO NOT USE
# =====================================================================
# This CLI script is deprecated and should not be used.
# Use the Flask web service instead: http://localhost:5002/build_package
#
# Replacement:
#   - Web interface: Navigate to /build_package
#   - Click "Start Packaging" button
#   - Tasks automatically transcode/downscale assets (ffmpeg/ImageMagick)
#   - Creates zip packages via 16 parallel Celery tasks [a-f, 0-9]
#   - Download SQLite DB + packages from /download page
#
# Why deprecated:
#   - Processes assets sequentially (slow for large databases)
#   - No parallel encoding/packaging
#   - No web-based download interface
#   - All functionality is now in Flask API + Celery tasks:
#     * package_all_assets: Orchestrates packaging
#     * package_asset_group: Packages assets for specific letter
#
# NOTE: The external_assets table is also deprecated.
#
# See DEPRECATED_SCRIPTS.md for migration guide.
# =====================================================================

import os
import subprocess
import shutil
import argparse
from libs.dictionary import Dictionary
from rich.progress import track
from dotenv import load_dotenv
from zipfile import ZipFile
from os import path
import re

# Load environment variables from .env file
load_dotenv()

OUTDIR = "assets_hires"
MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


load_dotenv()  # Load .env file if present


def encode_audio(file: str, bitrate) -> str | None:
    """Encode to low-bitrate mono mp3 using ffmpeg
    
    Checks for audio files in two locations:
    1. OUTDIR/audio/{file} (new organized structure)
    2. OUTDIR/{file} (legacy location)
    """
    # Try new audio/ subdirectory first
    raw_path_new = os.path.join(OUTDIR, "audio", f"{file}")
    raw_path_legacy = os.path.join(OUTDIR, f"{file}")
    low_path = os.path.join(OUTDIR, f"low_{file}")
    
    # Determine which path exists
    if os.path.exists(raw_path_new):
        raw_path = raw_path_new
        print(f"[encode_audio] Found audio file in audio/: {raw_path}")
    elif os.path.exists(raw_path_legacy):
        raw_path = raw_path_legacy
        print(f"[encode_audio] Found audio file in root: {raw_path}")
    else:
        print(f"[encode_audio] Raw file NOT FOUND. Tried:")
        print(f"  - {raw_path_new}")
        print(f"  - {raw_path_legacy}")
        return None
    
    if os.path.exists(low_path):
        print(f"[encode_audio] Low file already exists: {low_path}")
        return low_path

    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                raw_path,
                "-ac",
                "1",  # mono
                "-b:a",
                f"{bitrate}k",  # target bitrate
                "-ar",
                "24000",  # optional: resample
                low_path,
                "-loglevel",
                "quiet",
            ],
            check=True,
        )
        print(f"[encode_audio] Successfully encoded: {low_path}")
        return low_path
    except subprocess.CalledProcessError as e:
        print(f"Error running ffmpeg: {e}")
        print(
            "Command:",
            " ".join(
                [
                    "ffmpeg",
                    "-y",
                    "-i",
                    raw_path,
                    "-ac",
                    "1",
                    "-b:a",
                    f"{bitrate}k",
                    "-ar",
                    "24000",
                    low_path,
                    "-loglevel",
                    "quiet",
                ]
            ),
        )
        raise


def encode_image(file: str) -> str | None:
    """Reduce image resolution by half using ImageMagick
    
    Checks for image files in two locations:
    1. OUTDIR/image/{file} (new organized structure)
    2. OUTDIR/{file} (legacy location)
    """
    # Try new image/ subdirectory first
    raw_path_new = os.path.join(OUTDIR, "image", f"{file}")
    raw_path_legacy = os.path.join(OUTDIR, f"{file}")
    base_name = os.path.splitext(file)[0]
    low_path = os.path.join(OUTDIR, f"low_{base_name}.heif")
    
    # Determine which path exists
    if os.path.exists(raw_path_new):
        raw_path = raw_path_new
        print(f"[encode_image] Found image file in image/: {raw_path}")
    elif os.path.exists(raw_path_legacy):
        raw_path = raw_path_legacy
        print(f"[encode_image] Found image file in root: {raw_path}")
    else:
        print(f"[encode_image] Raw file NOT FOUND. Tried:")
        print(f"  - {raw_path_new}")
        print(f"  - {raw_path_legacy}")
        return None

    if os.path.exists(low_path):
        print(f"[encode_image] Low file already exists: {low_path}")
        return low_path
    try:
        subprocess.run(
            [
                "magick",
                raw_path,
                "-resize",
                "50%",
                "-quality",
                "25",
                low_path,
            ],
            check=True,
        )
        print(f"[encode_image] Successfully encoded: {low_path}")
        return low_path
    except subprocess.CalledProcessError as e:
        print(f"Error running ImageMagick: {e}")
        print(
            "Command:",
            " ".join(
                [
                    "magick",
                    raw_path,
                    "-resize",
                    "50%",
                    "-quality",
                    "25",
                    low_path,
                ]
            ),
        )
        raise


def store_file(filename: str) -> str | None:
    package_id = 0
    path_re = "low_(?:image|word|shortdef|)_([a-z0-9])"
    match = re.search(path_re, filename)
    if match:
        first_letter = match.group(1)  # get the character after 'low_'
    else:
        first_letter = os.path.basename(filename)[0]
    
    print(f"[store_file] Attempting to store: {filename}")
    print(f"[store_file] File exists: {path.exists(filename)}")
    print(f"[store_file] Extracted letter: {first_letter}")
    
    if not path.exists(filename):
        print(f"[store_file] ERROR: File not found: {filename}")
        return None
    
    while True:
        package_file = path.join("assets", f"package_{first_letter}{package_id}.zip")
        print(f"[store_file] Trying package: {package_file}")
        
        if path.exists(package_file):
            size = path.getsize(package_file)
            print(f"[store_file] Package exists, size: {size} bytes (max: {MAX_FILE_SIZE})")
            if size > MAX_FILE_SIZE:
                package_id += 1
                continue
        
        with ZipFile(package_file, "a") as package:
            arcname = os.path.basename(filename)
            if arcname in package.namelist():
                print(f"[store_file] {arcname} already exists in {package_file}")
                return f"{first_letter}{package_id}"
            package.write(filename, arcname=arcname)
            print(f"[store_file] ✓ Stored {arcname} into {package_file}")
            return f"{first_letter}{package_id}"


def clean_packages() -> None:
    assets_dir = "assets"
    if not os.path.exists(assets_dir):
        print(f"[clean_packages] Creating assets directory: {assets_dir}")
        os.makedirs(assets_dir, exist_ok=True)
        return
    
    print(f"[clean_packages] Cleaning packages in {assets_dir}")
    count = 0
    for filename in os.listdir(assets_dir):
        if filename.startswith("package_") and filename.endswith(".zip"):
            filepath = os.path.join(assets_dir, filename)
            os.remove(filepath)
            count += 1
            print(f"[clean_packages] Deleted: {filepath}")
    print(f"[clean_packages] Deleted {count} package file(s)")


def main():
    """
    DEPRECATED: This standalone packaging script is deprecated.
    
    Use the Celery task system instead:
        from celery_tasks import package_all_assets
        task = package_all_assets.delay(db_path, asset_dir, package_dir)
    
    The package_all_assets task will launch 16 parallel tasks for [a-f, 0-9]
    and does NOT write to the external_assets table (which is deprecated).
    """
    parser = argparse.ArgumentParser(description="Package assets for distribution")
    parser.add_argument(
        "--dryrun", action="store_true", help="Show actions without writing files"
    )
    parser.add_argument(
        "--verbosity",
        "-v",
        type=int,
        choices=[1, 2, 3],
        default=1,
        help="Verbosity level (default 1)",
    )
    parser.add_argument(
        "--outdir",
        default="assets_hires",
        help="Output directory for assets (default: assets_hires)",
    )
    args = parser.parse_args()

    import tempfile

    global OUTDIR
    OUTDIR = args.outdir

    load_dotenv()

    # Packaging must always write to a SQLite database. If POSTGRES_CONNECTION
    # is configured, convert Postgres -> SQLite first and operate on that file.
    postgres_conn = os.getenv("POSTGRES_CONNECTION")
    temp_dir = None
    temp_db_path = None
    final_db_destination = None
    
    if postgres_conn:
        # Create temp directory for SQLite conversion
        temp_dir = tempfile.mkdtemp(prefix="honeyspeak_pkg_")
        temp_db_path = os.path.join(temp_dir, "Dictionary.sqlite")
        final_db_destination = os.path.join(OUTDIR, "Dictionary.sqlite")
        
        print(f"[PACKAGE] Created temp directory: {temp_dir}")
        print(f"[PACKAGE] Temp DB path: {temp_db_path}")
        print(f"[PACKAGE] Final destination: {final_db_destination}")
        print(f"Converting Postgres -> SQLite for packaging: {temp_db_path}")
        
        from scripts.convert_postgres_to_sqlite import convert_database
        ok = convert_database(postgres_conn, temp_db_path)
        if not ok:
            print("Conversion failed - aborting packaging")
            shutil.rmtree(temp_dir, ignore_errors=True)
            return
        
        sqlite_path = temp_db_path
    else:
        sqlite_path = os.environ.get("DATABASE_PATH", "Dictionary.sqlite")
        
        # If DATABASE_PATH is in /data, create a temp copy
        if sqlite_path.startswith('/data'):
            temp_dir = tempfile.mkdtemp(prefix="honeyspeak_pkg_")
            temp_db_path = os.path.join(temp_dir, "Dictionary.sqlite")
            final_db_destination = os.path.join(OUTDIR, "Dictionary.sqlite")
            
            print(f"[PACKAGE] DB path is in /data, creating temp copy")
            print(f"[PACKAGE] Temp directory: {temp_dir}")
            print(f"[PACKAGE] Copying {sqlite_path} -> {temp_db_path}")
            
            shutil.copy(sqlite_path, temp_db_path)
            sqlite_path = temp_db_path
            
            print(f"[PACKAGE] Temp DB created: {temp_db_path}")
            print(f"[PACKAGE] Final destination: {final_db_destination}")

    print(f"[PACKAGE] Using packaging DB: {sqlite_path}")

    # Use SQLiteDictionary so packaging metadata always goes to SQLite
    from libs.sqlite_dictionary import SQLiteDictionary
    db = SQLiteDictionary(sqlite_path)
    words = db.get_all_words()
    db.delete_assets()
    clean_packages()

    if args.verbosity >= 1:
        print(f"Packaging assets to {OUTDIR} (dryrun={args.dryrun})")

    iterator = (
        track(words, description="Packaging words") if args.verbosity == 1 else words
    )

    for word in iterator:
        definitions = db.get_shortdefs(word.uuid)
        if args.verbosity >= 2:
            print(f"Processing word: {word.word}")
        filename = encode_audio(f"word_{word.uuid}_0.aac", 32)
        if not args.dryrun:
            if filename is not None:
                package_id = store_file(filename)
                if package_id is not None:
                    db.add_asset(word.uuid, "word", 0, 0, package_id, f"low_{filename}")
        if args.verbosity == 2:
            print(
                f"add_asset uuid:{word.uuid} assetgroup: word sid: 0 package_id: {package_id} filename: low_{filename}"
            )
        for definition in definitions:
            filename = encode_audio(f"shortdef_{word.uuid}_{definition.id}_0.aac", 32)
            if not args.dryrun:
                if filename is not None:
                    package_id = store_file(filename)
                    if package_id is not None:
                        db.add_asset(
                            word.uuid, "shortdef", definition.id, 0, package_id, filename
                        )
                if args.verbosity == 2:
                    print(
                        f"add_asset uuid:{word.uuid} assetgroup: shortdef sid: {definition.id} variant: 0 package_id: {package_id} filename: {filename}"
                    )

            # Package 2 variants of definition image (i=0, i=1)
            for variant in range(2):
                filename = encode_image(f"image_{word.uuid}_{definition.id}_{variant}.png")
                if not args.dryrun:
                    if filename is not None:
                        package_id = store_file(filename)
                        if package_id is not None:
                            # Encode both def_id and variant i into sid: sid = def_id * 100 + i
                            db.add_asset(
                                word.uuid, "image", definition.id, variant, package_id, filename
                            )
                if args.verbosity == 2:
                    print(
                        f"add_asset uuid:{word.uuid} assetgroup: image sid: {definition.id * 100 + variant} package_id: {package_id} filename: {filename}"
                    )

    db.close()
    
    # Export words and shortdef tables to assets/db.sqlite
    if not args.dryrun:
        if args.verbosity >= 1:
            print("Exporting words and shortdef tables to assets/db.sqlite...")
        
        try:
            # Determine the source database path
            source_db = sqlite_path
            
            # Create assets directory if it doesn't exist
            assets_dir = "assets"
            os.makedirs(assets_dir, exist_ok=True)
            
            # Path for the exported db
            export_db_path = os.path.join(assets_dir, "db.sqlite")
            
            # Remove existing db.sqlite if it exists
            if os.path.exists(export_db_path):
                os.remove(export_db_path)
                print(f"[EXPORT] Removed existing {export_db_path}")
            
            # Connect to source and export databases
            import sqlite3
            source_conn = sqlite3.connect(source_db)
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
            
            # Copy shortdef table
            source_cursor.execute("SELECT uuid, definition, id FROM shortdef")
            shortdef_data = source_cursor.fetchall()
            export_cursor.executemany(
                "INSERT INTO shortdef (uuid, definition, id) VALUES (?, ?, ?)",
                shortdef_data
            )
            
            # Commit and close
            export_conn.commit()
            source_conn.close()
            export_conn.close()
            
            if args.verbosity >= 1:
                export_size = os.path.getsize(export_db_path)
                print(f"✓ Exported {len(words_data)} words and {len(shortdef_data)} definitions to {export_db_path} ({export_size:,} bytes)")
        except Exception as e:
            print(f"Error exporting db.sqlite: {e}")
            import traceback
            traceback.print_exc()
    
    # Move temp DB to final destination if needed
    if temp_db_path and final_db_destination:
        try:
            print(f"[PACKAGE] Moving temp DB to final destination")
            print(f"[PACKAGE] Source: {temp_db_path}")
            print(f"[PACKAGE] Destination: {final_db_destination}")
            
            # Ensure destination directory exists
            os.makedirs(os.path.dirname(final_db_destination), exist_ok=True)
            
            # Copy the database file
            shutil.copy(temp_db_path, final_db_destination)
            print(f"[PACKAGE] ✓ Database moved to {final_db_destination}")
            
            # Update sqlite_path for subsequent operations
            sqlite_path = final_db_destination
            
            # Clean up temp directory
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)
                print(f"[PACKAGE] ✓ Cleaned up temp directory: {temp_dir}")
            
        except Exception as e:
            print(f"[PACKAGE] Error moving database: {e}")
            return
    
    # Create production.sqlite from Dictionary.sqlite with WAL disabled
    if not args.dryrun:
        if args.verbosity >= 1:
            print("Creating production.sqlite (WAL disabled for iOS deployment)...")
        
        try:
            # Determine source path for production.sqlite
            source_db = final_db_destination if final_db_destination else sqlite_path
            production_path = os.path.join(os.path.dirname(source_db), "production.sqlite")
            
            print(f"[PACKAGE] Creating production.sqlite from {source_db}")
            
            # Copy to production.sqlite
            shutil.copy(source_db, production_path)
            
            # For production, always use SQLite directly
            from libs.sqlite_dictionary import SQLiteDictionary
            # Open with production_mode=True to disable WAL and create clean production DB
            prod_db = SQLiteDictionary(production_path, production_mode=True)
            prod_db.close()
            
            # Verify production.sqlite has no WAL/SHM files
            production_wal = f"{production_path}-wal"
            production_shm = f"{production_path}-shm"
            
            if os.path.exists(production_wal):
                os.remove(production_wal)
            if os.path.exists(production_shm):
                os.remove(production_shm)
            
            if args.verbosity >= 1:
                print(f"✓ production.sqlite created at {production_path} ({os.path.getsize(production_path)} bytes, no WAL files)")
        except Exception as e:
            print(f"Error creating production.sqlite: {e}")
    
    if not args.dryrun:
        copyto_dir = os.getenv("COPYTO_DIRECTORY", "")
        if copyto_dir:
            # Determine which production.sqlite to copy
            source_db = final_db_destination if final_db_destination else sqlite_path
            production_path = os.path.join(os.path.dirname(source_db), "production.sqlite")
            
            if args.verbosity >= 1:
                print(f"Copying {production_path} to {copyto_dir}/database.sqlite")
            try:
                shutil.copyfile(
                    production_path, os.path.join(copyto_dir, "database.sqlite")
                )
            except Exception as e:
                print(
                    f"Error copying production.sqlite: {e} to {copyto_dir}/database.sqlite"
                )
            if args.verbosity >= 1:
                print(f"Copying assets/packages*.zip to {copyto_dir}")
                # Copy all package_*.zip files to COPYTO_DIRECTORY
                try:
                    for filename in os.listdir("assets"):
                        if filename.startswith("package_") and filename.endswith(".zip"):
                            shutil.copy(
                                os.path.join("assets", filename),
                                os.path.join(copyto_dir, filename),
                            )
                except Exception as e:
                    print(
                        f"Error copying package zip files: {e} to {copyto_dir}"
                    )
    if args.verbosity >= 1:
        print("Packaging complete!")


if __name__ == "__main__":
    main()
