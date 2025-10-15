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
        offensive INTEGER DEFAULT 0
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
]


# Typed models returned by the repository
@dataclass(frozen=True)
class Word:
    word: str
    functional_label: Optional[str]
    uuid: str
    offensive: int = 0

    @staticmethod
    def from_row(row: sqlite3.Row) -> "Word":
        return Word(
            word=row["word"],
            functional_label=row["functional_label"],
            uuid=row["uuid"],
            offensive=row["offensive"] if "offensive" in row.keys() else 0,
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
        offensive: int = 0,
    ) -> str | None:
        try:
            cursor = self.connection.cursor()
            if not uuid_:
                uuid_ = str(uuid.uuid4())
            cursor.execute("SELECT 1 FROM words WHERE uuid = ?", (uuid_,))
            if cursor.fetchone():
                return None
            cursor.execute(
                "INSERT INTO words (word, functional_label, uuid, offensive) VALUES (?, ?, ?, ?)",
                (word, functional_label, uuid_, offensive),
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
        offensive: int | None = None,
    ) -> int:
        try:
            cursor = self.connection.cursor()
            updates = []
            params = []
            if functional_label is not None:
                updates.append("functional_label = ?")
                params.append(functional_label)
            if offensive is not None:
                updates.append("offensive = ?")
                params.append(offensive)
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
        offensive: int | None = None,
    ) -> int:
        """Preferred update using uuid as identifier."""
        try:
            cursor = self.connection.cursor()
            updates = []
            params = []
            if functional_label is not None:
                updates.append("functional_label = ?")
                params.append(functional_label)
            if offensive is not None:
                updates.append("offensive = ?")
                params.append(offensive)
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
        package: int,
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

    def close(self):
        try:
            if self.connection:
                self.connection.close()
        except Exception as e:
            print(f"[close] Exception: {e}")
