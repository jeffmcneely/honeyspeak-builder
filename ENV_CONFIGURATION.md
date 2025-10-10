# Environment Variables Configuration

This document describes all environment variables that can be configured in your `.env` file to customize the ESL Dictionary Builder behavior.

## 📁 Setup

1. **Copy the example file:**
   ```bash
   cp .env.example .env
   ```

2. **Edit the values:**
   ```bash
   nano .env  # or your preferred editor
   ```

3. **The .env file is automatically loaded** by all scripts at startup.

## 🔧 Configuration Variables

### **Core Database Settings**

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_PATH` | `Dictionary.sqlite` | Path to the Core Data SQLite database |
| `CORE_DATA_MODEL_NAME` | `DictionaryModel` | Name of the Core Data model |
| `API_USAGE_FILE` | `api_usage.txt` | File to track API usage count |

### **AWS Configuration**

| Variable | Default | Description |
|----------|---------|-------------|
| `AWS_PROFILE` | `eslbuilder` | AWS profile name for credentials |
| `AWS_REGION` | `us-west-2` | AWS region for services |
| `AWS_SECRET_NAME` | `esl-writer` | Secrets Manager secret name |

### **API Keys**

| Variable | Default | Description |
|----------|---------|-------------|
| `DICTIONARY_API_KEY` | *(none)* | Direct API key (bypasses AWS Secrets Manager) |
| `OPENAI_API_KEY` | *(none)* | OpenAI API key for additional features |

### **Behavior Settings**

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG_MODE` | `false` | Enable detailed debug output |
| `VERBOSE_LOGGING` | `false` | Enable verbose logging |
| `SKIP_EXISTING_WORDS` | `true` | Skip words that already exist in database |
| `MAX_API_CALLS_PER_RUN` | `1000` | Maximum API calls per execution |

### **Export Settings**

| Variable | Default | Description |
|----------|---------|-------------|
| `EXPORT_DIRECTORY` | `DictionaryAppExport` | Default directory for Xcode exports |
| `DEFAULT_APP_NAME` | `DictionaryApp` | Default app name for exports |

## 🚀 Usage Examples

### **Basic Configuration**

```bash
# .env file
DATABASE_PATH=MyVocabulary.sqlite
CORE_DATA_MODEL_NAME=VocabularyModel
DEBUG_MODE=true
```

### **Production Setup with Direct API Key**

```bash
# .env file
DICTIONARY_API_KEY=your-actual-api-key-here
DATABASE_PATH=/data/production_dictionary.sqlite
SKIP_EXISTING_WORDS=true
MAX_API_CALLS_PER_RUN=500
VERBOSE_LOGGING=true
```

### **Development Setup**

```bash
# .env file
DEBUG_MODE=true
DATABASE_PATH=dev_dictionary.sqlite
CORE_DATA_MODEL_NAME=DevDictionaryModel
EXPORT_DIRECTORY=DevAppExport
SKIP_EXISTING_WORDS=false  # Allow overwriting for testing
```

### **AWS-Only Setup (No Direct API Key)**

```bash
# .env file
AWS_PROFILE=my-aws-profile
AWS_REGION=us-east-1
AWS_SECRET_NAME=my-dictionary-secret
DATABASE_PATH=aws_dictionary.sqlite
```

## 🔄 Variable Priority

The system uses this priority order for configuration:

1. **Command line arguments** (highest priority)
2. **Environment variables** from `.env` file
3. **Default values** (lowest priority)

### Example:
```bash
# .env file has DATABASE_PATH=MyDict.sqlite
python dictionary.py wordlist.txt CustomDict.sqlite

# Result: Uses CustomDict.sqlite (command line overrides .env)
```

## 🛠️ Environment Variable Loading

All scripts automatically load environment variables at startup:

```python
from dotenv import load_dotenv
load_dotenv()  # Loads .env file from current directory
```

### **Files that load .env:**
- `dictionary.py` - Main dictionary processor
- `coredata_dictionary.py` - Core Data database class
- `migrate_to_coredata.py` - Migration tools
- `libs/helper.py` - Helper functions
- `startup.py` - Startup and testing script

## 🧪 Testing Configuration

Use the startup script to test your configuration:

```bash
# Test Core Data connection with current .env settings
python startup.py test

# Start interactive mode with .env settings
python startup.py interactive

# Show current configuration
python startup.py
```

## 🔒 Security Notes

### **API Keys**
- Never commit `.env` files to version control
- Use AWS Secrets Manager in production when possible
- Rotate API keys regularly

### **File Permissions**
```bash
chmod 600 .env  # Only owner can read/write
```

### **.gitignore Entry**
Ensure your `.gitignore` includes:
```
.env
*.env
!.env.example
```

## 🚨 Troubleshooting

### **Environment Variables Not Loading**
1. Check `.env` file exists in project root
2. Verify no syntax errors (no spaces around `=`)
3. Install python-dotenv: `pip install python-dotenv`

### **API Key Issues**
1. If using `DICTIONARY_API_KEY`, remove AWS settings
2. If using AWS, ensure profile is configured: `aws configure --profile eslbuilder`
3. Check AWS Secrets Manager permissions

### **Path Issues**
1. Use absolute paths for production deployments
2. Ensure directories exist and are writable
3. Check file permissions

### **Debug Mode**
Enable debug mode to see detailed information:
```bash
DEBUG_MODE=true python dictionary.py wordlist.txt
```

## 📝 Example .env Files

### **Minimal Setup**
```bash
DICTIONARY_API_KEY=your-api-key-here
DATABASE_PATH=Dictionary.sqlite
```

### **Complete Development Setup**
```bash
# Development Configuration
DEBUG_MODE=true
VERBOSE_LOGGING=true
DATABASE_PATH=dev_dictionary.sqlite
CORE_DATA_MODEL_NAME=DevDictionary
API_USAGE_FILE=dev_api_usage.txt

# API Configuration
DICTIONARY_API_KEY=dev-api-key-here
OPENAI_API_KEY=openai-key-for-features

# Export Settings
EXPORT_DIRECTORY=DevAppExport
DEFAULT_APP_NAME=DevVocabApp

# Behavior
SKIP_EXISTING_WORDS=false
MAX_API_CALLS_PER_RUN=100
```

### **Production AWS Setup**
```bash
# Production Configuration
AWS_PROFILE=production-profile
AWS_REGION=us-west-2
AWS_SECRET_NAME=prod-dictionary-secret
DATABASE_PATH=/data/production_dictionary.sqlite
CORE_DATA_MODEL_NAME=ProductionDictionary

# Production Settings
SKIP_EXISTING_WORDS=true
MAX_API_CALLS_PER_RUN=1000
VERBOSE_LOGGING=true

# Export
EXPORT_DIRECTORY=/exports/DictionaryAppExport
DEFAULT_APP_NAME=VocabularyApp
```

---

💡 **Remember:** Environment variables make your application flexible and secure. Use them for any value that might change between environments or contains sensitive information!