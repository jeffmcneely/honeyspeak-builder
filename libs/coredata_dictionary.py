#!/usr/bin/env python3
"""
Core Data dictionary implementation for storing dictionary words from dictionaryapi.com

This module creates Core Data model files and generates SQLite databases compatible
with Apple's Core Data framework for iOS/macOS applications.
"""

import sqlite3
import json
import os
import plistlib
import uuid
from datetime import datetime
from typing import Optional, List, Dict, Any
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class CoreDataDictionary:
    """Core Data compatible database handler for dictionary words"""
    
    def __init__(self, db_path: str = None, model_name: str = None):
        """
        Initialize Core Data compatible database
        
        Args:
            db_path: Path to the Core Data SQLite file (defaults to env var or "Dictionary.sqlite")
            model_name: Name of the Core Data model (defaults to env var or "DictionaryModel")
        """
        self.db_path = db_path or os.getenv('DATABASE_PATH', 'Dictionary.sqlite')
        self.model_name = model_name or os.getenv('CORE_DATA_MODEL_NAME', 'DictionaryModel')
        self.connection = None
        
        # Core Data specific paths
        self.model_dir = f"{model_name}.xcdatamodeld"
        self.model_file = f"{self.model_dir}/contents"
        
        self.connect()
        self.create_core_data_model()
        self.create_core_data_tables()
    
    def connect(self):
        """Establish database connection with Core Data compatible settings"""
        try:
            self.connection = sqlite3.connect(self.db_path)
            self.connection.row_factory = sqlite3.Row
            
            # Enable Core Data compatible settings
            cursor = self.connection.cursor()
            cursor.execute("PRAGMA journal_mode=DELETE")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA cache_size=10000")
            cursor.execute("PRAGMA temp_store=MEMORY")
            
            return True
        except sqlite3.Error as e:
            print(f"Error connecting to database: {e}")
            return False
    
    def create_core_data_model(self):
        """Create Core Data model definition files (.xcdatamodeld)"""
        
        # Create model directory
        os.makedirs(self.model_dir, exist_ok=True)
        
        # Core Data model XML content
        model_content = '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<model type="com.apple.IDECoreDataModeler.DataModel" documentVersion="1.0" lastSavedToolsVersion="22522" systemVersion="23C71" minimumToolsVersion="Automatic" sourceLanguage="Swift" usedWithSwiftData="YES" userDefinedModelVersionIdentifier="">
    <entity name="CDWord" representedClassName="CDWord" syncable="YES" codeGenerationType="class">
        <attribute name="createdAt" optional="YES" attributeType="Date" usesScalarValueType="NO"/>
        <attribute name="rawData" optional="YES" attributeType="String"/>
        <attribute name="updatedAt" optional="YES" attributeType="Date" usesScalarValueType="NO"/>
        <attribute name="word" attributeType="String"/>
        <relationship name="definitions" optional="YES" toMany="YES" deletionRule="Cascade" destinationEntity="CDDefinition" inverseName="word" inverseEntity="CDDefinition"/>
        <relationship name="variants" optional="YES" toMany="YES" deletionRule="Cascade" destinationEntity="CDWordVariant" inverseName="word" inverseEntity="CDWordVariant"/>
    </entity>
    <entity name="CDDefinition" representedClassName="CDDefinition" syncable="YES" codeGenerationType="class">
        <attribute name="functionalLabel" optional="YES" attributeType="String"/>
        <attribute name="metaId" optional="YES" attributeType="String"/>
        <attribute name="pronunciation" optional="YES" attributeType="String"/>
        <attribute name="shortDefinition" optional="YES" attributeType="String"/>
        <relationship name="shortDefinitions" optional="YES" toMany="YES" deletionRule="Cascade" destinationEntity="CDShortDefinition" inverseName="definition" inverseEntity="CDShortDefinition"/>
        <relationship name="word" optional="YES" maxCount="1" deletionRule="Nullify" destinationEntity="CDWord" inverseName="definitions" inverseEntity="CDWord"/>
    </entity>
    <entity name="CDShortDefinition" representedClassName="CDShortDefinition" syncable="YES" codeGenerationType="class">
        <attribute name="definitionOrder" optional="YES" attributeType="Integer 16" defaultValueString="0" usesScalarValueType="YES"/>
        <attribute name="definitionText" attributeType="String"/>
        <relationship name="definition" optional="YES" maxCount="1" deletionRule="Nullify" destinationEntity="CDDefinition" inverseName="shortDefinitions" inverseEntity="CDDefinition"/>
    </entity>
    <entity name="CDWordVariant" representedClassName="CDWordVariant" syncable="YES" codeGenerationType="class">
        <attribute name="variantText" attributeType="String"/>
        <attribute name="variantType" optional="YES" attributeType="String"/>
        <relationship name="word" optional="YES" maxCount="1" deletionRule="Nullify" destinationEntity="CDWord" inverseName="variants" inverseEntity="CDWordVariant"/>
    </entity>
