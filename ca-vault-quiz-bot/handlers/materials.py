"""Material handlers - /addpdf, smart keyword triggers, context-aware redirects."""

import hashlib
import json
import logging
import re

from telegram import Update
from telegram.ext import ContextTypes

from permissions import ensure_user_registered
from database import async_session
from models import PDFIndex
from services.pdf import index_pdf, extract_text_from_pdf, approve_pdf
from services.moderation import (
    check_message_spam, find_material_for_keyword,
    check_channel_subscription, set_force_mute, add_audit_log,
)
from services.ai import classify_message_intent
from config import OWNER_ID, ANNOUNCEMENT_CHANNEL
from constants import SUBJECT_ALIASES

log = logging.getLogger(__name__)


async def addpdf_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Index a PDF: /addpdf (reply to a PDF document message).
    Bot downloads, parses, and sends to owner for approval."""
    if not update.message.reply_to_message or not update.message.reply_to_message.document:
        await update.message.reply_text("❌ Kisi PDF document ko reply karo.")
        return

    doc = update.message.reply_to_message.document
    if not doc.file_name or not doc.file_name.lower().endswith(".pdf"):
        await update.message.reply_text("❌ Sirf PDF files supported hain.")
        return

    await update.message.reply_text("📥 PDF download ho rahi hai... Baki raho!")

    try:
        file = await doc.get_file()
        content = await file.download_as_bytearray()
    except Exception as e:
        await update.message.reply_text(f"❌ Download fail: {e}")
        return

    # Extract text for content analysis
    text = extract_text_from_pdf(bytes(content))

    # Auto-detect subject from filename or text
    subject = None
    for alias, canonical in SUBJECT_ALIASES.items():
        if alias in (doc.file_name or "").lower() or (text and alias in text[:500].lower()):
            subject = canonical
            break

    # Send to owner for approval
    result = await index_pdf(
        file_id=doc.file_id,
        file_name=doc.file_name,
        file_content=bytes(content),
        uploaded_by=update.effective_user.id,
        subject=subject,
    )

    await update.message.reply_text(result["message"])

    # Notify owner
    if result["status"] == "pending_approval":
        from telegram import InlineKeyboardButton, InlineKeyboardMarkup
        btns = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_pdf_{result['pdf_id']}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_pdf_{result['pdf_id']}"),
            ]
        ]
        try:
            await context.bot.send_message(
                OWNER_ID,
                f"📥 New Material Detected!\n"
                f"File: {doc.file_name}\n"
                f"Subject: {subject or 'N/A'}\n"
                f"Uploaded by: {update.effective_user.first_name} (#{update.effective_user.id})",
                reply_markup=InlineKeyboardMarkup(btns),
            )
        except Exception:
            pass


async def handle_material_request(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle smart keyword triggers in group messages.
    Called from the main message handler when a potential keyword is detected."""
    text = update.message.text or ""
    if not text.strip():
        return

    # Check for hashtag-style keywords (#accounts_ch1, #law_notes, etc.)
    hashtag_match = re.findall(r'#(\w+)', text)
    if hashtag_match:
        keyword = hashtag_match[0]
        pdf = await find_material_for_keyword(keyword)
        if pdf:
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            if pdf.channel_message_id and ANNOUNCEMENT_CHANNEL:
                link = f"https://t.me/{ANNOUNCEMENT_CHANNEL.lstrip('@')}/{pdf.channel_message_id}"
                btn = InlineKeyboardButton("📖 Open in Study Channel", url=link)
                await update.message.reply_text(
                    f"📚 Yeh lijiye aapka material:\n📄 {pdf.file_name}",
                    reply_markup=InlineKeyboardMarkup([[btn]]),
                )
                return

    # Check if this is a material request (not just discussion)
    intent = await classify_message_intent(text)
    if intent != "request_material":
        return

    # Try to find material based on subject keywords in the message
    for alias, subject in SUBJECT_ALIASES.items():
        if alias in text.lower():
            pdf = await find_material_for_keyword(alias)
            if pdf:
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                if pdf.channel_message_id and ANNOUNCEMENT_CHANNEL:
                    link = f"https://t.me/{ANNOUNCEMENT_CHANNEL.lstrip('@')}/{pdf.channel_message_id}"
                    btn = InlineKeyboardButton("📖 Open in Study Channel", url=link)
                    await update.message.reply_text(
                        f"📚 {subject} ka material yahan hai:\n📄 {pdf.file_name}",
                        reply_markup=InlineKeyboardMarkup([[btn]]),
                    )
                    return


async def handle_pdf_approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks for PDF approval."""
    query = update.callback_query
    if not query.data or not query.data.startswith("approve_pdf_"):
        return

    await query.answer()
    pdf_id = int(query.data.split("_")[-1])

    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    btns = [
        [
            InlineKeyboardButton("✅ Approve & Publish", callback_data=f"confirm_approve_{pdf_id}"),
            InlineKeyboardButton("❌ Reject", callback_data=f"reject_pdf_{pdf_id}"),
        ]
    ]

    async with async_session() as session:
        pdf = await session.get(PDFIndex, pdf_id)
        if not pdf:
            await query.edit_message_reply_markup(reply_markup=None)
            return

        text = (
            f"📥 <b>PDF Approval</b>\n"
            f"📄 {pdf.file_name}\n"
            f"📚 {pdf.subject or 'N/A'} > {pdf.chapter or 'N/A'}\n"
            f"🔑 Keywords: {pdf.keywords or 'Set your keywords'}"
        )

    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(btns))
