import sqlite3
import os
from datetime import datetime, timedelta

DB_PATH = os.path.join(os.path.dirname(__file__), "quiz_vault.db")

def get_db():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    # 1. Users Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            role TEXT DEFAULT 'student',
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            streak_count INTEGER DEFAULT 0,
            last_active_date TEXT,
            joined_date TEXT,
            referrer_id INTEGER,
            is_flex_admin INTEGER DEFAULT 0,
            linked_group_id INTEGER
        )
    """)
    
    # Check for linked_group_id column migration
    cursor.execute("PRAGMA table_info(users)")
    columns = [col["name"] for col in cursor.fetchall()]
    if "linked_group_id" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN linked_group_id INTEGER")

    # 2. Quiz History Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quiz_history (
            attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            chat_id INTEGER,
            subject TEXT,
            chapter TEXT,
            score INTEGER,
            correct_count INTEGER,
            wrong_count INTEGER,
            time_taken INTEGER,
            timestamp TEXT
        )
    """)
    
    # 3. Badges Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS badges (
            badge_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            badge_name TEXT,
            earned_at TEXT
        )
    """)
    
    # 4. PDF Vault Index Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pdf_vault (
            pdf_id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT UNIQUE,
            file_name TEXT,
            uploaded_by INTEGER,
            timestamp TEXT,
            channel_message_id INTEGER,
            file_hash TEXT
        )
    """)
    
    # 5. Audit Logs Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            target_user_id INTEGER,
            action_type TEXT,
            reason TEXT,
            timestamp TEXT
        )
    """)
    
    # 6. Scheduled Quizzes Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS scheduled_quizzes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            datetime_str TEXT,
            subject TEXT,
            chapter TEXT,
            count INTEGER,
            timer INTEGER,
            level TEXT,
            break_freq INTEGER,
            break_duration INTEGER
        )
    """)

    # 7. Syllabus Planner Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS syllabus_planner (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject TEXT,
            chapter_name TEXT,
            day_order INTEGER DEFAULT 1,
            is_completed INTEGER DEFAULT 0,
            added_by INTEGER
        )
    """)

    # 8. Bot Settings Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bot_settings (
            setting_key TEXT PRIMARY KEY,
            setting_val TEXT
        )
    """)

    # 9. Daily Schedules Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_schedules (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date_str TEXT UNIQUE,
            subject TEXT,
            chapter_name TEXT,
            time_str TEXT DEFAULT '19:00',
            is_mega_quiz INTEGER DEFAULT 0,
            is_pinned INTEGER DEFAULT 0
        )
    """)

    # 10. Bad Words Filter Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bad_words_filter (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            word TEXT UNIQUE,
            added_by INTEGER,
            timestamp TEXT
        )
    """)

    # 11. User Warnings & Moderation Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_warnings (
            user_id INTEGER PRIMARY KEY,
            warn_count INTEGER DEFAULT 0,
            last_reason TEXT,
            is_perm_muted INTEGER DEFAULT 0,
            mute_until TEXT
        )
    """)

    # 12. Quiz Access Grants Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS quiz_access_grants (
            user_id INTEGER PRIMARY KEY,
            granted_by INTEGER,
            grant_type TEXT,
            granted_at TEXT,
            expires_at TEXT
        )
    """)

    # 13. Auto Purge Queue Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS auto_purge_queue (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            chat_id INTEGER,
            message_id INTEGER,
            purge_timestamp INTEGER
        )
    """)

    # 14. Smart Keywords Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS smart_keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT UNIQUE,
            channel_link TEXT,
            file_id TEXT,
            teacher_name TEXT,
            created_by INTEGER
        )
    """)

    # 15. Pending Approvals Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pending_approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT,
            file_name TEXT,
            suggested_keyword TEXT,
            uploaded_by INTEGER,
            status TEXT DEFAULT 'pending',
            file_hash TEXT,
            timestamp TEXT
        )
    """)

    # Default settings seed
    cursor.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_val) VALUES ('mode', 'auto')")
    cursor.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_val) VALUES ('default_time', '19:00')")
    cursor.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_val) VALUES ('block_stickers', 'on')")
    cursor.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_val) VALUES ('default_q_count', '15')")
    cursor.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_val) VALUES ('default_timer', '30')")
    cursor.execute("INSERT OR IGNORE INTO bot_settings (setting_key, setting_val) VALUES ('default_level', 'EXTREME_HIGH')")

    conn.commit()
    conn.close()

# --- GROUP LINKING HELPERS ---

def set_user_linked_group(user_id, group_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET linked_group_id = ? WHERE user_id = ?", (group_id, user_id))
    conn.commit()
    conn.close()

def get_user_linked_group(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT linked_group_id FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row["linked_group_id"] if row and row["linked_group_id"] else None

def get_all_linked_groups():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT DISTINCT linked_group_id FROM users WHERE linked_group_id IS NOT NULL AND linked_group_id != 0")
    rows = cursor.fetchall()
    conn.close()
    return [r["linked_group_id"] for r in rows]

# --- BOT SETTINGS ---

def get_setting(key, default=""):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT setting_val FROM bot_settings WHERE setting_key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row["setting_val"] if row else default

def set_setting(key, value):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO bot_settings (setting_key, setting_val) VALUES (?, ?)", (key, str(value)))
    conn.commit()
    conn.close()

# --- SMART KEYWORDS & KNOWLEDGE HUB ---

def add_smart_keyword(keyword, channel_link, file_id="", teacher_name="", created_by=0):
    conn = get_db()
    cursor = conn.cursor()
    kw = keyword.lower().strip()
    if not kw.startswith("#"):
        kw = "#" + kw
    cursor.execute("""
        INSERT OR REPLACE INTO smart_keywords (keyword, channel_link, file_id, teacher_name, created_by)
        VALUES (?, ?, ?, ?, ?)
    """, (kw, channel_link, file_id, teacher_name, created_by))
    conn.commit()
    conn.close()

def search_smart_keywords():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM smart_keywords")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def is_duplicate_file(file_id, file_hash=""):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pdf_vault WHERE file_id = ? OR (file_hash != '' AND file_hash = ?)", (file_id, file_hash))
    row = cursor.fetchone()
    conn.close()
    return True if row else False

def add_pending_approval(file_id, file_name, suggested_keyword, uploaded_by, file_hash=""):
    conn = get_db()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO pending_approvals (file_id, file_name, suggested_keyword, uploaded_by, status, file_hash, timestamp)
        VALUES (?, ?, ?, ?, 'pending', ?, ?)
    """, (file_id, file_name, suggested_keyword, uploaded_by, file_hash, now_str))
    conn.commit()
    app_id = cursor.lastrowid
    conn.close()
    return app_id

