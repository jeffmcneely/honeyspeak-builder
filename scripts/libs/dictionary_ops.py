"""
Dictionary operations library - granular functions for dictionary building.
All functions are designed to be called from Celery tasks.
"""

import requests
import logging
from typing import Dict, List, Optional, Tuple
from .sqlite_dictionary import SQLiteDictionary, Flags
from datetime import datetime
import os

logger = logging.getLogger(__name__)


def fetch_word_from_api(word: str, api_key: str) -> Optional[dict]:
    """
    Fetch a single word from the Merriam-Webster Learner's Dictionary API.
    
    Args:
        word: The word to fetch
        api_key: Dictionary API key
        
    Returns:
        API response as dict, or None if failed
    """
    try:
        url = f"https://www.dictionaryapi.com/api/v3/references/learners/json/{word}?key={api_key}"
        response = requests.get(url, timeout=30)
        
        if response.status_code == 200:
            logger.info(f"Successfully fetched '{word}' from API")
            return response.json()
        else:
            logger.error(f"API request failed for '{word}': {response.status_code}")
            return None
    except Exception as e:
        logger.error(f"Exception fetching '{word}': {e}")
        return None


def parse_flags(entry: dict) -> Flags:
    """
    Parse flags from a dictionary entry.
    
    Args:
        entry: Dictionary entry from API
        
    Returns:
        Flags enum value
    """
    fl = 0
    meta = entry.get("meta", {})
    
    if meta.get("offensive"):
        fl |= Flags.OFFENSIVE

    def_list = entry.get("def", [])
    for def_item in def_list:
        sseq_list = def_item.get("sseq", [])
        for sseq_item in sseq_list:
            for sense_group in sseq_item:
                if isinstance(sense_group, list) and len(sense_group) == 2 and sense_group[0] == "sense":
                    sense_data = sense_group[1]
                    sls_list = sense_data.get("sls", [])
                    for sls_item in sls_list:
                        text = sls_item.lower()
                        if "british" in text:
                            fl |= Flags.BRITISH
                        if "us" in text or "american" in text or "chiefly us" in text:
                            fl |= Flags.US
                        if "old-fashioned" in text or "archaic" in text:
                            fl |= Flags.OLD_FASHIONED
                        if "slang" in text or "informal" in text:
                            fl |= Flags.INFORMAL
                    
                    sdsense = sense_data.get("sdsense")
                    if isinstance(sdsense, dict):
                        sdsense_sls = sdsense.get("sls", [])
                        for sls_item in sdsense_sls:
                            text = sls_item.lower()
                            if "british" in text:
                                fl |= Flags.BRITISH
                            if "us" in text or "american" in text or "chiefly us" in text:
                                fl |= Flags.US
                            if "old-fashioned" in text or "archaic" in text:
                                fl |= Flags.OLD_FASHIONED
                            if "slang" in text or "informal" in text:
                                fl |= Flags.INFORMAL

    return Flags.from_int(fl)


