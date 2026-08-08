import os
import sys
import time
import json
import sqlite3
import secrets
import re
from datetime import datetime, timedelta
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- CONFIGURATION & API KEYS FROM RENDER ENV ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None
OWNER_ID = int(os.getenv("OWNER_ID", "8724204988"))

# 5 Free AI Keys
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
# OpenAI (added as an additional free-tier-compatible layer, per blueprint "Add both open ai")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# --- NEW: Production Pillars Config ---
FORCE_SUB_CHANNEL = os.getenv("FORCE_SUB_CHANNEL", "")          # e.g. "@ca_vault_channel" — leave blank to disable
FORCE_SUB_CHANNEL_LINK = os.getenv("FORCE_SUB_CHANNEL_LINK", "")  # public invite link shown to users
PDF_VAULT_CHANNEL_ID = os.getenv("PDF_VAULT_CHANNEL_ID", "")     # numeric channel id (as string) bot must be admin of

XP_CORRECT = 4
XP_WRONG = -1
XP_REFERRAL_BONUS = 20
LEVEL_XP_STEP = 100  # XP needed per level

BANNED_WORDS = [w.strip().lower() for w in os.getenv("BANNED_WORDS", "").split(",") if w.strip()]
MUTE_24H_SECONDS = 24 * 60 * 60

scheduled_quizzes = []
active_poll_tracker = {}
active_quiz_sessions = {}
quiz_builder_state = {}
schedule_wizard_state = {}
quiz_report_tracker = {}  # chat_id -> list of per-question stat dicts (for end-of-quiz report)

# Permanent mapping: user_id -> linked_group_id
user_linked_groups = {}

# Permanent mapping: group_id -> "HH:MM" (24h) daily time to post "Today's Quiz" announcement
group_reminder_time = {}
_reminder_sent_tracker = {}  # group_id -> date string already announced today (in-memory only)

SUBJECTS = ["Accounts", "Business Laws", "Quantitative Aptitude", "Economics"]

print("CA Vault Direct Execution Quiz Bot Starting...")

# --- DUMMY WEB SERVER FOR RENDER FREE WEB SERVICE ---
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Telegram Bot is Live and Healthy!")

def run_dummy_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    print(f"Dummy Web Server listening on port {port}")
    server.serve_forever()

# --- TELEGRAM API HELPER FUNCTIONS ---

def send_message(chat_id, text, reply_markup=None):
    if not BASE_URL: return {}
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        res = requests.post(f"{BASE_URL}/sendMessage", json=payload, timeout=5)
        return res.json()
    except Exception:
        return {}

def edit_message(chat_id, message_id, text, reply_markup=None):
    if not BASE_URL: return
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(f"{BASE_URL}/editMessageText", json=payload, timeout=5)
    except Exception:
        pass

def pin_message(chat_id, message_id):
    if not BASE_URL: return
    try:
        requests.post(f"{BASE_URL}/pinChatMessage", json={"chat_id": chat_id, "message_id": message_id}, timeout=5)
    except Exception:
        pass

def is_group_chat(chat_id):
    return str(chat_id).startswith("-")

def is_user_admin_owner_or_anonymous(message):
    user_id = message.get("from", {}).get("id", 0)
    if user_id == OWNER_ID:
        return True
    if "sender_chat" in message:
        return True
    chat_id = message["chat"]["id"]
    if is_group_chat(chat_id):
        try:
            res = requests.get(f"{BASE_URL}/getChatMember", params={"chat_id": chat_id, "user_id": user_id}, timeout=5)
            data = res.json()
            if data.get("ok"):
                return data["result"]["status"] in ["creator", "administrator"]
        except Exception:
            return False
        return False
    return True

# --- PERSISTENCE (so linked groups / schedules survive bot restarts) ---
DATA_FILE = "bot_data.json"
_save_lock = threading.Lock()

def load_persisted_data():
    global user_linked_groups, scheduled_quizzes
    if not os.path.exists(DATA_FILE):
        return
    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
        loaded_links = data.get("linked_groups", {})
        user_linked_groups.update({int(k): v for k, v in loaded_links.items()})
        scheduled_quizzes.extend(data.get("scheduled_quizzes", []))
        loaded_reminders = data.get("group_reminder_time", {})
        group_reminder_time.update({int(k): v for k, v in loaded_reminders.items()})
        print(f"Loaded {len(user_linked_groups)} linked group(s), {len(scheduled_quizzes)} scheduled quiz job(s), {len(group_reminder_time)} reminder setting(s) from disk.")
    except Exception as e:
        print(f"Could not load persisted data: {e}")

def save_persisted_data():
    with _save_lock:
        try:
            with open(DATA_FILE, "w") as f:
                json.dump({
                    "linked_groups": user_linked_groups,
                    "scheduled_quizzes": scheduled_quizzes,
                    "group_reminder_time": group_reminder_time
                }, f)
        except Exception as e:
            print(f"Could not save persisted data: {e}")

# ============================================================================
# --- PRODUCTION-READY DATABASE LAYER (SQLite) ---
# Pillars: A) Roles  B) Users/QuizHistory/Badges/PDFIndex/Leaderboard  C) Audit Logs
# ============================================================================
DB_FILE = os.getenv("DB_FILE", "ca_vault.db")
_db_lock = threading.Lock()

