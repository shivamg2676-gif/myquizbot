"""Scheduler Service - ICAI syllabus scheduling, daily pin, quiz timing, mega quiz."""

import json
import logging
import random
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, and_, delete

from config import (
    QUIZ_WINDOW_START, QUIZ_WINDOW_END, DAILY_PIN_TIME,
    MEGA_QUIZ_DAY, OWNER_ID,
)
from constants import DAYS_OF_WEEK, DEFAULT_SYLLABUS, SUBJECTS, MEGA_QUIZ_CONFIG
from database import async_session
from models import ScheduleConfig, ActiveQuiz, AuditLog

log = logging.getLogger(__name__)

# In-memory mode flag (auto / manual)
_mode: str = "auto"  # global, can be changed via /setmode


def get_mode() -> str:
    return _mode


def set_mode(mode: str):
    global _mode
    _mode = mode


# ── Schedule Management ──

async def init_default_schedule():
    """Seed the default Monday-Saturday schedule from DEFAULT_SYLLABUS."""
    async with async_session() as session:
        existing = await session.execute(select(ScheduleConfig))
        if existing.scalars().first():
            return  # Already has schedule data

        day_idx = 0
        for subject, chapters in DEFAULT_SYLLABUS.items():
            for chapter in chapters:
                day = DAYS_OF_WEEK[day_idx % 6]  # Monday-Saturday
                session.add(ScheduleConfig(
                    day_of_week=day,
                    subject=subject,
                    chapter=chapter,
                    quiz_time=QUIZ_WINDOW_START,  # Default 18:00
                    is_active=True,
                ))
                day_idx += 1

        await session.commit()
    log.info("Default schedule initialised.")


async def get_today_schedule() -> ScheduleConfig | None:
    """Get today's scheduled subject and chapter."""
    today = datetime.now(timezone.utc).strftime("%A")
    async with async_session() as session:
        result = await session.execute(
            select(ScheduleConfig).where(
                and_(
                    ScheduleConfig.day_of_week == today,
                    ScheduleConfig.is_active == True,
                )
            ).limit(1)
        )
        return result.scalar_one_or_none()


async def add_schedule(day: str, subject: str, chapter: str, time: str = "18:00") -> bool:
    try:
        async with async_session() as session:
            session.add(ScheduleConfig(
                day_of_week=day, subject=subject, chapter=chapter,
                quiz_time=time, is_active=True,
            ))
            await session.commit()
        return True
    except Exception as e:
        log.error("Failed to add schedule: %s", e)
        return False


async def remove_schedule(day: str, subject: str, chapter: str) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(ScheduleConfig).where(
                and_(
                    ScheduleConfig.day_of_week == day,
                    ScheduleConfig.subject == subject,
                    ScheduleConfig.chapter == chapter,
                )
            )
        )
        entry = result.scalar_one_or_none()
        if entry:
            await session.delete(entry)
            await session.commit()
            return True
    return False


async def get_week_schedule() -> str:
    """Get the full week's schedule for display."""
    async with async_session() as session:
        result = await session.execute(
            select(ScheduleConfig).where(ScheduleConfig.is_active == True)
            .order_by(ScheduleConfig.id)
        )
        entries = result.scalars().all()

    if not entries:
        return "Koi schedule set nahi hai. /addchapter se add karo."

    by_day: dict[str, list] = {d: [] for d in DAYS_OF_WEEK}
    for e in entries:
        by_day.setdefault(e.day_of_week, []).append(e)

    lines = ["📅 WEEKLY SCHEDULE", "─" * 35]
    for day in DAYS_OF_WEEK:
        entries_for_day = by_day.get(day, [])
        if entries_for_day:
            for e in entries_for_day:
                lines.append(f"  {day}: {e.subject} › {e.chapter} [{e.quiz_time}]")
        else:
            lines.append(f"  {day}: — No session —")
    return "\n".join(lines)


async def reschedule_all() -> str:
    """Re-arrange the schedule evenly across Mon-Sat."""
    async with async_session() as session:
        # Collect all unique subject+chapter combos
        result = await session.execute(select(ScheduleConfig))
        entries = result.scalars().all()

        chapters = [(e.subject, e.chapter, e.quiz_time) for e in entries]

        # Clear existing
        for e in entries:
            await session.delete(e)

        # Redistribute across Mon-Sat
        for i, (subj, ch, time) in enumerate(chapters):
            day = DAYS_OF_WEEK[i % 6]
            session.add(ScheduleConfig(
                day_of_week=day, subject=subj, chapter=ch,
                quiz_time=time, is_active=True,
            ))

        await session.commit()
    return "✅ Schedule successfully re-arranged across the week!"


