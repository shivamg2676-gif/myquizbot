# myquizbot

This repository contains a Telegram Quiz Bot built with aiogram.

Features added in branch feature/admin-quiz:
- Quiz sending and scoring (inline buttons)
- Admin dashboard (/dashboard) with interactive buttons
- Moderation commands: /filter, /mute, /unmute, /warn, /unwarn, /modlogs, /userlog
- Settings: /setwelcome, /setchannel
- Leaderboard and /quiz command

Setup
1. Create a Render service (or run locally).
2. Set environment variables (in Render dashboard or .env locally):
   - BOT_TOKEN — your telegram bot token
   - OWNER_ID — your Telegram user id (super admin)
   - DATABASE_PATH — optional (default: quiz.db)
   - QUESTIONS_FILE — optional (default: questions.json)
3. Install dependencies:
   pip install -r requirements.txt
4. Run:
   python bot.py

Security
- Do NOT commit or paste secrets. This code reads secrets from environment variables.

Notes
- The bot requires admin rights in groups to mute/unmute members.
- The DB is a local sqlite file by default; for production use Postgres and adapt code.
