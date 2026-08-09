"""Moderation Service - Anti-spam, content filter, 3-strike, mute, force subscribe.

All moderation actions are logged to audit_logs table.
"""

import hashlib
import logging
import re
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, and_

from config import (
    MAX_WARNINGS, MUTE_DURATION_HOURS, STICKER_FILTER_ENABLED,
    OWNER_ID, ANNOUNCEMENT_CHANNEL,
)
from constants import SUBJECT_ALIASES, DEFAULT_SYLLABUS
from database import async_session
from models import User, AuditLog, Filter, PDFIndex

log = logging.getLogger(__name__)

# Default abusive words list (extendable via /filter add)
DEFAULT_FILTERED_WORDS = [
    "mc", "bc", "b*c", "bsdk", "madarchod", "chod", "chud", "behenchod",
    "laude", "lodu", "gandu", "chutiya", "randi", "bhosdi", "bsdk",
    "fuck", "shit", "asshole", "dick", "bitch",
]


async def init_default_filters():
    """Seed default filtered words on first run."""
    async with async_session() as session:
        for word in DEFAULT_FILTERED_WORDS:
            existing = await session.execute(
                select(Filter).where(Filter.word == word)
            )
            if not existing.scalar_one_or_none():
                session.add(Filter(word=word, added_by=OWNER_ID or 0))
        await session.commit()
    log.info("Default filters initialised.")


async def get_filtered_words() -> list[str]:
    async with async_session() as session:
        result = await session.execute(select(Filter.word))
        return list(result.scalars().all())


async def add_filter_word(word: str, added_by: int) -> bool:
    try:
        async with async_session() as session:
            session.add(Filter(word=word.lower(), added_by=added_by))
            await session.commit()
        return True
    except Exception:
        return False


async def remove_filter_word(word: str) -> bool:
    async with async_session() as session:
        result = await session.execute(
            select(Filter).where(Filter.word == word.lower())
        )
        f = result.scalar_one_or_none()
        if f:
            await session.delete(f)
            await session.commit()
            return True
    return False


async def check_message_spam(text: str) -> str | None:
    """Check if message contains filtered words. Returns the matched word or None."""
    if not text:
        return None
    words = await get_filtered_words()
    text_lower = text.lower()
    for w in words:
        if w in text_lower:
            return w
    return None


async def add_audit_log(
    admin_id: int | None, target_user_id: int | None,
    action_type: str, reason: str | None = None, details: dict | None = None,
):
    """Record an audit log entry."""
    import json
    async with async_session() as session:
        session.add(AuditLog(
            admin_id=admin_id,
            target_user_id=target_user_id,
            action_type=action_type,
            reason=reason,
            details=json.dumps(details) if details else None,
        ))
        await session.commit()


async def warn_user(target_user_id: int, reason: str, admin_id: int | None = None) -> dict:
    """Apply a warning. Returns {action, duration, warning_count}."""
    async with async_session() as session:
        user = await session.get(User, target_user_id)
        if not user:
            return {"action": "none", "duration": 0, "warning_count": 0}

        user.warning_count += 1
        wc = user.warning_count

        if wc >= MAX_WARNINGS:
            # Permanent mute
            user.is_permanently_muted = True
            user.is_muted = True
            action = "permanent_mute"
            duration = 0
        else:
            # Temporary mute
            user.is_muted = True
            user.mute_until = datetime.now(timezone.utc) + timedelta(hours=MUTE_DURATION_HOURS)
            action = "temp_mute"
            duration = MUTE_DURATION_HOURS

        await session.commit()

        await add_audit_log(
            admin_id=admin_id, target_user_id=target_user_id,
            action_type=action, reason=reason,
            details={"warning_count": wc},
        )

        return {"action": action, "duration": duration, "warning_count": wc}


async def unmute_user(target_user_id: int, admin_id: int | None = None, reason: str = "Manual unmute") -> bool:
    async with async_session() as session:
        user = await session.get(User, target_user_id)
        if not user:
            return False
        user.is_muted = False
        user.is_permanently_muted = False
        user.mute_until = None
        await session.commit()

        await add_audit_log(
            admin_id=admin_id, target_user_id=target_user_id,
            action_type="unmute", reason=reason,
        )
        return True


async def reduce_warning(target_user_id: int, admin_id: int | None = None) -> int:
    """Reduce warning count by 1. Returns new count."""
    async with async_session() as session:
        user = await session.get(User, target_user_id)
        if not user:
            return 0
        user.warning_count = max(0, user.warning_count - 1)
        if user.warning_count < MAX_WARNINGS and user.is_permanently_muted:
            user.is_permanently_muted = False
            user.is_muted = False
            user.mute_until = None
        await session.commit()
        return user.warning_count