</model>'''
        
        # Write model file
        model_path = os.path.join(self.model_dir, "contents")
        with open(model_path, 'w') as f:
            f.write(model_content)
        
        print(f"Created Core Data model at: {self.model_dir}")
    
    def create_core_data_tables(self):
        """Create Core Data compatible SQLite tables with proper metadata"""
        cursor = self.connection.cursor()
        
        try:
            # Core Data metadata tables
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS Z_METADATA (
                    Z_VERSION INTEGER PRIMARY KEY,
                    Z_UUID VARCHAR(255),
                    Z_PLIST BLOB
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS Z_PRIMARYKEY (
                    Z_ENT INTEGER PRIMARY KEY,
                    Z_NAME VARCHAR,
                    Z_SUPER INTEGER,
                    Z_MAX INTEGER
                )
            ''')
            
            # Main entity tables with Core Data naming convention (Z_ENTITYNAME)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ZCDWORD (
                    Z_PK INTEGER PRIMARY KEY,
                    Z_ENT INTEGER,
                    Z_OPT INTEGER,
                    ZCREATEDAT TIMESTAMP,
                    ZUPDATEDAT TIMESTAMP,
                    ZWORD TEXT NOT NULL,
                    ZUUID TEXT,
                    ZRAWDATA TEXT
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ZCDDEFINITION (
                    Z_PK INTEGER PRIMARY KEY,
                    Z_ENT INTEGER,
                    Z_OPT INTEGER,
                    ZWORD INTEGER,
                    ZMETAID TEXT,
                    ZFUNCTIONALLABEL TEXT,
                    ZSHORTDEFINITION TEXT,
                    ZPRONUNCIATION TEXT,
                    FOREIGN KEY (ZWORD) REFERENCES ZCDWORD (Z_PK) ON DELETE CASCADE
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ZCDSHORTDEFINITION (
                    Z_PK INTEGER PRIMARY KEY,
                    Z_ENT INTEGER,
                    Z_OPT INTEGER,
                    ZDEFINITION INTEGER,
                    ZDEFINITIONTEXT TEXT NOT NULL,
                    ZDEFINITIONORDER INTEGER,
                    FOREIGN KEY (ZDEFINITION) REFERENCES ZCDDEFINITION (Z_PK) ON DELETE CASCADE
                )
            ''')
            
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS ZCDWORDVARIANT (
                    Z_PK INTEGER PRIMARY KEY,
                    Z_ENT INTEGER,
                    Z_OPT INTEGER,
                    ZWORD INTEGER,
                    ZVARIANTTEXT TEXT,
                    ZVARIANTTYPE TEXT,
                    FOREIGN KEY (ZWORD) REFERENCES ZCDWORD (Z_PK) ON DELETE CASCADE
                )
            ''')
            

            
            # Initialize Core Data metadata
            self._initialize_core_data_metadata()
            
            # Create indexes
            cursor.execute('CREATE INDEX IF NOT EXISTS ZCDWORD_ZWORD_INDEX ON ZCDWORD(ZWORD)')
            cursor.execute('CREATE INDEX IF NOT EXISTS ZCDDEFINITION_ZWORD_INDEX ON ZCDDEFINITION(ZWORD)')
            cursor.execute('CREATE INDEX IF NOT EXISTS ZCDSHORTDEFINITION_ZDEFINITION_INDEX ON ZCDSHORTDEFINITION(ZDEFINITION)')
            
            self.connection.commit()
            print("Core Data tables created successfully")
            
        except sqlite3.Error as e:
            print(f"Error creating Core Data tables: {e}")
            self.connection.rollback()
    
    def _initialize_core_data_metadata(self):
        """Initialize Core Data metadata required for proper Core Data functionality"""
        cursor = self.connection.cursor()
        
        # Check if metadata already exists
        cursor.execute("SELECT COUNT(*) FROM Z_METADATA")
        if cursor.fetchone()[0] > 0:
            return
        
        # Core Data version and UUID
        model_uuid = str(uuid.uuid4()).upper()
        
        # Metadata plist
        metadata_plist = {
            'NSPersistenceFrameworkVersion': 867,
            'NSStoreModelVersionHashes': {
                'CDWord': b'sample_hash_cdword',
                'CDDefinition': b'sample_hash_cddefinition',
                'CDShortDefinition': b'sample_hash_cdshortdefinition',
                'CDWordVariant': b'sample_hash_cdwordvariant'
            },
            'NSStoreModelVersionHashesVersion': 3,
            'NSStoreModelVersionIdentifiers': [self.model_name],
            'NSStoreType': 'SQLite',
            'NSStoreUUID': model_uuid,
            '_NSAutoVacuumLevel': 2
        }
        
        metadata_blob = plistlib.dumps(metadata_plist)
        
        # Insert metadata
        cursor.execute('''
            INSERT INTO Z_METADATA (Z_VERSION, Z_UUID, Z_PLIST)
            VALUES (1, ?, ?)
        ''', (model_uuid, metadata_blob))
        
        # Primary key tracking for entities
        entities = [
            (1, 'CDWord', 0),
            (2, 'CDDefinition', 0),
            (3, 'CDShortDefinition', 0),
            (4, 'CDWordVariant', 0)
        ]
        
        for ent_id, name, max_pk in entities:
            cursor.execute('''
                INSERT INTO Z_PRIMARYKEY (Z_ENT, Z_NAME, Z_SUPER, Z_MAX)
                VALUES (?, ?, 0, ?)
            ''', (ent_id, name, max_pk))
    
    def _get_next_primary_key(self, entity_id: int) -> int:
        """Get and increment the next primary key for a Core Data entity"""
        cursor = self.connection.cursor()
        
        # Get current max
        cursor.execute('SELECT Z_MAX FROM Z_PRIMARYKEY WHERE Z_ENT = ?', (entity_id,))
        result = cursor.fetchone()
        
        if result:
            next_pk = result[0] + 1
            # Update the max
            cursor.execute('UPDATE Z_PRIMARYKEY SET Z_MAX = ? WHERE Z_ENT = ?', (next_pk, entity_id))
            return next_pk
        else:
            # Initialize if not found
            cursor.execute('INSERT INTO Z_PRIMARYKEY (Z_ENT, Z_NAME, Z_SUPER, Z_MAX) VALUES (?, ?, 0, 1)', (entity_id, f'Entity{entity_id}'))
            return 1
    
    def store_word_data(self, word: str, api_data: List[Dict]) -> bool:
        """Store word data in Core Data format"""
        cursor = self.connection.cursor()
        
        try:
            # Get or create word record
            word_pk = self._get_next_primary_key(1)  # CDWord entity
            now = datetime.now()
            print(f"Inserting word data: {word}")
            print(json.dumps(api_data))
            cursor.execute('''
                INSERT OR REPLACE INTO ZCDWORD 
                (Z_PK, Z_ENT, Z_OPT, ZWORD, ZRAWDATA, ZCREATEDAT, ZUPDATEDAT, ZUUID)
                VALUES (?, 1, 1, ?, ?, ?, ?)
            ''', (word_pk, word, json.dumps(api_data), now, now, json.dumps(api_data)[0]['meta']['uuid']))
            
            # Clear existing definitions
            cursor.execute('DELETE FROM ZCDDEFINITION WHERE ZWORD = ?', (word_pk,))
            
            # Process definitions
            for data_item in api_data:
                if isinstance(data_item, dict) and "meta" in data_item:
                    meta_id = data_item.get("meta", {}).get("id", "")
                    
                    if meta_id.split(":")[0] == word:
                        definition_pk = self._get_next_primary_key(2)  # CDDefinition entity
                        
                        functional_label = data_item.get("fl", "")
                        
                        # Extract pronunciation
                        pronunciation = ""
                        if "hwi" in data_item and "prs" in data_item["hwi"]:
                            prs_list = data_item["hwi"]["prs"]
                            if prs_list and isinstance(prs_list[0], dict):
                                pronunciation = prs_list[0].get("mw", "")
                        
                        short_defs = data_item.get("shortdef", [])
                        first_short_def = short_defs[0] if short_defs else ""
                        
                        # Insert definition
                        cursor.execute('''
                            INSERT INTO ZCDDEFINITION 
                            (Z_PK, Z_ENT, Z_OPT, ZWORD, ZMETAID, ZFUNCTIONALLABEL, ZSHORTDEFINITION, ZPRONUNCIATION)
                            VALUES (?, 2, 1, ?, ?, ?, ?, ?)
                        ''', (definition_pk, word_pk, meta_id, functional_label, first_short_def, pronunciation))
                        
                        # Store short definitions
                        for i, short_def in enumerate(short_defs):
                            short_def_pk = self._get_next_primary_key(3)  # CDShortDefinition entity
                            cursor.execute('''
                                INSERT INTO ZCDSHORTDEFINITION 
                                (Z_PK, Z_ENT, Z_OPT, ZDEFINITION, ZDEFINITIONTEXT, ZDEFINITIONORDER)
                                VALUES (?, 3, 1, ?, ?, ?)
                            ''', (short_def_pk, definition_pk, short_def, i))
                        
                        # Store variants
                        if "ins" in data_item:
                            for inflection in data_item["ins"]:
                                if isinstance(inflection, dict) and "if" in inflection:
                                    variant_pk = self._get_next_primary_key(4)  # CDWordVariant entity
                                    variant_text = inflection["if"]
                                    cursor.execute('''
                                        INSERT INTO ZCDWORDVARIANT 
                                        (Z_PK, Z_ENT, Z_OPT, ZWORD, ZVARIANTTEXT, ZVARIANTTYPE)
                                        VALUES (?, 4, 1, ?, ?, ?)
                                    ''', (variant_pk, word_pk, variant_text, "inflection"))
            
            self.connection.commit()
            return True
            
        except sqlite3.Error as e:
            print(f"Error storing word data for '{word}': {e}")
            self.connection.rollback()
            return False
    
    def get_word_data(self, word: str) -> Optional[Dict]:
        """Retrieve word data from Core Data format"""
        cursor = self.connection.cursor()
        
        try:
            # Get word record
            cursor.execute('SELECT * FROM ZCDWORD WHERE ZWORD = ?', (word,))
            word_row = cursor.fetchone()
            
            if not word_row:
                return None
            
            word_data = {
                'word': word_row['ZWORD'],
                'created_at': word_row['ZCREATEDAT'],
                'updated_at': word_row['ZUPDATEDAT'],
                'raw_data': json.loads(word_row['ZRAWDATA']) if word_row['ZRAWDATA'] else [],
                'definitions': []
            }
            
            # Get definitions
            cursor.execute('''
                SELECT * FROM ZCDDEFINITION WHERE ZWORD = ? ORDER BY Z_PK
            ''', (word_row['Z_PK'],))
            
            definitions = cursor.fetchall()
            
            for def_row in definitions:
                # Get short definitions
                cursor.execute('''
                    SELECT ZDEFINITIONTEXT FROM ZCDSHORTDEFINITION 
                    WHERE ZDEFINITION = ? ORDER BY ZDEFINITIONORDER
                ''', (def_row['Z_PK'],))
                
                short_defs = [row[0] for row in cursor.fetchall()]
                
                # Get variants
                cursor.execute('''
                    SELECT ZVARIANTTEXT, ZVARIANTTYPE FROM ZCDWORDVARIANT 
                    WHERE ZWORD = ?
                ''', (word_row['Z_PK'],))
                
                variants = [{'text': row[0], 'type': row[1]} for row in cursor.fetchall()]
                
                definition_data = {
                    'meta_id': def_row['ZMETAID'],
                    'functional_label': def_row['ZFUNCTIONALLABEL'],
                    'pronunciation': def_row['ZPRONUNCIATION'],
                    'short_definitions': short_defs,
                    'variants': variants
                }
                
                word_data['definitions'].append(definition_data)
            
            return word_data
            
        except sqlite3.Error as e:
            print(f"Error retrieving word data for '{word}': {e}")
            return None
    
    def word_exists(self, word: str) -> bool:
        """Check if word exists in Core Data database"""
        cursor = self.connection.cursor()
        
        try:
            cursor.execute('SELECT 1 FROM ZCDWORD WHERE ZWORD = ? LIMIT 1', (word,))
            return cursor.fetchone() is not None
        except sqlite3.Error as e:
            print(f"Error checking word existence: {e}")
            return False
    
    def get_word_count(self) -> int:
        """Get total number of words"""
        cursor = self.connection.cursor()
        
        try:
            cursor.execute('SELECT COUNT(*) FROM ZCDWORD')
            return cursor.fetchone()[0]
        except sqlite3.Error as e:
            print(f"Error counting words: {e}")
            return 0
    
    def get_random_word(self) -> Optional[Dict]:
        """Get a random word from the database"""
        cursor = self.connection.cursor()
        
        try:
            cursor.execute('''
                SELECT w.ZWORD, d.ZSHORTDEFINITION, d.ZPRONUNCIATION, d.ZFUNCTIONALLABEL
                FROM ZCDWORD w
                JOIN ZCDDEFINITION d ON w.Z_PK = d.ZWORD
                ORDER BY RANDOM()
                LIMIT 1
            ''')
            
            row = cursor.fetchone()
            if row:
                return {
                    'word': row['ZWORD'],
                    'short_definition': row['ZSHORTDEFINITION'],
                    'pronunciation': row['ZPRONUNCIATION'],
                    'functional_label': row['ZFUNCTIONALLABEL']
                }
            return None
            
        except sqlite3.Error as e:
            print(f"Error getting random word: {e}")
            return None
    
    def get_api_usage(self, api_type: str, date: str = None) -> int:
        """Get API usage - returns 0 since we don't track in SQLite"""
        return 0
    
    def update_api_usage(self, api_type: str, count: int, date: str = None) -> bool:
        """Update API usage - no-op since we don't track in SQLite"""
        return True
    
    def export_for_xcode(self, output_dir: str = "DictionaryApp"):
        """Export the database and model files for Xcode project integration"""
        import shutil
        
        # Create output directory
        os.makedirs(output_dir, exist_ok=True)
        
        # Copy database file
        db_dest = os.path.join(output_dir, "Dictionary.sqlite")
        shutil.copy2(self.db_path, db_dest)
        
        # Copy model directory
        model_dest = os.path.join(output_dir, self.model_name + ".xcdatamodeld")
        if os.path.exists(model_dest):
            shutil.rmtree(model_dest)
        shutil.copytree(self.model_dir, model_dest)
        
        # Create Swift model classes
        self._generate_swift_classes(output_dir)
        
        print(f"Exported Core Data files to: {output_dir}")
        print(f"  - {db_dest}")
        print(f"  - {model_dest}")
        print(f"  - Swift model classes")
    
    def _generate_swift_classes(self, output_dir: str):
        """Generate Swift Core Data model classes"""
        
        swift_classes = '''//
//  CoreDataModels.swift
//  Dictionary App
//
//  Generated Core Data model classes
//

import Foundation
import CoreData

@objc(CDWord)
public class CDWord: NSManagedObject {
    
}

extension CDWord {
    
    @nonobjc public class func fetchRequest() -> NSFetchRequest<CDWord> {
        return NSFetchRequest<CDWord>(entityName: "CDWord")
    }
    
    @NSManaged public var word: String?
    @NSManaged public var rawData: String?
    @NSManaged public var createdAt: Date?
    @NSManaged public var updatedAt: Date?
    @NSManaged public var definitions: NSSet?
    @NSManaged public var variants: NSSet?
    
}

// MARK: Generated accessors for definitions
extension CDWord {
    
    @objc(addDefinitionsObject:)
    @NSManaged public func addToDefinitions(_ value: CDDefinition)
    
    @objc(removeDefinitionsObject:)
    @NSManaged public func removeFromDefinitions(_ value: CDDefinition)
    
    @objc(addDefinitions:)
    @NSManaged public func addToDefinitions(_ values: NSSet)
    
    @objc(removeDefinitions:)
    @NSManaged public func removeFromDefinitions(_ values: NSSet)
    
}

// MARK: Generated accessors for variants
extension CDWord {
    
    @objc(addVariantsObject:)
    @NSManaged public func addToVariants(_ value: CDWordVariant)
    
    @objc(removeVariantsObject:)
    @NSManaged public func removeFromVariants(_ value: CDWordVariant)
    
    @objc(addVariants:)
    @NSManaged public func addToVariants(_ values: NSSet)
    
    @objc(removeVariants:)
    @NSManaged public func removeFromVariants(_ values: NSSet)
    
}

@objc(CDDefinition)
public class CDDefinition: NSManagedObject {
    
}

extension CDDefinition {
    
    @nonobjc public class func fetchRequest() -> NSFetchRequest<CDDefinition> {
        return NSFetchRequest<CDDefinition>(entityName: "CDDefinition")
    }
    
    @NSManaged public var metaId: String?
    @NSManaged public var functionalLabel: String?
    @NSManaged public var shortDefinition: String?
    @NSManaged public var pronunciation: String?
    @NSManaged public var word: CDWord?
    @NSManaged public var shortDefinitions: NSSet?
    
}

// MARK: Generated accessors for shortDefinitions
extension CDDefinition {
    
    @objc(addShortDefinitionsObject:)
    @NSManaged public func addToShortDefinitions(_ value: CDShortDefinition)
    
    @objc(removeShortDefinitionsObject:)
    @NSManaged public func removeFromShortDefinitions(_ value: CDShortDefinition)
    
    @objc(addShortDefinitions:)
    @NSManaged public func addToShortDefinitions(_ values: NSSet)
    
    @objc(removeShortDefinitions:)
    @NSManaged public func removeFromShortDefinitions(_ values: NSSet)
    
}

@objc(CDShortDefinition)
public class CDShortDefinition: NSManagedObject {
    
}

extension CDShortDefinition {
    
    @nonobjc public class func fetchRequest() -> NSFetchRequest<CDShortDefinition> {
        return NSFetchRequest<CDShortDefinition>(entityName: "CDShortDefinition")
    }
    
    @NSManaged public var definitionText: String?
    @NSManaged public var definitionOrder: Int16
    @NSManaged public var definition: CDDefinition?
    
}

@objc(CDWordVariant)
public class CDWordVariant: NSManagedObject {
    
}

extension CDWordVariant {
    
    @nonobjc public class func fetchRequest() -> NSFetchRequest<CDWordVariant> {
        return NSFetchRequest<CDWordVariant>(entityName: "CDWordVariant")
    }
    
    @NSManaged public var variantText: String?
    @NSManaged public var variantType: String?
    @NSManaged public var word: CDWord?
    
}

'''
        
        swift_file_path = os.path.join(output_dir, "CoreDataModels.swift")
        with open(swift_file_path, 'w') as f:
            f.write(swift_classes)
    
    def close(self):
        """Close database connection"""
        if self.connection:
            self.connection.close()


# Compatibility functions
def create_coredata_dictionary(db_path: str = "Dictionary.sqlite", model_name: str = "DictionaryModel") -> CoreDataDictionary:
    """Create and return a CoreDataDictionary instance"""
    return CoreDataDictionary(db_path, model_name)