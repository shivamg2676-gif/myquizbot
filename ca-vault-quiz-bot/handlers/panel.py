"""Interactive Dashboard with Rose-Bot style inline buttons.

Handles:
  /dashboard, /panel, callback queries for all inline buttons.
"""

import logging

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from permissions import owner_only, mod_or_above, ensure_user_registered
from services.moderation import get_filtered_words, get_mute_logs
from services.scheduler import get_week_schedule, get_today_schedule, get_active_trials
from services.quiz_engine import get_question_count
from database import async_session
from models import User
from sqlalchemy import select, func
from config import OWNER_ID, ROLE_OWNER, ROLE_ADMIN, ROLE_MOD

log = logging.getLogger(__name__)


@owner_only
async def dashboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Open the main dashboard with inline buttons."""
    is_dm = update.effective_chat and update.effective_chat.type == "private"
    chat_id = update.effective_chat.id

    total_users = 0
    total_quizzes = 0
    total_questions = 0

    async with async_session() as session:
        total_users = (await session.execute(select(func.count(User.user_id)))).scalar_one() or 0
        total_quizzes = (await session.execute(select(func.count(User.user_id)).where(User.total_quizzes > 0))).scalar_one() or 0

    for subj in ["Accounts", "Law", "Economics", "Quantitative Aptitude"]:
        total_questions += await get_question_count(subj)

    text = (
        f"📊 <b>CA VAULT DASHBOARD</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"👥 Total Users: {total_users}\n"
        f"📝 Active Quiz Takers: {total_quizzes}\n"
        f"📚 Questions in Bank: {total_questions}\n"
    )

    keyboard = [
        [
            InlineKeyboardButton("🛡️ Moderation", callback_data="dash_moderation"),
            InlineKeyboardButton("👥 Access & Trials", callback_data="dash_trials"),
        ],
        [
            InlineKeyboardButton("📋 Audit Logs", callback_data="dash_audit"),
            InlineKeyboardButton("📅 Schedule", callback_data="dash_schedule"),
        ],
        [
            InlineKeyboardButton("⚙️ Bot Settings", callback_data="dash_settings"),
            InlineKeyboardButton("📥 Pending PDFs", callback_data="dash_pdfs"),
        ],
    ]

    await update.message.reply_text(
        text, parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def dashboard_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all dashboard inline button callbacks."""
    query = update.callback_query
    await query.answer()

    data = query.data
    user = update.effective_user

    # Only owner/admin can use dashboard
    if user.id != OWNER_ID:
        async with async_session() as session:
            u = await session.get(User, user.id)
            if not u or u.role not in (ROLE_ADMIN, ROLE_MOD):
                await query.answer("⛔ No permission", show_alert=True)
                return

    if data == "dash_moderation":
        await _show_moderation_panel(query, context)
    elif data == "dash_trials":
        await _show_trials_panel(query, context)
    elif data == "dash_audit":
        await _show_audit_panel(query, context)
    elif data == "dash_schedule":
        await _show_schedule_panel(query, context)
    elif data == "dash_settings":
        await _show_settings_panel(query, context)
    elif data == "dash_pdfs":
        await _show_pdfs_panel(query, context)
    elif data.startswith("approve_pdf_"):
        pdf_id = int(data.split("_")[-1])
        from services.pdf import approve_pdf as do_approve
        await do_approve(pdf_id)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.answer("✅ PDF approved!", show_alert=True)
    elif data.startswith("reject_pdf_"):
        pdf_id = int(data.split("_")[-1])
        from services.pdf import reject_pdf as do_reject
        await do_reject(pdf_id)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.answer("❌ PDF rejected.", show_alert=True)
    elif data == "back_to_dashboard":
        # Re-send main dashboard
        keyboard = [
            [
                InlineKeyboardButton("🛡️ Moderation", callback_data="dash_moderation"),
                InlineKeyboardButton("👥 Access & Trials", callback_data="dash_trials"),
            ],
            [
                InlineKeyboardButton("📋 Audit Logs", callback_data="dash_audit"),
                InlineKeyboardButton("📅 Schedule", callback_data="dash_schedule"),
            ],
            [
                InlineKeyboardButton("⚙️ Bot Settings", callback_data="dash_settings"),
                InlineKeyboardButton("📥 Pending PDFs", callback_data="dash_pdfs"),
            ],
        ]
        await query.edit_message_text(
            "📊 <b>CA VAULT DASHBOARD</b>\nMain menu:",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


async def _show_moderation_panel(query, context):
    words = await get_filtered_words()
    word_count = len(words)
    from handlers.mod import _sticker_filter_on

    text = (
        f"🛡️ <b>MODERATION PANEL</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"🚫 Filtered Words: {word_count}\n"
        f"🖼 Sticker Filter: {'ON ✅' if _sticker_filter_on else 'OFF ❌'}\n\n"
        f"Commands:\n"
        f"  /filter add [word]\n"
        f"  /filter remove [word]\n"
        f"  /filters — Sab words dekho\n"
        f"  /stickers — Toggle sticker filter\n"
        f"  /mutelog — Recent mute logs"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_dashboard")]]
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_trials_panel(query, context):
    text = await get_active_trials()
    keyboard = [
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_dashboard")],
    ]
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_audit_panel(query, context):
    text = await get_mute_logs(limit=15)
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_dashboard")]]
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_schedule_panel(query, context):
    text = await get_week_schedule()
    keyboard = [
        [
            InlineKeyboardButton("🔄 Reschedule", callback_data="schedule_reschedule"),
        ],
        [InlineKeyboardButton("🔙 Back", callback_data="back_to_dashboard")],
    ]
    try:
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
    except Exception:
        await query.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_settings_panel(query, context):
    text = (
        f"⚙️ <b>BOT SETTINGS</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"DM Commands:\n"
        f"  /settime [HH:MM]\n"
        f"  /settimer [secs]\n"
        f"  /addchapter [Subject] [Chapter]\n"
        f"  /removechapter [Subject] [Chapter]\n"
        f"  /setmode [auto/manual]\n"
        f"  /reschedule\n"
        f"  /setwelcome [text]\n"
        f"  /setchannel [link]"
    )
    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_dashboard")]]
    await query.edit_message_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))


async def _show_pdfs_panel(query, context):
    from services.pdf import get_pending_pdfs
    pdfs = await get_pending_pdfs()

    if not pdfs:
        text = "✅ Koi pending PDF nahi hai."
        keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_dashboard")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    for pdf in pdfs[:5]:
        btns = [
            [
                InlineKeyboardButton("✅ Approve", callback_data=f"approve_pdf_{pdf.pdf_id}"),
                InlineKeyboardButton("❌ Reject", callback_data=f"reject_pdf_{pdf.pdf_id}"),
            ],
            [InlineKeyboardButton("🔙 Back", callback_data="back_to_dashboard")],
        ]
        text = (
            f"📥 <b>Pending PDF</b>\n"
            f"📄 {pdf.file_name}\n"
            f"📚 {pdf.subject or 'N/A'} › {pdf.chapter or 'N/A'}\n"
            f"👤 #{pdf.uploaded_by}\n"
            f"🔑 {pdf.keywords or 'N/A'}"
        )
        await query.message.reply_text(text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(btns))

    keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="back_to_dashboard")]]
    await query.message.reply_text("PDF panel loaded above.", reply_markup=InlineKeyboardMarkup(keyboard))
