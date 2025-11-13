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

test (1) ──< question (many)

question (1) ──< answer (many)
  └──> words (via body_uuid)
```

### test

```sql
CREATE TABLE test (
  id         INTEGER PRIMARY KEY,
  name       TEXT NOT NULL,
  version    INTEGER DEFAULT 1,
  created_at TEXT    DEFAULT CURRENT_TIMESTAMP
);
```

- id: INTEGER — primary key
- name: TEXT — test name (required)
- version: INTEGER — test version number (default 1)
- created_at: TEXT — timestamp when test was created

### question

```sql
CREATE TABLE question (
  id        INTEGER PRIMARY KEY,
  test_id   INTEGER NOT NULL REFERENCES test(id) ON DELETE CASCADE,
  level     TEXT,
  prompt    TEXT    NOT NULL,
  explanation TEXT,
  flags     INTEGER DEFAULT 0,
  UNIQUE(test_id, prompt)
);
```

- id: INTEGER — primary key
- test_id: INTEGER — FK → test.id
- level: TEXT — CEFR level (e.g., "a1", "a2", "b1", "b2", "c1", "c2")
- prompt: TEXT — question prompt (required)
- explanation: TEXT — optional explanation for the answer
- flags: INTEGER — bitfield for question flags
- UNIQUE constraint on (test_id, prompt)

### answer

```sql
CREATE TABLE answer (
  id          INTEGER PRIMARY KEY,
  question_id INTEGER NOT NULL REFERENCES question(id) ON DELETE CASCADE,
  body_uuid   TEXT    NOT NULL,
  is_correct  INTEGER NOT NULL CHECK (is_correct IN (0,1)),
  weight      REAL    DEFAULT 1.0,
  UNIQUE(question_id, body_uuid)
);
```

- id: INTEGER — primary key
- question_id: INTEGER — FK → question.id
- body_uuid: TEXT — UUID of the word from words table (stores the word UUID, not the word text)
- is_correct: INTEGER — 1 if correct answer, 0 if incorrect (CHECK constraint)
- weight: REAL — weight for scoring (default 1.0)
- UNIQUE constraint on (question_id, body_uuid)

Indexes:
```sql
CREATE INDEX idx_answer_qid           ON answer(question_id);
CREATE INDEX idx_answer_qid_correct   ON answer(question_id) WHERE is_correct = 1;
CREATE INDEX idx_answer_qid_incorrect ON answer(question_id) WHERE is_correct = 0;
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

