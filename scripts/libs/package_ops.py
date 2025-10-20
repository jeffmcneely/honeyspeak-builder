"""
Package operations library - granular functions for asset packaging.
All functions are designed to be called from Celery tasks.
"""

import os
import subprocess
import logging
import re
from pathlib import Path
from zipfile import ZipFile
from typing import Optional, Dict
from .sqlite_dictionary import SQLiteDictionary

logger = logging.getLogger(__name__)

MAX_FILE_SIZE = 100 * 1024 * 1024  # 100 MB


def encode_audio_file(
    input_file: str,
    output_dir: str,
    bitrate: int = 32
) -> Dict[str, str]:
    """
    Encode audio file to low-bitrate mono AAC using ffmpeg.
    
    Args:
        input_file: Path to input audio file
        output_dir: Directory containing files
        bitrate: Target bitrate in kbps
        
    Returns:
        Dict with 'status', 'input_file', and 'output_file' keys
    """
    raw_path = os.path.join(output_dir, input_file)
    base_name = os.path.splitext(input_file)[0]
    low_path = os.path.join(output_dir, f"low_{base_name}.aac")
    
    if not os.path.exists(raw_path):
        logger.warning(f"Input file not found: {raw_path}")
        return {"status": "not_found", "input_file": input_file, "output_file": None}
    
    if os.path.exists(low_path):
        logger.info(f"Output file already exists: {low_path}")
        return {"status": "skipped", "input_file": input_file, "output_file": low_path}
    
    try:
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i", raw_path,
                "-ac", "1",  # mono
                "-b:a", f"{bitrate}k",
                "-ar", "24000",
                low_path,
                "-loglevel", "quiet",
            ],
            check=True,
            capture_output=True
        )
        logger.info(f"Encoded audio: {raw_path} -> {low_path}")
        return {"status": "success", "input_file": input_file, "output_file": low_path}
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error encoding {raw_path}: {e.stderr}")
        return {"status": "error", "input_file": input_file, "output_file": None, "error": str(e)}


def encode_image_file(
    input_file: str,
    output_dir: str,
    quality: int = 25
) -> Dict[str, str]:
    """
    Reduce image resolution and convert to HEIF using ImageMagick.
    
    Args:
        input_file: Path to input image file
        output_dir: Directory containing files
        quality: HEIF quality (0-100)
        
    Returns:
        Dict with 'status', 'input_file', and 'output_file' keys
    """
    raw_path = os.path.join(output_dir, input_file)
    base_name = os.path.splitext(input_file)[0]
    low_path = os.path.join(output_dir, f"low_{base_name}.heif")
    
    if not os.path.exists(raw_path):
        logger.warning(f"Input file not found: {raw_path}")
        return {"status": "not_found", "input_file": input_file, "output_file": None}
    
    if os.path.exists(low_path):
        logger.info(f"Output file already exists: {low_path}")
        return {"status": "skipped", "input_file": input_file, "output_file": low_path}
    
    try:
        subprocess.run(
            [
                "magick",
                raw_path,
                "-resize", "50%",
                "-quality", str(quality),
                low_path,
            ],
            check=True,
            capture_output=True
        )
        logger.info(f"Encoded image: {raw_path} -> {low_path}")
        return {"status": "success", "input_file": input_file, "output_file": low_path}
    except subprocess.CalledProcessError as e:
        logger.error(f"ImageMagick error encoding {raw_path}: {e.stderr}")
        return {"status": "error", "input_file": input_file, "output_file": None, "error": str(e)}


def add_file_to_package(
    filename: str,
    package_dir: str,
    max_size: int = MAX_FILE_SIZE
) -> Optional[str]:
    """
    Add a file to a zip package, creating or selecting appropriate package.
    
    Args:
        filename: Path to file to add
        package_dir: Directory for package files
        max_size: Maximum package size in bytes
        
    Returns:
        Package ID (e.g., 'a0') or None if failed
    """
    if not os.path.exists(filename):
        logger.warning(f"File not found: {filename}")
        return None
    
    # Extract first letter for package naming
    path_re = r"low_(?:image|word|shortdef)_([a-z0-9])"
    match = re.search(path_re, filename)
    if match:
        first_letter = match.group(1)
    else:
        first_letter = os.path.basename(filename)[0]
    
    # Find or create appropriate package
    package_id = 0
    os.makedirs(package_dir, exist_ok=True)
    
    while True:
        package_file = os.path.join(package_dir, f"package_{first_letter}{package_id}.zip")
        
        if os.path.exists(package_file) and os.path.getsize(package_file) > max_size:
            package_id += 1
            continue
        
        try:
            with ZipFile(package_file, "a") as package:
                arcname = os.path.basename(filename)
                if arcname in package.namelist():
                    logger.info(f"{arcname} already exists in {package_file}")
                    return f"{first_letter}{package_id}"
                
                package.write(filename, arcname=arcname)
                logger.info(f"Stored {arcname} into package_{first_letter}{package_id}.zip")
                return f"{first_letter}{package_id}"
        except Exception as e:
            logger.error(f"Error adding {filename} to package: {e}")
            return None


def store_asset_metadata(
    db_path: str,
    uuid: str,
    assetgroup: str,
    sid: int,
    package_id: str,
    filename: str
) -> Dict[str, str]:
    """
    Store asset metadata in database.
    
    Args:
        db_path: Path to SQLite database
        uuid: Word UUID
        assetgroup: Asset group ('word', 'shortdef', 'image')
        sid: Sense ID
        package_id: Package ID
        filename: Filename in package
        
    Returns:
        Dict with 'status' key
    """
    try:
        db = SQLiteDictionary(db_path)
        db.add_asset(uuid, assetgroup, sid, package_id, filename)
        db.close()
        logger.info(f"Stored asset metadata: {uuid}/{assetgroup}/{sid} -> {package_id}/{filename}")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error storing asset metadata: {e}")
        return {"status": "error", "error": str(e)}


def clean_packages(package_dir: str) -> Dict[str, any]:
    """
    Delete all existing package files.
    
    Args:
        package_dir: Directory containing package files
        
    Returns:
        Dict with 'status' and 'deleted_count' keys
    """
    deleted = 0
    try:
        if not os.path.exists(package_dir):
            return {"status": "success", "deleted_count": 0}
        
        for filename in os.listdir(package_dir):
            if filename.startswith("package_") and filename.endswith(".zip"):
                filepath = os.path.join(package_dir, filename)
                os.remove(filepath)
                deleted += 1
                logger.info(f"Deleted package: {filepath}")
        
        return {"status": "success", "deleted_count": deleted}
    except Exception as e:
        logger.error(f"Error cleaning packages: {e}")
        return {"status": "error", "deleted_count": deleted, "error": str(e)}


def delete_all_assets(db_path: str) -> Dict[str, str]:
    """
    Delete all asset metadata from database.
    
    Args:
        db_path: Path to SQLite database
        
    Returns:
        Dict with 'status' key
    """
    try:
        db = SQLiteDictionary(db_path)
        db.delete_assets()
        db.close()
        logger.info("Deleted all asset metadata from database")
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Error deleting assets: {e}")
        return {"status": "error", "error": str(e)}
