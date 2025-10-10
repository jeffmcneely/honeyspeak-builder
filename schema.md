# Core Data Schema for Merriam-Webster Dictionary API

## Overview

This Core Data schema is designed to store dictionary entries from the Merriam-Webster Dictionary API. The schema preserves the rich hierarchical structure of dictionary definitions while providing efficient lookup capabilities. The primary lookup key is `meta.uuid`, which uniquely identifies each dictionary entry variant.

## Entity Relationships

```
DictionaryEntry (Root Entity)
├── Meta (1:1) - Metadata about the entry
│   ├── Target (1:1) - Target reference information
│   └── Stem (1:many) - Word stems and variants
├── HeadwordInfo (1:1) - Pronunciation and headword data
│   └── Pronunciation (1:many) - IPA pronunciations with audio
├── Inflection (1:many) - Grammatical inflections
├── Definition (1:many) - Primary definitions
│   └── DefinitionSense (1:many) - Individual word senses
│       ├── DefinitionText (1:many) - Text components of definition
│       └── DefinitionExample (1:many) - Usage examples
├── DerivedPhrase (1:many) - Derived phrases and idioms
│   └── DerivedDefinition (1:many) - Definitions for derived phrases
└── ShortDefinition (1:many) - Simplified definitions
```

## Core Entities

### 1. DictionaryEntry (Root Entity)
Primary entity representing a complete dictionary entry.

**Attributes:**
- `uuid` (String, Required, Unique) - Primary lookup key from meta.uuid
- `entryId` (String, Required) - Dictionary ID (meta.id)
- `homograph` (Integer 16) - Homograph number (hom)
- `functionalLabel` (String) - Part of speech (fl)
- `offensive` (Boolean) - Whether entry contains offensive content
- `dateCreated` (Date) - Timestamp when entry was added
- `rawJSON` (String, Optional) - Complete original JSON for debugging

**Indexes:**
- Primary: uuid
- Secondary: entryId, functionalLabel

### 2. Meta (Metadata Entity)
Stores metadata information for each dictionary entry.

**Attributes:**
- `uuid` (String, Required) - Same as parent DictionaryEntry uuid
- `entryId` (String, Required) - Dictionary entry ID
- `source` (String) - Source dictionary (learners, collegiate, etc.)
- `section` (String) - Dictionary section (alpha, etc.)
- `highlight` (String, Optional) - Highlight status
- `offensive` (Boolean) - Offensive content flag

**Relationships:**
- `dictionaryEntry` (1:1 to DictionaryEntry)
- `target` (1:1 to Target)
- `stems` (1:many to Stem)

### 3. Target (Target Reference Entity)
Reference to related entries in other dictionaries.

**Attributes:**
- `targetUUID` (String) - Target entry UUID
- `targetSource` (String) - Target dictionary source

**Relationships:**
- `meta` (1:1 to Meta)

### 4. Stem (Word Stems Entity)
Individual word stems, variants, and phrases associated with the entry.

**Attributes:**
- `text` (String, Required) - The stem text
- `sortOrder` (Integer 16) - Order in original array

**Relationships:**
- `meta` (many:1 to Meta)

**Indexes:**
- Primary: text (for fast stem lookup)

### 5. HeadwordInfo (Headword Information)
Pronunciation and headword formatting information.

**Attributes:**
- `headword` (String, Required) - Formatted headword with syllable breaks

**Relationships:**
- `dictionaryEntry` (1:1 to DictionaryEntry)
- `pronunciations` (1:many to Pronunciation)

### 6. Pronunciation (Pronunciation Entity)
IPA pronunciation data with optional audio references.

**Attributes:**
- `ipa` (String, Required) - IPA pronunciation string
- `audioFile` (String, Optional) - Audio file reference
- `sortOrder` (Integer 16) - Order in pronunciations array

**Relationships:**
- `headwordInfo` (many:1 to HeadwordInfo)

### 7. Inflection (Inflection Entity)
Grammatical inflection information (plurals, verb forms, etc.).

**Attributes:**
- `label` (String) - Inflection label (e.g., "plural")
- `form` (String, Required) - Inflected form
- `cutback` (String, Optional) - Cutback notation
- `sortOrder` (Integer 16) - Order in inflections array

**Relationships:**
- `dictionaryEntry` (many:1 to DictionaryEntry)

### 8. Definition (Definition Group Entity)
Groups of related definition senses.

**Attributes:**
- `sortOrder` (Integer 16) - Order in definitions array

**Relationships:**
- `dictionaryEntry` (many:1 to DictionaryEntry)
- `senses` (1:many to DefinitionSense)

### 9. DefinitionSense (Individual Sense Entity)
Individual word senses within a definition group.

**Attributes:**
- `senseNumber` (String, Optional) - Sense number (e.g., "1", "1a")
- `grammar` (String, Optional) - Grammatical information
- `subject` (String, Optional) - Subject label (medical, informal, etc.)
- `sortOrder` (Integer 16) - Order within definition

**Relationships:**
- `definition` (many:1 to Definition)
- `texts` (1:many to DefinitionText)
- `examples` (1:many to DefinitionExample)

### 10. DefinitionText (Definition Text Components)
Individual text components that make up a definition.

**Attributes:**
- `textType` (String, Required) - Type of text ("text", "vis", "uns", etc.)
- `content` (String, Required) - The actual text content
- `sortOrder` (Integer 16) - Order within sense

