"""
Configuration file for Patent Search Application
Update these settings for your local environment
"""

# Database Configuration
DB_CONFIG = {
    'host': '100.76.27.122',  # Update to your server IP or 'localhost' if using SSH tunnel
    'port': 5432,
    'database': 'companies_db',
    'user': 'mark',
    'password': 'mark123'
}

# Ollama API Configuration
OLLAMA_URL = 'http://localhost:11434/api/generate'  # Update if Ollama is on different host
MODEL_NAME = 'gpt-oss:20b'

# Application Settings
APP_PORT = 8094
DEBUG_MODE = True

# Archive locations (only needed if extracting claims locally)
ARCHIVE_PATH = '/mnt/patents/data/historical/'  # Updated to new organized structure

# SSH Tunnel Information (for reference)
SSH_HOST = '100.76.27.122'
SSH_PORT = 17003
SSH_USER = 'mark'
SSH_PASSWORD = 'qwklmn711'