def get_db():
    conn = sqlite3.connect(DB_FILE, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with _db_lock:
        conn = get_db()
        c = conn.cursor()
        c.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            role TEXT DEFAULT 'student',
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            streak_count INTEGER DEFAULT 0,
            last_active_date TEXT,
            referred_by INTEGER,
            referral_code TEXT UNIQUE,
            joined_date TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS quiz_history (
            attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            subject TEXT,
            chapter TEXT,
            score INTEGER,
            correct_count INTEGER,
            wrong_count INTEGER,
            time_taken INTEGER,
            timestamp TEXT
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS badges (
            badge_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            badge_name TEXT,
            earned_at TEXT,
            UNIQUE(user_id, badge_name)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS pdf_index (
            pdf_id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_id TEXT,
            file_name TEXT,
            uploaded_by INTEGER,
            timestamp TEXT,
            channel_message_id INTEGER
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS leaderboard_cache (
            user_id INTEGER,
            period TEXT,
            periodic_score INTEGER,
            rank INTEGER,
            updated_at TEXT,
            PRIMARY KEY (user_id, period)
        )""")
        c.execute("""CREATE TABLE IF NOT EXISTS audit_logs (
            log_id INTEGER PRIMARY KEY AUTOINCREMENT,
            admin_id INTEGER,
            target_user_id INTEGER,
            action_type TEXT,
            reason TEXT,
            timestamp TEXT
        )""")
        conn.commit()
        conn.close()
        print("Database initialized (users, quiz_history, badges, pdf_index, leaderboard_cache, audit_logs).")

def log_audit(admin_id, target_user_id, action_type, reason=""):
    with _db_lock:
        conn = get_db()
        conn.execute(
            "INSERT INTO audit_logs (admin_id, target_user_id, action_type, reason, timestamp) VALUES (?,?,?,?,?)",
            (admin_id, target_user_id, action_type, reason, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
        conn.close()

def ensure_user(user_id, username=""):
    with _db_lock:
        conn = get_db()
        row = conn.execute("SELECT user_id FROM users WHERE user_id=?", (user_id,)).fetchone()
        if not row:
            role = "owner" if user_id == OWNER_ID else "student"
            ref_code = secrets.token_hex(4)
            conn.execute(
                "INSERT INTO users (user_id, username, role, xp, level, streak_count, last_active_date, referral_code, joined_date) VALUES (?,?,?,?,?,?,?,?,?)",
                (user_id, username, role, 0, 1, 0, "", ref_code, datetime.now().strftime("%Y-%m-%d"))
            )
            conn.commit()
        elif username:
            conn.execute("UPDATE users SET username=? WHERE user_id=?", (username, user_id))
            conn.commit()
        conn.close()

def get_user_row(user_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE user_id=?", (user_id,)).fetchone()
    conn.close()
    return row

def get_role(user_id):
    if user_id == OWNER_ID:
        return "owner"
    row = get_user_row(user_id)
    return row["role"] if row else "student"

def set_role(target_user_id, new_role, set_by):
    ensure_user(target_user_id)
    with _db_lock:
        conn = get_db()
        conn.execute("UPDATE users SET role=? WHERE user_id=?", (new_role, target_user_id))
        conn.commit()
        conn.close()
    log_audit(set_by, target_user_id, "role_change", f"role set to {new_role}")

ROLE_RANK = {"student": 0, "moderator": 1, "admin": 2, "owner": 3}

def role_at_least(user_id, required_role):
    return ROLE_RANK.get(get_role(user_id), 0) >= ROLE_RANK.get(required_role, 99)

def compute_level(xp):
    return max(1, (max(xp, 0) // LEVEL_XP_STEP) + 1)

def update_streak(user_id):
    """Daily streak: increments if last active was yesterday, resets if gap >1 day, no-op if already today."""
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    row = get_user_row(user_id)
    if not row:
        return 0
    last = row["last_active_date"] or ""
    streak = row["streak_count"] or 0
    if last == today:
        return streak
    elif last == yesterday:
        streak += 1
    else:
        streak = 1
    with _db_lock:
        conn = get_db()
        conn.execute("UPDATE users SET streak_count=?, last_active_date=? WHERE user_id=?", (streak, today, user_id))
        conn.commit()
        conn.close()
    return streak

def add_xp(user_id, delta, username=""):
    ensure_user(user_id, username)
    with _db_lock:
        conn = get_db()
        row = conn.execute("SELECT xp FROM users WHERE user_id=?", (user_id,)).fetchone()
        new_xp = max(0, (row["xp"] if row else 0) + delta)
        new_level = compute_level(new_xp)
        conn.execute("UPDATE users SET xp=?, level=? WHERE user_id=?", (new_xp, new_level, user_id))
        conn.commit()
        conn.close()
    return new_xp, new_level

def award_badge(user_id, badge_name):
    with _db_lock:
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO badges (user_id, badge_name, earned_at) VALUES (?,?,?)",
                (user_id, badge_name, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            )
            conn.commit()
            newly_awarded = True
        except sqlite3.IntegrityError:
            newly_awarded = False
        conn.close()
    if newly_awarded:
        send_message(user_id, f"🏅 *New Badge Unlocked!*\n\n`{badge_name}`\nKeep it up!")
    return newly_awarded

def check_and_award_badges(user_id):
    row = get_user_row(user_id)
    if not row:
        return
    xp, streak = row["xp"], row["streak_count"]
    conn = get_db()
    quiz_count = conn.execute("SELECT COUNT(*) c FROM quiz_history WHERE user_id=?", (user_id,)).fetchone()["c"]
    conn.close()
    if streak >= 7:
        award_badge(user_id, "7-Day Streak 🔥")
    if streak >= 3:
        award_badge(user_id, "3-Day Streak ⚡")
    if xp >= 500:
        award_badge(user_id, "Quiz Master 🏆")
    if quiz_count >= 10:
        award_badge(user_id, "Consistent Learner 📚")

def log_quiz_attempt(user_id, subject, chapter, correct_count, wrong_count, time_taken):
    score = correct_count - wrong_count
    with _db_lock:
        conn = get_db()
        conn.execute(
            "INSERT INTO quiz_history (user_id, subject, chapter, score, correct_count, wrong_count, time_taken, timestamp) VALUES (?,?,?,?,?,?,?,?)",
            (user_id, subject, chapter or "Full Syllabus", score, correct_count, wrong_count, time_taken, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
        conn.close()

def get_leaderboard(period="alltime", limit=10):
    conn = get_db()
    if period == "alltime":
        rows = conn.execute("SELECT user_id, username, xp, level FROM users ORDER BY xp DESC LIMIT ?", (limit,)).fetchall()
    else:
        days = {"daily": 1, "weekly": 7, "monthly": 30}.get(period, 7)
        since = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
        rows = conn.execute(
            """SELECT u.user_id, u.username, SUM(q.score) as periodic_score
               FROM quiz_history q JOIN users u ON u.user_id = q.user_id
               WHERE q.timestamp >= ? GROUP BY q.user_id ORDER BY periodic_score DESC LIMIT ?""",
            (since, limit)
        ).fetchall()
    conn.close()
    return rows

def process_referral(new_user_id, referral_code):
    conn = get_db()
    referrer = conn.execute("SELECT user_id FROM users WHERE referral_code=?", (referral_code,)).fetchone()
    conn.close()
    if not referrer or referrer["user_id"] == new_user_id:
        return
    row = get_user_row(new_user_id)
    if row and row["referred_by"]:
        return  # already processed
    with _db_lock:
        conn = get_db()
        conn.execute("UPDATE users SET referred_by=? WHERE user_id=?", (referrer["user_id"], new_user_id))
        conn.commit()
        conn.close()
    add_xp(referrer["user_id"], XP_REFERRAL_BONUS)
    log_audit(new_user_id, referrer["user_id"], "referral_bonus", f"+{XP_REFERRAL_BONUS} XP for referring {new_user_id}")
    send_message(referrer["user_id"], f"🎉 *Referral Shield Activated!*\n\nSomeone joined using your referral link. `+{XP_REFERRAL_BONUS} XP` credited.")

# --- ANTI-ABUSE / SECURITY HELPERS ---

def restrict_user(chat_id, user_id, seconds=None):
    payload = {
        "chat_id": chat_id,
        "user_id": user_id,
        "permissions": {"can_send_messages": False}
    }
    if seconds:
        payload["until_date"] = int(time.time()) + seconds
    try:
        requests.post(f"{BASE_URL}/restrictChatMember", json=payload, timeout=5)
    except Exception:
        pass

def unrestrict_user(chat_id, user_id):
    payload = {
        "chat_id": chat_id,
        "user_id": user_id,
        "permissions": {
            "can_send_messages": True, "can_send_audios": True, "can_send_documents": True,
            "can_send_photos": True, "can_send_videos": True, "can_send_video_notes": True,
            "can_send_voice_notes": True, "can_send_polls": True, "can_send_other_messages": True,
            "can_add_web_page_previews": True
        }
    }
    try:
        requests.post(f"{BASE_URL}/restrictChatMember", json=payload, timeout=5)
    except Exception:
        pass

def ban_user(chat_id, user_id):
    try:
        requests.post(f"{BASE_URL}/banChatMember", json={"chat_id": chat_id, "user_id": user_id}, timeout=5)
    except Exception:
        pass

def contains_banned_word(text):
    if not text or not BANNED_WORDS:
        return False
    lowered = text.lower()
    return any(w in lowered for w in BANNED_WORDS)

def handle_abuse_violation(chat_id, user_id, username, message_text):
    """Instant temp mute + DM to Bot Owner with Unmute/Mute24h/Block inline options."""
    restrict_user(chat_id, user_id, seconds=600)  # 10-min instant temp mute pending owner review
    log_audit(0, user_id, "auto_mute", "banned word detected")
    keyboard = {
        "inline_keyboard": [
            [
                {"text": "✅ Unmute", "callback_data": f"abuse_unmute_{chat_id}_{user_id}"},
                {"text": "🔇 Mute 24h", "callback_data": f"abuse_mute24_{chat_id}_{user_id}"},
                {"text": "⛔ Block", "callback_data": f"abuse_block_{chat_id}_{user_id}"}
            ]
        ]
    }
    send_message(
        OWNER_ID,
        f"🛡️ *Anti-Abuse Alert*\n────────────────────────\n👤 User: `{user_id}` ({username})\n📍 Group: `{chat_id}`\n"
        f"💬 Flagged Message: _{message_text[:200]}_\n\nUser has been auto-muted for 10 minutes pending your decision.",
        reply_markup=keyboard
    )

def is_force_sub_member(user_id):
    if not FORCE_SUB_CHANNEL:
        return True
    try:
        res = requests.get(f"{BASE_URL}/getChatMember", params={"chat_id": FORCE_SUB_CHANNEL, "user_id": user_id}, timeout=5)
        data = res.json()
        if data.get("ok"):
            return data["result"]["status"] in ["creator", "administrator", "member"]
    except Exception:
        return True  # fail-open so bot doesn't lock everyone out on API hiccups
    return True

def prompt_force_subscribe(chat_id, user_id):
    keyboard = {"inline_keyboard": [[{"text": "📢 Join Channel", "url": FORCE_SUB_CHANNEL_LINK or f"https://t.me/{FORCE_SUB_CHANNEL.lstrip('@')}"}],
                                     [{"text": "✅ I've Joined", "callback_data": "fsub_recheck"}]]}
    send_message(chat_id, "🔒 *Access Restricted*\n\nPlease join our official announcement channel to continue using the bot.", reply_markup=keyboard)

def set_focus_mode(chat_id, enable):
    """Mutes/unmutes the whole group's default permission during a live quiz to stop spam."""
    permissions = {"can_send_messages": not enable}
    try:
        requests.post(f"{BASE_URL}/setChatPermissions", json={"chat_id": chat_id, "permissions": permissions}, timeout=5)
    except Exception:
        pass

# --- REST AI CALLS (5 LAYERS) ---

def call_gemini(prompt):
    if not GEMINI_API_KEY: return None
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        res = requests.post(url, json=payload, timeout=5)
        if res.status_code == 200:
            return res.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        pass
    return None

def call_groq(prompt):
    if not GROQ_API_KEY: return None
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}]}
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        if res.status_code == 200:
            return res.json()["choices"][0]["message"]["content"]
    except Exception:
        pass
    return None

def call_cerebras(prompt):
    if not CEREBRAS_API_KEY: return None
    try:
        url = "https://api.cerebras.ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {CEREBRAS_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "llama3.1-70b", "messages": [{"role": "user", "content": prompt}]}
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        if res.status_code == 200:
            return res.json()["choices"][0]["message"]["content"]
    except Exception:
        pass
    return None

def call_mistral(prompt):
    if not MISTRAL_API_KEY: return None
    try:
        url = "https://api.mistral.ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "mistral-large-latest", "messages": [{"role": "user", "content": prompt}]}
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        if res.status_code == 200:
            return res.json()["choices"][0]["message"]["content"]
    except Exception:
        pass
    return None

def call_openrouter(prompt):
    if not OPENROUTER_API_KEY: return None
    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": prompt}]}
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        if res.status_code == 200:
            return res.json()["choices"][0]["message"]["content"]
    except Exception:
        pass
    return None

def fetch_fastest_ai_response(prompt):
    ai_funcs = [call_groq, call_gemini, call_cerebras, call_mistral, call_openrouter]
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(func, prompt) for func in ai_funcs]
        for future in as_completed(futures):
            result = future.result()
            if result and len(result.strip()) > 20:
                return result
    return None

def generate_ai_question(subject, chapter, subtopics="", level="EXTREME_HIGH"):
    scope_text = f"Chapter '{chapter}'" if chapter else f"Full Subject '{subject}' syllabus"
    if subtopics:
        scope_text += f" (Focus Sub-topics: '{subtopics}')"

    if level == "EXTREME_HIGH":
        diff_instruction = "Difficulty: EXTREME HIGH. Focus on conceptual traps, multi-statement evaluations, and complex ICAI module exceptions."
    elif level == "HIGH":
        diff_instruction = "Difficulty: HIGH. Focus on tricky ICAI exam-level standard logic and calculations."
    else:
        diff_instruction = "Difficulty: MEDIUM. Focus on fundamental ICAI module conceptual questions."

    tag_instruction = ""
    if subject in ["Quantitative Aptitude", "Economics"]:
        tag_instruction = (
            "IMPORTANT: If this question/logic appeared in an actual past ICAI PYQ, RTP, or MTP (2018-2025), specify the source tag strictly in Tag line.\n"
            "Format Tag line as: 'Tag: [ICAI PYQ Nov 2022]' or 'Tag: [ICAI RTP May 2023]'.\n"
            "DO NOT write 'ICAI Module Standard'. If no specific exam year applies, write 'Tag: None'.\n"
        )
    else:
        tag_instruction = "Write 'Tag: None'\n"

    prompt = (
        f"Generate exactly 1 multiple-choice question for CA Foundation '{subject}', {scope_text}.\n"
        f"{diff_instruction}\n"
        f"{tag_instruction}\n"
        f"Format strictly as:\n"
        f"Tag: [Source tag or None]\n"
        f"Q: [Question text]\n"
        f"O1: [Option 1]\n"
        f"O2: [Option 2]\n"
        f"O3: [Option 3]\n"
        f"O4: [Option 4]\n"
        f"Correct: 1\n"
        f"Explanation: [1-line precise ICAI logic explanation]"
    )

    raw_text = fetch_fastest_ai_response(prompt)
    return parse_single_ai_output(raw_text, subject)

