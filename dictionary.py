import boto3
import json
from botocore.exceptions import ClientError
from libs.helper import (
    get_aws_secret,
    print_json_rich
)
from libs.coredata_dictionary import CoreDataDictionary
import sys
import requests
from rich.progress import Progress
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def main():
    if len(sys.argv) < 2:
        print("Usage: python dictionary.py <wordlist_file> [database_path] [--debug]")
        sys.exit(1)
    
    # Get database path from command line, environment, or use default
    db_path = sys.argv[2] if len(sys.argv) > 2 and not sys.argv[2].startswith('--') else os.getenv('DATABASE_PATH', 'Dictionary.sqlite')
    debug = '--debug' in sys.argv or os.getenv('DEBUG_MODE', 'false').lower() == 'true'
    
    try:
        print(f"📖 Opening word list: {sys.argv[1]}")
        with open(sys.argv[1], "r") as f:
            wordlist = f.read().splitlines()
    except FileNotFoundError:
        print("📄 File not found, treating as comma-separated word list")
        wordlist = sys.argv[1].split(",")
        debug = True

    # Initialize Core Data database
    model_name = os.getenv('CORE_DATA_MODEL_NAME', 'DictionaryModel')
    print(f"🍎 Initializing Core Data database: {db_path}")
    db = CoreDataDictionary(db_path, model_name)
    
    # Get dictionary API key from environment or AWS
    dictionary_api_key = os.getenv('DICTIONARY_API_KEY')
    
    if dictionary_api_key:
        print("🔑 Using dictionary API key from environment variables")
        secret = {'dictionary_key': dictionary_api_key}
    else:
        # AWS session for dictionary API key
        try:
            aws_profile = os.getenv('AWS_PROFILE', 'eslbuilder')
            aws_region = os.getenv('AWS_REGION', 'us-west-2')
            secret_name = os.getenv('AWS_SECRET_NAME', 'esl-writer')
            
            session = boto3.session.Session(profile_name=aws_profile, region_name=aws_region)
            secret_client = session.client(service_name="secretsmanager", region_name=aws_region)
            secret = get_aws_secret(secret_client, secret_name)
            print(f"🔑 Using dictionary API key from AWS Secrets Manager ({secret_name})")
        except Exception as e:
            print(f"❌ Error getting API key: {e}")
            print("💡 Set DICTIONARY_API_KEY in .env file or configure AWS profile")
            sys.exit(1)
    
    # Track API usage separately (not in Core Data database)
    usage_count = 0
    usage_file = os.getenv('API_USAGE_FILE', 'api_usage.txt')
    try:
        with open(usage_file, "r") as f:
            usage_count = int(f.read().strip())
    except (FileNotFoundError, ValueError):
        usage_count = 0
    
    print(f"📊 Current API usage count: {usage_count}")
    print(f"📚 Processing {len(wordlist)} words...")
    
    # Processing statistics
    stats = {
        'processed': 0,
        'stored': 0,
        'skipped': 0,
        'errors': 0,
        'api_calls': 0
    }
    
    with Progress() as progress:
        # Main progress bar for word list
        main_task = progress.add_task(
            "[bold blue]📖 Processing Dictionary Words", 
            total=len(wordlist)
        )
        
        for word in wordlist:
            word = word.strip().lower()
            if not word:
                continue
                
            stats['processed'] += 1
            progress.update(
                main_task, 
                advance=1, 
                description=f"[bold blue]📖 Processing: {word} ({stats['processed']}/{len(wordlist)})"
            )
            
            # Check if word already exists in Core Data database (if enabled)
            skip_existing = os.getenv('SKIP_EXISTING_WORDS', 'true').lower() == 'true'
            if skip_existing and db.word_exists(word):
                if debug:
                    print(f"⏭️  Skipping '{word}' - already exists in database")
                stats['skipped'] += 1
                continue
            
            # Create subtask for this word
            word_task = progress.add_task(
                f"[cyan]🔍 {word}", 
                total=3
            )
            
            try:
                # Fetch from dictionary API
                progress.update(word_task, advance=1, description=f"[cyan]🔍 {word} - fetching")
                url = f"https://www.dictionaryapi.com/api/v3/references/learners/json/{word}?key={secret['dictionary_key']}"
                response = requests.get(url)
                
                if response.status_code == 200:
                    progress.update(word_task, advance=1, description=f"[cyan]📝 {word} - processing")
                    
                    # Track API usage
                    usage_count += 1
                    stats['api_calls'] += 1
                    
                    # Update usage file
                    with open(usage_file, "w") as f:
                        f.write(str(usage_count))
                    
                    data = response.json()
                    
                    if debug:
                        print_json_rich(data)
                    
                    # Validate response format
                    store_data = []
                    all_str = True
                    for data_item in data:
                        if not isinstance(data_item, str):
                            all_str = False
                            break
                    
                    if all_str:
                        print(f"⚠️  Unexpected data format for '{word}': {data}")
                        stats['errors'] += 1
                        progress.remove_task(word_task)
                        continue
                    
                    # Filter data items that match our word
                    for data_item in data:
