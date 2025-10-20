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


def process_api_entry(entry: dict, db_path: str) -> Tuple[bool, str]:
    """
    Process a single API entry and add to database.
    
    Args:
        entry: Dictionary entry from API
        db_path: Path to SQLite database
        
    Returns:
        Tuple of (success: bool, message: str)
    """
    try:
        db = SQLiteDictionary(db_path)
        
        meta = entry["meta"]
        word = meta.get("id").split(":")[0]
        shortdef = meta.get("app-shortdef", None)
        
        if shortdef is None or shortdef == []:
            db.close()
            return False, f"No shortdef for entry"
        
        fl = shortdef.get("fl")
        uuid = meta.get("uuid")
        flags = parse_flags(entry)
        
        try:
            # Convert Flags object to int for database storage
            db.add_word(word, fl, uuid, flags.to_int())
            logger.info(f"Added word '{word}' with uuid {uuid}")
            
            if shortdef != []:
                for sd in shortdef.get("def", []):
                    db.add_shortdef(uuid, sd)
                    logger.info(f"Added shortdef for {uuid}: {sd[:50]}...")
            
            db.close()
            return True, f"Successfully processed '{word}'"
        except Exception as e:
            db.close()
            logger.error(f"Error adding word '{word}': {e}")
            return False, f"Database error: {e}"
            
    except Exception as e:
        logger.error(f"Error processing entry: {e}")
        return False, f"Processing error: {e}"


def track_api_usage(usage_file: str = "api_usage.txt") -> int:
    """
    Track and return current API usage count for today.
    
    Args:
        usage_file: Path to usage tracking file
        
    Returns:
        Current usage count for today
    """
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


def increment_api_usage(usage_file: str = "api_usage.txt") -> int:
    """
    Increment API usage counter and return new count.
    
    Args:
        usage_file: Path to usage tracking file
        
    Returns:
        New usage count
    """
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
    db = SQLiteDictionary(db_path)
    count = db.get_word_count()
    db.close()
    return count
