"""Role-Based Access Control helpers."""

from functools import wraps
from typing import Callable

from telegram import Update
from telegram.ext import ContextTypes

from config import OWNER_ID, ROLE_ADMIN, ROLE_HIERARCHY, ROLE_MOD, ROLE_OWNER
from database import async_session
from models import User


async def _get_user_role(user_id: int) -> str:
    async with async_session() as session:
        user = await session.get(User, user_id)
        if user:
            return user.role
    # Owner is always owner regardless of DB
    if user_id == OWNER_ID:
        return ROLE_OWNER
    return "student"


async def ensure_user_registered(user_id: int, username: str | None, first_name: str | None) -> User:
    """Register user if not exists, return User object."""
    async with async_session() as session:
        user = await session.get(User, user_id)
        if not user:
            import hashlib, secrets
            user = User(
                user_id=user_id,
                username=username,
                first_name=first_name or "Student",
                role=ROLE_OWNER if user_id == OWNER_ID else "student",
                referral_code=secrets.token_hex(8),
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        else:
            # Update username if changed
            if username and user.username != username:
                user.username = username
                await session.commit()
                await session.refresh(user)
        return user


def require_role(min_role: str):
    """Decorator: only allow users with `min_role` or higher."""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
            user_id = update.effective_user.id if update.effective_user else 0
            role = await _get_user_role(user_id)
            if ROLE_HIERARCHY.get(role, 0) < ROLE_HIERARCHY.get(min_role, 0):
                if update.effective_chat and update.effective_chat.id != user_id:
                    await update.message.reply_text(
                        "⛔ You don't have permission to use this command."
                    )
                return
            return await func(update, context)
        return wrapper
    return decorator


def owner_only(func: Callable):
    """Decorator: only OWNER_ID can use this command."""
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id if update.effective_user else 0
        if user_id != OWNER_ID:
            await update.message.reply_text("⛔ Owner-only command.")
            return
        return await func(update, context)
    return wrapper


def admin_or_above(func: Callable):
    return require_role(ROLE_ADMIN)(func)


def mod_or_above(func: Callable):
    return require_role(ROLE_MOD)(func)