def parse_single_ai_output(text, subject):
    if not text:
        return {
            "tag": "",
            "question": f"[{subject}] ICAI Practice Question",
            "options": ["Option A", "Option B", "Option C", "Option D"],
            "correct": 0,
            "explanation": "Standard ICAI rule applies."
        }
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    tag_text, q_text, o1, o2, o3, o4, correct_idx, explanation = "", "", "", "", "", "", 0, "ICAI module principle applies."

    for line in lines:
        if line.startswith("Tag:"):
            val = line[4:].strip()
            if val and val.lower() != "none" and "module standard" not in val.lower() and subject in ["Quantitative Aptitude", "Economics"]:
                tag_text = val
        elif line.startswith("Q:"): q_text = line[2:].strip()
        elif line.startswith("O1:"): o1 = line[3:].strip()
        elif line.startswith("O2:"): o2 = line[3:].strip()
        elif line.startswith("O3:"): o3 = line[3:].strip()
        elif line.startswith("O4:"): o4 = line[3:].strip()
        elif line.startswith("Correct:"):
            digits = ''.join(filter(str.isdigit, line))
            if digits: correct_idx = int(digits) - 1
        elif line.startswith("Explanation:"): explanation = line[12:].strip()

    return {
        "tag": tag_text,
        "question": q_text or f"[{subject}] ICAI Exam Question",
        "options": [o1 or "A", o2 or "B", o3 or "C", o4 or "D"],
        "correct": max(0, min(correct_idx, 3)),
        "explanation": explanation
    }

def send_poll(chat_id, question, options, correct_option_id, open_period=30):
    payload = {
        "chat_id": chat_id,
        "question": question[:300],
        "options": [str(opt)[:100] for opt in options],
        "is_anonymous": False,
        "type": "quiz",
        "correct_option_id": max(0, min(correct_option_id, len(options) - 1)),
        "open_period": open_period
    }
    try:
        res = requests.post(f"{BASE_URL}/sendPoll", json=payload, timeout=5)
        data = res.json()
        if data.get("ok"):
            poll_id = data["result"]["poll"]["id"]
            active_poll_tracker[poll_id] = {
                "correct": max(0, min(correct_option_id, len(options) - 1)),
                "chat_id": chat_id,
                "options": options,
                "question": question,
                "wrong_count": 0,
                "total_votes": 0
            }
        return data
    except Exception:
        return {}

def run_quiz_session(target_chat_id, subject, chapter, count, timer, break_freq=0, break_duration=0, level="EXTREME_HIGH", conductor_user_id=None, subtopics=""):
    if not is_group_chat(target_chat_id):
        if conductor_user_id:
            send_message(conductor_user_id, "*Quiz Error*\nQuizzes can ONLY be conducted inside Telegram Groups, not in DM.")
        return

    active_quiz_sessions[target_chat_id] = True
    quiz_report_tracker[target_chat_id] = []
    set_focus_mode(target_chat_id, enable=True)  # Focus Mode: mute group chatter during the quiz

    chap_display = chapter if chapter else "Full Syllabus"
    subtopic_display = f"\nSub-topics: `{subtopics}`" if subtopics else ""
    break_info = f"Break: Every `{break_freq}` Qs for `{break_duration//60}` min" if break_freq > 0 else "Mode: Non-stop (No Breaks)"

    start_msg = (
        f"🎯 *CA VAULT — LIVE QUIZ SESSION*\n"
        f"────────────────────────\n"
        f"📘 Subject: `{subject}`\n"
        f"📖 Chapter: `{chap_display}`{subtopic_display}\n"
        f"🔢 Questions: `{count}`  |  ⏱ Timer: `{timer}s`\n"
        f"☕ {break_info}\n"
        f"────────────────────────\n"
        f"🚀 Quiz starting now. All the best!"
    )
    send_message(target_chat_id, start_msg)

    current_difficulty = level

    if conductor_user_id:
        send_message(conductor_user_id, f"🚀 *Quiz Started* in group `{target_chat_id}`\n🔥 Starting level: `{current_difficulty}`\n📊 A full performance report will be sent here once the quiz ends.")

    for idx in range(count):
        if not active_quiz_sessions.get(target_chat_id, False):
            send_message(target_chat_id, "Quiz session stopped.")
            if conductor_user_id:
                send_message(conductor_user_id, f"Quiz session stopped in group `{target_chat_id}`.")
            break

        if idx > 0 and break_freq > 0 and idx % break_freq == 0:
            send_message(target_chat_id, f"{idx} questions complete. `{break_duration // 60}` minute break starting now...")
            for _ in range(break_duration):
                if not active_quiz_sessions.get(target_chat_id, False):
                    break
                time.sleep(1)
            send_message(target_chat_id, "Break over. Resuming quiz...")

        q = generate_ai_question(subject, chapter, subtopics, current_difficulty)

        question_header = f"Q{idx+1}/{count}"
        if q["tag"]:
            question_header += f" {q['tag']}"

        full_q_text = f"{question_header}: {q['question']}"

        poll_res = send_poll(target_chat_id, full_q_text, q['options'], q['correct'], open_period=timer)
        poll_id = poll_res.get("result", {}).get("poll", {}).get("id") if poll_res.get("ok") else None

        time.sleep(timer + 1)

        if poll_id and poll_id in active_poll_tracker:
            p_data = active_poll_tracker[poll_id]
            total_v = p_data["total_votes"]
            wrong_v = p_data["wrong_count"]

            wrong_percentage = (wrong_v / total_v * 100) if total_v > 0 else 0

            # Record this question's stats for the end-of-quiz report (no live DM anymore)
            quiz_report_tracker.setdefault(target_chat_id, []).append({
                "q_no": idx + 1,
                "difficulty": current_difficulty,
                "total_votes": total_v,
                "wrong_count": wrong_v,
                "wrong_pct": wrong_percentage
            })

            if total_v > 0 and wrong_percentage > 60:
                if current_difficulty == "EXTREME_HIGH":
                    current_difficulty = "HIGH"
                elif current_difficulty == "HIGH":
                    current_difficulty = "MEDIUM"

        time.sleep(2)

    active_quiz_sessions[target_chat_id] = False
    set_focus_mode(target_chat_id, enable=False)  # Focus Mode: restore normal chat after quiz ends
    send_message(target_chat_id, f"🎉 *QUIZ COMPLETE*\n\n📘 Subject: `{subject}`\n🔢 Total Questions: `{count}`")

    if conductor_user_id:
        send_message(conductor_user_id, build_performance_report(subject, chap_display, quiz_report_tracker.get(target_chat_id, [])))

    quiz_report_tracker.pop(target_chat_id, None)

def build_performance_report(subject, chapter, report_rows):
    """Builds a single consolidated performance report, sent once the quiz has finished."""
    if not report_rows:
        return "📊 *QUIZ PERFORMANCE REPORT*\nNo votes were recorded for this quiz."

    total_q = len(report_rows)
    total_votes = sum(r["total_votes"] for r in report_rows)
    total_wrong = sum(r["wrong_count"] for r in report_rows)
    overall_wrong_pct = (total_wrong / total_votes * 100) if total_votes > 0 else 0
    overall_accuracy = 100 - overall_wrong_pct
    final_difficulty = report_rows[-1]["difficulty"]
    toughest = max(report_rows, key=lambda r: r["wrong_pct"]) if any(r["total_votes"] > 0 for r in report_rows) else None

    lines = [
        "📊 *QUIZ PERFORMANCE REPORT*",
        "────────────────────────",
        f"📘 Subject: `{subject}` ({chapter})",
        f"🔢 Questions Conducted: `{total_q}`",
        f"🔥 Final Difficulty Level: `{final_difficulty}`",
        f"✅ Overall Accuracy: `{overall_accuracy:.1f}%`  |  ❌ Overall Wrong: `{overall_wrong_pct:.1f}%`",
        "────────────────────────",
        "*Question-wise Breakdown:*"
    ]
    for r in report_rows:
        lines.append(f"Q{r['q_no']}: `{r['total_votes']}` votes, `{r['wrong_count']}` wrong (`{r['wrong_pct']:.1f}%`) — {r['difficulty']}")

    if toughest and toughest["total_votes"] > 0:
        lines.append("────────────────────────")
        lines.append(f"🧩 Toughest Question: Q{toughest['q_no']} (`{toughest['wrong_pct']:.1f}%` wrong)")

    return "\n".join(lines)

# --- "TODAY'S QUIZ" DAILY GROUP ANNOUNCEMENT ---

def build_today_announcement(jobs):
    jobs_sorted = sorted(jobs, key=lambda j: j["datetime"])
    lines = [
        "📢 *TODAY'S QUIZ SCHEDULE*",
        "────────────────────────"
    ]
    for j in jobs_sorted:
        try:
            dt_obj = datetime.strptime(j["datetime"], "%Y-%m-%d %H:%M")
            time_disp = dt_obj.strftime("%I:%M %p")
        except Exception:
            time_disp = j["datetime"]
        chap = j.get("chapter") or "Full Syllabus"
        lines.append(f"🕐 `{time_disp}`  —  📘 *{j['subject']}* ({chap})  —  🔢 `{j['count']}` Qs")
    lines.append("────────────────────────")
    lines.append("Quizzes will start automatically at the time(s) shown above. Good luck! 🎯")
    return "\n".join(lines)

def daily_reminder_worker():
    while True:
        try:
            now = datetime.now()
            current_hm = now.strftime("%H:%M")
            today_str = now.strftime("%Y-%m-%d")
            for group_id, rem_time in list(group_reminder_time.items()):
                if rem_time == current_hm and _reminder_sent_tracker.get(group_id) != today_str:
                    todays_jobs = [j for j in scheduled_quizzes if j.get("chat_id") == group_id and j["datetime"].startswith(today_str)]
                    if todays_jobs:
                        send_message(group_id, build_today_announcement(todays_jobs))
                    _reminder_sent_tracker[group_id] = today_str
        except Exception:
            pass
        time.sleep(30)

# --- BACKGROUND SCHEDULER WORKER ---

def scheduler_background_worker():
    while True:
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        fired = False
        for job in list(scheduled_quizzes):
            if job["datetime"] == current_time_str:
                threading.Thread(
                    target=run_quiz_session,
                    args=(
                        job["chat_id"],
                        job["subject"],
                        job["chapter"],
                        job["count"],
                        job["timer"],
                        job.get("break_freq", 0),
                        job.get("break_duration", 0),
                        job.get("level", "EXTREME_HIGH"),
                        job.get("conductor_id"),
                        job.get("subtopics", "")
                    ),
                    daemon=True
                ).start()
                scheduled_quizzes.remove(job)
                fired = True
        if fired:
            save_persisted_data()
        time.sleep(15)

