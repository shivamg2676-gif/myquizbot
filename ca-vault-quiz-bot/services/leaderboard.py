"""Leaderboard Service - Daily, weekly, monthly rankings."""

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func, and_, delete

from database import async_session
from models import User, LeaderboardCache, QuizHistory, Badge
from constants import BADGES, SHAYARI_LINES

log = logging.getLogger(__name__)


def _date_key(period: str, dt: datetime | None = None) -> str:
    dt = dt or datetime.now(timezone.utc)
    if period == "daily":
        return dt.strftime("%Y-%m-%d")
    elif period == "weekly":
        # ISO week: YYYY-WXX
        iso = dt.isocalendar()
        return f"{iso[0]}-W{iso[1]:02d}"
    elif period == "monthly":
        return dt.strftime("%Y-%m")
    return dt.strftime("%Y-%m-%d")


def _period_start(period: str, dt: datetime | None = None) -> datetime:
    dt = dt or datetime.now(timezone.utc)
    if period == "daily":
        return dt.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "weekly":
        # Monday start
        days_since_monday = dt.weekday()
        monday = dt - timedelta(days=days_since_monday)
        return monday.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "monthly":
        return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return dt


async def update_leaderboard(period: str, group_id: int | None = None) -> None:
    """Rebuild leaderboard cache for a period."""
    start = _period_start(period)
    dk = _date_key(period)

    async with async_session() as session:
        # Sum scores from quiz_history for this period
        result = await session.execute(
            select(
                QuizHistory.user_id,
                func.sum(QuizHistory.score).label("total_score"),
                func.count(QuizHistory.attempt_id).label("quiz_count"),
            )
            .where(QuizHistory.timestamp >= start)
            .group_by(QuizHistory.user_id)
            .order_by(func.sum(QuizHistory.score).desc())
        )
        rows = result.all()

        # Clear old cache for this period
        await session.execute(
            delete(LeaderboardCache).where(
                and_(LeaderboardCache.period == period, LeaderboardCache.date_key == dk)
            )
        )

        # Insert new rankings
        for rank, (user_id, total_score, quiz_count) in enumerate(rows, 1):
            session.add(LeaderboardCache(
                user_id=user_id,
                period=period,
                score=int(total_score or 0),
                rank=rank,
                date_key=dk,
            ))

        await session.commit()


def _format_time(seconds: int) -> str:
    m, s = divmod(seconds, 60)
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


async def get_leaderboard_text(period: str, top_n: int = 10) -> str:
    """Get formatted leaderboard text."""
    dk = _date_key(period)

    async with async_session() as session:
        result = await session.execute(
            select(LeaderboardCache, User.first_name, User.username, User.level, User.xp)
            .join(User, LeaderboardCache.user_id == User.user_id)
            .where(and_(
                LeaderboardCache.period == period,
                LeaderboardCache.date_key == dk,
            ))
            .order_by(LeaderboardCache.rank)
            .limit(top_n)
        )
        rows = result.all()

    if not rows:
        return f"Abhi {period} leaderboard mein koi data nahi hai. Quizzes dene ke baad yahan results dikhai denge!"

    period_label = {"daily": "Daily", "weekly": "Weekly", "monthly": "Monthly"}.get(period, period)
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}

    lines = [f"🏆 {period_label.upper()} LEADERBOARD"]
    lines.append("─" * 28)

    for cache, name, username, level, xp in rows:
        rank = cache.rank
        icon = medal.get(rank, f"  {rank}.")
        mention = f"@{username}" if username else (name or "Unknown")
        lines.append(f"{icon}  {mention}  —  {cache.score} pts  (Lv.{level})")

    return "\n".join(lines)


async def get_daily_topper_text() -> str | None:
    """Generate daily topper message with badges and shayari for pinning."""
    dk = _date_key("daily")
    import random

    async with async_session() as session:
        result = await session.execute(
            select(LeaderboardCache, User.first_name, User.username)
            .join(User, LeaderboardCache.user_id == User.user_id)
            .where(and_(
                LeaderboardCache.period == "daily",
                LeaderboardCache.date_key == dk,
            ))
            .order_by(LeaderboardCache.rank)
            .limit(3)
        )
        rows = result.all()

    if not rows:
        return None

    medals = ["🥇", "🥈", "🥉"]
    shayari = random.choice(SHAYARI_LINES)

    lines = []
    for i, (cache, name, username) in enumerate(rows):
        mention = f"@{username}" if username else (name or "Unknown")
        lines.append(f"{medals[i]}  Rank #{i+1}: {mention} — {cache.score} pts")

    lines.append("")
    lines.append(f"✨ {shayari}")
    return "\n".join(lines)


async def record_quiz_score(
    user_id: int, subject: str, chapter: str | None,
    quiz_type: str, score: int, total: int, correct: int, wrong: int, time_taken: int
) -> None:
    """Record a quiz attempt and update user stats."""
    async with async_session() as session:
        session.add(QuizHistory(
            user_id=user_id,
            subject=subject,
            chapter=chapter,
            quiz_type=quiz_type,
            score=score,
            total_questions=total,
            correct_count=correct,
            wrong_count=wrong,
            time_taken=time_taken,
        ))
        user = await session.get(User, user_id)
        if user:
            user.total_quizzes += 1
            from datetime import datetime, timezone
            user.last_quiz_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        await session.commit()

    # Update leaderboard caches
    for period in ["daily", "weekly", "monthly"]:
        await update_leaderboard(period)
