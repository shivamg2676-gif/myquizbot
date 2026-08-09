import os
from dotenv import load_dotenv

load_dotenv()

# Telegram Bot Credentials
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
OWNER_ID = int(os.getenv("OWNER_ID", "0"))
MAIN_CHANNEL_ID = os.getenv("MAIN_CHANNEL_ID", "@your_channel_username")
STUDY_CHANNEL_ID = os.getenv("STUDY_CHANNEL_ID", "@your_study_channel")

# AI API Keys
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

# Server Config for Render Health Check
PORT = int(os.getenv("PORT", 8080))
