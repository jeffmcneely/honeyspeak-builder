"""
Unified dictionary interface that automatically selects PostgreSQL or SQLite backend
based on environment configuration.
"""

import os
from typing import Union

def get_dictionary_backend(db_path=None, production_mode=False):
    """
    Get the appropriate dictionary backend based on environment configuration.
    
    If POSTGRES_CONNECTION is set, use PostgreSQL.
    Otherwise, fall back to SQLite.
    
    Args:
        db_path: Path to SQLite database (ignored for PostgreSQL)
        production_mode: Production mode flag (only used for SQLite)
    
    Returns:
        Either PostgresDictionary or SQLiteDictionary instance
    """
    postgres_conn = os.getenv("POSTGRES_CONNECTION")
    
    if postgres_conn:
        # Use PostgreSQL for development
        from libs.pg_dictionary import PostgresDictionary
        return PostgresDictionary(postgres_conn)
    else:
        # Use SQLite for production/legacy. If db_path is not provided,
        # fall back to env/DATA defaults so callers can pass None safely.
        from libs.sqlite_dictionary import SQLiteDictionary
        default_db = db_path
        if not default_db:
            storage_dir = os.getenv("STORAGE_DIRECTORY", "/data/honeyspeak")
            default_db = os.path.join(storage_dir, "Dictionary.sqlite")
        return SQLiteDictionary(default_db, production_mode=production_mode)

# Alias for backward compatibility
Dictionary = get_dictionary_backend