def get_help_text():
    return (
        "🦅 *CA VAULT QUIZ BOT — CONTROL PANEL*\n"
        "────────────────────────\n\n"
        "👥 *Group Commands*\n"
        "▸ `/quiz` — Launch interactive live quiz setup\n"
        "▸ `/stopquiz` — Stop the active quiz\n"
        "▸ `/myid` — Show this group's Chat ID\n\n"
        "💬 *DM Control Wizard (Bot DM only)*\n"
        "▸ `/link_group <GroupID>` — Link your group once (stays linked forever)\n"
        "▸ `/schedule` — Guided scheduler wizard\n"
        "      📅 One-time custom date & time (AM/PM)\n"
        "      🔁 Recurring daily preset/custom slots\n"
        "▸ `/myschedules` — View your upcoming scheduled quizzes\n"
        "▸ `/reminder` — Set the daily \"Today's Quiz\" announcement time\n\n"
        "🎮 *Gamification*\n"
        "▸ `/profile` — XP, Level, Streak & Badges\n"
        "▸ `/leaderboard [daily|weekly|monthly|alltime]` — Top rankers\n"
        "▸ `/refer` — Get your referral link (+20 XP per join)\n\n"
        "📄 *Study Vault*\n"
        "▸ `/addpdf` — Reply to a PDF to index it into the Study Vault channel\n\n"
        "🛡️ *Admin/Owner Only*\n"
        "▸ `/setrole <user_id> <student|moderator|admin|owner>`\n"
        "▸ `/audit` — View recent moderation/audit logs\n\n"
        "📊 *After every quiz:* a full performance report is DM'd to whoever started it."
    )

# --- WIZARD HELPER TO BUILD SUMMARY TEXT ---
def get_wizard_summary(st):
    grp = st.get("group_id", "Not Set")
    subj = st.get("subject", "Not Selected")
    chap = st.get("chapter", "Full Subject Syllabus")
    subtop = st.get("subtopics", "None")
    lvl = st.get("level", "Not Selected")
    mode = st.get("schedule_mode")
    if mode == "onetime":
        schedule_line = f"📅 Date/Time: `{st.get('display_datetime', 'Not Selected')}`"
    else:
        slots = ", ".join(st.get("slots", [])) if st.get("slots") else "Not Selected"
        schedule_line = f"🔁 Daily Slots: `{slots}`"
    cnt = st.get("count", "Not Selected")
    tmr = st.get("timer", "Not Selected")

    return (
        f"📊 *CURRENT SCOPE SUMMARY*\n"
        f"────────────────────────\n"
        f"📌 Group: `{grp}`\n"
        f"📘 Subject: `{subj}`\n"
        f"📖 Chapter: `{chap or 'Full Subject Syllabus'}`\n"
        f"🎯 Sub-topics: `{subtop or 'None'}`\n"
        f"🔥 Difficulty: `{lvl}`\n"
        f"{schedule_line}\n"
        f"🔢 Questions: `{cnt}`\n"
        f"⏱ Timer/Question: `{tmr}`\n"
        f"────────────────────────\n"
    )

# --- REUSABLE KEYBOARD BUILDERS (preset + manual custom option, everywhere) ---
def build_count_keyboard(prefix, back_cb):
    return {
        "inline_keyboard": [
            [{"text": "10 Qs", "callback_data": f"{prefix}10"}, {"text": "20 Qs", "callback_data": f"{prefix}20"}],
            [{"text": "30 Qs", "callback_data": f"{prefix}30"}, {"text": "40 Qs", "callback_data": f"{prefix}40"}],
            [{"text": "50 Qs", "callback_data": f"{prefix}50"}],
            [{"text": "Custom (type it)", "callback_data": f"{prefix}custom_prompt"}],
            [{"text": "Back", "callback_data": back_cb}]
        ]
    }

def build_timer_keyboard(prefix, back_cb):
    return {
        "inline_keyboard": [
            [{"text": "20s", "callback_data": f"{prefix}20"}, {"text": "30s", "callback_data": f"{prefix}30"}],
            [{"text": "45s", "callback_data": f"{prefix}45"}, {"text": "60s", "callback_data": f"{prefix}60"}],
            [{"text": "Custom (type it)", "callback_data": f"{prefix}custom_prompt"}],
            [{"text": "Back", "callback_data": back_cb}]
        ]
    }

