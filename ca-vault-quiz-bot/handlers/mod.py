"""Moderation command handlers - /mute, /unmute, /warn, /unwarn, /filter, /stickers, /mutelog, /userlog."""

import logging

from telegram import Update, ChatPermissions
from telegram.ext import ContextTypes

from sqlalchemy import select

from permissions import mod_or_above, ensure_user_registered
from database import async_session
from models import User
from services.moderation import (
    warn_user, unmute_user, reduce_warning,
    add_filter_word, remove_filter_word, get_filtered_words,
    get_mute_logs, get_user_logs, add_audit_log,
    check_channel_subscription, set_force_mute,
)
from config import STICKER_FILTER_ENABLED

log = logging.getLogger(__name__)


# Global sticker filter toggle
_sticker_filter_on: bool = STICKER_FILTER_ENABLED


async def _extract_target(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """Extract target user_id from reply or @mention or direct ID."""
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        return update.message.reply_to_message.from_user.id
    args = context.args or []
    if args:
        arg = args[0]
        if arg.startswith("@"):
            username = arg[1:]
            async with async_session() as session:
                result = await session.execute(select(User).where(User.username == username))
                user = result.scalar_one_or_none()
                return user.user_id if user else None
        elif arg.isdigit():
            return int(arg)
    return None


@mod_or_above
async def mute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Mute a user: /mute @user [reason]"""
    target_id = await _extract_target(update, context)
    if not target_id:
        await update.message.reply_text("❌ User specify karo (reply ya @mention ya ID).")
        return

    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "Manual mute by admin"
    chat_id = update.effective_chat.id

    # Telegram mute (restrict permissions)
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_id,
            permissions=ChatPermissions(can_send_messages=False),
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Telegram mute fail: {e}")
        return

    # DB mute
    result = await warn_user(target_id, reason, admin_id=update.effective_user.id)
    action_text = "🔇 PERMANENTLY MUTED" if result["action"] == "permanent_mute" else f"🔇 MUTED for {result['duration']}h"
    warning_text = f" (Warning {result['warning_count']}/{3})" if result['warning_count'] > 0 else ""

    await update.message.reply_text(
        f"{action_text}{warning_text}\n📝 Reason: {reason}"
    )

    # Notify owner
    from config import OWNER_ID
    try:
        target_user = await ensure_user_registered(target_id, None, None)
        await context.bot.send_message(
            OWNER_ID,
            f"🔇 Mute Action\n"
            f"User: {target_user.first_name} (#{target_id})\n"
            f"By: {update.effective_user.first_name}\n"
            f"Reason: {reason}\n"
            f"Status: {result['action']} | Warnings: {result['warning_count']}/3",
        )
    except Exception:
        pass


@mod_or_above
async def unmute_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unmute a user: /unmute @user"""
    target_id = await _extract_target(update, context)
    if not target_id:
        await update.message.reply_text("❌ User specify karo.")
        return

    chat_id = update.effective_chat.id

    # Telegram unmute
    try:
        await context.bot.restrict_chat_member(
            chat_id=chat_id,
            user_id=target_id,
            permissions=ChatPermissions(can_send_messages=True),
        )
    except Exception as e:
        await update.message.reply_text(f"❌ Telegram unmute fail: {e}")
        return

    await unmute_user(target_id, admin_id=update.effective_user.id)
    await update.message.reply_text(f"✅ User #{target_id} unmuted.")


@mod_or_above
async def warn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Warn a user: /warn @user [reason]"""
    target_id = await _extract_target(update, context)
    if not target_id:
        await update.message.reply_text("❌ User specify karo.")
        return

    reason = " ".join(context.args[1:]) if len(context.args) > 1 else "Manual warning"
    result = await warn_user(target_id, reason, admin_id=update.effective_user.id)

    action_text = {
        "temp_mute": f"⚠️ Warning {result['warning_count']}/3 — 24h MUTE",
        "permanent_mute": "🚨 3rd WARNING — PERMANENT MUTE",
    }.get(result["action"], f"Warning {result['warning_count']}/3")

    # Apply Telegram mute too
    if result["action"] in ("temp_mute", "permanent_mute"):
        chat_id = update.effective_chat.id
        try:
            await context.bot.restrict_chat_member(
                chat_id=chat_id, user_id=target_id,
                permissions=ChatPermissions(can_send_messages=False),
            )
        except Exception:
            pass

    await update.message.reply_text(f"{action_text}\n📝 Reason: {reason}")


@mod_or_above
async def unwarn_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reduce warning: /unwarn @user"""
    target_id = await _extract_target(update, context)
    if not target_id:
        await update.message.reply_text("❌ User specify karo.")
        return

    new_count = await reduce_warning(target_id, admin_id=update.effective_user.id)
    await update.message.reply_text(f"✅ Warning reduced. New count: {new_count}/3")


@mod_or_above
async def filter_add_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add filter word: /filter add [word]"""
    if not context.args or len(context.args) < 2 or context.args[0].lower() != "add":
        await update.message.reply_text("Usage: /filter add [word]")
        return

    word = " ".join(context.args[1:]).lower()
    success = await add_filter_word(word, update.effective_user.id)
    if success:
        await update.message.reply_text(f"✅ Filter added: '{word}'")
    else:
        await update.message.reply_text(f"❌ '{word}' already filtered hai.")


@mod_or_above
async def filter_remove_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove filter word: /filter remove [word]"""
    if not context.args or len(context.args) < 2 or context.args[0].lower() != "remove":
        await update.message.reply_text("Usage: /filter remove [word]")
        return

    word = " ".join(context.args[1:]).lower()
    success = await remove_filter_word(word)
    if success:
        await update.message.reply_text(f"✅ Filter removed: '{word}'")
    else:
        await update.message.reply_text(f"❌ '{word}' filter mein nahi mila.")


@mod_or_above
async def filters_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show all filtered words."""
    words = await get_filtered_words()
    if not words:
        await update.message.reply_text("Koi filtered words nahi hai.")
        return
    await update.message.reply_text(f"🚫 Filtered Words ({len(words)}):\n" + ", ".join(words))


@mod_or_above
async def stickers_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle sticker filter."""
    global _sticker_filter_on
    _sticker_filter_on = not _sticker_filter_on
    status = "ON ✅" if _sticker_filter_on else "OFF ❌"
    await update.message.reply_text(f"Sticker filter: {status}")


@mod_or_above
async def mutelog_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show recent mute/warning logs."""
    text = await get_mute_logs()
    await update.message.reply_text(text)


@mod_or_above
async def userlog_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show specific user logs: /userlog @user"""
    target_id = await _extract_target(update, context)
    if not target_id:
        await update.message.reply_text("❌ User specify karo.")
        return
    text = await get_user_logs(target_id)
    await update.message.reply_text(text)