**Relationships:**
- `sense` (many:1 to DefinitionSense)

### 11. DefinitionExample (Usage Examples)
Usage examples within definitions.

**Attributes:**
- `text` (String, Required) - Example text
- `sortOrder` (Integer 16) - Order within sense

**Relationships:**
- `sense` (many:1 to DefinitionSense)

### 12. DerivedPhrase (Derived Phrases/Idioms)
Derived phrases, idioms, and phrasal verbs.

**Attributes:**
- `phrase` (String, Required) - The derived phrase
- `grammar` (String, Optional) - Grammatical information
- `region` (String, Optional) - Regional usage (US, British, etc.)
- `variants` (String, Optional) - Alternative forms
- `sortOrder` (Integer 16) - Order in derived phrases

**Relationships:**
- `dictionaryEntry` (many:1 to DictionaryEntry)
- `definitions` (1:many to DerivedDefinition)

**Indexes:**
- Primary: phrase (for phrase lookup)

### 13. DerivedDefinition (Derived Phrase Definitions)
Definitions for derived phrases and idioms.

**Attributes:**
- `text` (String, Required) - Definition text
- `subject` (String, Optional) - Subject label
- `examples` (String, Optional) - JSON array of examples
- `sortOrder` (Integer 16) - Order within phrase

**Relationships:**
- `derivedPhrase` (many:1 to DerivedPhrase)

### 14. ShortDefinition (Simplified Definitions)
Simplified, learner-friendly definitions.

**Attributes:**
- `text` (String, Required) - Short definition text
- `sortOrder` (Integer 16) - Order in shortdef array

**Relationships:**
- `dictionaryEntry` (many:1 to DictionaryEntry)

## Key Design Decisions

### 1. UUID as Primary Key
- **Rationale**: Meta.uuid provides unique identification across dictionary variants
- **Benefits**: Enables reliable lookups, prevents duplicates, supports data synchronization
- **Implementation**: UUID field indexed for O(1) lookup performance

### 2. Hierarchical Definition Structure
- **Rationale**: Preserves the complex nested structure of dictionary definitions
- **Benefits**: Maintains semantic relationships, enables rich querying
- **Trade-off**: More complex than flat structure but preserves data fidelity

### 3. Separate Text Components
- **Rationale**: Dictionary definitions contain mixed content types (text, examples, cross-references)
- **Benefits**: Enables type-specific processing, maintains formatting information
- **Use Cases**: Rich text rendering, cross-reference resolution

### 4. Derived Phrases as Separate Entity
- **Rationale**: Phrases like "water under the bridge" are semantically distinct
- **Benefits**: Enables phrase-specific searches, maintains phrase-definition relationships
- **Indexing**: Phrase text indexed for efficient phrase lookup

### 5. Raw JSON Preservation
- **Rationale**: API response format may evolve, debugging complex parsing issues
- **Benefits**: Data recovery, format migration, debugging support
- **Storage**: Optional field to minimize storage when not needed

## Query Patterns

### Primary Lookups
```swift
// Find entry by UUID
let entry = fetchEntry(uuid: "4f1b9f17-247e-47c4-a43d-e6955d716bf3")

// Find entries by word stem
let entries = fetchEntries(stem: "water")

// Find entries by part of speech
let nouns = fetchEntries(functionalLabel: "noun")
```

### Complex Queries
```swift
// Find all derived phrases containing a word
let phrases = fetchDerivedPhrases(containing: "water")

// Find entries with audio pronunciations
let entriesWithAudio = fetchEntriesWithAudio()

// Find informal usage examples
let informalUsages = fetchExamples(subject: "informal")
```

## Performance Considerations

### Indexing Strategy
- **Primary Index**: UUID (unique, clustered)
- **Secondary Indexes**: entryId, functionalLabel, stem.text, derivedPhrase.phrase
- **Search Optimization**: Full-text search on definition text for semantic queries

### Data Loading
- **Lazy Loading**: Load definition details only when needed
- **Batch Operations**: Use batch inserts for initial data import
- **Caching**: Core Data's built-in object caching for frequently accessed entries

### Storage Optimization
- **String Normalization**: Consistent encoding for special characters
- **JSON Compression**: Compress rawJSON field when stored
- **Relationship Efficiency**: Use to-many relationships sparingly in main queries

## Migration Considerations

### Version 1.0 → Future
- **Additive Changes**: New entities/attributes can be added without migration
- **Schema Evolution**: Use Core Data's lightweight migration for compatible changes
- **Data Preservation**: rawJSON field enables data recovery during major migrations

### API Changes
- **Backward Compatibility**: Schema accommodates additional API fields
- **Field Mapping**: Clear mapping between API response and Core Data entities
- **Validation**: Entity validation rules ensure data consistency

## Usage Examples

### Import Process
1. Parse JSON response from Merriam-Webster API
2. Extract meta.uuid as primary key
3. Create DictionaryEntry with related entities
4. Populate hierarchical definition structure
5. Index stem words for fast lookup

### Query Examples
- **Word Lookup**: Find all entries where stems contain search term
- **Definition Search**: Full-text search across DefinitionText entities  
- **Phrase Discovery**: Search DerivedPhrase entities for idiomatic expressions
- **Cross-References**: Follow target relationships between entries

This schema provides a robust foundation for storing and querying Merriam-Webster dictionary data while maintaining the rich semantic structure of the original API responses.