def update_approval_status(app_id, status):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE pending_approvals SET status = ? WHERE id = ?", (status, app_id))
    conn.commit()
    conn.close()

def get_pending_approval_by_id(app_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pending_approvals WHERE id = ?", (app_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {}

# --- MODERATION & BAD WORDS FILTER ---

def add_bad_word(word, admin_id=0):
    conn = get_db()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("INSERT OR IGNORE INTO bad_words_filter (word, added_by, timestamp) VALUES (?, ?, ?)", (word.lower().strip(), admin_id, now_str))
    conn.commit()
    conn.close()
    log_audit(admin_id, 0, "FILTER_ADD", f"Added word '{word}'")

def remove_bad_word(word):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM bad_words_filter WHERE LOWER(word) = LOWER(?)", (word.strip(),))
    conn.commit()
    conn.close()

def get_bad_words():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT word FROM bad_words_filter")
    rows = cursor.fetchall()
    conn.close()
    return [r["word"] for r in rows]

def add_user_warning(user_id, reason="Violation"):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_warnings WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    
    now = datetime.now()
    mute_until = (now + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")
    
    if not row:
        warn_count = 1
        is_perm = 0
        cursor.execute("INSERT INTO user_warnings (user_id, warn_count, last_reason, is_perm_muted, mute_until) VALUES (?, 1, ?, 0, ?)",
                       (user_id, reason, mute_until))
    else:
        warn_count = row["warn_count"] + 1
        is_perm = 1 if warn_count >= 3 else 0
        cursor.execute("UPDATE user_warnings SET warn_count = ?, last_reason = ?, is_perm_muted = ?, mute_until = ? WHERE user_id = ?",
                       (warn_count, reason, is_perm, mute_until, user_id))
        
    conn.commit()
    conn.close()
    log_audit(0, user_id, f"WARN_{warn_count}", f"{reason} | Perm Mute: {is_perm}")
    return warn_count, is_perm

def get_user_warnings(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM user_warnings WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else {"warn_count": 0, "last_reason": "None", "is_perm_muted": 0, "mute_until": ""}

# --- QUIZ ACCESS GRANTS ---

def grant_quiz_access(user_id, granted_by, grant_type):
    conn = get_db()
    cursor = conn.cursor()
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H:%M:%S")
    
    if grant_type == "1week":
        exp_str = (now + timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S")
    elif grant_type == "2weeks":
        exp_str = (now + timedelta(days=14)).strftime("%Y-%m-%d %H:%M:%S")
    else:
        exp_str = "2099-12-31 23:59:59"
        
    cursor.execute("""
        INSERT OR REPLACE INTO quiz_access_grants (user_id, granted_by, grant_type, granted_at, expires_at)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, granted_by, grant_type, now_str, exp_str))
    conn.commit()
    conn.close()
    log_audit(granted_by, user_id, "QUIZ_ACCESS_GRANT", f"Granted {grant_type}")

def get_user_quiz_access(user_id, owner_id=None):
    if owner_id and int(user_id) == int(owner_id):
        return True, "owner", "Unlimited"
    
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM quiz_access_grants WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    
    if not row:
        return False, "none", "Expired"
    
    exp_dt = datetime.strptime(row["expires_at"], "%Y-%m-%d %H:%M:%S")
    if datetime.now() > exp_dt:
        return False, row["grant_type"], "Expired"
        
    return True, row["grant_type"], row["expires_at"]

# --- AUTO PURGE QUEUE ---

def add_auto_purge_message(chat_id, message_id, delay_seconds=60):
    conn = get_db()
    cursor = conn.cursor()
    purge_time = int(datetime.now().timestamp()) + delay_seconds
    cursor.execute("INSERT INTO auto_purge_queue (chat_id, message_id, purge_timestamp) VALUES (?, ?, ?)",
                   (chat_id, message_id, purge_time))
    conn.commit()
    conn.close()

def get_pending_purge_messages():
    conn = get_db()
    cursor = conn.cursor()
    now_ts = int(datetime.now().timestamp())
    cursor.execute("SELECT * FROM auto_purge_queue WHERE purge_timestamp <= ?", (now_ts,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_purge_message_entry(entry_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM auto_purge_queue WHERE id = ?", (entry_id,))
    conn.commit()
    conn.close()

# --- USER & ROLE HELPERS ---

def get_or_create_user(user_id, username="", first_name="", owner_id=None, referrer_id=None):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    if not user:
        default_role = 'owner' if owner_id and int(user_id) == int(owner_id) else 'student'
        cursor.execute("""
            INSERT INTO users (user_id, username, first_name, role, xp, level, streak_count, last_active_date, joined_date, referrer_id, is_flex_admin)
            VALUES (?, ?, ?, ?, 0, 1, 1, ?, ?, ?, 0)
        """, (user_id, username, first_name, default_role, today_str, today_str, referrer_id))
        conn.commit()
        
        if referrer_id and referrer_id != user_id:
            add_user_xp(referrer_id, 20)
            log_audit(admin_id=user_id, target_user_id=referrer_id, action_type="REFERRAL_BONUS", reason="Referred new student (+20 XP)")
            
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
    else:
        last_active = user["last_active_date"]
        streak = user["streak_count"]
        if last_active != today_str:
            try:
                last_dt = datetime.strptime(last_active, "%Y-%m-%d")
                curr_dt = datetime.strptime(today_str, "%Y-%m-%d")
                if (curr_dt - last_dt).days == 1:
                    streak += 1
                elif (curr_dt - last_dt).days > 1:
                    streak = 1
            except Exception:
                streak = 1
            cursor.execute("UPDATE users SET username = ?, first_name = ?, last_active_date = ?, streak_count = ? WHERE user_id = ?",
                           (username, first_name, today_str, streak, user_id))
            conn.commit()
            
    conn.close()
    return dict(user) if user else {}

def get_user_role(user_id, owner_id=None):
    if owner_id and int(user_id) == int(owner_id):
        return 'owner'
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT role FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row["role"] if row else 'student'

def add_user_xp(user_id, xp_delta):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT xp, level FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    if user:
        new_xp = max(0, user["xp"] + xp_delta)
        new_level = 1 + (new_xp // 50)
        cursor.execute("UPDATE users SET xp = ?, level = ? WHERE user_id = ?", (new_xp, new_level, user_id))
        conn.commit()
    conn.close()

def set_flex_admin(user_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET is_flex_admin = 0")
    cursor.execute("UPDATE users SET is_flex_admin = 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# --- DAILY SCHEDULES ---

def get_or_create_daily_schedule(date_str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM daily_schedules WHERE date_str = ?", (date_str,))
    row = cursor.fetchone()
    
    if not row:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        is_sunday = dt.weekday() == 6
        
        subjects = ["Accounts", "Business Laws", "Quantitative Aptitude", "Economics"]
        sub_idx = (dt.timetuple().tm_yday) % 4
        chosen_sub = "CUMULATIVE MEGA QUIZ" if is_sunday else subjects[sub_idx]
        chosen_chap = "All Completed Modules" if is_sunday else f"Module Practice Ch.{dt.day}"
        
        cursor.execute("""
            INSERT INTO daily_schedules (date_str, subject, chapter_name, time_str, is_mega_quiz, is_pinned)
            VALUES (?, ?, ?, '19:00', ?, 0)
        """, (date_str, chosen_sub, chosen_chap, 1 if is_sunday else 0))
        conn.commit()
        
        cursor.execute("SELECT * FROM daily_schedules WHERE date_str = ?", (date_str,))
        row = cursor.fetchone()
        
    conn.close()
    return dict(row)

def set_daily_quiz_time(date_str, time_str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE daily_schedules SET time_str = ? WHERE date_str = ?", (time_str, date_str))
    conn.commit()
    conn.close()

# --- QUIZ HISTORY & LEADERBOARD ---

def record_quiz_history(user_id, chat_id, subject, chapter, score, correct, wrong, time_taken=0):
    conn = get_db()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO quiz_history (user_id, chat_id, subject, chapter, score, correct_count, wrong_count, time_taken, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (user_id, chat_id, subject, chapter, score, correct, wrong, time_taken, now_str))
    conn.commit()
    conn.close()

def log_audit(admin_id, target_user_id, action_type, reason=""):
    conn = get_db()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT INTO audit_logs (admin_id, target_user_id, action_type, reason, timestamp)
        VALUES (?, ?, ?, ?, ?)
    """, (admin_id, target_user_id, action_type, reason, now_str))
    conn.commit()
    conn.close()

def add_pdf_to_vault(file_id, file_name, uploaded_by, channel_message_id=0, file_hash=""):
    conn = get_db()
    cursor = conn.cursor()
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute("""
        INSERT OR REPLACE INTO pdf_vault (file_id, file_name, uploaded_by, timestamp, channel_message_id, file_hash)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (file_id, file_name, uploaded_by, now_str, channel_message_id, file_hash))
    conn.commit()
    pdf_id = cursor.lastrowid
    conn.close()
    return pdf_id

def load_scheduled_quizzes():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM scheduled_quizzes")
    rows = cursor.fetchall()
    conn.close()
    return [dict(r) for r in rows]

def delete_scheduled_quiz(sched_id):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM scheduled_quizzes WHERE id = ?", (sched_id,))
    conn.commit()
    conn.close()

init_db()
