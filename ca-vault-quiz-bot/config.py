"""
CA Vault Quiz Bot - Configuration
All settings loaded from environment variables with sensible defaults.
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Telegram ──
BOT_TOKEN: str = os.environ["BOT_TOKEN"]
WEBHOOK_URL: str = os.environ.get("WEBHOOK_URL", "")
OWNER_ID: int = int(os.environ.get("OWNER_ID", "0"))
ANNOUNCEMENT_CHANNEL: str = os.environ.get("ANNOUNCEMENT_CHANNEL", "")
LOG_CHANNEL: str = os.environ.get("LOG_CHANNEL", "")
PORT: int = int(os.environ.get("PORT", "8080"))

# ── Database ──
DATABASE_URL: str = os.environ.get(
    "DATABASE_URL", "sqlite+aiosqlite:///cavault.db"
)

# ── AI Provider Keys (set on Render env vars) ──
CEREBRAS_API_KEY: str = os.environ.get("CEREBRAS_API_KEY", "")
GEMINI_API_KEY: str = os.environ.get("GEMINI_API_KEY", "")
GROQ_API_KEY: str = os.environ.get("GROQ_API_KEY", "")
MISTRAL_API_KEY: str = os.environ.get("MISTRAL_API_KEY", "")
OPENROUTER_API_KEY: str = os.environ.get("OPENROUTER_API_KEY", "")
OPENAI_API_KEY: str = os.environ.get("OPENAI_API_KEY", "")
AI_DEFAULT_PROVIDER: str = os.environ.get("AI_DEFAULT_PROVIDER", "groq")

# ── Quiz Defaults ──
DEFAULT_TIMER_THEORY: int = int(os.environ.get("DEFAULT_TIMER_THEORY", "25"))
DEFAULT_TIMER_PRACTICAL: int = int(os.environ.get("DEFAULT_TIMER_PRACTICAL", "45"))
QUIZ_WINDOW_START: str = os.environ.get("QUIZ_WINDOW_START", "18:00")
QUIZ_WINDOW_END: str = os.environ.get("QUIZ_WINDOW_END", "20:00")
DAILY_PIN_TIME: str = os.environ.get("DAILY_PIN_TIME", "06:00")
MEGA_QUIZ_DAY: str = os.environ.get("MEGA_QUIZ_DAY", "Sunday")

# ── Moderation ──
MAX_WARNINGS: int = 3
MUTE_DURATION_HOURS: int = 24
STICKER_FILTER_ENABLED: bool = os.environ.get(
    "STICKER_FILTER_ENABLED", "true"
).lower() == "true"

# ── Gamification ──
XP_CORRECT: int = 4
XP_WRONG: int = -1
XP_REFERRAL_BONUS: int = 20
XP_REFERRAL_PENALTY: int = -20
STREAK_XP_BONUS: int = 2

# ── Roles ──
ROLE_OWNER: str = "owner"
ROLE_ADMIN: str = "admin"
ROLE_MOD: str = "mod"
ROLE_STUDENT: str = "student"
ROLE_HIERARCHY: dict[str, int] = {
    ROLE_OWNER: 4,
    ROLE_ADMIN: 3,
    ROLE_MOD: 2,
    ROLE_STUDENT: 1,
}
