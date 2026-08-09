"""Gamification Service - XP, levels, streaks, badges, referrals."""

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, func, and_

from config import (
    XP_CORRECT, XP_WRONG, XP_REFERRAL_BONUS, XP_REFERRAL_PENALTY, STREAK_XP_BONUS,
)
from constants import BADGES, CORRECT_FEEDBACK
from database import async_session
from models import User, Badge

log = logging.getLogger(__name__)

# XP required for each level (cumulative)
LEVEL_THRESHOLDS = [0, 20, 50, 100, 180, 300, 450, 650, 900, 1200, 1600, 2100, 2700, 3500, 4500]


def _level_from_xp(xp: int) -> int:
    for i, threshold in enumerate(reversed(LEVEL_THRESHOLDS)):
        if xp >= threshold:
            return len(LEVEL_THRESHOLDS) - i
    return 1


def _xp_for_next_level(xp: int) -> tuple[int, int]:
    """Returns (current_level, xp_needed_for_next)."""
    lvl = _level_from_xp(xp)
    if lvl < len(LEVEL_THRESHOLDS):
        return lvl, LEVEL_THRESHOLDS[lvl] - xp
    return lvl, 9999


async def award_xp(user_id: int, is_correct: bool, streak: int = 0) -> tuple[int, int, bool]:
    """Award XP for a quiz answer. Returns (new_xp, new_level, leveled_up)."""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return 0, 1, False

        gained = XP_CORRECT if is_correct else XP_WRONG
        if is_correct and streak >= 3:
            gained += STREAK_XP_BONUS

        old_level = user.level
        user.xp += gained
        user.xp = max(user.xp, 0)  # XP can't go below 0
        user.level = _level_from_xp(user.xp)
        leveled_up = user.level > old_level

        if is_correct:
            user.total_correct += 1
        else:
            user.total_wrong += 1

        await session.commit()
        return user.xp, user.level, leveled_up


async def update_streak(user_id: int) -> int:
    """Update daily streak. Returns new streak count."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return 0

        if user.last_active_date == today:
            return user.streak_count

        yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).strftime("%Y-%m-%d")
        if user.last_active_date == yesterday:
            user.streak_count += 1
        else:
            user.streak_count = 1

        user.last_active_date = today
        await session.commit()
        return user.streak_count


def get_correct_feedback(correct_streak: int) -> str:
    """Get motivational feedback based on consecutive correct answers."""
    for text, threshold in reversed(CORRECT_FEEDBACK):
        if correct_streak >= threshold:
            return text
    return CORRECT_FEEDBACK[0][0]


async def check_and_award_badges(user_id: int, **kwargs) -> list[str]:
    """Check badge conditions and award new badges. Returns list of newly earned badge keys."""
    earned = []
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            return earned

        existing = set(
            (await session.execute(
                select(Badge.badge_key).where(Badge.user_id == user_id)
            )).scalars().all()
        )

        # Quiz Master: 100% score in a quiz with 10+ questions
        if kwargs.get("perfect_score") and kwargs.get("total_questions", 0) >= 10:
            if "quiz_master" not in existing:
                session.add(Badge(user_id=user_id, badge_key="quiz_master"))
                earned.append("quiz_master")

        # 7-Day Streak
        if user.streak_count >= 7 and "streak_7" not in existing:
            session.add(Badge(user_id=user_id, badge_key="streak_7"))
            earned.append("streak_7")

        # 30-Day Streak
        if user.streak_count >= 30 and "streak_30" not in existing:
            session.add(Badge(user_id=user_id, badge_key="streak_30"))
            earned.append("streak_30")

        # First Quiz
        if user.total_quizzes == 1 and "first_quiz" not in existing:
            session.add(Badge(user_id=user_id, badge_key="first_quiz"))
            earned.append("first_quiz")

        # Speed Demon: 5 questions answered in <5s each (checked externally)
        if kwargs.get("speed_demon") and "speed_demon" not in existing:
            session.add(Badge(user_id=user_id, badge_key="speed_demon"))
            earned.append("speed_demon")

        # XP milestones
        if user.xp >= 500 and "xp_500" not in existing:
            session.add(Badge(user_id=user_id, badge_key="xp_500"))
            earned.append("xp_500")
        if user.xp >= 1000 and "xp_1000" not in existing:
            session.add(Badge(user_id=user_id, badge_key="xp_1000"))
            earned.append("xp_1000")

        # Daily topper (set externally)
        if kwargs.get("daily_topper") and "topper_daily" not in existing:
            session.add(Badge(user_id=user_id, badge_key="topper_daily"))
            earned.append("topper_daily")

        # Mega quiz winner (set externally)
        if kwargs.get("mega_winner") and "mega_winner" not in existing:
            session.add(Badge(user_id=user_id, badge_key="mega_winner"))
            earned.append("mega_winner")

        # Referral king: 10+ referrals
        if kwargs.get("referral_count", 0) >= 10 and "referral_king" not in existing:
            session.add(Badge(user_id=user_id, badge_key="referral_king"))
            earned.append("referral_king")

        await session.commit()
    return earned


async def get_user_badges(user_id: int) -> list[dict]:
    """Get all badges for a user with metadata."""
    async with async_session() as session:
        result = await session.execute(
            select(Badge).where(Badge.user_id == user_id)
        )
        badges = []
        for b in result.scalars().all():
            info = BADGES.get(b.badge_key, {})
            badges.append({
                "key": b.badge_key,
                "emoji": info.get("emoji", "🏅"),
                "name": info.get("name", b.badge_key),
                "desc": info.get("desc", ""),
                "earned_at": b.earned_at.isoformat() if b.earned_at else "",
            })
        return badges


async def process_referral(referrer_id: int, new_user_id: int) -> str:
    """Process a referral. Returns 'added' or 'already_referred'."""
    async with async_session() as session:
        new_user = await session.get(User, new_user_id)
        if not new_user or new_user.referred_by:
            return "already_referred"

        new_user.referred_by = referrer_id

        referrer = await session.get(User, referrer_id)
        if referrer:
            referrer.xp += XP_REFERRAL_BONUS
            referrer.level = _level_from_xp(referrer.xp)

        await session.commit()
        return "added"


async def handle_referral_leave(referred_user_id: int) -> None:
    """Penalise referrer if a referred user leaves."""
    async with async_session() as session:
        user = await session.get(User, referred_user_id)
        if user and user.referred_by:
            referrer = await session.get(User, user.referred_by)
            if referrer:
                referrer.xp = max(0, referrer.xp + XP_REFERRAL_PENALTY)
                referrer.level = _level_from_xp(referrer.xp)
                await session.commit()