async def get_mute_logs(limit: int = 20) -> str:
    """Get recent mute/warning logs for /mutelog command."""
    async with async_session() as session:
        result = await session.execute(
            select(AuditLog)
            .where(AuditLog.action_type.in_(["temp_mute", "permanent_mute", "unmute", "warning"]))
            .order_by(AuditLog.timestamp.desc())
            .limit(limit)
        )
        logs = result.scalars().all()

    if not logs:
        return "Abhi koi mute/warning log nahi hai."

    lines = ["📋 RECENT MOD LOGS", "─" * 30]
    for l in logs:
        time_str = l.timestamp.strftime("%d/%m %H:%M") if l.timestamp else "?"
        target = f"User#{l.target_user_id}" if l.target_user_id else "System"
        admin = f"Admin#{l.admin_id}" if l.admin_id else "Bot"
        reason = l.reason or "No reason"
        lines.append(f"[{time_str}] {l.action_type} | Target: {target} | By: {admin} | {reason}")

    return "\n".join(lines)


async def get_user_logs(target_user_id: int) -> str:
    """Get all logs for a specific user."""
    async with async_session() as session:
        result = await session.execute(
            select(AuditLog).where(AuditLog.target_user_id == target_user_id)
            .order_by(AuditLog.timestamp.desc())
            .limit(30)
        )
        logs = result.scalars().all()

    if not logs:
        return "Is user ke liye koi log nahi mila."

    lines = [f"📋 LOGS — User #{target_user_id}", "─" * 30]
    for l in logs:
        time_str = l.timestamp.strftime("%d/%m %H:%M") if l.timestamp else "?"
        lines.append(f"[{time_str}] {l.action_type}: {l.reason or 'No reason'}")

    return "\n".join(lines)


async def check_channel_subscription(user_id: int, bot) -> bool:
    """Check if user is subscribed to the announcement channel."""
    if not ANNOUNCEMENT_CHANNEL:
        return True  # No channel configured = no restriction

    try:
        member = await bot.get_chat_member(ANNOUNCEMENT_CHANNEL, user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception:
        return False


async def set_force_mute(user_id: int, muted: bool) -> None:
    """Set/unset force mute for non-subscribers."""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if user:
            user.is_muted = muted
            if muted:
                user.is_subscribed = False
            else:
                user.is_subscribed = True
            await session.commit()


async def check_expired_mutes() -> list[int]:
    """Return list of user_ids whose temporary mute has expired."""
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        result = await session.execute(
            select(User).where(
                and_(
                    User.is_muted == True,
                    User.is_permanently_muted == False,
                    User.mute_until != None,
                    User.mute_until <= now,
                )
            )
        )
        expired = []
        for user in result.scalars().all():
            user.is_muted = False
            user.mute_until = None
            expired.append(user.user_id)
        await session.commit()
    return expired


async def compute_file_hash(file_content: bytes) -> str:
    """Compute SHA-256 hash of file content for duplicate detection."""
    return hashlib.sha256(file_content).hexdigest()


async def is_duplicate_file(file_hash: str) -> bool:
    """Check if a file with this hash already exists."""
    async with async_session() as session:
        result = await session.execute(
            select(PDFIndex).where(PDFIndex.file_hash == file_hash)
        )
        return result.scalar_one_or_none() is not None


# ── Smart Material Keyword Matching ──
async def find_material_for_keyword(keyword: str) -> PDFIndex | None:
    """Find a PDF by keyword (custom hashtag or subject+chapter match)."""
    keyword_lower = keyword.lower().strip().lstrip("#")

    async with async_session() as session:
        # First try exact keyword match in the keywords JSON column
        result = await session.execute(
            select(PDFIndex).where(
                and_(
                    PDFIndex.is_approved == True,
                    PDFIndex.keywords.contains(keyword_lower),
                )
            )
        )
        pdf = result.scalar_one_or_none()
        if pdf:
            return pdf

        # Try subject/chapter match
        for alias, subject in SUBJECT_ALIASES.items():
            if alias in keyword_lower:
                # Find chapter keyword in the remaining text
                chapter_query = keyword_lower.replace(alias, "").strip("_").strip()
                if chapter_query:
                    result = await session.execute(
                        select(PDFIndex).where(
                            and_(
                                PDFIndex.is_approved == True,
                                PDFIndex.subject == subject,
                                PDFIndex.chapter.ilike(f"%{chapter_query}%"),
                            )
                        )
                    )
                    pdf = result.scalar_one_or_none()
                    if pdf:
                        return pdf

                # Return any approved PDF for this subject
                result = await session.execute(
                    select(PDFIndex).where(
                        and_(
                            PDFIndex.is_approved == True,
                            PDFIndex.subject == subject,
                        )
                    ).limit(1)
                )
                return result.scalar_one_or_none()

    return None
