"""Admin command handlers - /grant, /revoke, /trials, /setrole, /broadcast, /pending, /addquestions."""

import json
import logging

from telegram import Update
from telegram.ext import ContextTypes

from permissions import owner_only, admin_or_above, ensure_user_registered
from sqlalchemy import select

from database import async_session
from models import User
from services.scheduler import grant_trial, revoke_access, get_active_trials
from services.pdf import get_pending_pdfs, approve_pdf, reject_pdf
from services.moderation import add_audit_log
from services.quiz_engine import add_questions_from_ai, get_question_count
from services.ai import generate_quiz_from_text

log = logging.getLogger(__name__)


async def _extract_user_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int | None:
    """Extract user_id from reply or @mention or direct ID."""
    # From reply
    if update.message.reply_to_message and update.message.reply_to_message.from_user:
        return update.message.reply_to_message.from_user.id

    # From @mention or direct ID
    args = context.args or []
    if args:
        arg = args[0]
        if arg.startswith("@"):
            username = arg[1:]
            async with async_session() as session:
                from sqlalchemy import select
                result = await session.execute(
                    select(User).where(User.username == username)
                )
                user = result.scalar_one_or_none()
                return user.user_id if user else None
        elif arg.isdigit():
            return int(arg)

    return None


@admin_or_above
async def grant_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Grant quiz access: /grant @user [1week/2weeks/3weeks/fullfree]"""
    target_id = await _extract_user_id(update, context)
    if not target_id:
        await update.message.reply_text("❌ User specify karo (reply ya @mention ya ID).")
        return

    trial_type = "1week"
    if len(context.args) > 1:
        trial_type = context.args[1].lower()

    valid = ["1week", "2weeks", "3weeks", "fullfree"]
    if trial_type not in valid:
        await update.message.reply_text(f"❌ Invalid trial type. Valid: {', '.join(valid)}")
        return

    result = await grant_trial(target_id, trial_type)
    await update.message.reply_text(result)
    await add_audit_log(
        admin_id=update.effective_user.id,
        target_user_id=target_id,
        action_type="grant_access",
        reason=f"Trial: {trial_type}",
    )


@admin_or_above
async def revoke_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Revoke quiz access: /revoke @user"""
    target_id = await _extract_user_id(update, context)
    if not target_id:
        await update.message.reply_text("❌ User specify karo.")
        return

    result = await revoke_access(target_id)
    await update.message.reply_text(result)
    await add_audit_log(
        admin_id=update.effective_user.id,
        target_user_id=target_id,
        action_type="revoke_access",
        reason="Access revoked by admin",
    )


@admin_or_above
async def trials_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show active trials."""
    text = await get_active_trials()
    await update.message.reply_text(text)


@owner_only
async def setrole_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Set user role: /setrole @user [owner/admin/mod/student]"""
    target_id = await _extract_user_id(update, context)
    if not target_id:
        await update.message.reply_text("❌ User specify karo.")
        return

    if len(context.args) < 2:
        await update.message.reply_text("Usage: /setrole @user [owner/admin/mod/student]")
        return

    new_role = context.args[1].lower()
    valid_roles = ["owner", "admin", "mod", "student"]
    if new_role not in valid_roles:
        await update.message.reply_text(f"❌ Invalid role. Valid: {', '.join(valid_roles)}")
        return

    async with async_session() as session:
        user = await session.get(User, target_id)
        if not user:
            await update.message.reply_text("❌ User not found.")
            return
        old_role = user.role
        user.role = new_role
        await session.commit()

    await update.message.reply_text(f"✅ {user.first_name} ka role: {old_role} → {new_role}")
    await add_audit_log(
        admin_id=update.effective_user.id,
        target_user_id=target_id,
        action_type="role_change",
        reason=f"{old_role} → {new_role}",
    )


@owner_only
async def broadcast_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Broadcast a message: /broadcast [text]"""
    if not context.args:
        await update.message.reply_text("Usage: /broadcast [message]")
        return

    message = " ".join(context.args)
    sent_count = 0

    async with async_session() as session:
        result = await session.execute(select(User))
        users = result.scalars().all()

        for u in users:
            try:
                await context.bot.send_message(chat_id=u.user_id, text=f"📢 {message}")
                sent_count += 1
            except Exception:
                pass  # User hasn't started the bot

    await update.message.reply_text(f"✅ Broadcast sent to {sent_count} users.")


@admin_or_above
async def pending_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show pending PDF approvals with inline buttons."""
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    pdfs = await get_pending_pdfs()
    if not pdfs:
        await update.message.reply_text("✅ Koi pending PDF nahi hai.")
        return

    for pdf in pdfs[:5]:  # Show max 5
        btns = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_pdf_{pdf.pdf_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_pdf_{pdf.pdf_id}"),
            ]
        ]
        text = (
            f"📥 <b>Pending PDF</b>\n"
            f"📄 File: {pdf.file_name}\n"
            f"📚 Subject: {pdf.subject or 'N/A'}\n"
            f"📑 Chapter: {pdf.chapter or 'N/A'}\n"
            f"👤 Uploaded by: #{pdf.uploaded_by}\n"
            f"🔑 Keywords: {pdf.keywords or 'N/A'}"
        )
        await update.message.reply_text(
            text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(btns)
        )


@owner_only
async def addquestions_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add questions from text file or message: /addquestions [subject] [chapter]
    Must reply to a message/file containing questions."""
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /addquestions [subject] [chapter] (reply to text/file)")
        return

    subject = context.args[0]
    chapter = " ".join(context.args[1:])

    # Resolve subject alias
    from constants import SUBJECT_ALIASES
    subject = SUBJECT_ALIASES.get(subject.lower(), subject)

    if not update.message.reply_to_message:
        await update.message.reply_text("❌ Kisi message ya file ko reply karo.")
        return

    reply = update.message.reply_to_message
    text_content = None

    if reply.document:
        try:
            file = await reply.document.get_file()
            content = await file.download_as_bytearray()
            text_content = content.decode("utf-8", errors="ignore")
        except Exception as e:
            await update.message.reply_text(f"❌ File read nahi ho payi: {e}")
            return
    elif reply.text:
        text_content = reply.text
    else:
        await update.message.reply_text("❌ Text ya document reply karo.")
        return

    await update.message.reply_text(f"🔄 AI se {subject} > {chapter} ke questions generate ho rahe hain... Baki raho!")

    questions = await generate_quiz_from_text(text_content, subject, chapter, count=20)
    if not questions:
        await update.message.reply_text("❌ AI se questions generate nahi ho paaye. Raw text format check karo.")
        return

    added = await add_questions_from_ai(questions, subject, chapter, source="ai")
    await update.message.reply_text(f"✅ {added} questions successfully add ho gaye bank mein! 🎯")
    await add_audit_log(
        admin_id=update.effective_user.id,
        target_user_id=None,
        action_type="questions_added",
        reason=f"{added} Qs for {subject} > {chapter}",
    )
