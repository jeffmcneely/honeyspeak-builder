import os
import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2 import sql
from dataclasses import dataclass
from pathlib import Path
import uuid as uuid_lib
from typing import Literal, Optional, Iterable, List
import logging

# PostgreSQL schema matching SQLite schema
POSTGRES_SCHEMA = [
    # words: uuid is the PRIMARY KEY; index on word for faster lookups
    """CREATE TABLE IF NOT EXISTS words (
        word TEXT NOT NULL,
        level TEXT,
        functional_label TEXT,
        uuid TEXT PRIMARY KEY,
        flags INTEGER DEFAULT 0
    )""",
    """CREATE INDEX IF NOT EXISTS idx_words_word ON words(word)""",
    # shortdef: unique per (uuid, def), cascade delete on words.uuid
    """CREATE TABLE IF NOT EXISTS shortdef (
        uuid TEXT,
        definition TEXT,
        id SERIAL PRIMARY KEY,
        FOREIGN KEY (uuid) REFERENCES words(uuid) ON DELETE CASCADE,
        UNIQUE(uuid, definition)
    )""",
    """CREATE INDEX IF NOT EXISTS idx_shortdef_uuid ON shortdef(uuid)""",
    """CREATE TABLE IF NOT EXISTS external_assets (
        uuid TEXT,
        assetgroup TEXT,
        sid INTEGER,
        package TEXT NOT NULL CHECK(length(package) = 2),
        filename TEXT,
        FOREIGN KEY (uuid) REFERENCES words(uuid) ON DELETE CASCADE,
        UNIQUE(uuid, assetgroup, sid)
    )""",
    """CREATE INDEX IF NOT EXISTS idx_external_assets_type_int ON external_assets(assetgroup,sid)""",
    """CREATE INDEX IF NOT EXISTS idx_external_assets_uuid ON external_assets(uuid)""",
    """CREATE TABLE IF NOT EXISTS stories (
        uuid TEXT,
        title TEXT,
        style TEXT,
        grouping TEXT,
        difficulty TEXT,
        PRIMARY KEY(uuid)
    )""",
    """CREATE INDEX IF NOT EXISTS idx_stories_grouping ON stories(grouping)""",
    """CREATE INDEX IF NOT EXISTS idx_stories_difficulty ON stories(difficulty)""",
    """CREATE INDEX IF NOT EXISTS idx_stories_uuid ON stories(uuid)""",
    """CREATE TABLE IF NOT EXISTS story_paragraphs(
        story_uuid TEXT,
        paragraph_index INTEGER,
        paragraph_title TEXT,
        content TEXT,
        PRIMARY KEY(story_uuid, paragraph_index),
        FOREIGN KEY(story_uuid) REFERENCES stories(uuid) ON DELETE CASCADE
    )""",
    """CREATE INDEX IF NOT EXISTS idx_story_paragraphs_uuid ON story_paragraphs(story_uuid)""",
    """CREATE TABLE IF NOT EXISTS story_words(
        story_uuid TEXT,
        word_uuid TEXT,
        paragraph_index INTEGER,
        FOREIGN KEY(story_uuid) REFERENCES stories(uuid) ON DELETE CASCADE,
        FOREIGN KEY(word_uuid) REFERENCES words(uuid) ON DELETE CASCADE
        )""",
    """CREATE INDEX IF NOT EXISTS idx_story_words_uuid ON story_words(story_uuid)""",
    """CREATE INDEX IF NOT EXISTS idx_story_words_word_uuid ON story_words(word_uuid)"""
]

# Reuse dataclasses from sqlite_dictionary
from libs.sqlite_dictionary import Flags, Word, ShortDef, Asset, Story, StoryParagraph