def process_api_entry(entry: dict, function_label: str, level: str, db_path: str, original_word: Optional[str] = None) -> Tuple[bool, str]:
    """
    Process a single API entry and add to database.
    Extracts ALL shortdefs from the API response, not just app-shortdef.
    
    Args:
        entry: Dictionary entry from API
        function_label: Functional label (e.g., "verb", "noun")
        level: CEFR level (e.g., "a1", "a2")
        db_path: Path to SQLite database
        original_word: Original word requested (if different from entry word, level set to "z1")
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        # Use unified Dictionary backend which auto-selects PostgreSQL or SQLite
        from libs.dictionary import Dictionary
        db = Dictionary(db_path)
        
        meta = entry["meta"]
        word = meta.get("id").split(":")[0]
        
        # If original_word provided and doesn't match, set level to "z1"
        if original_word is not None and word != original_word:
            level = "z1"
            logger.info(f"Word mismatch: requested '{original_word}', got '{word}' - setting level to 'z1'")
        
        # Get functional label from entry's 'fl' field (NOT from app-shortdef)
        fl = entry.get("fl", function_label)
        uuid = meta.get("uuid")
        flags = parse_flags(entry)
        
        # Extract ALL shortdefs from the entry
        all_shortdefs = []
        
        # Method 1: Use app-shortdef if available (quick reference definitions)
        shortdef = meta.get("app-shortdef", None)
        if shortdef and isinstance(shortdef, dict):
            for sd in shortdef.get("def", []):
                if sd and sd not in all_shortdefs:
                    all_shortdefs.append(sd)
        
        # Method 2: Extract from main 'def' structure (more comprehensive)
        def_list = entry.get("def", [])
        for def_item in def_list:
            sseq_list = def_item.get("sseq", [])
            for sseq_item in sseq_list:
                for sense_group in sseq_item:
                    if isinstance(sense_group, list) and len(sense_group) == 2:
                        sense_type, sense_data = sense_group
                        if sense_type == "sense":
                            # Get definition text from 'dt' (defining text)
                            dt_list = sense_data.get("dt", [])
                            for dt_item in dt_list:
                                if isinstance(dt_item, list) and len(dt_item) >= 2:
                                    dt_type, dt_content = dt_item[0], dt_item[1]
                                    if dt_type == "text":
                                        # Clean up the definition text
                                        clean_def = dt_content.strip()
                                        # Remove leading colon or whitespace
                                        if clean_def.startswith(":"):
                                            clean_def = clean_def[1:].strip()
                                        if clean_def and clean_def not in all_shortdefs:
                                            all_shortdefs.append(clean_def)
        
        if not all_shortdefs:
            db.close()
            return False, f"No definitions found for entry"
        
        try:
            # Convert Flags object to int for database storage
            db.add_word(word, level, fl, uuid, flags.to_int())
            logger.info(f"Added word '{word}' with uuid {uuid}, functional_label='{fl}'")
            
            # Add all shortdefs
            for sd in all_shortdefs:
                db.add_shortdef(uuid, sd)
                logger.info(f"Added shortdef for {uuid}: {sd[:50]}...")
            
            logger.info(f"Successfully added {len(all_shortdefs)} definitions for '{word}'")
            
            db.close()
            return True, f"Successfully processed '{word}' with {len(all_shortdefs)} definitions"
        except Exception as e:
            db.close()
            logger.error(f"Error adding word '{word}': {e}")
            return False, f"Database error: {e}"
            
    except Exception as e:
        logger.error(f"Error processing entry: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False, f"Processing error: {e}"


def track_api_usage(usage_file: Optional[str] = None) -> int:
    """
    Track and return current API usage count for today.
    
    Args:
        usage_file: Path to usage tracking file (defaults to STORAGE_DIRECTORY/api_usage.txt)
        
    Returns:
        Current usage count for today
    """
    if usage_file is None:
        storage_dir = os.getenv("STORAGE_DIRECTORY", ".")
        usage_file = os.path.join(storage_dir, "api_usage.txt")
    
    today = datetime.now().date()
    usage_count = 0
    
    try:
        with open(usage_file, "r") as f:
            content = f.read().strip()
            if "|" in content:
                date_str, count_str = content.split("|", 1)
                file_date = datetime.fromisoformat(date_str).date()
                if file_date == today:
                    usage_count = int(count_str)
    except (FileNotFoundError, ValueError):
        usage_count = 0
    
    return usage_count


def increment_api_usage(usage_file: Optional[str] = None) -> int:
    """
    Increment API usage counter and return new count.
    
    Args:
        usage_file: Path to usage tracking file (defaults to STORAGE_DIRECTORY/api_usage.txt)
        
    Returns:
        New usage count
    """
    if usage_file is None:
        storage_dir = os.getenv("STORAGE_DIRECTORY", ".")
        usage_file = os.path.join(storage_dir, "api_usage.txt")
    
    today = datetime.now().date()
    current_count = track_api_usage(usage_file)
    new_count = current_count + 1
    
    try:
        with open(usage_file, "w") as f:
            f.write(f"{today.isoformat()}|{new_count}")
    except Exception as e:
        logger.error(f"Failed to update API usage file: {e}")
    
    return new_count


def get_word_count(db_path: str) -> int:
    """
    Get total word count from database.
    
    Args:
        db_path: Path to SQLite database
        
    Returns:
        Total word count
    """
    # Use unified backend so db_path may be None for PostgreSQL setups
    from libs.dictionary import Dictionary
    db = Dictionary(db_path)
    count = db.get_word_count()
    db.close()
    return count
