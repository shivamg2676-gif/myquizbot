import aiosqlite
from typing import Optional, List, Tuple

DB_NAME = "ca_vault.db"

async def init_db():
    async with aiosqlite.connect(DB_NAME) as db:
        # Users Table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                role TEXT DEFAULT 'student',
                xp INTEGER DEFAULT 0,
                level INTEGER DEFAULT 1,
                streak_count INTEGER DEFAULT 0,
                warnings INTEGER DEFAULT 0,
                trial_status TEXT DEFAULT 'free',
                trial_ends_at TIMESTAMP,
                joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Quiz History Table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS quiz_history (
                attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                subject TEXT,
                chapter TEXT,
                score INTEGER,
                correct_count INTEGER,
                wrong_count INTEGER,
                time_taken INTEGER,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # PDF Vault Index
        await db.execute("""
            CREATE TABLE IF NOT EXISTS pdf_vault (
                pdf_id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id TEXT,
                file_name TEXT,
                keyword TEXT UNIQUE,
                uploaded_by INTEGER,
                channel_msg_id INTEGER,
                is_approved INTEGER DEFAULT 0,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Audit Logs Table
        await db.execute("""
            CREATE TABLE IF NOT EXISTS audit_logs (
                log_id INTEGER PRIMARY KEY AUTOINCREMENT,
                admin_id INTEGER,
                target_user_id INTEGER,
                action_type TEXT,
                reason TEXT,
                timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Custom Spam Filters
        await db.execute("""
            CREATE TABLE IF NOT EXISTS spam_filters (
                word TEXT PRIMARY KEY
            )
        """)

        await db.commit()

async def get_or_create_user(user_id: int, username: str = "") -> dict:
    async with aiosqlite.connect(DB_NAME) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            user = await cursor.fetchone()
            if not user:
                await db.execute(
                    "INSERT INTO users (user_id, username) VALUES (?, ?)",
                    (user_id, username)
                )
                await db.commit()
                async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as c2:
                    user = await c2.fetchone()
            return dict(user)

async def update_user_xp(user_id: int, delta_xp: int):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "UPDATE users SET xp = MAX(0, xp + ?) WHERE user_id = ?",
            (delta_xp, user_id)
        )
        await db.commit()

async def add_audit_log(admin_id: int, target_user_id: int, action_type: str, reason: str):
    async with aiosqlite.connect(DB_NAME) as db:
        await db.execute(
            "INSERT INTO audit_logs (admin_id, target_user_id, action_type, reason) VALUES (?, ?, ?, ?)",
            (admin_id, target_user_id, action_type, reason)
        )
        await db.commit()
