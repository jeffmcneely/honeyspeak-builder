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
    """Encode to low-bitrate mono mp3 using ffmpeg"""

    raw_path = os.path.join(OUTDIR, f"{file}")
    low_path = os.path.join(OUTDIR, f"low_{file}")
    print(f"[encode_audio] Looking for raw file: {raw_path}")
    if not os.path.exists(raw_path):
        print(f"[encode_audio] Raw file NOT FOUND: {raw_path}")
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
    """Reduce image resolution by half using ImageMagick"""
    raw_path = os.path.join(OUTDIR, f"{file}")
    base_name = os.path.splitext(file)[0]
    low_path = os.path.join(OUTDIR, f"low_{base_name}.heif")
    print(f"[encode_image] Looking for raw file: {raw_path}")

    if not os.path.exists(raw_path):
        print(f"[encode_image] Raw file NOT FOUND: {raw_path}")
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
                        f"add_asset uuid:{word.uuid} assetgroup: image sid: {definition.id * 100 + i} package_id: {package_id} filename: {filename}"
                    )

    db.close()
    
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
