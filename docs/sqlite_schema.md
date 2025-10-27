# SQLite Schema Documentation

This document describes the database schema used by the ESL Builder project as implemented in `libs/sqlite_dictionary.py`.functional_label TEXT,

## SQLite schema and data model

This document summarizes the SQLite schema used by the ESL Builder project. The implementation in `libs/sqlite_dictionary.py` is the source of truth. If this doc and the code differ, follow the code.

### Database configuration

```sql
PRAGMA journal_mode=DELETE;   -- Disable WAL/SHM files
PRAGMA foreign_keys=ON;       -- Enforce FK constraints with CASCADE deletes
```

### words

```sql
CREATE TABLE IF NOT EXISTS words (
  word TEXT NOT NULL,
  functional_label TEXT,
  uuid TEXT PRIMARY KEY,
  flags INTEGER DEFAULT 0,
  level TEXT
);

CREATE INDEX IF NOT EXISTS idx_words_word ON words(word);
CREATE INDEX IF NOT EXISTS idx_words_level ON words(level);
CREATE INDEX IF NOT EXISTS idx_words_level_word ON words(level, word);
```

- word: TEXT — headword (required)
- functional_label: TEXT — part of speech / label (e.g., "noun")
- uuid: TEXT — primary key per word sense
- flags: INTEGER — bitfield (see below)
- level: TEXT — CEFR level (e.g., "A1", "A2", "B1", "B2", "C1", "C2")

#### Flags bitfield

| Bit | Value | Meaning         |
|-----|-------|----------------|
| 1   | 1     | offensive      |
| 2   | 2     | british        |
| 3   | 4     | us             |
| 4   | 8     | old-fashioned  |

Dataclass:
```python
@dataclass(frozen=True)
class Flags:
  offensive: bool = False
  british: bool = False
  us: bool = False
  old_fashioned: bool = False

  @staticmethod
  def from_int(flags: int) -> "Flags":
    ...
  def to_int(self) -> int:
    ...

@dataclass(frozen=True)
class Word:
  word: str
  functional_label: Optional[str]
  uuid: str
  flags: int = 0
  level: Optional[str] = None

  @property
  def flagset(self) -> Flags:
    ...
```

### shortdef

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

- uuid: TEXT — FK → words.uuid
- definition: TEXT — short definition
- id: INTEGER — primary key

Dataclass:
```python
@dataclass(frozen=True)
class ShortDef:
  uuid: str
  definition: str
  id: int
```

### external_assets

```sql
CREATE TABLE IF NOT EXISTS external_assets (
  uuid TEXT,
  assetgroup TEXT,
  sid INTEGER,
  package TEXT NOT NULL CHECK(length(package) = 2),
  filename TEXT,
  FOREIGN KEY (uuid) REFERENCES words(uuid) ON DELETE CASCADE,
  UNIQUE(uuid, assetgroup, sid)
);

CREATE INDEX IF NOT EXISTS idx_external_assets_type_int ON external_assets(assetgroup, sid);
CREATE INDEX IF NOT EXISTS idx_external_assets_uuid ON external_assets(uuid);
```

- assetgroup: one of "word", "shortdef", "image"
- sid: 0 for word-level assets; otherwise `shortdef.id`
- package: two-character id (e.g., `a0`)

Dataclass (intent):
```python
@dataclass(frozen=True)
class Asset:
  uuid: str
  assetgroup: Literal["word", "image", "shortdef"]
  sid: int
  package: str
  filename: str
```

### Relationships

```
words (1) ──< shortdef (many)
  │
  └──< external_assets (many)

shortdef (1) ──< external_assets (many)  [via sid]
```

### Asset naming conventions

- Word audio: `word_{uuid}_0.{ext}` → assetgroup="word", sid=0
- Definition audio: `shortdef_{uuid}_{id}.{ext}` → assetgroup="shortdef", sid=id
- Definition image: `image_{uuid}_{id}.{ext}` → assetgroup="image", sid=id

### Packaging (build_package.py)

- Audio transcoded to low-bitrate mono AAC; images downscaled to HEIF; filenames prefixed with `low_`.
- Assets zipped in ~100MB chunks. The two-character `package` id is stored with each asset.

### Examples

```python
db = SQLiteDictionary()
entries = db.get_word("apple")
for e in entries:
  defs = db.get_shortdefs(e.uuid)
  # word audio
  # db.add_asset(e.uuid, "word", 0, pkg, fname)
  # def audio + image
  # db.add_asset(e.uuid, "shortdef", defs[0].id, pkg, fname)
  # db.add_asset(e.uuid, "image", defs[0].id, pkg, fname)
db.close()
```

