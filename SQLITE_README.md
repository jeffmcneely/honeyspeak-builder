# SQLite Dictionary Database (DEPRECATED)

⚠️ **This SQLite implementation has been deprecated in favor of the Core Data system.**

Please use the Core Data implementation instead:
- `dictionary.py` - Main Core Data dictionary script
- `coredata_dictionary.py` - Core Data database class
- See `COREDATA_README.md` for current documentation

## Features

- **Complete Dictionary Storage**: Stores full word definitions, pronunciations, parts of speech, and variations
- **Normalized Database Schema**: Efficient storage with proper relationships between words, definitions, and variants
- **API Usage Tracking**: Built-in tracking of dictionary API usage with date-based statistics  
- **Search Capabilities**: Fast word lookup, search, and random word selection
- **Migration Support**: Easy migration from existing DynamoDB data
- **Rich CLI Interface**: Interactive command-line tools with progress bars and formatted output

## Database Schema

The SQLite database uses a normalized schema with the following tables:

### Core Tables

- **`words`**: Main word entries with metadata and raw API data
- **`definitions`**: Individual word definitions with pronunciation and part of speech
- **`short_definitions`**: Multiple short definitions per word definition
- **`word_variants`**: Word inflections and variations
- **`api_usage`**: API usage tracking by date and type

### Relationships

```
words (1) ──── (many) definitions
              │
              └── (many) short_definitions
              └── (many) word_variants
```

## Installation

1. Install the required dependencies:
```bash
pip install -r requirements.txt
```

2. The SQLite database will be created automatically when you first use the system.

## Usage

### 1. Populate Database from Word Lists

Use the main script to fetch definitions and populate your database:

```bash
# From a word list file
python dictionary_sqlite.py wordlist.txt

# Specify custom database path
python dictionary_sqlite.py wordlist.txt my_dictionary.db

# Enable debug output
python dictionary_sqlite.py wordlist.txt dictionary.db --debug

# From comma-separated words (if file not found)
python dictionary_sqlite.py "word1,word2,word3"
```

### 2. Interactive Word Lookup

Run without arguments for interactive mode:

```bash
python dictionary_sqlite.py
```

Interactive commands:
- `quit` - Exit the program
- `random` - Get a random word from the database
- `search <term>` - Search for words containing the term
- `<word>` - Look up a specific word

### 3. Migrate from DynamoDB

If you have existing data in DynamoDB:

```bash
python migrate_dynamo_to_sqlite.py [output_database.db]
```

### 4. Example Usage Script

Run the example to see all features:

```bash
python example_usage.py
```

## API Reference

### DictionaryDB Class

The main database interface class.

```python
from sqlite_dictionary import DictionaryDB

# Initialize database
db = DictionaryDB("my_dictionary.db")

# Store word data (from dictionaryapi.com response)
db.store_word_data(word, api_response_data)

# Retrieve word data
word_data = db.get_word_data("example")

# Check if word exists
exists = db.word_exists("example")

# Search for words
results = db.search_words("exam", limit=50)

# Get random word
random_word = db.get_random_word()

# Get word count
count = db.get_word_count()

# List all words
words = db.list_all_words(limit=100, offset=0)

# API usage tracking
usage = db.get_api_usage("dictionary", "2024-01-15")
db.update_api_usage("dictionary", 150, "2024-01-15")

# Close connection
db.close()
```

### Key Methods

#### `store_word_data(word: str, api_data: List[Dict]) -> bool`
Stores complete word data from dictionaryapi.com API response.

#### `get_word_data(word: str) -> Optional[Dict]`
Retrieves complete word information including all definitions and variants.

#### `word_exists(word: str) -> bool`
Quick check if a word exists in the database.

#### `search_words(search_term: str, limit: int = 50) -> List[str]`
Searches for words containing the given term.

#### `get_random_word() -> Optional[Dict]`
Returns a random word with basic information for vocabulary practice.

## Data Structure

### Stored Word Data Format

When you retrieve a word, you get a comprehensive structure:

```python
{
    'word': 'example',
    'created_at': '2024-01-15 10:30:00',
    'updated_at': '2024-01-15 10:30:00',
    'raw_data': [...],  # Original API response
    'definitions': [
        {
            'meta_id': 'example:1',
            'functional_label': 'noun',
            'pronunciation': 'ɪg-ˈzæm-pəl',
            'short_definitions': [
                'something that serves as a pattern...',
                'a punishment inflicted on someone...'
            ],
            'variants': [
                {'text': 'examples', 'type': 'inflection'}
            ]
        }
    ]
}
```

## AWS Integration

The system still uses AWS for:
- **Secrets Manager**: Storing the dictionary API key
- **Profile-based Authentication**: Using the 'eslbuilder' profile

Make sure your AWS credentials are configured:

```bash
aws configure --profile eslbuilder
```

## Performance Features

- **Indexed searches** for fast word lookup
- **Batch operations** for efficient data loading
- **Connection pooling** for multiple operations
- **Progress tracking** with rich progress bars
- **Minimal memory footprint** with streaming operations

## File Structure

```
esl-random/
├── sqlite_dictionary.py      # Main database class
├── dictionary_sqlite.py      # CLI tool for populating database
├── migrate_dynamo_to_sqlite.py  # Migration utility
├── example_usage.py          # Usage examples
├── libs/
│   └── helper.py            # AWS helper functions
└── requirements.txt         # Python dependencies
```

## Advantages over DynamoDB

1. **No AWS costs** - Local SQLite database
2. **Faster queries** - Direct SQL operations
3. **Better search** - Full-text search capabilities
4. **Offline access** - No internet required after population
5. **Easier backup** - Single file database
6. **SQL flexibility** - Complex queries and joins
7. **Development friendly** - Easy to inspect and modify

## Database Management

### View Database Contents

```bash
# Install sqlite-utils for easy database inspection
pip install sqlite-utils

# View table schemas
sqlite-utils schema dictionary.db

# View word count
sqlite-utils "SELECT COUNT(*) as word_count FROM words" dictionary.db

# Search words
sqlite-utils "SELECT * FROM words WHERE word LIKE '%exam%'" dictionary.db
```

### Backup and Restore

```bash
# Backup (SQLite database is just a file)
cp dictionary.db dictionary_backup.db

# Or export to SQL
sqlite3 dictionary.db .dump > dictionary_backup.sql

# Restore from SQL
sqlite3 new_dictionary.db < dictionary_backup.sql
```

## Troubleshooting

### Common Issues

1. **AWS Profile not found**: Make sure `eslbuilder` profile is configured
2. **API key missing**: Check AWS Secrets Manager for `esl-writer` secret
3. **Database locked**: Close any existing connections before operations
4. **Permission denied**: Ensure write permissions for the database file location

### Debug Mode

Enable debug output to see API responses and database operations:

```bash
python dictionary_sqlite.py wordlist.txt dictionary.db --debug
```

## Contributing

1. Follow the existing code style
2. Add tests for new features
3. Update documentation for API changes
4. Ensure backward compatibility when possible

## License

This project uses the same license as the parent eslbuilder project.