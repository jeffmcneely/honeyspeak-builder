import os
import subprocess
import shutil
import argparse
from libs.sqlite_dictionary import SQLiteDictionary
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


def encode_audio(file: str, bitrate) -> str:
    """Encode to low-bitrate mono mp3 using ffmpeg"""

    raw_path = os.path.join(OUTDIR, f"{file}")
    low_path = os.path.join(OUTDIR, f"low_{file}")
    if not os.path.exists(raw_path):
        return None
    if os.path.exists(low_path):
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


def encode_image(file: str) -> str:
    """Reduce image resolution by half using ImageMagick"""
    raw_path = os.path.join(OUTDIR, f"{file}")
    base_name = os.path.splitext(file)[0]
    low_path = f"low_{base_name}.heif"

    if not os.path.exists(raw_path):
        return None

    if os.path.exists(low_path):
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


def store_file(filename: str) -> str:
    package_id = 0
    path_re = "low_(?:image|word|shortdef|)_([a-z0-9])"
    match = re.search(path_re, filename)
    if match:
        first_letter = match.group(1)  # get the character after 'low_'
    else:
        first_letter = os.path.basename(filename)[0]
    if not path.exists(filename):
        return None
    while True:
        package_file = path.join("assets", f"package_{first_letter}{package_id}.zip")
        if path.exists(package_file) and path.getsize(package_file) > MAX_FILE_SIZE:
            package_id += 1
            continue
        with ZipFile(package_file, "a") as package:
            if filename in package.namelist():
                print(f"{filename} already exists in zip")
                break
            package.write(filename)
            print(f"stored {filename} into package_{first_letter}{package_id}.zip")
            return f"{first_letter}{package_id}"


def clean_packages() -> None:
    for filename in os.listdir("assets"):
        if filename.startswith("package_") and filename.endswith(".zip"):
            os.remove(os.path.join("assets", filename))


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

    global OUTDIR
    OUTDIR = args.outdir

    load_dotenv()
    db = SQLiteDictionary()
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
                    db.add_asset(word.uuid, "word", 0, package_id, f"low_{filename}")
        if args.verbosity == 2:
            print(
                f"add_asset uuid:{word.uuid} assetgroup: word sid: 0 package_id: {package_id} filename: low_{filename}"
            )
        for definition in definitions:
            filename = encode_audio(f"shortdef_{word.uuid}_{definition.id}.aac", 32)
            if not args.dryrun:
                if filename is not None:
                    package_id = store_file(filename)
                    if package_id is not None:
                        db.add_asset(
                            word.uuid, "shortdef", definition.id, package_id, filename
                        )
            if args.verbosity == 2:
                print(
                    f"add_asset uuid:{word.uuid} assetgroup: shortdef sid: {definition.id} package_id: {package_id} filename: {filename}"
                )

            filename = encode_image(f"image_{word.uuid}_{definition.id}.png")
            if not args.dryrun:
                if filename is not None:
                    package_id = store_file(filename)
                    db.add_asset(
                        word.uuid, "image", definition.id, package_id, filename
                    )
            if args.verbosity == 2:
                print(
                    f"add_asset uuid:{word.uuid} assetgroup: image sid: {definition.id} package_id: {package_id} filename: {filename}"
                )

    db.close()
    if not args.dryrun:
        if os.getenv("COPYTO_DIRECTORY","") != "":
            if args.verbosity >= 1:
                print(f"Copying Dictionary.sqlite to {os.getenv('COPYTO_DIRECTORY')}/database.sqlite")
            try:
                shutil.copyfile(
                    "Dictionary.sqlite", os.path.join(os.getenv("COPYTO_DIRECTORY"), "database.sqlite")
                )
            except Exception as e:
                print(
                    f"Error copying Dictionary.sqlite: {e} to {os.getenv('COPYTO_DIRECTORY')}/database.sqlite"
                )
            if args.verbosity >= 1:
                print(f"Copying assets/packages*.zip to {os.getenv('COPYTO_DIRECTORY')}")
                # Copy all package_*.zip files to COPYTO_DIRECTORY
                try:
                    for filename in os.listdir("assets"):
                        if filename.startswith("package_") and filename.endswith(".zip"):
                            shutil.copy(
                                os.path.join("assets", filename),
                                os.path.join(os.getenv("COPYTO_DIRECTORY"), filename),
                            )
                except Exception as e:
                    print(
                        f"Error copying package zip files: {e} to {os.getenv('COPYTO_DIRECTORY')}"
                    )
    if args.verbosity >= 1:
        print("Packaging complete!")


if __name__ == "__main__":
    main()
