# Apple Core Data Dictionary System

A comprehensive Core Data implementation for storing dictionary words from dictionaryapi.com, specifically designed for iOS and macOS app development.

## 🍎 Overview

This system creates Apple Core Data compatible databases that can be directly integrated into Xcode projects for iOS and macOS applications. Unlike standard SQLite databases, these use Core Data's specific table structure, metadata, and model definitions.

## ✨ Features

- **🏗️ Core Data Compatible**: Creates proper Core Data SQLite databases with metadata
- **📱 iOS/macOS Ready**: Direct integration with Xcode projects
- **🔄 Auto Model Generation**: Creates .xcdatamodeld files and Swift classes
- **⚡ Optimized Schema**: Normalized Core Data entity relationships
- **� Environment Variables**: Configurable via .env files
- **�📊 Usage Tracking**: Built-in API usage analytics
- **🔍 Rich Querying**: NSFetchRequest compatible structure
- **📦 Export Tools**: Complete Xcode integration packages

## 📁 Files Structure

```
esl-random/
├── coredata_dictionary.py          # Core Data database class
├── dictionary_coredata.py          # CLI tool for populating database
├── migrate_to_coredata.py          # Migration utilities
├── coredata_example.py             # Usage examples and demos
├── libs/helper.py                  # AWS helper functions
└── Generated Output/
    ├── DictionaryModel.xcdatamodeld/    # Core Data model
    │   └── contents                      # Model XML definition
    ├── Dictionary.sqlite                # Core Data database
    └── CoreDataModels.swift             # Generated Swift classes
```

## 🗄️ Core Data Schema

### Entities and Relationships

```
CDWord (Main Entity)
├── word: String
├── rawData: String (JSON)
├── createdAt: Date
├── updatedAt: Date
├── definitions: [CDDefinition] (One-to-Many)
└── variants: [CDWordVariant] (One-to-Many)

CDDefinition
├── metaId: String
├── functionalLabel: String (part of speech)
├── shortDefinition: String
├── pronunciation: String
├── word: CDWord (Many-to-One)
└── shortDefinitions: [CDShortDefinition] (One-to-Many)

CDShortDefinition
├── definitionText: String
├── definitionOrder: Int16
└── definition: CDDefinition (Many-to-One)

CDWordVariant
├── variantText: String
├── variantType: String
└── word: CDWord (Many-to-One)

// API Usage tracking removed from Core Data database 
// (keeps the database focused on dictionary content only)
```

## 🚀 Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Create Core Data Database

```bash
# From word list file
python dictionary_coredata.py wordlist.txt

# Custom database name
python dictionary_coredata.py wordlist.txt MyVocabulary.sqlite

# Interactive mode
python dictionary_coredata.py
```

### 3. Run Examples

```bash
python coredata_example.py
```

## 📱 iOS/macOS Integration

### Export for Xcode

```bash
# Export everything for Xcode integration
python migrate_to_coredata.py --export Dictionary.sqlite MyApp

# This creates:
# MyAppExport/
# ├── MyApp.sqlite
# ├── DictionaryModel.xcdatamodeld/
# ├── CoreDataModels.swift
# └── README.md (integration instructions)
```

### Xcode Integration Steps

1. **Add Files to Project:**
   - Drag `DictionaryModel.xcdatamodeld` into Xcode
   - Add `MyApp.sqlite` to app bundle
   - Include `CoreDataModels.swift` in project

2. **Configure Core Data Stack:**

```swift
import CoreData

lazy var persistentContainer: NSPersistentContainer = {
    let container = NSPersistentContainer(name: "DictionaryModel")
    
    // Use existing database
    let storeURL = Bundle.main.url(forResource: "MyApp", withExtension: "sqlite")!
    let storeDescription = NSPersistentStoreDescription(url: storeURL)
    storeDescription.shouldMigrateStoreAutomatically = true
    storeDescription.shouldInferMappingModelAutomatically = true
    
    container.persistentStoreDescriptions = [storeDescription]
    
    container.loadPersistentStores { _, error in
        if let error = error {
            fatalError("Core Data error: \(error)")
        }
    }
    
    return container
}()
```