class PostgresDictionary:
    """
    PostgreSQL dictionary with connection pooling for concurrent access.
    """
    
    def __init__(self, connection_string: Optional[str] = None):
        """
        Initialize PostgreSQL connection.
        
        Args:
            connection_string: PostgreSQL connection string. If not provided, uses POSTGRES_CONNECTION env var.
        """
        self.connection_string = connection_string or os.getenv("POSTGRES_CONNECTION")
        if not self.connection_string:
            raise ValueError("POSTGRES_CONNECTION environment variable not set and no connection string provided")
        
        self.logger = logging.getLogger(__name__)
        self.logger.debug(f"[PostgresDictionary] Connecting to PostgreSQL...")
        
        # Test connection and create schema if needed
        self._ensure_schema()
        self.logger.debug(f"[PostgresDictionary] Ready")
    
    def _get_connection(self):
        """Get a new database connection."""
        return psycopg2.connect(self.connection_string)
    
    def _ensure_schema(self):
        """Ensure all tables and indexes exist."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                for stmt in POSTGRES_SCHEMA:
                    cursor.execute(stmt)
                conn.commit()
        finally:
            conn.close()
    
    def begin_immediate(self):
        """Start a transaction - returns a connection to be used for the transaction."""
        conn = self._get_connection()
        conn.autocommit = False
        return conn
    
    def commit(self, conn):
        """Commit a transaction."""
        conn.commit()
        conn.close()
    
    def rollback(self, conn):
        """Rollback a transaction."""
        conn.rollback()
        conn.close()
    
    def execute_fetchall(self, query: str, params=None):
        """Execute a query and return all results."""
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params or ())
                return cursor.fetchall()
        finally:
            conn.close()
    
    def execute_fetchone(self, query: str, params=None):
        """Execute a query and return one result."""
        conn = self._get_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(query, params or ())
                return cursor.fetchone()
        finally:
            conn.close()
    
    def execute(self, query: str, params=None):
        """Execute a query without returning results."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(query, params or ())
                conn.commit()
        finally:
            conn.close()
    
    def add_word(self, word: str, level: str, functional_label: Optional[str] = None, uuid_: Optional[str] = None, flags: int = 0) -> str:
        """
        Add a word to the dictionary.
        
        Returns:
            The UUID of the added word.
        """
        # Allow caller to provide uuid (keeps parity with SQLite implementation)
        word_uuid = uuid_ if uuid_ else str(uuid_lib.uuid4())
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO words (word, level, functional_label, uuid, flags) 
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (uuid) DO NOTHING""",
                    (word, level, functional_label, word_uuid, flags)
                )
                conn.commit()
        except Exception as e:
            self.logger.warning(f"[add_word] Exception: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
        return word_uuid
    
    def add_shortdef(self, word_uuid: str, definition: str) -> int:
        """
        Add a short definition for a word.
        
        Returns:
            The ID of the added definition.
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO shortdef (uuid, definition) 
                       VALUES (%s, %s)
                       ON CONFLICT (uuid, definition) DO NOTHING
                       RETURNING id""",
                    (word_uuid, definition)
                )
                result = cursor.fetchone()
                conn.commit()
                
                if result:
                    return result[0]
                else:
                    # If it was a duplicate, fetch the existing ID
                    cursor.execute(
                        "SELECT id FROM shortdef WHERE uuid = %s AND definition = %s",
                        (word_uuid, definition)
                    )
                    result = cursor.fetchone()
                    return result[0] if result else -1
        except Exception as e:
            self.logger.warning(f"[add_shortdef] Exception: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def add_external_asset(self, word_uuid: str, assetgroup: str, sid: int, package: str, filename: str):
        """Add an external asset record."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO external_assets (uuid, assetgroup, sid, package, filename)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (uuid, assetgroup, sid) 
                       DO UPDATE SET package = EXCLUDED.package, filename = EXCLUDED.filename""",
                    (word_uuid, assetgroup, sid, package, filename)
                )
                conn.commit()
        except Exception as e:
            self.logger.warning(f"[add_external_asset] Exception: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def get_word_by_uuid(self, word_uuid: str) -> Optional[Word]:
        """Get a word by its UUID."""
        row = self.execute_fetchone(
            "SELECT * FROM words WHERE uuid = %s",
            (word_uuid,)
        )
        return Word.from_row(row) if row else None
    
    def get_word_by_text(self, word: str) -> Optional[Word]:
        """Get a word by its text."""
        row = self.execute_fetchone(
            "SELECT * FROM words WHERE word = %s",
            (word,)
        )
        return Word.from_row(row) if row else None

    def get_uuids(self, word: str) -> List[str]:
        """Return a list of UUIDs matching the given word text."""
        try:
            rows = self.execute_fetchall("SELECT uuid FROM words WHERE word = %s", (word,))
            return [r["uuid"] for r in rows]
        except Exception as e:
            self.logger.warning(f"[get_uuids] Exception: {e}")
            return []
    
    def get_shortdefs(self, word_uuid: str) -> List[ShortDef]:
        """Get all short definitions for a word."""
        rows = self.execute_fetchall(
            "SELECT * FROM shortdef WHERE uuid = %s ORDER BY id",
            (word_uuid,)
        )
        return [ShortDef.from_row(row) for row in rows]
    
    def get_external_assets(self, word_uuid: str, assetgroup: Optional[str] = None) -> List[Asset]:
        """Get external assets for a word."""
        if assetgroup:
            rows = self.execute_fetchall(
                "SELECT * FROM external_assets WHERE uuid = %s AND assetgroup = %s ORDER BY sid",
                (word_uuid, assetgroup)
            )
        else:
            rows = self.execute_fetchall(
                "SELECT * FROM external_assets WHERE uuid = %s ORDER BY assetgroup, sid",
                (word_uuid,)
            )
        return [Asset.from_row(row) for row in rows]
    
    def get_all_words(self, limit: Optional[int] = None) -> List[Word]:
        """Get all words in the dictionary."""
        query = "SELECT * FROM words ORDER BY word"
        if limit:
            query += f" LIMIT {limit}"
        rows = self.execute_fetchall(query)
        return [Word.from_row(row) for row in rows]
    
    def get_word_count(self) -> int:
        """Get the total number of words."""
        row = self.execute_fetchone("SELECT COUNT(*) as count FROM words")
        return row['count'] if row else 0
    
    def get_shortdef_count(self) -> int:
        """Get the total number of short definitions."""
        row = self.execute_fetchone("SELECT COUNT(*) as count FROM shortdef")
        return row['count'] if row else 0
    
    def get_asset_count(self) -> int:
        """Get the total number of external assets."""
        row = self.execute_fetchone("SELECT COUNT(*) as count FROM external_assets")
        return row['count'] if row else 0
    
    def get_asset_count_by_group(self) -> dict:
        """Get asset counts grouped by assetgroup."""
        rows = self.execute_fetchall(
            """SELECT assetgroup, COUNT(*) as count 
               FROM external_assets 
               GROUP BY assetgroup"""
        )
        return {row['assetgroup']: row['count'] for row in rows}

    def get_asset_count_by_package(self) -> dict:
        """Get asset counts grouped by package id."""
        rows = self.execute_fetchall(
            "SELECT package, COUNT(*) as count FROM external_assets GROUP BY package"
        )
        return {row['package']: row['count'] for row in rows}
    
    def delete_word(self, word_uuid: str):
        """Delete a word and all its related data (cascading)."""
        self.execute("DELETE FROM words WHERE uuid = %s", (word_uuid,))
    
    def clear_all_data(self):
        """Clear all data from the database."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM story_paragraphs")
                cursor.execute("DELETE FROM stories")
                cursor.execute("DELETE FROM external_assets")
                cursor.execute("DELETE FROM shortdef")
                cursor.execute("DELETE FROM words")
                conn.commit()
        finally:
            conn.close()
    
    def get_words_with_definitions(self, limit: Optional[int] = None) -> List[tuple]:
        """Get words with their definitions."""
        query = """
            SELECT w.uuid, w.word, w.functional_label, w.flags, 
                   array_agg(s.definition ORDER BY s.id) as definitions
            FROM words w
            LEFT JOIN shortdef s ON w.uuid = s.uuid
            GROUP BY w.uuid, w.word, w.functional_label, w.flags
            ORDER BY w.word
        """
        if limit:
            query += f" LIMIT {limit}"
        
        rows = self.execute_fetchall(query)
        result = []
        for row in rows:
            word = Word(
                word=row['word'],
                functional_label=row['functional_label'],
                uuid=row['uuid'],
                flags=row['flags'] or 0
            )
            definitions = row['definitions'] or []
            result.append((word, definitions))
        return result
    
    def get_all_definitions_with_words(self, limit: Optional[int] = None, starting_letter: Optional[str] = None, function_label: Optional[str] = None) -> List[dict]:
        """
        Get all definitions with their word data in a single optimized query.
        
        This eliminates the N+1 query problem when iterating through all words
        and their definitions (e.g., in the moderator page or asset generation).
        
        Args:
            limit: Maximum number of rows to return
            starting_letter: Filter by starting letter (a-z) or '-' for non-alphabetic
            function_label: Filter by function label (e.g., noun, verb, adjective, adverb)
        
        Returns:
            List of dicts with keys: uuid, word, functional_label, flags, def_id, definition
        """
        query = """
            SELECT 
                w.uuid, w.word, w.functional_label, w.flags,
                s.id as def_id, s.definition
            FROM words w
            INNER JOIN shortdef s ON w.uuid = s.uuid
        """
        params = []
        conditions = []
        if starting_letter:
            if starting_letter == '-':
                conditions.append("LOWER(SUBSTRING(w.word, 1, 1)) !~ '^[a-z]$'")
            else:
                conditions.append("LOWER(SUBSTRING(w.word, 1, 1)) = %s")
                params.append(starting_letter.lower())
        if function_label:
            conditions.append("w.functional_label = %s")
            params.append(function_label)
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY w.word, s.id"
        if limit:
            query += f" LIMIT {limit}"
        return self.execute_fetchall(query, tuple(params) if params else None)
    
    def get_words_needing_assets(self, assetgroup: str, limit: Optional[int] = None) -> List[str]:
        """Get UUIDs of words that don't have a specific asset type."""
        query = """
            SELECT DISTINCT w.uuid
            FROM words w
            LEFT JOIN external_assets e 
                ON w.uuid = e.uuid AND e.assetgroup = %s
            WHERE e.uuid IS NULL
            ORDER BY w.uuid
        """
        if limit:
            query += f" LIMIT {limit}"
        
        rows = self.execute_fetchall(query, (assetgroup,))
        return [row['uuid'] for row in rows]
    
    def get_definitions_needing_assets(self, assetgroup: str, limit: Optional[int] = None) -> List[tuple]:
        """Get (uuid, definition_id) pairs that don't have a specific asset type."""
        query = """
            SELECT DISTINCT s.uuid, s.id
            FROM shortdef s
            LEFT JOIN external_assets e 
                ON s.uuid = e.uuid AND e.assetgroup = %s AND e.sid = s.id
            WHERE e.uuid IS NULL
            ORDER BY s.uuid, s.id
        """
        if limit:
            query += f" LIMIT {limit}"
        
        rows = self.execute_fetchall(query, (assetgroup,))
        return [(row['uuid'], row['id']) for row in rows]
    
    def batch_add_words(self, words: List[tuple]) -> int:
        """
        Add multiple words in a single transaction.
        
        Args:
            words: List of (word, functional_label, uuid, flags) tuples
        
        Returns:
            Number of words added
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO words (word, functional_label, uuid, flags)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (uuid) DO NOTHING""",
                    words
                )
                count = cursor.rowcount
                conn.commit()
                return count
        except Exception as e:
            self.logger.error(f"[batch_add_words] Exception: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def batch_add_shortdefs(self, definitions: List[tuple]) -> int:
        """
        Add multiple short definitions in a single transaction.
        
        Args:
            definitions: List of (uuid, definition) tuples
        
        Returns:
            Number of definitions added
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO shortdef (uuid, definition)
                       VALUES (%s, %s)
                       ON CONFLICT (uuid, definition) DO NOTHING""",
                    definitions
                )
                count = cursor.rowcount
                conn.commit()
                return count
        except Exception as e:
            self.logger.error(f"[batch_add_shortdefs] Exception: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def update_word_flags(self, word_uuid: str, flags: int):
        """Update the flags for a word."""
        self.execute(
            "UPDATE words SET flags = %s WHERE uuid = %s",
            (flags, word_uuid)
        )
    
    # Story-related methods
    def add_story(self, story_uuid: str, title: str, style: str, grouping: str, difficulty: str):
        """Add a story to the database."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO stories (uuid, title, style, grouping, difficulty)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (uuid) DO UPDATE SET 
                           title = EXCLUDED.title,
                           style = EXCLUDED.style,
                           grouping = EXCLUDED.grouping,
                           difficulty = EXCLUDED.difficulty""",
                    (story_uuid, title, style, grouping, difficulty)
                )
                conn.commit()
        finally:
            conn.close()
    
    def add_story_paragraph(self, story_uuid: str, paragraph_index: int, 
                           paragraph_title: str, content: str):
        """Add a paragraph to a story."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO story_paragraphs 
                       (story_uuid, paragraph_index, paragraph_title, content)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (story_uuid, paragraph_index) DO UPDATE SET 
                           paragraph_title = EXCLUDED.paragraph_title,
                           content = EXCLUDED.content""",
                    (story_uuid, paragraph_index, paragraph_title, content)
                )
                conn.commit()
        finally:
            conn.close()
    
    def get_story(self, story_uuid: str) -> Optional[Story]:
        """Get a story by its UUID."""
        row = self.execute_fetchone(
            "SELECT * FROM stories WHERE uuid = %s",
            (story_uuid,)
        )
        return Story.from_row(row) if row else None
    
    def get_story_paragraphs(self, story_uuid: str) -> List[StoryParagraph]:
        """Get all paragraphs for a story."""
        rows = self.execute_fetchall(
            """SELECT * FROM story_paragraphs 
               WHERE story_uuid = %s 
               ORDER BY paragraph_index""",
            (story_uuid,)
        )
        return [StoryParagraph.from_row(row) for row in rows]
    
    def get_all_stories(self) -> List[Story]:
        """Get all stories."""
        rows = self.execute_fetchall("SELECT * FROM stories ORDER BY title")
        return [Story.from_row(row) for row in rows]
    
    def add_story_word(self, story_uuid: str, word_uuid: str, paragraph_index: int):
        """Add a word reference to a story."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """INSERT INTO story_words (story_uuid, word_uuid, paragraph_index)
                       VALUES (%s, %s, %s)
                       ON CONFLICT DO NOTHING""",
                    (story_uuid, word_uuid, paragraph_index)
                )
                conn.commit()
        finally:
            conn.close()
    
    def batch_add_story_words(self, story_words: List[tuple]) -> int:
        """
        Add multiple story word references in a single transaction.
        
        Args:
            story_words: List of (story_uuid, word_uuid, paragraph_index) tuples
        
        Returns:
            Number of story words added
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO story_words (story_uuid, word_uuid, paragraph_index)
                       VALUES (%s, %s, %s)
                       ON CONFLICT DO NOTHING""",
                    story_words
                )
                count = cursor.rowcount
                conn.commit()
                return count
        except Exception as e:
            self.logger.error(f"[batch_add_story_words] Exception: {e}")
            conn.rollback()
            raise
        finally:
            conn.close()
    
    def get_story_words(self, story_uuid: str) -> List[dict]:
        """Get all word UUIDs and paragraph indices for a story."""
        rows = self.execute_fetchall(
            """SELECT word_uuid, paragraph_index 
               FROM story_words 
               WHERE story_uuid = %s 
               ORDER BY paragraph_index, word_uuid""",
            (story_uuid,)
        )
        return [{"word_uuid": row["word_uuid"], "paragraph_index": row["paragraph_index"]} for row in rows]
    
    def delete_story_words(self, story_uuid: str) -> int:
        """Delete all word references for a story."""
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM story_words WHERE story_uuid = %s",
                    (story_uuid,)
                )
                count = cursor.rowcount
                conn.commit()
                return count
        finally:
            conn.close()
    
    def delete_story(self, story_uuid: str) -> bool:
        """
        Delete a story and all associated data (paragraphs and word references).
        Returns True if story was deleted, False if it didn't exist.
        """
        conn = self._get_connection()
        try:
            with conn.cursor() as cursor:
                # Check if story exists
                cursor.execute(
                    "SELECT COUNT(*) as count FROM stories WHERE uuid = %s",
                    (story_uuid,)
                )
                result = cursor.fetchone()
                if not result or result[0] == 0:
                    return False
                
                # Delete story (CASCADE will handle paragraphs and word references)
                cursor.execute(
                    "DELETE FROM stories WHERE uuid = %s",
                    (story_uuid,)
                )
                conn.commit()
                return True
        finally:
            conn.close()
    
    def vacuum(self):
        """PostgreSQL doesn't need explicit VACUUM in normal operation."""
        # PostgreSQL auto-vacuum handles this
        pass
    
    def close(self):
        """Close is handled per-connection in PostgreSQL."""
        # Each method handles its own connection
        pass