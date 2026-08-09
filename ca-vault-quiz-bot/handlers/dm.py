"""DM Control Center - All bot DM commands for zero-coding manual control.

These commands work only in the bot's private DM with the owner.
Commands: /settime, /settimer, /addchapter, /removechapter, /setmode, /reschedule,
           /setwelcome, /setchannel, /leaderboard, /settime (user-specific).
"""

import logging

from telegram import Update
from telegram.ext import ContextTypes

from config import OWNER_ID
from permissions import owner_only
from services.scheduler import (
    add_schedule, remove_schedule, reschedule_all,
    set_mode, get_mode, get_week_schedule, generate_daily_pin_message,
    grant_trial, revoke_access,
)
from services.quiz_engine import get_active_quiz, set_live_timer
from services.leaderboard import get_leaderboard_text, update_leaderboard
from constants import SUBJECT_ALIASES, DAYS_OF_WEEK, SUBJECTS

log = logging.getLogger(__name__)


@owner_only
async def settime_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set quiz time: /settime [HH:MM]"""
    if not context.args:
        from services.scheduler import get_today_schedule
        sched = await get_today_schedule()
        current = sched.quiz_time if sched else "Not set"
        await update.message.reply_text(
            f"⏰ Current quiz time: {current}\nUsage: /settime 19:30"
        )
        return

    time_str = context.args[0]
    if not _validate_time(time_str):
        await update.message.reply_text("❌ Invalid time. Use HH:MM format (e.g., 19:30)")
        return

    from services.scheduler import get_today_schedule
    sched = await get_today_schedule()
    if sched:
        from database import async_session
        from models import ScheduleConfig
        from sqlalchemy import select, and_
        async with async_session() as session:
            entry = await session.execute(
                select(ScheduleConfig).where(
                    and_(
                        ScheduleConfig.day_of_week == sched.day_of_week,
                        ScheduleConfig.subject == sched.subject,
                        ScheduleConfig.chapter == sched.chapter,
                    )
                )
            )
            sched_entry = entry.scalar_one_or_none()
            if sched_entry:
                sched_entry.quiz_time = time_str
                await session.commit()

    await update.message.reply_text(f"✅ Aaj ka quiz time set: {time_str}")


@owner_only
async def settimer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set/change live quiz timer: /settimer [seconds]"""
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /settimer 30")
        return

    new_timer = int(context.args[0])
    if new_timer < 5 or new_timer > 300:
        await update.message.reply_text("❌ Timer 5-300 seconds ke beech hona chahiye.")
        return

    # Find any active quiz and change its timer
    from database import async_session
    from models import ActiveQuiz
    from sqlalchemy import select

    async with async_session() as session:
        result = await session.execute(
            select(ActiveQuiz).where(ActiveQuiz.status == "active")
        )
        quiz = result.scalar_one_or_none()

    if quiz:
        success = await set_live_timer(quiz.quiz_id, new_timer)
        if success:
            await update.message.reply_text(f"✅ Live quiz timer changed to {new_timer}s!")
        else:
            await update.message.reply_text("❌ Timer change fail.")
    else:
        await update.message.reply_text("ℹ️ Koi active quiz nahi hai. Yeh timer next quiz ke liye set hoga.")

    # Update default for future quizzes
    from constants import TYPE_TIMERS
    for qt in TYPE_TIMERS:
        TYPE_TIMERS[qt] = new_timer


@owner_only
async def addchapter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add chapter to schedule: /addchapter [Subject] [Chapter Name]"""
    if len(context.args) < 2:
        await update.message.reply_text('Usage: /addchapter Law "Contract Act"')
        return

    raw_subject = context.args[0]
    chapter = " ".join(context.args[1:])

    subject = SUBJECT_ALIASES.get(raw_subject.lower())
    if not subject:
        # Check if it's a direct subject name
        for s in SUBJECTS:
            if s.lower() == raw_subject.lower():
                subject = s
                break

    if not subject:
        await update.message.reply_text(
            f"❌ Unknown subject. Valid: {', '.join(SUBJECTS)}"
        )
        return

    # Find next available day (Mon-Sat)
    import random
    day = random.choice(DAYS_OF_WEEK[:6])

    success = await add_schedule(day, subject, chapter)
    if success:
        await update.message.reply_text(
            f"✅ Chapter added!\n📚 {subject} > {chapter}\n📅 {day}"
        )
    else:
        await update.message.reply_text("❌ Add nahi ho paya. Try again.")


@owner_only
async def removechapter_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove chapter from schedule: /removechapter [Subject] [Chapter Name]"""
    if len(context.args) < 2:
        await update.message.reply_text('Usage: /removechapter Law Contract Act')
        return

    raw_subject = context.args[0]
    chapter = " ".join(context.args[1:])

    subject = SUBJECT_ALIASES.get(raw_subject.lower())
    if not subject:
        for s in SUBJECTS:
            if s.lower() == raw_subject.lower():
                subject = s
                break

    if not subject:
        await update.message.reply_text("❌ Unknown subject.")
        return

    # Try all days
    removed = False
    for day in DAYS_OF_WEEK:
        if await remove_schedule(day, subject, chapter):
            removed = True
            break

    if removed:
        await update.message.reply_text(f"✅ Removed: {subject} > {chapter}")
    else:
        await update.message.reply_text("❌ Yeh chapter schedule mein nahi mila.")


@owner_only
async def setmode_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set bot mode: /setmode [auto/manual]"""
    if not context.args:
        current = get_mode()
        await update.message.reply_text(f"Current mode: {current}\nUsage: /setmode auto ya /setmode manual")
        return

    mode = context.args[0].lower()
    if mode not in ("auto", "manual"):
        await update.message.reply_text("❌ Invalid mode. Use 'auto' or 'manual'.")
        return

    set_mode(mode)
    await update.message.reply_text(f"✅ Mode set to: {mode}")


@owner_only
async def reschedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Re-arrange the entire schedule evenly across Mon-Sat."""
    result = await reschedule_all()
    await update.message.reply_text(result)


@owner_only
async def setwelcome_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set welcome message text: /setwelcome [text]"""
    if not context.args:
        await update.message.reply_text("Usage: /setwelcome [your motivational quote or shayari]")
        return

    text = " ".join(context.args)
    from constants import WELCOME_QUOTES
    WELCOME_QUOTES.insert(0, text)
    await update.message.reply_text(f"✅ Welcome message set: {text[:100]}")


@owner_only
async def setchannel_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set announcement channel: /setchannel [@channel_username]"""
    if not context.args:
        from config import ANNOUNCEMENT_CHANNEL
        await update.message.reply_text(f"Current channel: {ANNOUNCEMENT_CHANNEL or 'Not set'}\nUsage: /setchannel @your_channel")
        return

    channel = context.args[0]
    import config
    config.ANNOUNCEMENT_CHANNEL = channel
    await update.message.reply_text(f"✅ Announcement channel set to: {channel}")


# ── Helper ──

def _validate_time(time_str: str) -> bool:
    """Validate HH:MM format."""
    try:
        parts = time_str.split(":")
        h, m = int(parts[0]), int(parts[1])
        return 0 <= h <= 23 and 0 <= m <= 59
    except (ValueError, IndexError):
        return False