3. **Query Words:**

```swift
// Fetch random word
func fetchRandomWord() -> CDWord? {
    let request: NSFetchRequest<CDWord> = CDWord.fetchRequest()
    request.fetchLimit = 1
    
    let context = persistentContainer.viewContext
    do {
        let words = try context.fetch(request)
        return words.first
    } catch {
        print("Fetch error: \(error)")
        return nil
    }
}

// Search words
func searchWords(containing text: String) -> [CDWord] {
    let request: NSFetchRequest<CDWord> = CDWord.fetchRequest()
    request.predicate = NSPredicate(format: "word CONTAINS[cd] %@", text)
    request.sortDescriptors = [NSSortDescriptor(key: "word", ascending: true)]
    
    let context = persistentContainer.viewContext
    do {
        return try context.fetch(request)
    } catch {
        print("Search error: \(error)")
        return []
    }
}
```

## 🔄 Migration Options

### From SQLite Database

```bash
python migrate_to_coredata.py existing_dictionary.db Dictionary.sqlite
```

### From DynamoDB

```bash
python migrate_to_coredata.py --dynamo Dictionary.sqlite
```

### Verify Migration

```bash
python migrate_to_coredata.py --verify Dictionary.sqlite
```

## 🛠️ API Reference

### CoreDataDictionary Class

```python
from coredata_dictionary import CoreDataDictionary

# Initialize
db = CoreDataDictionary("MyApp.sqlite", "MyAppModel")

# Store word (from dictionaryapi.com response)
success = db.store_word_data("example", api_response_data)

# Retrieve word
word_data = db.get_word_data("example")

# Check existence
exists = db.word_exists("example")

# Get random word
random_word = db.get_random_word()

# Statistics
count = db.get_word_count()

# API usage tracking (handled separately from Core Data)
# Keeps the Core Data database clean and focused on dictionary content

# Export for Xcode
db.export_for_xcode("MyAppExport")

# Close
db.close()
```

### Key Features

#### Core Data Metadata
- ✅ Proper Z_METADATA table with Core Data versioning
- ✅ Z_PRIMARYKEY tracking for entity primary keys
- ✅ Core Data compatible table naming (ZCDWORD, etc.)
- ✅ Optimistic locking support (Z_OPT columns)

#### Model Generation
- ✅ Automatic .xcdatamodeld creation
- ✅ Entity relationships and attributes
- ✅ Swift class generation
- ✅ NSManagedObject subclasses

#### iOS App Features
- ✅ Offline dictionary access
- ✅ Fast Core Data queries
- ✅ NSFetchedResultsController compatibility
- ✅ CloudKit sync ready structure

## 📊 Performance Features

- **🔍 Indexed Searches**: Fast word lookup with Core Data indexes
- **⚡ Relationship Loading**: Efficient relationship traversal
- **💾 Memory Efficient**: Core Data faulting and batch processing
- **🔄 Background Processing**: Thread-safe Core Data operations

## 🎯 Use Cases

### Educational Apps
```python
# Create vocabulary learning app database
db = CoreDataDictionary("VocabularyLearner.sqlite")

# Add educational words with categories
for category, words in educational_categories.items():
    for word in words:
        db.store_word_data(word, api_data)

db.export_for_xcode("VocabularyLearnerApp")
```

### Language Learning
```python
# Multi-language dictionary
for language in ["english", "spanish", "french"]:
    db = CoreDataDictionary(f"{language}_dictionary.sqlite")
    # Populate with language-specific words
```

### Professional Apps
```python
# Technical term dictionary
tech_db = CoreDataDictionary("TechDictionary.sqlite")
# Add programming, science, medical terms
```

## 🔧 Advanced Features

