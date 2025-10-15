# SQLite Schema Documentationcreate table words(

word TEXT,

This document describes the database schema used by the ESL Builder project as implemented in `libs/sqlite_dictionary.py`.functional_label TEXT,

uuid TEXT,

## Database Configurationoffensive INTEGER

);

```sql

PRAGMA journal_mode=DELETE;  -- Disable WAL and SHM filescreate table shortdef (

PRAGMA foreign_keys=ON;      -- Enable foreign key constraints for CASCADE DELETEuuid TEXT,

```def TEXT

);

## Tables

create table external_assets (

### words  uuid TEXT

  type TEXT,

Stores dictionary word entries with their metadata.  package INTEGER,

  filename TEXT

```sql);

CREATE TABLE IF NOT EXISTS words (

    word TEXT NOT NULL,
    functional_label TEXT,
    uuid TEXT PRIMARY KEY,
    offensive INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_words_word ON words(word);
```

**Columns:**
- `word` (TEXT, NOT NULL): The dictionary word
- `functional_label` (TEXT): Part of speech or grammatical function (e.g., "noun", "verb")
- `uuid` (TEXT, PRIMARY KEY): Unique identifier for this word sense
- `offensive` (INTEGER, DEFAULT 0): Flag indicating if word contains offensive content (0=false, 1=true)

**Indexes:**
- `idx_words_word`: Index on `word` column for fast lookups by word text

**Dataclass:**
```python
@dataclass(frozen=True)
class Word:
    word: str
    functional_label: Optional[str]
    uuid: str
    offensive: int = 0
```

---

### shortdef

Stores short definitions for word senses. Each word UUID can have multiple definitions.

```sql
CREATE TABLE IF NOT EXISTS shortdef (
    uuid TEXT,
    definition TEXT,
    id INTEGER PRIMARY KEY,
    FOREIGN KEY (uuid) REFERENCES words(uuid) ON DELETE CASCADE,
    UNIQUE(uuid, definition)
);

CREATE INDEX IF NOT EXISTS idx_shortdef_uuid ON shortdef(uuid);
```

**Columns:**
- `uuid` (TEXT): Foreign key to `words.uuid` - identifies which word this definition belongs to
- `definition` (TEXT): The short definition text
- `id` (INTEGER, PRIMARY KEY): Auto-incrementing unique identifier for this definition

**Constraints:**
- Foreign key to `words(uuid)` with `ON DELETE CASCADE` - deleting a word removes all its definitions
- `UNIQUE(uuid, definition)` - prevents duplicate definitions for the same word sense

**Indexes:**
- `idx_shortdef_uuid`: Index on `uuid` for fast lookups by word

**Dataclass:**
```python
@dataclass(frozen=True)
class ShortDef:
    uuid: str
    definition: str
    id: int
```

---

### external_assets

Stores references to external asset files (audio, images) associated with words and definitions.

```sql
CREATE TABLE IF NOT EXISTS external_assets (
    uuid TEXT,
    assetgroup TEXT,
    sid INTEGER,
    package INTEGER,
    filename TEXT,
    FOREIGN KEY (uuid) REFERENCES words(uuid) ON DELETE CASCADE,
    UNIQUE(uuid, assetgroup, sid)
);

CREATE INDEX IF NOT EXISTS idx_external_assets_type_int ON external_assets(assetgroup, sid);
```

**Columns:**
- `uuid` (TEXT): Foreign key to `words.uuid` - identifies which word this asset belongs to
- `assetgroup` (TEXT): Type of asset - one of: "word", "image", "shortdef"
  - `"word"`: Audio file for the word pronunciation
  - `"shortdef"`: Audio file for definition pronunciation
  - `"image"`: Image illustration for the definition
- `sid` (INTEGER): Shortdef ID reference (0 for word-level assets, shortdef.id for definition assets)
- `package` (INTEGER): Package file number (for splitting assets across multiple zip files)
- `filename` (TEXT): Filename of the asset in the package

**Constraints:**
- Foreign key to `words(uuid)` with `ON DELETE CASCADE` - deleting a word removes all its assets
- `UNIQUE(uuid, assetgroup, sid)` - prevents duplicate asset entries for the same word/type/definition combination

**Indexes:**
- `idx_external_assets_type_int`: Composite index on `(assetgroup, sid)` for fast lookups by asset type

**Dataclass:**
```python
@dataclass(frozen=True)
class Asset:
    uuid: str
    assetgroup: Literal["word", "image", "shortdef"]
    sid: int
    package: int
    filename: str
```

---

## Relationships

```
words (1) ──< (many) shortdef
  │
  └──< (many) external_assets

shortdef (1) ──< (many) external_assets [via sid]
```

- A `word` can have multiple `shortdef` entries (different definitions/senses)
- A `word` can have multiple `external_assets` (audio for word, images/audio for definitions)
- A `shortdef` can have multiple `external_assets` (audio and images for that definition)
- All relationships use `ON DELETE CASCADE` to maintain referential integrity

---

## Asset Organization

Assets are organized as follows:

### Word-level assets
- **Audio**: `word_{uuid}_0.{format}` (pronunciation of the word itself)
- References: `uuid` from words table, `sid=0`, `assetgroup="word"`

### Definition-level assets
- **Audio**: `shortdef_{uuid}_{id}.{format}` (pronunciation of definition)
- **Image**: `image_{uuid}_{id}.{format}` (illustration for definition)
- References: `uuid` from words table, `sid={shortdef.id}`, `assetgroup="shortdef"` or `"image"`

### Packaging
- Assets are bundled into zip files: `package_0.zip`, `package_1.zip`, etc.
- Package splitting occurs when a package exceeds `MAX_FILE_SIZE` (100 MB by default)
- The `package` column tracks which zip file contains each asset

---

## Usage Examples

### Finding a word and its definitions
```python
db = SQLiteDictionary()
word_entries = db.get_word("apple")  # Returns List[Word]
for entry in word_entries:
    definitions = db.get_shortdefs(entry.uuid)  # Returns List[ShortDef]
```

### Getting assets for a word
```python
assets = db.get_assets(uuid, "word", 0)  # Get word audio
assets = db.get_assets(uuid, "image", definition_id)  # Get definition image
```

### Cascade deletion
```python
db.delete_word_by_uuid(uuid)  # Automatically deletes all shortdefs and external_assets
```
