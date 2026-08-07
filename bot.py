import os
import json
import random
import logging
import asyncio
from datetime import datetime

from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, ChatPermissions
from aiogram.utils.keyboard import InlineKeyboardBuilder

from apscheduler.schedulers.asyncio import AsyncIOScheduler
import aiosqlite

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
OWNER_ID = int(os.getenv("OWNER_ID")) if os.getenv("OWNER_ID") else None
DB_PATH = os.getenv("DATABASE_PATH", "quiz.db")
QUESTIONS_FILE = os.getenv("QUESTIONS_FILE", "questions.json")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN not set in environment")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=TOKEN)
dp = Dispatcher()

# Load questions into memory
if os.path.exists(QUESTIONS_FILE):
    with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
        QUESTIONS = {q["id"]: q for q in json.load(f)}
else:
    QUESTIONS = {}

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                score INTEGER DEFAULT 0
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS answers (
                question_id INTEGER,
                user_id INTEGER,
                PRIMARY KEY (question_id, user_id)
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS filters (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                word TEXT UNIQUE
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS warns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                moderator_id INTEGER,
                reason TEXT,
                created_at TEXT
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS mutes (
                user_id INTEGER PRIMARY KEY,
                until TEXT
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS admins (
                user_id INTEGER PRIMARY KEY,
                granted_by INTEGER,
                granted_at TEXT
            );
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)
        await db.commit()

async def is_admin(user_id: int):
    if OWNER_ID and user_id == OWNER_ID:
        return True
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM admins WHERE user_id=?", (user_id,))
        r = await cur.fetchone()
        return bool(r)

def build_help_message():
    return (
        "📜 Super Admin Master Help Menu\n\n"
        "1. 🎛️ Dashboard & Core Control\n"
        "/dashboard or /panel — Open interactive controls\n\n"
        "2. 🛡️ Moderation & Anti-Spam\n"
        "/filter add [word]\n"
        "/filter remove [word]\n"
        "/filters\n"
        "/stickers (toggle)\n\n"
        "3. ⚠️ Manual Mod & Warnings\n"
        "/mute @user\n"
        "/unmute @user\n"
        "/warn @user [reason]\n"
        "/unwarn @user\n\n"
        "4. 📊 Audit Logs\n"
        "/mutelog or /modlogs\n"
        "/userlog @user\n\n"
        "5. 👥 Quiz Access & Trial\n"
        "/grant @user [1week/2weeks/fullfree]\n"
        "/revoke @user\n"
        "/trials\n"
        "/settime @user [1week/2weeks/3weeks]\n\n"
        "6. ⚙️ System Settings\n"
        "/setwelcome <text>\n"
        "/setchannel <channel_link>\n\n"
        "Use these commands in group (as admin) or in bot DM (where applicable)."
    )

@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(build_help_message())

@dp.message(Command(["dashboard", "panel"]))
async def cmd_dashboard(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("Sirf admins ke liye.")
        return
    kb = InlineKeyboardBuilder()
    kb.button(text="Moderation", callback_data="dash:moderation")
    kb.button(text="Quiz Controls", callback_data="dash:quiz")
    kb.button(text="Trials", callback_data="dash:trials")
    kb.button(text="Settings", callback_data="dash:settings")
    kb.adjust(2)
    await message.answer("Dashboard — choose a panel:", reply_markup=kb.as_markup())

@dp.callback_query(lambda c: c.data and c.data.startswith("dash:"))
async def cb_dashboard(call: types.CallbackQuery):
    panel = call.data.split(":", 1)[1]
    if not await is_admin(call.from_user.id):
        await call.answer("Admin only", show_alert=True)
        return
    if panel == "moderation":
        await call.message.edit_text("Moderation panel (use commands):\n/filter add [word]\n/mute @user\n/warn @user")
    elif panel == "quiz":
        await call.message.edit_text("Quiz panel:\n/quiz to send question\n/grant /revoke etc.")
    elif panel == "trials":
        await call.message.edit_text("Trials panel: /trials /settime")
    elif panel == "settings":
        await call.message.edit_text("Settings panel: /setwelcome /setchannel")
    await call.answer()

@dp.message(Command("filter"))
async def cmd_filter(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("Admin command.")
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        await message.reply("Usage: /filter add|remove [word]")
        return
    action = parts[1].lower()
    if action == "add" and len(parts) == 3:
        word = parts[2].strip().lower()
        async with aiosqlite.connect(DB_PATH) as db:
            try:
                await db.execute("INSERT INTO filters (word) VALUES (?)", (word,))
                await db.commit()
                await message.reply(f"Filter added: {word}")
            except aiosqlite.IntegrityError:
                await message.reply("Word already in filters.")
    elif action == "remove" and len(parts) == 3:
        word = parts[2].strip().lower()
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM filters WHERE word=?", (word,))
            await db.commit()
            await message.reply(f"Filter removed: {word}")
    elif action == "list" or action == "filters":
        async with aiosqlite.connect(DB_PATH) as db:
            cur = await db.execute("SELECT word FROM filters")
            rows = await cur.fetchall()
            if not rows:
                await message.reply("No filters set.")
            else:
                await message.reply("Filters:\n" + "\n".join(r[0] for r in rows))
    else:
        await message.reply("Unknown action. Use add/remove/list.")

@dp.message(Command("mute"))
async def cmd_mute(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("Admin only.")
        return
    if not message.reply_to_message and len(message.entities or []) == 0 and "@" not in message.text:
        await message.reply("Reply to a user's message or mention them: /mute @username")
        return
    target = None
    if message.reply_to_message:
        target = message.reply_to_message.from_user
    else:
        parts = message.text.split()
        if len(parts) >= 2:
            username = parts[1]
            await message.reply("Please use reply to user's message to mute (or ensure bot can resolve username).")
            return
    try:
        await bot.restrict_chat_member(message.chat.id, target.id, ChatPermissions(can_send_messages=False))
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("INSERT OR REPLACE INTO mutes (user_id, until) VALUES (?, ?)", (target.id, None))
            await db.commit()
        await message.reply(f"{target.full_name} muted.")
    except Exception as e:
        logger.exception("mute failed")
        await message.reply("Mute failed. Bot needs to be admin with permissions to restrict_members.")

@dp.message(Command("unmute"))
async def cmd_unmute(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("Admin only.")
        return
    if not message.reply_to_message:
        await message.reply("Reply to a user's message to unmute.")
        return
    target = message.reply_to_message.from_user
    try:
        await bot.restrict_chat_member(message.chat.id, target.id, ChatPermissions(can_send_messages=True, can_send_media_messages=True,
                                                                       can_send_other_messages=True, can_add_web_page_previews=True))
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("DELETE FROM mutes WHERE user_id=?", (target.id,))
            await db.commit()
        await message.reply(f"{target.full_name} unmuted.")
    except Exception as e:
        logger.exception("unmute failed")
        await message.reply("Unmute failed. Bot needs proper admin rights.")

@dp.message(Command("warn"))
async def cmd_warn(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("Admin only.")
        return
    if not message.reply_to_message:
        await message.reply("Reply to a user's message to warn them: /warn [reason]")
        return
    reason = " ".join(message.text.split()[1:]) or "No reason provided"
    target = message.reply_to_message.from_user
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO warns (user_id, moderator_id, reason, created_at) VALUES (?, ?, ?, ?)",
                         (target.id, message.from_user.id, reason, datetime.utcnow().isoformat()))
        await db.commit()
        cur = await db.execute("SELECT COUNT(*) FROM warns WHERE user_id=?", (target.id,))
        count = (await cur.fetchone())[0]
    await message.reply(f"{target.full_name} warned. Total warnings: {count}")
    if count >= 3:
        await message.reply(f"{target.full_name} has {count} warnings — consider muting or banning.")

@dp.message(Command("unwarn"))
async def cmd_unwarn(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("Admin only.")
        return
    if not message.reply_to_message:
        await message.reply("Reply to a user's message to remove last warn: /unwarn")
        return
    target = message.reply_to_message.from_user
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT id FROM warns WHERE user_id=? ORDER BY id DESC LIMIT 1", (target.id,))
        row = await cur.fetchone()
        if row:
            await db.execute("DELETE FROM warns WHERE id=?", (row[0],))
            await db.commit()
            await message.reply("Last warning removed.")
        else:
            await message.reply("No warnings to remove.")

@dp.message(Command(["modlogs", "mutelog"]))
async def cmd_modlogs(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("Admin only.")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT user_id, moderator_id, reason, created_at FROM warns ORDER BY created_at DESC LIMIT 50")
        rows = await cur.fetchall()
    if not rows:
        await message.reply("No mod logs.")
        return
    text = "Recent warns:\n" + "\n".join([f"user:{r[0]} by:{r[1]} at:{r[3]} reason:{r[2]}" for r in rows])
    await message.reply(text)

@dp.message(Command("userlog"))
async def cmd_userlog(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("Admin only.")
        return
    if not message.reply_to_message:
        await message.reply("Reply to user's message or mention them: /userlog")
        return
    target = message.reply_to_message.from_user
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT reason, created_at, moderator_id FROM warns WHERE user_id=? ORDER BY created_at DESC", (target.id,))
        rows = await cur.fetchall()
    if not rows:
        await message.reply("No logs for this user.")
        return
    text = f"Logs for {target.full_name}:\n" + "\n".join([f"{r[1]} by {r[2]} — {r[0]}" for r in rows])
    await message.reply(text)

def build_options_markup(question):
    kb = InlineKeyboardBuilder()
    for i, opt in enumerate(question["options"]):
        kb.button(text=opt, callback_data=f"ans:{question['id']}:{i}")
    kb.adjust(1)
    return kb.as_markup()

async def send_question_to(chat_id, question=None):
    if question is None and QUESTIONS:
        question = random.choice(list(QUESTIONS.values()))
    if not question:
        await bot.send_message(chat_id, "No questions available.")
        return
    await bot.send_message(chat_id, f"Quiz: {question['question']}", reply_markup=build_options_markup(question))

@dp.message(Command("quiz"))
async def cmd_quiz_public(message: types.Message):
    await send_question_to(message.chat.id)

@dp.callback_query(lambda c: c.data and c.data.startswith("ans:"))
async def handle_answer(callback: types.CallbackQuery):
    data = callback.data.split(":")
    qid = int(data[1]); choice = int(data[2])
    user = callback.from_user
    question = QUESTIONS.get(qid)
    if not question:
        await callback.answer("Question not found", show_alert=True)
        return
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT 1 FROM answers WHERE question_id=? AND user_id=?", (qid, user.id))
        if await cur.fetchone():
            await callback.answer("You already answered.", show_alert=True)
            return
        correct = (choice == question["answer_index"])
        if correct:
            await db.execute("INSERT OR IGNORE INTO users (user_id, username, score) VALUES (?, ?, 0)", (user.id, user.username))
            await db.execute("UPDATE users SET score = score + 1 WHERE user_id = ?", (user.id,))
        await db.execute("INSERT INTO answers (question_id, user_id) VALUES (?, ?)", (qid, user.id))
        await db.commit()
    text = "Sahi jawab! 🎉" if correct else f"Ghalat. ❌ Sahi: {question['options'][question['answer_index']]}"
    await callback.answer(text, show_alert=True)
    await send_question_to(callback.message.chat.id)

@dp.message(Command("leaderboard"))
async def cmd_leaderboard(message: types.Message):
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT username, score FROM users ORDER BY score DESC LIMIT 10")
        rows = await cur.fetchall()
    if not rows:
        await message.reply("No scores yet.")
        return
    text = "Leaderboard:\n" + "\n".join([f"{i+1}. {r[0] or r[0]} — {r[1]} pts" for i, r in enumerate(rows)])
    await message.reply(text)

@dp.message(Command("setwelcome"))
async def cmd_setwelcome(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("Admin only.")
        return
    text = message.text.partition(" ")[2].strip()
    if not text:
        await message.reply("Usage: /setwelcome <text>")
        return
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("REPLACE INTO settings (key, value) VALUES (?, ?)", ("welcome_text", text))
        await db.commit()
    await message.reply("Welcome text set.")

@dp.message(Command("setchannel"))
async def cmd_setchannel(message: types.Message):
    if not await is_admin(message.from_user.id):
        await message.reply("Admin only.")
        return
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.reply("Usage: /setchannel <channel_link_or_id>")
        return
    link = parts[1].strip()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("REPLACE INTO settings (key, value) VALUES (?, ?)", ("mandatory_channel", link))
        await db.commit()
    await message.reply("Channel set.")

async def scheduled_daily():
    async with aiosqlite.connect(DB_PATH) as db:
        cur = await db.execute("SELECT value FROM settings WHERE key='daily_post_chat_id'")
        r = await cur.fetchone()
    if r:
        try:
            await send_question_to(int(r[0]))
        except Exception:
            logger.exception("Scheduled send failed")

async def main():
    await init_db()
    scheduler = AsyncIOScheduler()
    scheduler.add_job(scheduled_daily, "cron", hour=9, minute=0)
    scheduler.start()
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