### Custom Model Names
```python
# Different model names for different apps
vocab_db = CoreDataDictionary("vocab.sqlite", "VocabularyModel")
tech_db = CoreDataDictionary("tech.sqlite", "TechnicalModel")
```

### Batch Operations
```python
# Efficient bulk loading
with Progress() as progress:
    for word_batch in word_batches:
        for word, data in word_batch:
            db.store_word_data(word, data)
```

### Export Customization
```python
# Custom export for specific apps
db.export_for_xcode("MyCustomApp", app_name="CustomVocab")
```

## 🚨 Core Data Specific Considerations

### Database Location
- Place SQLite file in app bundle for read-only access
- Copy to Documents for writable database
- Use application support directory for user data

### Threading
- Use separate NSManagedObjectContext for background operations
- Perform Core Data operations on appropriate queues
- Handle merge notifications for UI updates

### Performance
- Use NSFetchedResultsController for table views
- Implement proper predicate and sort descriptor usage
- Consider batch insert for large data sets

## 📱 iOS App Examples

### SwiftUI Vocabulary App
```swift
struct ContentView: View {
    @Environment(\.managedObjectContext) private var viewContext
    @FetchRequest(
        sortDescriptors: [NSSortDescriptor(keyPath: \CDWord.word, ascending: true)],
        animation: .default)
    private var words: FetchedResults<CDWord>
    
    var body: some View {
        NavigationView {
            List {
                ForEach(words) { word in
                    WordRowView(word: word)
                }
            }
            .navigationTitle("Dictionary")
        }
    }
}
```

### UIKit Word Detail
```swift
class WordDetailViewController: UIViewController {
    @IBOutlet weak var wordLabel: UILabel!
    @IBOutlet weak var definitionTextView: UITextView!
    
    var word: CDWord? {
        didSet {
            updateUI()
        }
    }
    
    private func updateUI() {
        guard let word = word else { return }
        
        wordLabel.text = word.word
        
        if let definitions = word.definitions as? Set<CDDefinition> {
            let definitionText = definitions.compactMap { definition in
                "\(definition.functionalLabel ?? ""): \(definition.shortDefinition ?? "")"
            }.joined(separator: "\n\n")
            
            definitionTextView.text = definitionText
        }
    }
}
```

## 🔍 Troubleshooting

### Common Issues

1. **Model Version Conflicts**
   - Delete existing .sqlite file when changing model
   - Use lightweight migration for schema changes

2. **Threading Issues**
   - Always use Core Data on correct queues
   - Use child contexts for background operations

3. **Performance Problems**
   - Add appropriate indexes to fetch requests
   - Use batch operations for large datasets

4. **Export Problems**
   - Ensure proper file permissions
   - Check Xcode project integration steps

### Debug Commands

```bash
# Verify database structure
sqlite3 Dictionary.sqlite ".schema"

# Check Core Data metadata
sqlite3 Dictionary.sqlite "SELECT * FROM Z_METADATA;"

# Count entities
sqlite3 Dictionary.sqlite "SELECT COUNT(*) FROM ZCDWORD;"
```

## 📚 Resources

- [Apple Core Data Documentation](https://developer.apple.com/documentation/coredata)
- [Core Data Programming Guide](https://developer.apple.com/library/archive/documentation/Cocoa/Conceptual/CoreData/)
- [NSFetchRequest Reference](https://developer.apple.com/documentation/coredata/nsfetchrequest)
- [Core Data Best Practices](https://developer.apple.com/videos/play/wwdc2019/230/)

## 🤝 Contributing

1. Follow Core Data naming conventions
2. Maintain entity relationship integrity
3. Test with actual iOS/macOS projects
4. Update Swift class generation as needed

## 📄 License

This project uses the same license as the parent eslbuilder project.

---

🍎 **Ready for iOS and macOS development!** Your dictionary data is now perfectly formatted for Apple's Core Data framework, complete with model files and Swift classes for immediate Xcode integration.