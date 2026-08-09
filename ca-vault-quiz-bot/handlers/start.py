"""Handlers for /start and /help commands."""

import logging
import random

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes

from config import OWNER_ID, ROLE_OWNER, ROLE_ADMIN, ROLE_MOD, ROLE_STUDENT
from permissions import ensure_user_registered, _get_user_role
from constants import WELCOME_QUOTES, BADGES
from services.gamification import get_user_badges

log = logging.getLogger(__name__)


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start - register user and send welcome message."""
    user = update.effective_user
    if not user:
        return

    await ensure_user_registered(user.id, user.username, user.first_name)

    # Referral tracking via deep-link
    if context.args:
        payload = context.args[0]
        if payload.startswith("ref_"):
            ref_code = payload[4:]
            from sqlalchemy import select
            from database import async_session
            from models import User
            async with async_session() as session:
                result = await session.execute(select(User).where(User.referral_code == ref_code))
                referrer = result.scalar_one_or_none()
                if referrer and referrer.user_id != user.id:
                    from services.gamification import process_referral
                    await process_referral(referrer.user_id, user.id)

    quote = random.choice(WELCOME_QUOTES)
    text = (
        f"🏛️ <b>CA Vault Quiz Bot</b>\n\n"
        f"Welcome, {user.first_name or 'Student'}! 👋\n"
        f"\n{quote}\n\n"
        f"📚 /help — Sab commands dekhne ke liye\n"
        f"🏆 /leaderboard — Rankings dekho\n"
        f"📝 /quiz — Quiz shuru karo\n"
        f"📊 /stats — Apna stats dekho"
    )

    await update.message.reply_text(text, parse_mode="HTML")

    # If in a group, send motivational message that auto-deletes
    if update.effective_chat and update.effective_chat.type in ["group", "supergroup"]:
        welcome_msg = random.choice(WELCOME_QUOTES)
        sent = await update.message.reply_text(f"✨ {welcome_msg}")
        # Schedule deletion after 60 seconds
        context.job_queue.run_once(
            _delete_message,
            60,
            data={"chat_id": sent.chat_id, "message_id": sent.message_id},
        )


async def _delete_message(context: ContextTypes.DEFAULT_TYPE):
    """Job callback to delete a message."""
    data = context.job.data
    try:
        await context.bot.delete_message(chat_id=data["chat_id"], message_id=data["message_id"])
    except Exception:
        pass


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Role-based /help command - shows different commands based on user role."""
    user = update.effective_user
    if not user:
        return

    role = await _get_user_role(user.id)
    is_dm = update.effective_chat and update.effective_chat.type == "private"

    text = "🖥️ <b>CA VAULT QUIZ BOT — HELP MENU</b>\n" + "━" * 32 + "\n\n"

    # Available to all
    text += "📖 <b>STUDENT COMMANDS</b>\n"
    text += "  /quiz — Quiz participate karo\n"
    text += "  /stats — Apna XP, level, streak dekho\n"
    text += "  /badges — Apne badges dekho\n"
    text += "  /leaderboard — Rankings dekho\n"
    text += "  /refer — Apna referral link lo\n"
    text += "  /schedule — Aaj ka schedule dekho\n\n"

    if role in (ROLE_MOD, ROLE_ADMIN, ROLE_OWNER):
        text += "🛡️ <b>MODERATION</b>\n"
        text += "  /mute @user — User mute karo\n"
        text += "  /unmute @user — Mute hatao\n"
        text += "  /warn @user — Warning do\n"
        text += "  /unwarn @user — Warning kam karo\n"
        text += "  /filter add [word] — Naya filter add karo\n"
        text += "  /filter remove [word] — Filter hatao\n"
        text += "  /filters — Sab filters dekho\n"
        text += "  /stickers — Sticker filter on/off\n"
        text += "  /mutelog — Mute/warning logs\n"
        text += "  /userlog @user — User ki activity\n\n"

    if role in (ROLE_ADMIN, ROLE_OWNER):
        text += "👥 <b>ACCESS & TRIALS</b>\n"
        text += "  /grant @user [1week/2weeks/fullfree]\n"
        text += "  /revoke @user — Access cancel\n"
        text += "  /trials — Active trials dekho\n"
        text += "  /setrole @user [role] — Role change\n\n"

    if role == ROLE_OWNER:
        text += "👑 <b>OWNER CONTROLS</b>\n"
        text += "  /dashboard ya /panel — Control panel\n"
        text += "  /settime [HH:MM] — Quiz time change\n"
        text += "  /settimer [secs] — Live timer change\n"
        text += "  /addchapter [Subject] [Chapter]\n"
        text += "  /removechapter [Subject] [Chapter]\n"
        text += "  /setmode [auto/manual]\n"
        text += "  /reschedule — Schedule rearrange\n"
        text += "  /addpdf (reply to PDF) — PDF index\n"
        text += "  /setwelcome [text] — Welcome message set\n"
        text += "  /setchannel [link] — Channel link set\n"
        text += "  /broadcast [text] — Group mein broadcast\n"
        text += "  /pending — Pending PDFs approve\n"
        text += "  /addquestions (reply to file) — Qs add from text\n"

    await update.message.reply_text(text, parse_mode="HTML")


async def stats_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's personal stats."""
    user = update.effective_user
    if not user:
        return

    from database import async_session
    from models import User

    async with async_session() as session:
        u = await session.get(User, user.id)
        if not u:
            await update.message.reply_text("Pehle /start karo!")
            return

        badges = await get_user_badges(user.id)
        badge_str = " ".join([b["emoji"] for b in badges]) if badges else "Koi badge nahi"

        text = (
            f"📊 <b>APNA STATS</b>\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"👤 Name: {u.first_name or 'Unknown'}\n"
            f"🏷 Username: @{u.username or 'N/A'}\n"
            f"🎖 Role: {u.role.title()}\n"
            f"⭐ XP: {u.xp}  |  📈 Level: {u.level}\n"
            f"🔥 Streak: {u.streak_count} days\n"
            f"📝 Quizzes: {u.total_quizzes}\n"
            f"✅ Correct: {u.total_correct}\n"
            f"❌ Wrong: {u.total_wrong}\n"
            f"🏅 Badges: {badge_str}"
        )

    await update.message.reply_text(text, parse_mode="HTML")


async def badges_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's earned badges."""
    user = update.effective_user
    if not user:
        return

    badges = await get_user_badges(user.id)
    if not badges:
        await update.message.reply_text("Abhi koi badge nahi mila. Quizzes dene shuru karo! 🎯")
        return

    lines = ["🏅 <b>YOUR BADGES</b>", "━" * 25]
    for b in badges:
        lines.append(f"{b['emoji']} {b['name']}: {b['desc']}")

    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def refer_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show user's referral link."""
    user = update.effective_user
    if not user:
        return

    from database import async_session
    from models import User

    async with async_session() as session:
        u = await session.get(User, user.id)
        if not u or not u.referral_code:
            await update.message.reply_text("Pehle /start karo!")
            return

    text = (
        f"🤝 <b>REFERRAL LINK</b>\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Apna link share karo aur +20 XP kamao!\n\n"
        f"🔗 https://t.me/{context.bot.username}?start=ref_{u.referral_code}\n\n"
        f"Dost join karega = +20 XP\n"
        f"Dost leave karega = -20 XP (Referral Shield)\n"
    )
    await update.message.reply_text(text, parse_mode="HTML")


async def schedule_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show today's schedule."""
    from services.scheduler import get_today_schedule, generate_daily_pin_message

    msg = await generate_daily_pin_message()
    await update.message.reply_text(msg)