#                        if isinstance(data_item, dict) and "meta" in data_item:
#                            if data_item["meta"].get("id", "").split(":")[0] == word:
                        store_data.append(data_item)
                    
                    if not store_data:
                        print(f"⚠️  No valid data found for '{word}': {data}")
                        stats['errors'] += 1
                        progress.remove_task(word_task)
                        continue
                    
                    # Store in Core Data database
                    progress.update(word_task, advance=1, description=f"[cyan]💾 {word} - storing")
                    
                    if db.store_word_data(word, store_data):
                        stats['stored'] += 1
                        if debug:
                            print(f"✅ Successfully stored '{word}' in Core Data database")
                    else:
                        stats['errors'] += 1
                        print(f"❌ Failed to store '{word}' in database")
                
                else:
                    print(f"❌ API request failed for '{word}': {response.status_code}")
                    stats['errors'] += 1
                
            except Exception as e:
                print(f"❌ Error processing '{word}': {e}")
                stats['errors'] += 1
            
            finally:
                progress.remove_task(word_task)
    
    # Final statistics
    total_words = db.get_word_count()
    
    print("\n" + "="*60)
    print("🎉 Dictionary Processing Complete!")
    print("="*60)
    print(f"📊 Processing Statistics:")
    print(f"   Words processed: {stats['processed']}")
    print(f"   Successfully stored: {stats['stored']}")
    print(f"   Already existed (skipped): {stats['skipped']}")
    print(f"   Errors: {stats['errors']}")
    print(f"   API calls made: {stats['api_calls']}")
    print(f"\n🍎 Core Data Database:")
    print(f"   Database file: {db_path}")
    print(f"   Total words in database: {total_words}")
    print(f"   Model definition: {db.model_dir}")
    print(f"\n📈 API Usage:")
    print(f"   Total API calls: {usage_count}")
    print(f"   Usage tracking: {usage_file}")
    
    # Show sample words
    if total_words > 0:
        print(f"\n🔍 Sample from database:")
        random_word = db.get_random_word()
        if random_word:
            print(f"   📝 {random_word['word']} ({random_word['functional_label']})")
            print(f"   🔊 {random_word['pronunciation']}")
            print(f"   📖 {random_word['short_definition']}")
    
    # Close database connection
    db.close()
    print("="*60)


def interactive_lookup():
    """Interactive mode for looking up words in the Core Data database"""
    default_db = os.getenv('DATABASE_PATH', 'Dictionary.sqlite')
    db_path = input(f"Enter database path (default: {default_db}): ").strip()
    if not db_path:
        db_path = default_db
    
    if not os.path.exists(db_path):
        print(f"❌ Database file not found: {db_path}")
        print("💡 Run 'python dictionary.py <wordlist>' first to create the database")
        return
    
    try:
        db = CoreDataDictionary(db_path)
        print(f"🍎 Connected to Core Data database: {db_path}")
        print(f"📊 Total words in database: {db.get_word_count()}")
        print("\n📖 Interactive Dictionary Lookup")
        print("Commands:")
        print("  • Enter a word to look up")
        print("  • 'random' - Get a random word")
        print("  • 'stats' - Show database statistics")
        print("  • 'export' - Export for Xcode integration")
        print("  • 'quit' - Exit")
        print("-" * 50)
        
        while True:
            user_input = input("\n🔍 > ").strip()
            
            if user_input.lower() == 'quit':
                break
            elif user_input.lower() == 'random':
                random_word = db.get_random_word()
                if random_word:
                    print(f"🎲 Random word:")
                    print_json_rich(random_word)
                else:
                    print("❌ No words found in database")
            elif user_input.lower() == 'stats':
                print(f"📊 Database Statistics:")
                print(f"   Total words: {db.get_word_count()}")
                print(f"   Database file: {db_path}")
                print(f"   Model: {db.model_dir}")
            elif user_input.lower() == 'export':
                default_app_name = os.getenv('DEFAULT_APP_NAME', 'DictionaryApp')
                app_name = input(f"Enter app name (default: {default_app_name}): ").strip()
                if not app_name:
                    app_name = default_app_name
                export_dir = os.getenv('EXPORT_DIRECTORY', f"{app_name}Export")
                db.export_for_xcode(export_dir)
                print(f"✅ Exported Core Data files to {export_dir}/")
            elif user_input:
                word_data = db.get_word_data(user_input.lower())
                if word_data:
                    print(f"📝 Found '{user_input}':")
                    print_json_rich(word_data)
                else:
                    print(f"❌ Word '{user_input}' not found in database")
                    # Suggest similar words (simple contains search)
                    similar = [w for w in [user_input[:3], user_input[:4]] if len(w) >= 2]
                    if similar:
                        print(f"💡 Try searching for words containing: {', '.join(similar)}")
        
        db.close()
        print("👋 Goodbye!")
        
    except Exception as e:
        print(f"❌ Error: {e}")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # No arguments, run in interactive mode
        interactive_lookup()
    else:
        # Run main processing
        main()
