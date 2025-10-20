import sqlite3
from dataclasses import dataclass
from pathlib import Path
import uuid
from typing import Literal, Optional, Iterable, List

SQLITE_SCHEMA = [
    # words: uuid is the PRIMARY KEY; index on word for faster lookups
    """CREATE TABLE IF NOT EXISTS words (
        word TEXT NOT NULL,
        functional_label TEXT,
        uuid TEXT PRIMARY KEY,
        flags INTEGER DEFAULT 0
    )""",
    """CREATE INDEX IF NOT EXISTS idx_words_word ON words(word)""",
    # shortdef: unique per (uuid, def), cascade delete on words.uuid
    """CREATE TABLE IF NOT EXISTS shortdef (
        uuid TEXT,
        definition TEXT,
        id INTEGER PRIMARY KEY,
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
    """CREATE INDEX IF NOT EXISTS idx_story_paragraphs_uuid ON story_paragraphs(story_uuid)"""
]


# Typed models returned by the repository
@dataclass(frozen=True)
class Flags:
    offensive: bool = False
    british: bool = False
    us: bool = False
    old_fashioned: bool = False
    informal: bool = False

    NONE: int = 0
    OFFENSIVE: int = 1
    BRITISH: int = 2
    US: int = 4
    OLD_FASHIONED: int = 8
    INFORMAL: int = 16

    @staticmethod
    def from_int(flags: int) -> "Flags":
        return Flags(
            offensive=bool(flags & Flags.OFFENSIVE),
            british=bool(flags & Flags.BRITISH),
            us=bool(flags & Flags.US),
            old_fashioned=bool(flags & Flags.OLD_FASHIONED),
            informal=bool(flags & Flags.INFORMAL),
        )

    def to_int(self) -> int:
        val = 0
        if self.offensive:
            val |= Flags.OFFENSIVE
        if self.british:
            val |= Flags.BRITISH
        if self.us:
            val |= Flags.US
        if self.old_fashioned:
            val |= Flags.OLD_FASHIONED
        if self.informal:
            val |= Flags.INFORMAL
        return val

@dataclass(frozen=True)
class Word:
    word: str
    functional_label: Optional[str]
    uuid: str
    flags: int = 0

    @property
    def flagset(self) -> Flags:
        return Flags.from_int(self.flags)

    @staticmethod
    def from_row(row: sqlite3.Row) -> "Word":
        return Word(
            word=row["word"],
            functional_label=row["functional_label"],
            uuid=row["uuid"],
            flags=row["flags"] if "flags" in row.keys() else 0,
        )


@dataclass(frozen=True)
class ShortDef:
    uuid: str
    definition: str
    id: int

    @staticmethod
    def from_row(row: sqlite3.Row) -> "ShortDef":
        return ShortDef(uuid=row["uuid"], definition=row["definition"], id=row["id"])


@dataclass(frozen=True)
class Asset:
    uuid: str
    assetgroup: Literal["word", "word", "shortdef"]
    sid: int
    package: int
    filename: str

    @staticmethod
    def from_row(row: sqlite3.Row) -> "Asset":
        return Asset(
            uuid=row["uuid"],
            assetgroup=row["type"],
            sid=int(row["sid"]) if str(row["sid"]).isdigit() else 0,
            package=row["package"],
            filename=row["filename"],
        )


@dataclass(frozen=True)
class Story:
    uuid: str
    title: str
    style: str
    grouping: str
    difficulty: str

    @staticmethod
    def from_row(row: sqlite3.Row) -> "Story":
        return Story(
            uuid=row["uuid"],
            title=row["title"],
            style=row["style"],
            grouping=row["grouping"],
            difficulty=row["difficulty"],
        )


@dataclass(frozen=True)
class StoryParagraph:
    story_uuid: str
    paragraph_index: int
    paragraph_title: str
    content: str

    @staticmethod
    def from_row(row: sqlite3.Row) -> "StoryParagraph":
        return StoryParagraph(
            story_uuid=row["story_uuid"],
            paragraph_index=row["paragraph_index"],
            paragraph_title=row["paragraph_title"],
            content=row["content"],
        )


class SQLiteDictionary:
    def __init__(self, db_path: str = "Dictionary.sqlite"):
        self.db_path = db_path
        new_db = not Path(db_path).exists() or Path(db_path).stat().st_size == 0
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row

        # Disable WAL and SHM files
        self.connection.execute("PRAGMA journal_mode=DELETE")

        # Enable foreign key constraints for CASCADE DELETE
        self.connection.execute("PRAGMA foreign_keys=ON")

        if new_db:
            self._create_tables()

    def _create_tables(self) -> None:
        cursor = self.connection.cursor()
        for stmt in SQLITE_SCHEMA:
            try:
                cursor.execute(stmt)
            except Exception as e:
                print(f"unable to execute statement '{stmt}'\n{e}")
        self.connection.commit()

        # CRUD for words

    def add_word(
        self,
        word: str,
        functional_label: str | None = None,
        uuid_: str | None = None,
        flags: int = 0,
    ) -> str | None:
        try:
            cursor = self.connection.cursor()
            if not uuid_:
                uuid_ = str(uuid.uuid4())
            cursor.execute("SELECT 1 FROM words WHERE uuid = ?", (uuid_,))
            if cursor.fetchone():
                return None
            cursor.execute(
                "INSERT INTO words (word, functional_label, uuid, flags) VALUES (?, ?, ?, ?)",
                (word, functional_label, uuid_, flags),
            )
            self.connection.commit()
            return uuid_
        except Exception as e:
            print(f"[add_word] Exception: {e}")
            raise

    def get_word_by_uuid(self, uuid: str) -> Optional[Word]:
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM words WHERE uuid = ?", (uuid,))
            row = cursor.fetchone()
            return Word.from_row(row) if row else None
        except Exception as e:
            print(f"[get_word_by_uuid] Exception: {e}")
            return None

    def get_uuids(self, word: str) -> list[str]:
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT uuid FROM words WHERE word = ?", (word,))
            rows = cursor.fetchall()
            return [row["uuid"] for row in rows]
        except Exception as e:
            print(f"[get_uuids] Exception: {e}")
            return []

    def get_word(self, word: str) -> List[Word]:
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM words WHERE word = ?", (word,))
            rows = cursor.fetchall()
            return [Word.from_row(r) for r in rows]
        except Exception as e:
            print(f"[get_word] Exception: {e}")
            return []

    def get_all_words(self) -> List[Word]:
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM words")
            return [Word.from_row(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"[get_all_words] Exception: {e}")
            return []

    def get_word_count(self) -> int:
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT COUNT(*) as count FROM words")
            row = cursor.fetchone()
            return row["count"] if row else 0
        except Exception as e:
            print(f"[get_word_count] Exception: {e}")
            return 0

    def get_random_word(self) -> Optional[Word]:
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM words ORDER BY RANDOM() LIMIT 1")
            row = cursor.fetchone()
            return Word.from_row(row) if row else None
        except Exception as e:
            print(f"[get_random_word] Exception: {e}")
            return None

    def update_word(
        self,
        word: str,
        functional_label: str | None = None,
        flags: int | None = None,
    ) -> int:
        try:
            cursor = self.connection.cursor()
            updates = []
            params = []
            if functional_label is not None:
                updates.append("functional_label = ?")
                params.append(functional_label)
            if flags is not None:
                updates.append("flags = ?")
                params.append(flags)
            if not updates:
                return 0
            params.append(word)
            cursor.execute(
                f"UPDATE words SET {', '.join(updates)} WHERE word = ?", params
            )
            self.connection.commit()
            return cursor.rowcount
        except Exception as e:
            print(f"[update_word] Exception: {e}")
            return 0

    def update_word_by_uuid(
        self,
        uuid_: str,
        functional_label: str | None = None,
        flags: int | None = None,
    ) -> int:
        """Preferred update using uuid as identifier."""
        try:
            cursor = self.connection.cursor()
            updates = []
            params = []
            if functional_label is not None:
                updates.append("functional_label = ?")
                params.append(functional_label)
            if flags is not None:
                updates.append("flags = ?")
                params.append(flags)
            if not updates:
                return 0
            params.append(uuid_)
            cursor.execute(
                f"UPDATE words SET {', '.join(updates)} WHERE uuid = ?", params
            )
            self.connection.commit()
            return cursor.rowcount
        except Exception as e:
            print(f"[update_word_by_uuid] Exception: {e}")
            return 0

    def delete_word(self, word: str) -> int:
        try:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM words WHERE word = ?", (word,))
            self.connection.commit()
            return cursor.rowcount
        except Exception as e:
            print(f"[delete_word] Exception: {e}")
            return 0

    def delete_word_by_uuid(self, uuid_: str) -> int:
        try:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM words WHERE uuid = ?", (uuid_,))
            self.connection.commit()
            return cursor.rowcount
        except Exception as e:
            print(f"[delete_word_by_uuid] Exception: {e}")
            return 0

    # CRUD for shortdef
    def add_shortdef(self, uuid_: str, definition: str) -> bool:
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT 1 FROM shortdef WHERE uuid = ? AND definition = ?",
                (uuid_, definition),
            )
            if cursor.fetchone():
                return False
            cursor.execute(
                "INSERT INTO shortdef (uuid, definition) VALUES (?, ?)",
                (uuid_, definition),
            )
            self.connection.commit()
            return True
        except Exception as e:
            print(f"[add_shortdef] Exception: {e}")
            return False

    def get_shortdefs(self, uuid_: str) -> List[ShortDef]:
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM shortdef WHERE uuid = ?", (uuid_,))
            return [ShortDef.from_row(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"[get_shortdefs] Exception: {e}")
            return []

    def update_shortdef(self, uuid_: str, def_: str) -> int:
        try:
            cursor = self.connection.cursor()
            cursor.execute("UPDATE shortdef SET def = ? WHERE uuid = ?", (def_, uuid_))
            self.connection.commit()
            return cursor.rowcount
        except Exception as e:
            print(f"[update_shortdef] Exception: {e}")
            return 0

    def delete_shortdef(self, uuid_: str) -> int:
        try:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM shortdef WHERE uuid = ?", (uuid_,))
            self.connection.commit()
            return cursor.rowcount
        except Exception as e:
            print(f"[delete_shortdef] Exception: {e}")
            return 0

    # CRUD for external_assets
    def add_asset(
        self,
        uuid_: str,
        assetgroup: Literal["word", "image", "shortdef"],
        sid: int,
        package: str,
        filename: str,
    ) -> bool:
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO external_assets (uuid, assetgroup, sid, package, filename) VALUES (?, ?, ?, ?, ?)",
                (uuid_, assetgroup, sid, package, str(filename)),
            )
            self.connection.commit()
            return True
        except Exception as e:
            print(f"[add_asset] Exception: {e}")
            return False

    def get_assets(
        self, uuid_: str, assetgroup: Literal["word", "image", "shortdef"], id: int
    ) -> List[Asset]:
        try:
            cursor = self.connection.cursor()
            query = "SELECT * FROM external_assets WHERE uuid = ? AND assetgroup = ? AND sid = ?"
            cursor.execute(query, (uuid_, assetgroup, id))
            return [Asset.from_row(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"[get_assets] Exception: {e}")
            return []

    def delete_asset(
        self, uuid_: str, assetgroup: Literal["word", "image", "shortdef"], sid: int = 0
    ) -> int:
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "DELETE FROM external_assets WHERE uuid = ? AND assetgroup = ? AND sid = ?",
                (uuid_, assetgroup, sid),
            )
            self.connection.commit()
            return cursor.rowcount
        except Exception as e:
            print(f"[delete_asset] Exception: {e}")
            return 0

    def delete_assets(self) -> int:
        try:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM external_assets")
            self.connection.commit()
            return cursor.rowcount
        except Exception as e:
            print(f"[delete_assets] Exception: {e}")
            return 0

    # CRUD for stories
    def add_story(
        self,
        uuid_: str,
        title: str,
        style: str,
        grouping: str,
        difficulty: str,
    ) -> bool:
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO stories (uuid, title, style, grouping, difficulty) VALUES (?, ?, ?, ?, ?)",
                (uuid_, title, style, grouping, difficulty),
            )
            self.connection.commit()
            return True
        except Exception as e:
            print(f"[add_story] Exception: {e}")
            return False

    def get_story(self, uuid_: str) -> Optional[Story]:
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM stories WHERE uuid = ?", (uuid_,))
            row = cursor.fetchone()
            return Story.from_row(row) if row else None
        except Exception as e:
            print(f"[get_story] Exception: {e}")
            return None

    def get_all_stories(self) -> List[Story]:
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM stories")
            return [Story.from_row(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"[get_all_stories] Exception: {e}")
            return []

    def get_stories_by_grouping(self, grouping: str) -> List[Story]:
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM stories WHERE grouping = ?", (grouping,))
            return [Story.from_row(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"[get_stories_by_grouping] Exception: {e}")
            return []

    def get_stories_by_difficulty(self, difficulty: str) -> List[Story]:
        try:
            cursor = self.connection.cursor()
            cursor.execute("SELECT * FROM stories WHERE difficulty = ?", (difficulty,))
            return [Story.from_row(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"[get_stories_by_difficulty] Exception: {e}")
            return []

    def update_story(
        self,
        uuid_: str,
        title: str | None = None,
        style: str | None = None,
        grouping: str | None = None,
        difficulty: str | None = None,
    ) -> int:
        try:
            cursor = self.connection.cursor()
            updates = []
            params = []
            if title is not None:
                updates.append("title = ?")
                params.append(title)
            if style is not None:
                updates.append("style = ?")
                params.append(style)
            if grouping is not None:
                updates.append("grouping = ?")
                params.append(grouping)
            if difficulty is not None:
                updates.append("difficulty = ?")
                params.append(difficulty)
            if not updates:
                return 0
            params.append(uuid_)
            cursor.execute(
                f"UPDATE stories SET {', '.join(updates)} WHERE uuid = ?", params
            )
            self.connection.commit()
            return cursor.rowcount
        except Exception as e:
            print(f"[update_story] Exception: {e}")
            return 0

    def delete_story(self, uuid_: str) -> int:
        try:
            cursor = self.connection.cursor()
            cursor.execute("DELETE FROM stories WHERE uuid = ?", (uuid_,))
            self.connection.commit()
            return cursor.rowcount
        except Exception as e:
            print(f"[delete_story] Exception: {e}")
            return 0

    # CRUD for story_paragraphs
    def add_story_paragraph(
        self,
        story_uuid: str,
        paragraph_index: int,
        paragraph_title: str,
        content: str,
    ) -> bool:
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "INSERT INTO story_paragraphs (story_uuid, paragraph_index, paragraph_title, content) VALUES (?, ?, ?, ?)",
                (story_uuid, paragraph_index, paragraph_title, content),
            )
            self.connection.commit()
            return True
        except Exception as e:
            print(f"[add_story_paragraph] Exception: {e}")
            return False

    def get_story_paragraphs(self, story_uuid: str) -> List[StoryParagraph]:
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT * FROM story_paragraphs WHERE story_uuid = ? ORDER BY paragraph_index",
                (story_uuid,),
            )
            return [StoryParagraph.from_row(row) for row in cursor.fetchall()]
        except Exception as e:
            print(f"[get_story_paragraphs] Exception: {e}")
            return []

    def get_story_paragraph(
        self, story_uuid: str, paragraph_index: int
    ) -> Optional[StoryParagraph]:
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "SELECT * FROM story_paragraphs WHERE story_uuid = ? AND paragraph_index = ?",
                (story_uuid, paragraph_index),
            )
            row = cursor.fetchone()
            return StoryParagraph.from_row(row) if row else None
        except Exception as e:
            print(f"[get_story_paragraph] Exception: {e}")
            return None

    def update_story_paragraph(
        self,
        story_uuid: str,
        paragraph_index: int,
        paragraph_title: str | None = None,
        content: str | None = None,
    ) -> int:
        try:
            cursor = self.connection.cursor()
            updates = []
            params = []
            if paragraph_title is not None:
                updates.append("paragraph_title = ?")
                params.append(paragraph_title)
            if content is not None:
                updates.append("content = ?")
                params.append(content)
            if not updates:
                return 0
            params.extend([story_uuid, paragraph_index])
            cursor.execute(
                f"UPDATE story_paragraphs SET {', '.join(updates)} WHERE story_uuid = ? AND paragraph_index = ?",
                params,
            )
            self.connection.commit()
            return cursor.rowcount
        except Exception as e:
            print(f"[update_story_paragraph] Exception: {e}")
            return 0

    def delete_story_paragraph(self, story_uuid: str, paragraph_index: int) -> int:
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "DELETE FROM story_paragraphs WHERE story_uuid = ? AND paragraph_index = ?",
                (story_uuid, paragraph_index),
            )
            self.connection.commit()
            return cursor.rowcount
        except Exception as e:
            print(f"[delete_story_paragraph] Exception: {e}")
            return 0

    def delete_story_paragraphs(self, story_uuid: str) -> int:
        try:
            cursor = self.connection.cursor()
            cursor.execute(
                "DELETE FROM story_paragraphs WHERE story_uuid = ?", (story_uuid,)
            )
            self.connection.commit()
            return cursor.rowcount
        except Exception as e:
            print(f"[delete_story_paragraphs] Exception: {e}")
            return 0

    def close(self):
        try:
            if self.connection:
                self.connection.close()
        except Exception as e:
            print(f"[close] Exception: {e}")