# ── Daily Pin Message ──

async def generate_daily_pin_message() -> str:
    """Generate the 6 AM daily pinned schedule message."""
    schedule = await get_today_schedule()
    if not schedule:
        return ("📖 Aaj koi scheduled quiz nahi hai.\n"
                "Admin se /addchapter ya /reschedule karke set karao.")

    return (
        f"📚 Aaj ka Subject & Chapter\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"📖 Subject: {schedule.subject}\n"
        f"📑 Chapter: {schedule.chapter}\n"
        f"⏰ Time: {schedule.quiz_time} (6 PM - 8 PM window)\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Quizzes ke liye ready raho! Best of luck! 🚀"
    )


# ── Sunday Mega Quiz Prep ──

async def get_mega_quiz_chapters() -> dict[str, list[str]]:
    """Get all chapters studied Mon-Sat for the cumulative Sunday mega quiz."""
    async with async_session() as session:
        result = await session.execute(
            select(ScheduleConfig).where(
                and_(
                    ScheduleConfig.is_active == True,
                    ScheduleConfig.day_of_week != MEGA_QUIZ_DAY,
                )
            ).order_by(ScheduleConfig.id)
        )
        entries = result.scalars().all()

    chapters: dict[str, list[str]] = {}
    for e in entries:
        chapters.setdefault(e.subject, []).append(e.chapter)
    return chapters


async def is_mega_quiz_day() -> bool:
    """Check if today is the mega quiz day (Sunday)."""
    return datetime.now(timezone.utc).strftime("%A") == MEGA_QUIZ_DAY


# ── Smart Time Slot Selection ──

def _parse_time(time_str: str) -> tuple[int, int]:
    parts = time_str.split(":")
    return int(parts[0]), int(parts[1])


def get_quiz_window_minutes() -> tuple[int, int]:
    """Return (start_minutes, end_minutes) for the quiz window."""
    sh, sm = _parse_time(QUIZ_WINDOW_START)
    eh, em = _parse_time(QUIZ_WINDOW_END)
    return sh * 60 + sm, eh * 60 + em


def generate_random_time_in_window() -> str:
    """Pick a random time between QUIZ_WINDOW_START and QUIZ_WINDOW_END."""
    start_min, end_min = get_quiz_window_minutes()
    if end_min <= start_min:
        end_min = start_min + 120
    chosen = random.randint(start_min, end_min)
    h, m = divmod(chosen, 60)
    return f"{h:02d}:{m:02d}"


# ── Trial Management ──

from constants import TRIAL_DURATIONS
from database import async_session
from models import User


async def grant_trial(user_id: int, trial_type: str) -> str:
    """Grant quiz-start access with a trial period."""
    days = TRIAL_DURATIONS.get(trial_type, 7)
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return "User not found."
        user.can_start_quiz = True
        user.trial_type = trial_type
        user.trial_start_date = datetime.now(timezone.utc)
        user.trial_end_date = datetime.now(timezone.utc) + timedelta(days=days)
        await session.commit()
    return f"✅ Trial '{trial_type}' ({days} days) granted to User #{user_id}."


async def revoke_access(user_id: int) -> str:
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return "User not found."
        user.can_start_quiz = False
        user.trial_type = None
        user.trial_start_date = None
        user.trial_end_date = None
        await session.commit()
    return f"❌ Access revoked for User #{user_id}."


async def get_active_trials() -> str:
    """Get list of users on active trials."""
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        result = await session.execute(
            select(User).where(
                and_(
                    User.can_start_quiz == True,
                    User.trial_end_date != None,
                    User.trial_end_date > now,
                )
            )
        )
        users = result.scalars().all()

    if not users:
        return "Koi active trial nahi hai."

    lines = ["📋 ACTIVE TRIALS", "─" * 35]
    for u in users:
        mention = f"@{u.username}" if u.username else f"#{u.user_id}"
        remaining = (u.trial_end_date - now).days if u.trial_end_date else 0
        lines.append(f"  {mention} | {u.trial_type} | {remaining} days left")
    return "\n".join(lines)


async def check_expired_trials() -> list[int]:
    """Return user_ids whose trial has expired."""
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        result = await session.execute(
            select(User).where(
                and_(
                    User.can_start_quiz == True,
                    User.trial_end_date != None,
                    User.trial_end_date <= now,
                )
            )
        )
        expired = []
        for u in result.scalars().all():
            u.can_start_quiz = False
            expired.append(u.user_id)
        await session.commit()
    return expired
