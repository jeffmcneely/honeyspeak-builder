#!/usr/bin/env python3
"""
Convert PostgreSQL database to SQLite for production deployment.

This script reads from the development PostgreSQL database and creates
a production-ready SQLite database with all data and proper configuration.
"""

import os
import sys
import argparse
from pathlib import Path
from dotenv import load_dotenv
import logging

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def convert_database(postgres_conn: str = None, sqlite_path: str = "production.sqlite", batch_size: int = 1000):
    """
    Convert PostgreSQL database to SQLite.
    
    Args:
        postgres_conn: PostgreSQL connection string (uses env if not provided)
        sqlite_path: Path for output SQLite database
        batch_size: Number of records to process at once
    """
    from libs.pg_dictionary import PostgresDictionary
    from libs.sqlite_dictionary import SQLiteDictionary, SQLITE_SCHEMA
    import sqlite3
    
    # Get PostgreSQL connection
    postgres_conn = postgres_conn or os.getenv("POSTGRES_CONNECTION")
    if not postgres_conn:
        raise ValueError("POSTGRES_CONNECTION not set and no connection string provided")
    
    logger.info(f"Connecting to PostgreSQL...")
    pg_db = PostgresDictionary(postgres_conn)
    
    # Create SQLite database
    logger.info(f"Creating SQLite database: {sqlite_path}")
    
    # Remove existing file if present
    if Path(sqlite_path).exists():
        logger.warning(f"Removing existing file: {sqlite_path}")
        Path(sqlite_path).unlink()
    
    # Create and initialize SQLite database
    conn = sqlite3.connect(sqlite_path)
    cursor = conn.cursor()
    
    try:
        # Set pragmas for production
        logger.info("Setting SQLite pragmas...")
        cursor.execute("PRAGMA journal_mode = DELETE")  # No WAL for production
        cursor.execute("PRAGMA synchronous = FULL")  # Maximum durability
        cursor.execute("PRAGMA foreign_keys = ON")
        
        # Create schema
        logger.info("Creating SQLite schema...")
        for stmt in SQLITE_SCHEMA:
            cursor.execute(stmt)
        conn.commit()
        
        # Transfer words
        logger.info("Transferring words...")
        words = pg_db.get_all_words()
        word_count = 0
        
        for i in range(0, len(words), batch_size):
            batch = words[i:i+batch_size]
            word_data = [
                (w.word, w.functional_label, w.uuid, w.flags)
                for w in batch
            ]
            
            cursor.executemany(
                "INSERT INTO words (word, functional_label, uuid, flags) VALUES (?, ?, ?, ?)",
                word_data
            )
            word_count += len(batch)
            logger.info(f"  Transferred {word_count}/{len(words)} words...")
            conn.commit()
        
        # Transfer shortdefs
        logger.info("Transferring short definitions...")
        shortdef_count = 0
        
        for word in words:
            shortdefs = pg_db.get_shortdefs(word.uuid)
            for sd in shortdefs:
                cursor.execute(
                    "INSERT INTO shortdef (uuid, definition, id) VALUES (?, ?, ?)",
                    (sd.uuid, sd.definition, sd.id)
                )
                shortdef_count += 1
            
            if shortdef_count % 1000 == 0:
                logger.info(f"  Transferred {shortdef_count} definitions...")
                conn.commit()
        
        conn.commit()
        logger.info(f"  Total definitions transferred: {shortdef_count}")
        
        # Transfer external_assets
        logger.info("Transferring external assets...")
        asset_count = 0
        
        for word in words:
            assets = pg_db.get_external_assets(word.uuid)
            for asset in assets:
                cursor.execute(
                    """INSERT INTO external_assets (uuid, assetgroup, sid, package, filename) 
                       VALUES (?, ?, ?, ?, ?)""",
                    (asset.uuid, asset.assetgroup, asset.sid, asset.package, asset.filename)
                )
                asset_count += 1
            
            if asset_count > 0 and asset_count % 1000 == 0:
                logger.info(f"  Transferred {asset_count} assets...")
                conn.commit()
        
        conn.commit()
        if asset_count > 0:
            logger.info(f"  Total assets transferred: {asset_count}")
        else:
            logger.info(f"  No assets to transfer")
        
        # Transfer stories if they exist
        try:
            stories = pg_db.get_all_stories()
            if stories:
                logger.info(f"Transferring {len(stories)} stories...")
                
                for story in stories:
                    cursor.execute(
                        """INSERT INTO stories (uuid, title, style, grouping, difficulty)
                           VALUES (?, ?, ?, ?, ?)""",
                        (story.uuid, story.title, story.style, story.grouping, story.difficulty)
                    )
                    
                    # Get and transfer paragraphs
                    paragraphs = pg_db.get_story_paragraphs(story.uuid)
                    for para in paragraphs:
                        cursor.execute(
                            """INSERT INTO story_paragraphs 
                               (story_uuid, paragraph_index, paragraph_title, content)
                               VALUES (?, ?, ?, ?)""",
                            (para.story_uuid, para.paragraph_index, para.paragraph_title, para.content)
                        )
                
                conn.commit()
                logger.info(f"  Stories and paragraphs transferred")
        except Exception as e:
            logger.warning(f"Could not transfer stories: {e}")
        
        # Verify the conversion
        logger.info("Verifying conversion...")
        cursor.execute("SELECT COUNT(*) FROM words")
        sqlite_word_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM shortdef")
        sqlite_def_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM external_assets")
        sqlite_asset_count = cursor.fetchone()[0]
        
        pg_word_count = pg_db.get_word_count()
        pg_def_count = pg_db.get_shortdef_count()
        pg_asset_count = pg_db.get_asset_count()
        
        logger.info(f"Verification:")
        logger.info(f"  Words: PostgreSQL={pg_word_count}, SQLite={sqlite_word_count}")
        logger.info(f"  Definitions: PostgreSQL={pg_def_count}, SQLite={sqlite_def_count}")
        logger.info(f"  Assets: PostgreSQL={pg_asset_count}, SQLite={sqlite_asset_count}")
        
        if sqlite_word_count != pg_word_count:
            logger.error("Word count mismatch!")
        if sqlite_def_count != pg_def_count:
            logger.error("Definition count mismatch!")
        if sqlite_asset_count != pg_asset_count:
            logger.error("Asset count mismatch!")
        
        # Run VACUUM to optimize the database
        logger.info("Optimizing SQLite database...")
        cursor.execute("VACUUM")
        
        conn.close()
        
        # Verify file size
        file_size = Path(sqlite_path).stat().st_size
        logger.info(f"SQLite database created: {sqlite_path} ({file_size:,} bytes)")
        
        # Clean up any WAL/SHM files that might have been created
        for suffix in ['-wal', '-shm']:
            wal_file = Path(f"{sqlite_path}{suffix}")
            if wal_file.exists():
                wal_file.unlink()
                logger.info(f"Removed {wal_file}")
        
        logger.info("Conversion complete!")
        return True
        
    except Exception as e:
        logger.error(f"Conversion failed: {e}")
        import traceback
        traceback.print_exc()
        conn.rollback()
        conn.close()
        
        # Clean up partial file
        if Path(sqlite_path).exists():
            Path(sqlite_path).unlink()
        
        return False


def main():
    parser = argparse.ArgumentParser(
        description="Convert PostgreSQL database to SQLite for production"
    )
    parser.add_argument(
        "-o", "--output",
        default="production.sqlite",
        help="Output SQLite database path (default: production.sqlite)"
    )
    parser.add_argument(
        "-c", "--connection",
        help="PostgreSQL connection string (uses POSTGRES_CONNECTION env if not provided)"
    )
    parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=1000,
        help="Batch size for bulk operations (default: 1000)"
    )
    parser.add_argument(
        "--ios-path",
        help="Path to iOS app bundle to copy database to"
    )
    
    args = parser.parse_args()
    
    # Run conversion
    success = convert_database(
        postgres_conn=args.connection,
        sqlite_path=args.output,
        batch_size=args.batch_size
    )
    
    if success:
        # Copy to iOS if path provided
        if args.ios_path:
            ios_path = Path(args.ios_path)
            if ios_path.exists():
                import shutil
                dest = ios_path / "production.sqlite"
                logger.info(f"Copying to iOS bundle: {dest}")
                shutil.copy2(args.output, dest)
            else:
                logger.warning(f"iOS path not found: {ios_path}")
        
        sys.exit(0)
    else:
        sys.exit(1)


if __name__ == "__main__":
    main()