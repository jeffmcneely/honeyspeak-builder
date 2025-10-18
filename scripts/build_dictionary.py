from libs.sqlite_dictionary import SQLiteDictionary


from libs.helper import print_json_rich
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
    db_path = (
        sys.argv[2]
        if len(sys.argv) > 2 and not sys.argv[2].startswith("--")
        else os.getenv("DATABASE_PATH", "Dictionary.sqlite")
    )
    debug = "--debug" in sys.argv or os.getenv("DEBUG_MODE", "false").lower() == "true"

    try:
        print(f"📖 Opening word list: {sys.argv[1]}")
        with open(sys.argv[1], "r") as f:
            wordlist = f.read().splitlines()
    except FileNotFoundError:
        print("📄 File not found, treating as comma-separated word list")
        wordlist = sys.argv[1].split(",")
        debug = True
    db = SQLiteDictionary(db_path)

    # Get dictionary API key from environment or AWS
    dictionary_api_key = os.getenv("DICTIONARY_API_KEY")

    # Track API usage separately (not in Core Data database)
    usage_count = 0
    usage_file = os.getenv("API_USAGE_FILE", "api_usage.txt")
    today = datetime.now().date()

    try:
        with open(usage_file, "r") as f:
            content = f.read().strip()
            if "|" in content:
                date_str, count_str = content.split("|", 1)
                file_date = datetime.fromisoformat(date_str).date()
                if file_date == today:
                    usage_count = int(count_str)
                else:
                    # Different day, reset counter
                    usage_count = 0
            else:
                # Old format without date, reset
                usage_count = 0
    except (FileNotFoundError, ValueError):
        usage_count = 0

    print(f"📊 Current API usage count: {usage_count}")
    print(f"📚 Processing {len(wordlist)} words...")

    # Processing statistics
    stats = {"processed": 0, "stored": 0, "skipped": 0, "errors": 0, "api_calls": 0}

    with Progress() as progress:
        # Main progress bar for word list
        main_task = progress.add_task(
            "[bold blue]📖 Processing Dictionary Words", total=len(wordlist)
        )

        for word in wordlist:
            word = word.strip().lower()
            if not word:
                continue

            stats["processed"] += 1
            progress.update(
                main_task,
                advance=1,
                description=f"[bold blue]📖 Processing: {word} ({stats['processed']}/{len(wordlist)})",
            )

            # Create subtask for this word
            word_task = progress.add_task(f"[cyan]🔍 {word}", total=3)

            try:
                # Fetch from dictionary API
                progress.update(
                    word_task, advance=1, description=f"[cyan]🔍 {word} - fetching"
                )
                url = f"https://www.dictionaryapi.com/api/v3/references/learners/json/{word}?key={dictionary_api_key}"
                response = requests.get(url)

                if response.status_code == 200:
                    progress.update(
                        word_task,
                        advance=1,
                        description=f"[cyan]📝 {word} - processing",
                    )
                else:
                    print(f"❌ API request failed for '{word}': {response.status_code}")
                    stats["errors"] += 1
                    continue

                # Track API usage
                usage_count += 1
                stats["api_calls"] += 1

                # Update usage file
                with open(usage_file, "w") as f:
                    f.write(f"{today.isoformat()}|{usage_count}")

                data = response.json()

                if debug:
                    print_json_rich(data)

                for entry in data:
                    meta = entry["meta"]
                    word = meta.get("id").split(":")[0]
                    shortdef = meta.get("app-shortdef", None)
                    if shortdef is None or shortdef == []:
                        continue
                    fl = shortdef.get("fl")
                    uuid = meta.get("uuid")
                    offensive = meta.get("offensive")
                    try:
                        db.add_word(word, fl, uuid, offensive)
                        try:
                            if shortdef == []:
                                continue
                            for sd in shortdef.get("def", []):
                                db.add_shortdef(uuid, sd)
                        except Exception as e:
                            print(f"❌ Error adding shortdef '{uuid}' '{sd}'\n{e}")
                    except Exception as e:
                        print(f"❌ Error adding '{word}'\n{e}")

            except Exception as e:
                print(f"❌ Error processing '{word}': {e}")
                print_json_rich(entry)
                stats["errors"] += 1

            finally:
                progress.remove_task(word_task)

    # Final statistics
    total_words = db.get_word_count()

    print("\n" + "=" * 60)
    print("🎉 Dictionary Processing Complete!")
    print("=" * 60)
    print(f"📊 Processing Statistics:")
    print(f"   Words processed: {stats['processed']}")
    print(f"   Successfully stored: {stats['stored']}")
    print(f"   Already existed (skipped): {stats['skipped']}")
    print(f"   Errors: {stats['errors']}")
    print(f"   API calls made: {stats['api_calls']}")
    print(f"\n🗄️ SQLite database:")
    print(f"   Database file: {db_path}")
    print(f"   Total words in database: {total_words}")
    print(f"\n📈 API Usage:")
    print(f"   Total API calls: {usage_count}")
    print(f"   Usage tracking: {usage_file}")

    # Close database connection
    db.close()
    print("=" * 60)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        # No arguments, run in interactive mode
        print("Usage: python dictionary.py <wordlist_file> [database_path] [--debug]")
        sys.exit(1)
    else:
        # Run main processing
        main()