def handle_updates():
    offset = 0
    while True:
        try:
            if not BASE_URL:
                print("Error: BOT_TOKEN Environment Variable is missing!")
                time.sleep(5)
                continue

            response = requests.get(f"{BASE_URL}/getUpdates", params={"offset": offset, "timeout": 5}, timeout=10)
            data = response.json()

            if data.get("ok"):
                for result in data.get("result", []):
                    offset = result["update_id"] + 1

                    if "poll_answer" in result:
                        p_ans = result["poll_answer"]
                        poll_id = p_ans["poll_id"]
                        user = p_ans["user"]
                        user_id = user["id"]
                        chosen_options = p_ans.get("option_ids", [])

                        if poll_id in active_poll_tracker and chosen_options:
                            info = active_poll_tracker[poll_id]
                            correct_idx = info["correct"]
                            info["total_votes"] += 1

                            username = user.get("username") or user.get("first_name", "")
                            ensure_user(user_id, username)
                            streak = update_streak(user_id)

                            if correct_idx not in chosen_options:
                                info["wrong_count"] += 1
                                add_xp(user_id, XP_WRONG, username)
                                log_quiz_attempt(user_id, "N/A", "N/A", 0, 1, 0)
                                wrong_dm_text = (
                                    f"Your answer was incorrect. `{XP_WRONG} XP`\n\n"
                                    f"_{info['question']}_\n\n"
                                    f"Correct Option: `{info['options'][correct_idx]}`\n"
                                    f"Explanation: _{info.get('explanation', 'ICAI module principle applies.')}_"
                                )
                                send_message(user_id, wrong_dm_text)
                            else:
                                add_xp(user_id, XP_CORRECT, username)
                                log_quiz_attempt(user_id, "N/A", "N/A", 1, 0, 0)

                            check_and_award_badges(user_id)

                    if "message" in result:
                        message = result["message"]
                        chat_id = message["chat"]["id"]
                        user_id = message.get("from", {}).get("id", 0)
                        username = message.get("from", {}).get("username") or message.get("from", {}).get("first_name", "")
                        text = message.get("text", "").strip()

                        if user_id:
                            ensure_user(user_id, username)

                        # --- FORCE SUBSCRIBE GATE (skips owner/admins and non-command chatter checks) ---
                        if FORCE_SUB_CHANNEL and user_id and user_id != OWNER_ID and not is_force_sub_member(user_id):
                            prompt_force_subscribe(chat_id, user_id)
                            continue

                        # --- ANTI-ABUSE KEYWORD SCAN (group messages only, skip admins/owner) ---
                        if is_group_chat(chat_id) and text and not text.startswith("/") and contains_banned_word(text):
                            if not is_user_admin_owner_or_anonymous(message):
                                handle_abuse_violation(chat_id, user_id, username, text)
                                continue

                        # --- PDF VAULT: reply to a document with /addpdf ---
                        if text.startswith("/addpdf"):
                            replied = message.get("reply_to_message", {})
                            doc = replied.get("document")
                            if not doc:
                                send_message(chat_id, "⚠️ Reply to a PDF/document message with `/addpdf` to index it.")
                                continue
                            if not PDF_VAULT_CHANNEL_ID:
                                send_message(chat_id, "⚠️ PDF Vault channel is not configured by the Owner yet.")
                                continue
                            fwd_res = {}
                            try:
                                fwd_res = requests.post(f"{BASE_URL}/forwardMessage", json={
                                    "chat_id": PDF_VAULT_CHANNEL_ID, "from_chat_id": chat_id, "message_id": replied["message_id"]
                                }, timeout=5).json()
                            except Exception:
                                pass
                            channel_msg_id = fwd_res.get("result", {}).get("message_id") if fwd_res.get("ok") else None
                            with _db_lock:
                                conn = get_db()
                                conn.execute(
                                    "INSERT INTO pdf_index (file_id, file_name, uploaded_by, timestamp, channel_message_id) VALUES (?,?,?,?,?)",
                                    (doc.get("file_id"), doc.get("file_name", "unnamed.pdf"), user_id, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), channel_msg_id)
                                )
                                conn.commit()
                                conn.close()
                            log_audit(user_id, user_id, "pdf_upload", doc.get("file_name", "unnamed.pdf"))
                            send_message(chat_id, f"📄 *PDF Indexed to Study Vault*\n\nFile: `{doc.get('file_name', 'unnamed.pdf')}`")
                            continue

                        # --- PROFILE / LEADERBOARD / REFERRAL / ROLE / AUDIT COMMANDS ---
                        if text.startswith("/profile"):
                            row = get_user_row(user_id)
                            conn = get_db()
                            b_rows = conn.execute("SELECT badge_name FROM badges WHERE user_id=?", (user_id,)).fetchall()
                            conn.close()
                            badges_text = ", ".join([b["badge_name"] for b in b_rows]) or "None yet"
                            send_message(chat_id,
                                f"👤 *YOUR PROFILE*\n────────────────────────\n"
                                f"🏷 Role: `{get_role(user_id).title()}`\n"
                                f"✨ XP: `{row['xp']}`  |  📈 Level: `{row['level']}`\n"
                                f"🔥 Streak: `{row['streak_count']} day(s)`\n"
                                f"🏅 Badges: {badges_text}\n"
                                f"🔗 Referral Code: `{row['referral_code']}`"
                            )
                            continue

                        elif text.startswith("/leaderboard"):
                            parts = text.split()
                            period = parts[1].lower() if len(parts) > 1 and parts[1].lower() in ["daily", "weekly", "monthly", "alltime"] else "alltime"
                            rows = get_leaderboard(period)
                            if not rows:
                                send_message(chat_id, "No leaderboard data yet. Play a quiz to get ranked!")
                                continue
                            lines = [f"🏆 *LEADERBOARD ({period.upper()})*", "────────────────────────"]
                            for i, r in enumerate(rows, 1):
                                score_val = r["xp"] if period == "alltime" else r["periodic_score"]
                                uname = r["username"] or str(r["user_id"])
                                lines.append(f"{i}. {uname} — `{score_val}` pts")
                            send_message(chat_id, "\n".join(lines))
                            continue

                        elif text.startswith("/refer"):
                            row = get_user_row(user_id)
                            bot_username = os.getenv("BOT_USERNAME", "")
                            link = f"https://t.me/{bot_username}?start=ref_{row['referral_code']}" if bot_username else f"Referral Code: `{row['referral_code']}`"
                            send_message(chat_id, f"🎁 *Your Referral Shield*\n\nInvite friends using this link — you earn `+{XP_REFERRAL_BONUS} XP` per join:\n{link}")
                            continue

                        elif text.startswith("/setrole"):
                            if not role_at_least(user_id, "admin"):
                                send_message(chat_id, "Permission denied. Admins/Owner only.")
                                continue
                            parts = text.replace("/setrole", "").strip().split()
                            if len(parts) != 2 or not parts[0].lstrip("-").isdigit() or parts[1].lower() not in ["student", "moderator", "admin", "owner"]:
                                send_message(chat_id, "Usage: `/setrole <user_id> <student|moderator|admin|owner>`")
                                continue
                            if parts[1].lower() == "owner" and user_id != OWNER_ID:
                                send_message(chat_id, "Only the Owner can grant the Owner role.")
                                continue
                            set_role(int(parts[0]), parts[1].lower(), user_id)
                            send_message(chat_id, f"✅ Role for `{parts[0]}` set to `{parts[1].lower()}`.")
                            continue

                        elif text.startswith("/audit"):
                            if not role_at_least(user_id, "admin"):
                                send_message(chat_id, "Permission denied. Admins/Owner only.")
                                continue
                            conn = get_db()
                            rows = conn.execute("SELECT * FROM audit_logs ORDER BY log_id DESC LIMIT 15").fetchall()
                            conn.close()
                            if not rows:
                                send_message(chat_id, "No audit log entries yet.")
                                continue
                            lines = ["📜 *RECENT AUDIT LOG*", "────────────────────────"]
                            for r in rows:
                                lines.append(f"`{r['timestamp']}` — {r['action_type']} — target:`{r['target_user_id']}` by:`{r['admin_id']}`\n_{r['reason']}_")
                            send_message(chat_id, "\n".join(lines))
                            continue

                        if text.startswith("/start"):
                            payload = text.replace("/start", "").strip()
                            if payload.startswith("ref_"):
                                process_referral(user_id, payload.replace("ref_", "").strip())
                            welcome_msg = (
                                "🦅 *Welcome to CA Vault Quiz Engine*\n\n"
                                "⚡ High-yield, AI-generated practice quizzes for CA Foundation.\n\n"
                                "Tap below to open the control menu 👇"
                            )
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "📖 Open Help Menu", "callback_data": "show_help_menu"}]
                                ]
                            }
                            send_message(chat_id, welcome_msg, reply_markup=keyboard)

                        elif text.startswith("/help"):
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Schedule Wizard (DM)", "callback_data": "sched_wiz_start"}]
                                ]
                            }
                            send_message(chat_id, get_help_text(), reply_markup=keyboard)

                        elif text.startswith("/myid"):
                            send_message(chat_id, f"Chat ID: `{chat_id}`")

                        elif text == "/stopquiz":
                            if is_user_admin_owner_or_anonymous(message):
                                if active_quiz_sessions.get(chat_id, False):
                                    active_quiz_sessions[chat_id] = False
                                    send_message(chat_id, "Stopping active quiz...")
                                else:
                                    send_message(chat_id, "No active quiz running.")
                            else:
                                send_message(chat_id, "Permission denied.")

                        elif text == "/myschedules":
                            if is_group_chat(chat_id):
                                send_message(chat_id, "Please use `/myschedules` in Bot DM.")
                                continue
                            my_jobs = [j for j in scheduled_quizzes if j.get("conductor_id") == user_id]
                            if not my_jobs:
                                send_message(chat_id, "You have no upcoming scheduled quizzes.")
                                continue
                            my_jobs_sorted = sorted(my_jobs, key=lambda j: j["datetime"])[:20]
                            lines = ["📅 *YOUR UPCOMING SCHEDULED QUIZZES*", "────────────────────────"]
                            for j in my_jobs_sorted:
                                try:
                                    dt_disp = datetime.strptime(j["datetime"], "%Y-%m-%d %H:%M").strftime("%Y-%m-%d, %I:%M %p")
                                except Exception:
                                    dt_disp = j["datetime"]
                                lines.append(f"🕐 `{dt_disp}` — 📘 {j['subject']} ({j.get('chapter') or 'Full Syllabus'}) — 🔢 {j['count']} Qs")
                            if len(my_jobs) > 20:
                                lines.append(f"...and {len(my_jobs) - 20} more.")
                            send_message(chat_id, "\n".join(lines))

                        elif text.startswith("/quiz"):
                            if not is_group_chat(chat_id):
                                send_message(chat_id, "Live quizzes can only run inside Telegram Groups.\nLink your group using `/link_group <GroupID>` and use `/schedule` in DM.")
                                continue

                            if not is_user_admin_owner_or_anonymous(message):
                                send_message(chat_id, "Permission denied. Only Admins or Owners can start quizzes.")
                                continue

                            quiz_builder_state[chat_id] = {"subject": "Accounts", "chapter": "", "subtopics": "", "level": "EXTREME_HIGH", "break_freq": 0, "break_duration": 0, "conductor_id": user_id}
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Accounts", "callback_data": "sub_Accounts"}],
                                    [{"text": "Business Laws", "callback_data": "sub_Business Laws"}],
                                    [{"text": "Quantitative Aptitude", "callback_data": "sub_Quantitative Aptitude"}],
                                    [{"text": "Economics", "callback_data": "sub_Economics"}]
                                ]
                            }
                            send_message(chat_id, "*Step 1:* Select Subject", reply_markup=keyboard)

                        elif text.startswith("/customcount_sched"):
                            if user_id in schedule_wizard_state:
                                raw = text.replace("/customcount_sched", "").strip()
                                if raw.isdigit() and int(raw) > 0:
                                    schedule_wizard_state[user_id]["count"] = int(raw)
                                    st = schedule_wizard_state[user_id]
                                    summary = get_wizard_summary(st)
                                    keyboard = build_timer_keyboard("swiz_tmr_", "swiz_back_to_cnt")
                                    send_message(chat_id, f"{summary}Questions set to `{raw}`.\n\n*Step:* Select Timer per Question", reply_markup=keyboard)
                                else:
                                    send_message(chat_id, "Invalid number. Use: `/customcount_sched 25`")

                        elif text.startswith("/customtimer_sched"):
                            if user_id in schedule_wizard_state:
                                raw = text.replace("/customtimer_sched", "").strip()
                                if raw.isdigit() and int(raw) > 0:
                                    finalize_schedule_wizard(chat_id, user_id, int(raw))
                                else:
                                    send_message(chat_id, "Invalid number. Use: `/customtimer_sched 40` (seconds)")

                        elif text.startswith("/customcount"):
                            if chat_id in quiz_builder_state:
                                raw = text.replace("/customcount", "").strip()
                                if raw.isdigit() and int(raw) > 0:
                                    quiz_builder_state[chat_id]["count"] = int(raw)
                                    keyboard = {
                                        "inline_keyboard": [
                                            [{"text": "No Breaks", "callback_data": "break_none"}],
                                            [{"text": "Every 20 Qs (5 min)", "callback_data": "break_20_5"}],
                                            [{"text": "Every 30 Qs (10 min)", "callback_data": "break_30_10"}],
                                            [{"text": "Back", "callback_data": "lvl_EXTREME_HIGH"}]
                                        ]
                                    }
                                    send_message(chat_id, f"Questions set to `{raw}`.\n\n*Step:* Select Break Setting", reply_markup=keyboard)
                                else:
                                    send_message(chat_id, "Invalid number. Use: `/customcount 25`")

                        elif text.startswith("/customtimer"):
                            if chat_id in quiz_builder_state:
                                raw = text.replace("/customtimer", "").strip()
                                if raw.isdigit() and int(raw) > 0:
                                    state = quiz_builder_state.get(chat_id, {})
                                    subj = state.get("subject", "Accounts")
                                    chap = state.get("chapter", "")
                                    subtop = state.get("subtopics", "")
                                    cnt = state.get("count", 10)
                                    bf = state.get("break_freq", 0)
                                    bd = state.get("break_duration", 0)
                                    lvl = state.get("level", "EXTREME_HIGH")
                                    cond_id = state.get("conductor_id")
                                    tmr = int(raw)
                                    send_message(chat_id, f"*Starting Quiz...*\n\nSubject: `{subj}`\nQuestions: `{cnt}`\nTimer: `{tmr}s`")
                                    threading.Thread(target=run_quiz_session, args=(chat_id, subj, chap, cnt, tmr, bf, bd, lvl, cond_id, subtop), daemon=True).start()
                                else:
                                    send_message(chat_id, "Invalid number. Use: `/customtimer 40` (seconds)")

                        elif text.startswith("/chapter_only"):
                            target_chat_id = chat_id
                            chap_val = text.replace("/chapter_only", "").strip()

                            if text.startswith("/chapter_only_sched"):
                                chap_val = text.replace("/chapter_only_sched", "").strip()
                                schedule_wizard_state[user_id]["chapter"] = chap_val
                                schedule_wizard_state[user_id]["subtopics"] = ""
                                st = schedule_wizard_state[user_id]
                                summary = get_wizard_summary(st)

                                keyboard = {
                                    "inline_keyboard": [
                                        [{"text": "MEDIUM", "callback_data": "swiz_lvl_MEDIUM"}],
                                        [{"text": "HIGH", "callback_data": "swiz_lvl_HIGH"}],
                                        [{"text": "EXTREME HIGH", "callback_data": "swiz_lvl_EXTREME_HIGH"}],
                                        [{"text": "Back", "callback_data": "swiz_back_to_chap_choice"}]
                                    ]
                                }
                                send_message(chat_id, f"{summary}\n*Step 3:* Select Starting Difficulty Level", reply_markup=keyboard)
                            else:
                                if target_chat_id in quiz_builder_state:
                                    quiz_builder_state[target_chat_id]["chapter"] = chap_val
                                    quiz_builder_state[target_chat_id]["subtopics"] = ""
                                    keyboard = {
                                        "inline_keyboard": [
                                            [{"text": "MEDIUM", "callback_data": "lvl_MEDIUM"}],
                                            [{"text": "HIGH", "callback_data": "lvl_HIGH"}],
                                            [{"text": "EXTREME HIGH", "callback_data": "lvl_EXTREME_HIGH"}],
                                            [{"text": "Back", "callback_data": "back_to_chap_choice"}]
                                        ]
                                    }
                                    send_message(target_chat_id, f"Chapter set: `{chap_val}`\n\n*Step 3:* Select Difficulty Level", reply_markup=keyboard)

                        elif text.startswith("/chapter"):
                            target_chat_id = chat_id
                            if text.startswith("/chapter_sched"):
                                raw_input = text.replace("/chapter_sched", "").strip()
                                parts = raw_input.split("|")
                                chap_val = parts[0].strip()
                                subtopic_val = parts[1].strip() if len(parts) > 1 else ""

                                schedule_wizard_state[user_id]["chapter"] = chap_val
                                schedule_wizard_state[user_id]["subtopics"] = subtopic_val
                                st = schedule_wizard_state[user_id]
                                summary = get_wizard_summary(st)

                                keyboard = {
                                    "inline_keyboard": [
                                        [{"text": "MEDIUM", "callback_data": "swiz_lvl_MEDIUM"}],
                                        [{"text": "HIGH", "callback_data": "swiz_lvl_HIGH"}],
                                        [{"text": "EXTREME HIGH", "callback_data": "swiz_lvl_EXTREME_HIGH"}],
                                        [{"text": "Back", "callback_data": "swiz_back_to_chap_choice"}]
                                    ]
                                }
                                send_message(chat_id, f"{summary}\n*Step 3:* Select Difficulty Level", reply_markup=keyboard)
                            else:
                                raw_input = text.replace("/chapter", "").strip()
                                parts = raw_input.split("|")
                                chap_val = parts[0].strip()
                                subtopic_val = parts[1].strip() if len(parts) > 1 else ""

                                if target_chat_id in quiz_builder_state:
                                    quiz_builder_state[target_chat_id]["chapter"] = chap_val
                                    quiz_builder_state[target_chat_id]["subtopics"] = subtopic_val

                                    keyboard = {
                                        "inline_keyboard": [
                                            [{"text": "MEDIUM", "callback_data": "lvl_MEDIUM"}],
                                            [{"text": "HIGH", "callback_data": "lvl_HIGH"}],
                                            [{"text": "EXTREME HIGH", "callback_data": "lvl_EXTREME_HIGH"}],
                                            [{"text": "Back", "callback_data": "back_to_chap_choice"}]
                                        ]
                                    }
                                    send_message(target_chat_id, f"Chapter set: `{chap_val}`\nSub-topics: `{subtopic_val or 'All'}`\n\n*Step 3:* Select Difficulty Level", reply_markup=keyboard)

                        elif text.startswith("/link_group"):
                            if is_group_chat(chat_id):
                                send_message(chat_id, "Send `/link_group` in Bot DM.")
                                continue

                            try:
                                target_group_id = int(text.replace("/link_group", "").strip())
                                user_linked_groups[user_id] = target_group_id
                                if target_group_id not in group_reminder_time:
                                    group_reminder_time[target_group_id] = "08:00"
                                save_persisted_data()
                                send_message(chat_id, f"✅ *Group Linked Successfully*\n\n📌 Group ID: `{target_group_id}`\n⏰ Daily \"Today's Quiz\" reminder: `08:00 AM` (change with `/reminder`)\n\nThis link is saved permanently — you will not need to link again. Type `/schedule` any time to open the scheduler wizard.")
                            except Exception:
                                send_message(chat_id, "⚠️ Invalid format.\nUse: `/link_group -100123456789`\n\n(Tip: send `/myid` in the group to copy its Group ID)")

                        elif text == "/reminder":
                            if is_group_chat(chat_id):
                                send_message(chat_id, "Please use `/reminder` in Bot DM.")
                                continue
                            if user_id not in user_linked_groups:
                                send_message(chat_id, "⚠️ No group linked yet.\nFirst send: `/link_group <GroupID>`")
                                continue
                            grp = user_linked_groups[user_id]
                            current = group_reminder_time.get(grp, "08:00")
                            current_disp = datetime.strptime(current, "%H:%M").strftime("%I:%M %p")
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "07:00 AM", "callback_data": "rem_07:00"}, {"text": "08:00 AM", "callback_data": "rem_08:00"}],
                                    [{"text": "09:00 AM", "callback_data": "rem_09:00"}, {"text": "06:00 PM", "callback_data": "rem_18:00"}],
                                    [{"text": "Custom (type it)", "callback_data": "rem_custom_prompt"}]
                                ]
                            }
                            send_message(
                                chat_id,
                                f"⏰ *DAILY \"TODAY'S QUIZ\" REMINDER*\n────────────────────────\n📌 Group: `{grp}`\n🕐 Current Time: `{current_disp}`\n\n"
                                f"Every day at this time, if a quiz is scheduled for that day, the bot posts a \"Today's Quiz\" announcement in your group with subject, question count & time.\n\n"
                                f"Choose a new time:",
                                reply_markup=keyboard
                            )

                        elif text.startswith("/setreminder_custom"):
                            if user_id in user_linked_groups:
                                raw = text.replace("/setreminder_custom", "").strip().upper()
                                try:
                                    t_obj = datetime.strptime(raw, "%I:%M %p")
                                    grp = user_linked_groups[user_id]
                                    group_reminder_time[grp] = t_obj.strftime("%H:%M")
                                    save_persisted_data()
                                    send_message(chat_id, f"✅ Daily reminder time updated to `{t_obj.strftime('%I:%M %p')}` for group `{grp}`.")
                                except Exception:
                                    send_message(chat_id, "⚠️ Invalid format. Use: `/setreminder_custom 08:30 AM`")
                            else:
                                send_message(chat_id, "⚠️ No group linked yet.\nFirst send: `/link_group <GroupID>`")

                        elif text == "/schedule":
                            if is_group_chat(chat_id):
                                send_message(chat_id, "Please use `/schedule` in Bot DM.")
                                continue

                            if user_id not in user_linked_groups:
                                send_message(chat_id, "No group linked yet.\nFirst send: `/link_group <GroupID>`")
                                continue

                            schedule_wizard_state[user_id] = {"group_id": user_linked_groups[user_id]}
                            st = schedule_wizard_state[user_id]
                            summary = get_wizard_summary(st)

                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Accounts", "callback_data": "swiz_sub_Accounts"}],
                                    [{"text": "Business Laws", "callback_data": "swiz_sub_Business Laws"}],
                                    [{"text": "Quantitative Aptitude", "callback_data": "swiz_sub_Quantitative Aptitude"}],
                                    [{"text": "Economics", "callback_data": "swiz_sub_Economics"}]
                                ]
                            }
                            send_message(chat_id, f"{summary}*SCHEDULER WIZARD*\n\n*Step 1:* Select Subject", reply_markup=keyboard)

                        elif text.startswith("/setschedule"):
                            if user_id in schedule_wizard_state:
                                raw = text.replace("/setschedule", "").strip()
                                try:
                                    parts = raw.split("|")
                                    date_part = parts[0].strip()
                                    time_part = parts[1].strip().upper()
                                    dt_obj = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %I:%M %p")
                                    if dt_obj < datetime.now():
                                        send_message(chat_id, "That date/time is in the past. Please pick a future date & time.")
                                        continue
                                    schedule_wizard_state[user_id]["custom_datetime"] = dt_obj.strftime("%Y-%m-%d %H:%M")
                                    schedule_wizard_state[user_id]["display_datetime"] = dt_obj.strftime("%Y-%m-%d, %I:%M %p")
                                    schedule_wizard_state[user_id]["schedule_mode"] = "onetime"
                                    st = schedule_wizard_state[user_id]
                                    summary = get_wizard_summary(st)
                                    keyboard = build_count_keyboard("swiz_cnt_", "swiz_mode_onetime")
                                    send_message(chat_id, f"{summary}Date & Time set: `{st['display_datetime']}`\n\n*Step 5:* Select Question Count", reply_markup=keyboard)
                                except Exception:
                                    send_message(chat_id, "Invalid format.\nUse: `/setschedule YYYY-MM-DD | hh:mm AM/PM`\nExample: `/setschedule 2026-08-10 | 06:30 PM`")
                            else:
                                send_message(chat_id, "Start the wizard first with `/schedule`.")

                        elif text.startswith("/slots"):
                            if user_id in schedule_wizard_state:
                                slots_val = text.replace("/slots", "").strip()
                                slots_list = [s.strip() for s in slots_val.split(",") if s.strip()]
                                schedule_wizard_state[user_id]["slots"] = slots_list
                                schedule_wizard_state[user_id]["schedule_mode"] = "recurring"
                                st = schedule_wizard_state[user_id]
                                summary = get_wizard_summary(st)

                                keyboard = build_count_keyboard("swiz_cnt_", "swiz_back_to_lvl")
                                send_message(chat_id, f"{summary}\n*Step 5:* Select Question Count per Quiz", reply_markup=keyboard)

                    elif "callback_query" in result:
                        query = result["callback_query"]
                        query_chat_id = query["message"]["chat"]["id"]
                        message_id = query["message"]["message_id"]
                        data_cb = query["data"]
                        cb_user_id = query.get("from", {}).get("id", query_chat_id)

                        requests.post(f"{BASE_URL}/answerCallbackQuery", json={"callback_query_id": query["id"]}, timeout=5)

                        if data_cb == "show_help_menu":
                            edit_message(query_chat_id, message_id, get_help_text())

                        elif data_cb == "fsub_recheck":
                            if is_force_sub_member(cb_user_id):
                                edit_message(query_chat_id, message_id, "✅ Verified! You now have full access. Send /start to open the menu.")
                            else:
                                send_message(query_chat_id, "⚠️ Still not detected as a member. Please join the channel first.")

                        elif data_cb.startswith("abuse_"):
                            if cb_user_id != OWNER_ID:
                                continue
                            try:
                                _, action, grp_id_str, target_id_str = data_cb.split("_", 3)
                            except ValueError:
                                continue
                            grp_id, target_id = int(grp_id_str), int(target_id_str)
                            if action == "unmute":
                                unrestrict_user(grp_id, target_id)
                                log_audit(OWNER_ID, target_id, "unmute", "owner approved unmute")
                                edit_message(query_chat_id, message_id, f"✅ User `{target_id}` unmuted in group `{grp_id}`.")
                            elif action == "mute24":
                                restrict_user(grp_id, target_id, seconds=MUTE_24H_SECONDS)
                                log_audit(OWNER_ID, target_id, "mute_24h", "owner approved 24h mute")
                                edit_message(query_chat_id, message_id, f"🔇 User `{target_id}` muted for 24h in group `{grp_id}`.")
                            elif action == "block":
                                ban_user(grp_id, target_id)
                                log_audit(OWNER_ID, target_id, "block", "owner approved permanent block")
                                edit_message(query_chat_id, message_id, f"⛔ User `{target_id}` blocked from group `{grp_id}`.")

                        elif data_cb == "rem_custom_prompt":
                            edit_message(query_chat_id, message_id, "Send the exact reminder time as a command:\n`/setreminder_custom 08:30 AM`")

                        elif data_cb.startswith("rem_"):
                            time_val = data_cb.split("rem_")[1]
                            grp = user_linked_groups.get(cb_user_id)
                            if grp:
                                group_reminder_time[grp] = time_val
                                save_persisted_data()
                                disp = datetime.strptime(time_val, "%H:%M").strftime("%I:%M %p")
                                edit_message(query_chat_id, message_id, f"✅ Daily reminder time set to `{disp}` for group `{grp}`.\n\nThe bot will post \"Today's Quiz\" there each day at this time, whenever a quiz is scheduled.")
                            else:
                                edit_message(query_chat_id, message_id, "⚠️ No group linked. Send `/link_group <GroupID>` first.")

                        # --- LIVE QUIZ BUILDER BACK NAVIGATION & FLOW ---
                        elif data_cb == "start_interactive_quiz":
                            quiz_builder_state[query_chat_id] = {"subject": "Accounts", "chapter": "", "subtopics": "", "level": "EXTREME_HIGH", "break_freq": 0, "break_duration": 0, "conductor_id": query_chat_id}
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Accounts", "callback_data": "sub_Accounts"}],
                                    [{"text": "Business Laws", "callback_data": "sub_Business Laws"}],
                                    [{"text": "Quantitative Aptitude", "callback_data": "sub_Quantitative Aptitude"}],
                                    [{"text": "Economics", "callback_data": "sub_Economics"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "*Step 1:* Select Subject", reply_markup=keyboard)

                        elif data_cb.startswith("sub_"):
                            subj = data_cb.split("_", 1)[1]
                            quiz_builder_state[query_chat_id]["subject"] = subj
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Full Subject (Skip)", "callback_data": "chap_skip"}],
                                    [{"text": "Full Chapter Only", "callback_data": "chap_only_prompt"}],
                                    [{"text": "Chapter + Sub-topics", "callback_data": "chap_custom"}],
                                    [{"text": "Back", "callback_data": "start_interactive_quiz"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"Subject: *{subj}*\n\n*Step 2:* Choose Quiz Scope", reply_markup=keyboard)

                        elif data_cb == "back_to_chap_choice":
                            subj = quiz_builder_state.get(query_chat_id, {}).get("subject", "Accounts")
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Full Subject (Skip)", "callback_data": "chap_skip"}],
                                    [{"text": "Full Chapter Only", "callback_data": "chap_only_prompt"}],
                                    [{"text": "Chapter + Sub-topics", "callback_data": "chap_custom"}],
                                    [{"text": "Back", "callback_data": "start_interactive_quiz"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"Subject: *{subj}*\n\n*Step 2:* Choose Quiz Scope", reply_markup=keyboard)

                        elif data_cb == "chap_only_prompt":
                            edit_message(query_chat_id, message_id, "Send command for full chapter:\n`/chapter_only [Chapter Name]`")

                        elif data_cb == "chap_custom":
                            edit_message(query_chat_id, message_id, "Send command for chapter + sub-topics:\n`/chapter Chapter Name | Subtopic 1, Subtopic 2`")

                        elif data_cb == "chap_skip":
                            quiz_builder_state[query_chat_id]["chapter"] = ""
                            quiz_builder_state[query_chat_id]["subtopics"] = ""
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "MEDIUM", "callback_data": "lvl_MEDIUM"}],
                                    [{"text": "HIGH", "callback_data": "lvl_HIGH"}],
                                    [{"text": "EXTREME HIGH", "callback_data": "lvl_EXTREME_HIGH"}],
                                    [{"text": "Back", "callback_data": "back_to_chap_choice"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "*Step 3:* Select Starting Difficulty Level", reply_markup=keyboard)

                        elif data_cb.startswith("lvl_"):
                            lvl = data_cb.split("lvl_")[1]
                            quiz_builder_state[query_chat_id]["level"] = lvl
                            keyboard = build_count_keyboard("cnt_", "chap_skip")
                            edit_message(query_chat_id, message_id, f"Difficulty: *{lvl}*\n\n*Step 4:* Select Question Count (or type `/customcount N`)", reply_markup=keyboard)

                        elif data_cb == "cnt_custom_prompt":
                            edit_message(query_chat_id, message_id, "Send the exact question count as a command:\n`/customcount 25`")

                        elif data_cb.startswith("cnt_"):
                            cnt = int(data_cb.split("_")[1])
                            quiz_builder_state[query_chat_id]["count"] = cnt
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "No Breaks", "callback_data": "break_none"}],
                                    [{"text": "Every 20 Qs (5 min)", "callback_data": "break_20_5"}],
                                    [{"text": "Every 30 Qs (10 min)", "callback_data": "break_30_10"}],
                                    [{"text": "Back", "callback_data": "lvl_EXTREME_HIGH"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"Questions: *{cnt}*\n\n*Step 5:* Select Break Setting", reply_markup=keyboard)

                        elif data_cb == "break_none":
                            quiz_builder_state[query_chat_id]["break_freq"] = 0
                            quiz_builder_state[query_chat_id]["break_duration"] = 0
                            keyboard = build_timer_keyboard("timer_", "cnt_10")
                            edit_message(query_chat_id, message_id, "Mode: *Non-stop*\n\n*Step 6:* Select Timer per Question (or type `/customtimer N`)", reply_markup=keyboard)

                        elif data_cb == "break_20_5":
                            quiz_builder_state[query_chat_id]["break_freq"] = 20
                            quiz_builder_state[query_chat_id]["break_duration"] = 300
                            keyboard = build_timer_keyboard("timer_", "cnt_10")
                            edit_message(query_chat_id, message_id, "Break: *Every 20 Qs (5 min)*\n\n*Step 6:* Select Timer per Question (or type `/customtimer N`)", reply_markup=keyboard)

                        elif data_cb == "break_30_10":
                            quiz_builder_state[query_chat_id]["break_freq"] = 30
                            quiz_builder_state[query_chat_id]["break_duration"] = 600
                            keyboard = build_timer_keyboard("timer_", "cnt_10")
                            edit_message(query_chat_id, message_id, "Break: *Every 30 Qs (10 min)*\n\n*Step 6:* Select Timer per Question (or type `/customtimer N`)", reply_markup=keyboard)

                        elif data_cb == "timer_custom_prompt":
                            edit_message(query_chat_id, message_id, "Send the exact timer (seconds) as a command:\n`/customtimer 40`")

                        elif data_cb.startswith("timer_"):
                            tmr = int(data_cb.split("_")[1])
                            state = quiz_builder_state.get(query_chat_id, {})
                            subj = state.get("subject", "Accounts")
                            chap = state.get("chapter", "")
                            subtop = state.get("subtopics", "")
                            cnt = state.get("count", 10)
                            bf = state.get("break_freq", 0)
                            bd = state.get("break_duration", 0)
                            lvl = state.get("level", "EXTREME_HIGH")
                            cond_id = state.get("conductor_id")

                            edit_message(query_chat_id, message_id, f"*Starting Quiz...*\n\nSubject: `{subj}`\nQuestions: `{cnt}`\nTimer: `{tmr}s`")
                            threading.Thread(target=run_quiz_session, args=(query_chat_id, subj, chap, cnt, tmr, bf, bd, lvl, cond_id, subtop), daemon=True).start()

                        # --- SCHEDULER WIZARD WITH FULL BACK NAVIGATION & SCOPE DISPLAY ---
                        elif data_cb == "sched_wiz_start":
                            if cb_user_id not in user_linked_groups:
                                edit_message(query_chat_id, message_id, "No group linked.\nFirst send: `/link_group <GroupID>`")
                                continue
                            schedule_wizard_state[cb_user_id] = {"group_id": user_linked_groups[cb_user_id]}
                            st = schedule_wizard_state[cb_user_id]
                            summary = get_wizard_summary(st)

                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Accounts", "callback_data": "swiz_sub_Accounts"}],
                                    [{"text": "Business Laws", "callback_data": "swiz_sub_Business Laws"}],
                                    [{"text": "Quantitative Aptitude", "callback_data": "swiz_sub_Quantitative Aptitude"}],
                                    [{"text": "Economics", "callback_data": "swiz_sub_Economics"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"{summary}*SCHEDULER WIZARD*\n\n*Step 1:* Select Subject", reply_markup=keyboard)

                        elif data_cb.startswith("swiz_sub_"):
                            subj = data_cb.split("swiz_sub_")[1]
                            schedule_wizard_state[cb_user_id]["subject"] = subj
                            st = schedule_wizard_state[cb_user_id]
                            summary = get_wizard_summary(st)

                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Full Subject (Skip)", "callback_data": "swiz_chap_skip"}],
                                    [{"text": "Full Chapter Only", "callback_data": "swiz_chap_only_prompt"}],
                                    [{"text": "Chapter + Sub-topics", "callback_data": "swiz_chap_custom"}],
                                    [{"text": "Back", "callback_data": "sched_wiz_start"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"{summary}*Step 2:* Choose Scope", reply_markup=keyboard)

                        elif data_cb == "swiz_back_to_chap_choice":
                            st = schedule_wizard_state.get(cb_user_id, {})
                            summary = get_wizard_summary(st)
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Full Subject (Skip)", "callback_data": "swiz_chap_skip"}],
                                    [{"text": "Full Chapter Only", "callback_data": "swiz_chap_only_prompt"}],
                                    [{"text": "Chapter + Sub-topics", "callback_data": "swiz_chap_custom"}],
                                    [{"text": "Back", "callback_data": "sched_wiz_start"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"{summary}*Step 2:* Choose Scope", reply_markup=keyboard)

                        elif data_cb == "swiz_chap_only_prompt":
                            edit_message(query_chat_id, message_id, "Send command for full chapter:\n`/chapter_only_sched [Chapter Name]`")

                        elif data_cb == "swiz_chap_custom":
                            edit_message(query_chat_id, message_id, "Send command for chapter & sub-topics:\n`/chapter_sched Chapter Name | Subtopic 1, Subtopic 2`")

                        elif data_cb == "swiz_chap_skip":
                            schedule_wizard_state[cb_user_id]["chapter"] = ""
                            schedule_wizard_state[cb_user_id]["subtopics"] = ""
                            st = schedule_wizard_state[cb_user_id]
                            summary = get_wizard_summary(st)

                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "MEDIUM", "callback_data": "swiz_lvl_MEDIUM"}],
                                    [{"text": "HIGH", "callback_data": "swiz_lvl_HIGH"}],
                                    [{"text": "EXTREME HIGH", "callback_data": "swiz_lvl_EXTREME_HIGH"}],
                                    [{"text": "Back", "callback_data": "swiz_back_to_chap_choice"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"{summary}*Step 3:* Select Starting Difficulty Level", reply_markup=keyboard)

                        elif data_cb.startswith("swiz_lvl_"):
                            lvl = data_cb.split("swiz_lvl_")[1]
                            schedule_wizard_state[cb_user_id]["level"] = lvl
                            st = schedule_wizard_state[cb_user_id]
                            summary = get_wizard_summary(st)

                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "One-Time Custom Date & Time", "callback_data": "swiz_mode_onetime"}],
                                    [{"text": "Recurring Daily Slots", "callback_data": "swiz_mode_recurring"}],
                                    [{"text": "Back", "callback_data": "swiz_chap_skip"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"{summary}*Step 4:* Choose Scheduling Mode", reply_markup=keyboard)

                        elif data_cb == "swiz_mode_onetime":
                            schedule_wizard_state[cb_user_id]["schedule_mode"] = "onetime"
                            st = schedule_wizard_state[cb_user_id]
                            summary = get_wizard_summary(st)
                            edit_message(
                                query_chat_id, message_id,
                                f"{summary}*Step 4:* Send the exact date & time (24h date, 12h time with AM/PM):\n\n"
                                f"`/setschedule YYYY-MM-DD | hh:mm AM/PM`\n\n"
                                f"Example: `/setschedule 2026-08-10 | 06:30 PM`"
                            )

                        elif data_cb == "swiz_mode_recurring":
                            schedule_wizard_state[cb_user_id]["schedule_mode"] = "recurring"
                            st = schedule_wizard_state[cb_user_id]
                            summary = get_wizard_summary(st)
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "09:00 AM, 03:00 PM, 09:00 PM", "callback_data": "slot_preset_1"}],
                                    [{"text": "10:00 AM, 02:00 PM, 06:00 PM, 10:00 PM", "callback_data": "slot_preset_2"}],
                                    [{"text": "Custom Slots (type it)", "callback_data": "slot_custom"}],
                                    [{"text": "Back", "callback_data": "swiz_back_to_lvl"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"{summary}*Step 4:* Choose Daily Time Slots (repeats for next 30 days)", reply_markup=keyboard)

                        elif data_cb == "swiz_back_to_lvl":
                            st = schedule_wizard_state.get(cb_user_id, {})
                            summary = get_wizard_summary(st)
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "MEDIUM", "callback_data": "swiz_lvl_MEDIUM"}],
                                    [{"text": "HIGH", "callback_data": "swiz_lvl_HIGH"}],
                                    [{"text": "EXTREME HIGH", "callback_data": "swiz_lvl_EXTREME_HIGH"}],
                                    [{"text": "Back", "callback_data": "swiz_back_to_chap_choice"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"{summary}*Step 3:* Select Starting Difficulty Level", reply_markup=keyboard)

                        elif data_cb == "slot_preset_1":
                            schedule_wizard_state[cb_user_id]["slots"] = ["09:00", "15:00", "21:00"]
                            st = schedule_wizard_state[cb_user_id]
                            summary = get_wizard_summary(st)
                            keyboard = build_count_keyboard("swiz_cnt_", "swiz_mode_recurring")
                            edit_message(query_chat_id, message_id, f"{summary}*Step 5:* Select Question Count", reply_markup=keyboard)

                        elif data_cb == "slot_preset_2":
                            schedule_wizard_state[cb_user_id]["slots"] = ["10:00", "14:00", "18:00", "22:00"]
                            st = schedule_wizard_state[cb_user_id]
                            summary = get_wizard_summary(st)
                            keyboard = build_count_keyboard("swiz_cnt_", "swiz_mode_recurring")
                            edit_message(query_chat_id, message_id, f"{summary}*Step 5:* Select Question Count", reply_markup=keyboard)

                        elif data_cb == "slot_custom":
                            edit_message(query_chat_id, message_id, "Send command for custom daily slots (24h time, comma separated):\n`/slots 09:00, 13:00, 18:00, 21:00`")

                        elif data_cb == "swiz_cnt_custom_prompt":
                            mode = schedule_wizard_state.get(cb_user_id, {}).get("schedule_mode")
                            cmd = "/customcount_sched 25" if mode else "/customcount_sched 25"
                            edit_message(query_chat_id, message_id, f"Send the exact question count as a command:\n`{cmd}`")

                        elif data_cb.startswith("swiz_cnt_"):
                            cnt = int(data_cb.split("swiz_cnt_")[1])
                            schedule_wizard_state[cb_user_id]["count"] = cnt
                            st = schedule_wizard_state[cb_user_id]
                            summary = get_wizard_summary(st)

                            back_cb = "swiz_mode_onetime" if st.get("schedule_mode") == "onetime" else "swiz_back_to_lvl"
                            keyboard = build_timer_keyboard("swiz_tmr_", back_cb)
                            edit_message(query_chat_id, message_id, f"{summary}*Step 6:* Select Timer per Question", reply_markup=keyboard)

                        elif data_cb == "swiz_back_to_cnt":
                            st = schedule_wizard_state.get(cb_user_id, {})
                            summary = get_wizard_summary(st)
                            keyboard = build_count_keyboard("swiz_cnt_", "swiz_back_to_lvl")
                            edit_message(query_chat_id, message_id, f"{summary}*Step 5:* Select Question Count", reply_markup=keyboard)

                        elif data_cb == "swiz_tmr_custom_prompt":
                            edit_message(query_chat_id, message_id, "Send the exact timer (seconds) as a command:\n`/customtimer_sched 40`")

                        elif data_cb.startswith("swiz_tmr_"):
                            tmr = int(data_cb.split("swiz_tmr_")[1])
                            finalize_schedule_wizard(query_chat_id, cb_user_id, tmr, message_id=message_id)

        except Exception as e:
            time.sleep(2)


def finalize_schedule_wizard(chat_id, user_id, tmr, message_id=None):
    """Shared finalizer for both one-time and recurring schedule modes."""
    st = schedule_wizard_state.get(user_id, {})
    target_grp = st.get("group_id")
    subj = st.get("subject", "Accounts")
    chap = st.get("chapter", "")
    subtop = st.get("subtopics", "")
    lvl = st.get("level", "EXTREME_HIGH")
    cnt = st.get("count", 10)
    mode = st.get("schedule_mode", "recurring")

    chap_text = chap if chap else "Full Subject Syllabus"
    subtop_text = f"\nSubtopics: `{subtop}`" if subtop else ""

    if target_grp not in group_reminder_time:
        group_reminder_time[target_grp] = "08:00"

    if mode == "onetime":
        run_dt = st.get("custom_datetime")
        if not run_dt:
            send_message(chat_id, "Missing date/time. Please send `/setschedule YYYY-MM-DD | hh:mm AM/PM` again.")
            return
        scheduled_quizzes.append({
            "chat_id": target_grp,
            "datetime": run_dt,
            "subject": subj,
            "chapter": chap,
            "subtopics": subtop,
            "count": cnt,
            "timer": tmr,
            "level": lvl,
            "conductor_id": user_id
        })
        save_persisted_data()
        schedule_line = f"Date & Time: `{st.get('display_datetime')}`"
        announcement_schedule_line = f"Date & Time: `{st.get('display_datetime')}`"
    else:
        slots = st.get("slots", ["09:00", "15:00", "21:00"])
        today = datetime.now()
        for day in range(30):
            f_date = (today + timedelta(days=day)).strftime("%Y-%m-%d")
            for slot in slots:
                scheduled_quizzes.append({
                    "chat_id": target_grp,
                    "datetime": f"{f_date} {slot}",
                    "subject": subj,
                    "chapter": chap,
                    "subtopics": subtop,
                    "count": cnt,
                    "timer": tmr,
                    "level": lvl,
                    "conductor_id": user_id
                })
        save_persisted_data()
        schedule_line = f"Daily Slots (next 30 days): `{', '.join(slots)}`"
        announcement_schedule_line = f"Daily Time Slots: `{', '.join(slots)}`"

    announcement_text = (
        f"📢 *SCHEDULED QUIZ ANNOUNCEMENT*\n"
        f"────────────────────────\n"
        f"📘 Subject: `{subj}`\n"
        f"📖 Scope: `{chap_text}`{subtop_text}\n"
        f"{announcement_schedule_line}\n"
        f"🔢 Questions/Quiz: `{cnt}`  |  ⏱ Timer: `{tmr}s`\n"
        f"────────────────────────\n"
        f"🚀 Quizzes will start automatically at the scheduled time(s).\n"
        f"📌 A reminder will also be posted here on the day of each quiz."
    )
    res_msg = send_message(target_grp, announcement_text)
    if res_msg.get("ok"):
        pin_message(target_grp, res_msg["result"]["message_id"])

    final_text = (
        f"🎉 *Schedule Created & Announced*\n\n"
        f"📌 Group ID: `{target_grp}`\n"
        f"📘 Subject: `{subj}` (`{chap_text}`)\n"
        f"{schedule_line}\n\n"
        f"✅ Group announcement pinned successfully. Use `/myschedules` any time to review it, or `/reminder` to change the daily announcement time."
    )
    if message_id:
        edit_message(chat_id, message_id, final_text)
    else:
        send_message(chat_id, final_text)


if __name__ == "__main__":
    # Initialize the production database (users, quiz_history, badges, pdf_index, leaderboard_cache, audit_logs)
    init_db()

    # Load any previously saved links / schedules
    load_persisted_data()

    # Start Dummy Web Server for Render Free Tier Web Service
    threading.Thread(target=run_dummy_server, daemon=True).start()

    # Start Bot Tasks
    threading.Thread(target=scheduler_background_worker, daemon=True).start()
    threading.Thread(target=daily_reminder_worker, daemon=True).start()
    handle_updates()
