"""
CA Vault Quiz Bot — Main Entry Point
Production-ready Telegram bot for CA Foundation students.
On Render: uses webhook. Locally: uses polling.
"""

import logging
import os
from datetime import datetime, time, timezone, timedelta

from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    PollAnswerHandler,
    ChatMemberHandler,
    filters,
    ContextTypes,
)

from config import (
    BOT_TOKEN, WEBHOOK_URL, OWNER_ID, ANNOUNCEMENT_CHANNEL,
    PORT, DAILY_PIN_TIME, MEGA_QUIZ_DAY,
)
from database import init_db, async_session
from models import User
from permissions import ensure_user_registered

# ── Logging ──
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# IMPORT HANDLERS
# ═══════════════════════════════════════════════════════════════════

from handlers.start import (
    start_cmd, help_cmd, stats_cmd, badges_cmd, refer_cmd, schedule_cmd,
)
from handlers.quiz import quiz_cmd, poll_answer_handler
from handlers.admin import (
    grant_cmd, revoke_cmd, trials_cmd, setrole_cmd,
    broadcast_cmd, pending_cmd, addquestions_cmd,
)
from handlers.mod import (
    mute_cmd, unmute_cmd, warn_cmd, unwarn_cmd,
    filter_add_cmd, filter_remove_cmd, filters_cmd,
    stickers_cmd, mutelog_cmd, userlog_cmd,
)
from handlers.panel import dashboard_cmd, dashboard_callback
from handlers.materials import addpdf_cmd, handle_material_request
from handlers.dm import (
    settime_cmd, settimer_cmd, addchapter_cmd, removechapter_cmd,
    setmode_cmd, reschedule_cmd, setwelcome_cmd, setchannel_cmd,
)
from handlers.mod import _sticker_filter_on


# ═══════════════════════════════════════════════════════════════════
# GROUP MESSAGE HANDLER
# ═══════════════════════════════════════════════════════════════════

async def on_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle all group messages: spam, stickers, force subscribe, material triggers."""
    if not update.effective_message or not update.effective_user:
        return

    user = update.effective_user
    msg = update.effective_message
    chat = update.effective_chat

    if user.is_bot:
        return
    if not chat or chat.type not in ("group", "supergroup"):
        return

    await ensure_user_registered(user.id, user.username, user.first_name)

    # 1. Force Subscribe Check
    if ANNOUNCEMENT_CHANNEL:
        from services.moderation import check_channel_subscription, set_force_mute
        is_sub = await check_channel_subscription(user.id, context.bot)
        if not is_sub:
            try:
                await context.bot.restrict_chat_member(
                    chat.id, user.id,
                    permissions=ChatPermissions(can_send_messages=False),
                )
            except Exception:
                pass
            await set_force_mute(user.id, muted=True)
            try:
                await msg.delete()
            except Exception:
                pass
            try:
                await context.bot.send_message(
                    chat.id,
                    f"🔇 @{user.username or user.first_name}, pehle channel join karo!\n{ANNOUNCEMENT_CHANNEL}",
                )
            except Exception:
                pass
            return

    # 2. Mute check
    async with async_session() as session:
        db_user = await session.get(User, user.id)
        if db_user and db_user.is_muted:
            try:
                await msg.delete()
            except Exception:
                pass
            return

    # 3. Spam / Bad Word Filter
    if msg.text:
        from services.moderation import check_message_spam, warn_user, add_audit_log
        matched_word = await check_message_spam(msg.text)
        if matched_word:
            try:
                await msg.delete()
            except Exception:
                pass
            result = await warn_user(user.id, f"Filtered word: {matched_word}", admin_id=None)
            if result["action"] in ("temp_mute", "permanent_mute"):
                try:
                    await context.bot.restrict_chat_member(
                        chat.id, user.id,
                        permissions=ChatPermissions(can_send_messages=False),
                    )
                except Exception:
                    pass
            await add_audit_log(
                admin_id=None, target_user_id=user.id,
                action_type=result["action"],
                reason=f"Auto-filter: {matched_word}",
                details={"warning_count": result["warning_count"]},
            )
            try:
                await context.bot.send_message(
                    OWNER_ID,
                    f"🚨 Auto-Filter: {user.first_name} (@{user.username}) #{user.id}\n"
                    f"Word: {matched_word} | {result['action']} | W{result['warning_count']}/3\n"
                    f"/unmute {user.id} | /mute {user.id} filter",
                )
            except Exception:
                pass
            return

    # 4. Sticker Filter
    if msg.sticker and _sticker_filter_on:
        try:
            await msg.delete()
        except Exception:
            pass
        return

    # 5. Smart Material Keyword Trigger (hashtag detection)
    if msg.text:
        import re
        if re.findall(r'#\w+', msg.text):
            await handle_material_request(update, context)


# ═══════════════════════════════════════════════════════════════════
# MEMBER JOIN / LEAVE
# ═══════════════════════════════════════════════════════════════════

async def on_member_join(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new member joining the group."""
    if not update.chat_member:
        return
    cm = update.chat_member
    for member in cm.new_chat_members or []:
        if member.is_bot:
            continue
        await ensure_user_registered(member.user.id, member.user.username, member.user.first_name)

        # Note: referral tracking happens via /start command with deep-link, not here
        # Force subscribe check
        if ANNOUNCEMENT_CHANNEL:
            from services.moderation import check_channel_subscription, set_force_mute
            is_sub = await check_channel_subscription(member.user.id, context.bot)
            if not is_sub:
                try:
                    await context.bot.restrict_chat_member(
                        cm.chat.id, member.user.id,
                        permissions=ChatPermissions(can_send_messages=False),
                    )
                except Exception:
                    pass
                await set_force_mute(member.user.id, muted=True)


async def on_member_leave(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle member leaving — referral penalty."""
    if not update.chat_member:
        return
    old = update.chat_member.old_chat_member
    if old and not old.is_bot and old.user:
        from services.gamification import handle_referral_leave
        await handle_referral_leave(old.user.id)


# ═══════════════════════════════════════════════════════════════════
# SCHEDULED JOBS
# ═══════════════════════════════════════════════════════════════════

async def job_daily_pin(context: ContextTypes.DEFAULT_TYPE):
    """Send daily pinned schedule message."""
    from services.scheduler import generate_daily_pin_message
    msg = await generate_daily_pin_message()
    try:
        await context.bot.send_message(OWNER_ID, msg)
    except Exception:
        pass


async def job_daily_topper(context: ContextTypes.DEFAULT_TYPE):
    """Post daily topper badges + shayari."""
    from services.leaderboard import get_daily_topper_text
    text = await get_daily_topper_text()
    if text:
        try:
            await context.bot.send_message(OWNER_ID, text)
        except Exception:
            pass


async def job_check_expired_mutes(context: ContextTypes.DEFAULT_TYPE):
    """Auto-unmute expired mutes."""
    from services.moderation import check_expired_mutes, unmute_user
    expired = await check_expired_mutes()
    for uid in expired:
        await unmute_user(uid, reason="Mute duration expired")
        log.info("Auto-unmuted user %d", uid)


async def job_check_expired_trials(context: ContextTypes.DEFAULT_TYPE):
    """Expire finished trials."""
    from services.scheduler import check_expired_trials
    expired = await check_expired_trials()
    for uid in expired:
        log.info("Trial expired for user %d", uid)


async def job_update_leaderboards(context: ContextTypes.DEFAULT_TYPE):
    """Periodic leaderboard rebuild."""
    from services.leaderboard import update_leaderboard
    for period in ["daily", "weekly", "monthly"]:
        await update_leaderboard(period)


async def job_auto_quiz(context: ContextTypes.DEFAULT_TYPE):
    """Auto-start quiz at scheduled time (auto mode only)."""
    from services.scheduler import get_mode, get_today_schedule, is_mega_quiz_day
    if get_mode() != "auto":
        return

    if await is_mega_quiz_day():
        await _start_mega_quiz(context)
        return

    sched = await get_today_schedule()
    if not sched:
        return

    now = datetime.now(timezone.utc)
    parts = sched.quiz_time.split(":")
    h, m = int(parts[0]), int(parts[1])
    target_min = h * 60 + m
    current_min = now.hour * 60 + now.minute

    if abs(current_min - target_min) <= 5:
        from services.quiz_engine import start_quiz
        quiz = await start_quiz(
            group_id=OWNER_ID,
            subject=sched.subject,
            chapter=sched.chapter,
            quiz_type="daily",
            count=10,
            started_by=OWNER_ID,
        )
        if quiz:
            log.info("Auto quiz started: %s > %s", sched.subject, sched.chapter)


async def _start_mega_quiz(context: ContextTypes.DEFAULT_TYPE):
    """Start Sunday mega quiz."""
    from services.scheduler import get_mega_quiz_chapters
    from services.quiz_engine import start_quiz

    chapters = await get_mega_quiz_chapters()
    if not chapters:
        return

    all_chs = []
    for subject, chs in chapters.items():
        all_chs.extend(chs)

    quiz = await start_quiz(
        group_id=OWNER_ID,
        subject="All",
        chapter=", ".join(all_chs[:3]) + "...",
        quiz_type="mega",
        count=200,
        started_by=OWNER_ID,
        is_mega=True,
    )
    if quiz:
        try:
            await context.bot.send_message(
                OWNER_ID,
                "🏆 SUNDAY MEGA QUIZ STARTED!\n200 Questions | Breaks between subjects",
            )
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════
# ERROR HANDLER
# ═══════════════════════════════════════════════════════════════════

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    log.error("Bot error: %s", context.error, exc_info=context.error)
    try:
        if OWNER_ID:
            await context.bot.send_message(OWNER_ID, f"⚠️ Error: {context.error}")
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════
# POST-INIT
# ═══════════════════════════════════════════════════════════════════

async def post_init(application: Application):
    log.info("Initialising database...")
    await init_db()

    from services.moderation import init_default_filters
    await init_default_filters()

    from services.scheduler import init_default_schedule
    await init_default_schedule()

    # Set owner role
    if OWNER_ID:
        await ensure_user_registered(OWNER_ID, "owner", "Owner")
        async with async_session() as session:
            u = await session.get(User, OWNER_ID)
            if u and u.role != "owner":
                u.role = "owner"
                await session.commit()

    jq = application.job_queue

    # Daily pin
    pin_h, pin_m = map(int, DAILY_PIN_TIME.split(":"))
    jq.run_daily(job_daily_pin, time=time(pin_h, pin_m, 0), name="daily_pin")

    # Daily topper
    jq.run_daily(job_daily_topper, time=time(23, 0, 0), name="daily_topper")

    # Periodic checks
    jq.run_repeating(job_check_expired_mutes, interval=300, first=10, name="check_mutes")
    jq.run_repeating(job_check_expired_trials, interval=3600, first=60, name="check_trials")
    jq.run_repeating(job_update_leaderboards, interval=600, first=120, name="lb_update")
    jq.run_repeating(job_auto_quiz, interval=60, first=30, name="auto_quiz")

    log.info("All jobs registered. Bot ready!")


# ═══════════════════════════════════════════════════════════════════
# WEBHOOK SETUP (for Render)
# ═══════════════════════════════════════════════════════════════════

async def setup_webhook(application: Application):
    if WEBHOOK_URL:
        url = f"{WEBHOOK_URL}/webhook"
        await application.bot.set_webhook(url=url)
        log.info("Webhook set: %s", url)


# ═══════════════════════════════════════════════════════════════════
# BUILD APPLICATION
# ═══════════════════════════════════════════════════════════════════

def build_app() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # Commands
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("stats", stats_cmd))
    app.add_handler(CommandHandler("badges", badges_cmd))
    app.add_handler(CommandHandler("refer", refer_cmd))
    app.add_handler(CommandHandler("schedule", schedule_cmd))
    app.add_handler(CommandHandler("quiz", quiz_cmd))
    app.add_handler(CommandHandler("grant", grant_cmd))
    app.add_handler(CommandHandler("revoke", revoke_cmd))
    app.add_handler(CommandHandler("trials", trials_cmd))
    app.add_handler(CommandHandler("setrole", setrole_cmd))
    app.add_handler(CommandHandler("broadcast", broadcast_cmd))
    app.add_handler(CommandHandler("pending", pending_cmd))
    app.add_handler(CommandHandler("addquestions", addquestions_cmd))
    app.add_handler(CommandHandler("mute", mute_cmd))
    app.add_handler(CommandHandler("unmute", unmute_cmd))
    app.add_handler(CommandHandler("warn", warn_cmd))
    app.add_handler(CommandHandler("unwarn", unwarn_cmd))
    app.add_handler(CommandHandler("filter", filter_add_cmd))
    app.add_handler(CommandHandler("filters", filters_cmd))
    app.add_handler(CommandHandler("stickers", stickers_cmd))
    app.add_handler(CommandHandler("mutelog", mutelog_cmd))
    app.add_handler(CommandHandler("modlogs", mutelog_cmd))
    app.add_handler(CommandHandler("userlog", userlog_cmd))
    app.add_handler(CommandHandler("dashboard", dashboard_cmd))
    app.add_handler(CommandHandler("panel", dashboard_cmd))
    app.add_handler(CommandHandler("addpdf", addpdf_cmd))
    app.add_handler(CommandHandler("settime", settime_cmd))
    app.add_handler(CommandHandler("settimer", settimer_cmd))
    app.add_handler(CommandHandler("addchapter", addchapter_cmd))
    app.add_handler(CommandHandler("removechapter", removechapter_cmd))
    app.add_handler(CommandHandler("setmode", setmode_cmd))
    app.add_handler(CommandHandler("reschedule", reschedule_cmd))
    app.add_handler(CommandHandler("setwelcome", setwelcome_cmd))
    app.add_handler(CommandHandler("setchannel", setchannel_cmd))

    # Callbacks
    app.add_handler(CallbackQueryHandler(dashboard_callback))

    # Poll answers
    app.add_handler(PollAnswerHandler(poll_answer_handler))

    # Group messages
    app.add_handler(MessageHandler(
        filters.TEXT | filters.Sticker.ALL | filters.Document.ALL,
        on_group_message,
    ))

    # Member join/leave
    app.add_handler(ChatMemberHandler(on_member_join, ChatMemberHandler.CHAT_MEMBER))
    app.add_handler(ChatMemberHandler(on_member_leave, ChatMemberHandler.CHAT_MEMBER))

    # Errors
    app.add_error_handler(error_handler)

    return app


# ═══════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    application = build_app()

    if WEBHOOK_URL:
        # Webhook mode for Render
        log.info("Starting in WEBHOOK mode on port %d", PORT)
        import asyncio
        asyncio.run(setup_webhook(application))

        from http.server import HTTPServer, BaseHTTPRequestHandler
        import json

        class WebhookHandler(BaseHTTPRequestHandler):
            def do_POST(self):
                content_length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(content_length)
                update = Update.de_json(json.loads(body), application.bot)
                asyncio.run(application.process_update(update))
                self.send_response(200)
                self.end_headers()

            def do_GET(self):
                if self.path == "/health":
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"OK")
                else:
                    self.send_response(404)
                    self.end_headers()

        server = HTTPServer(("0.0.0.0", PORT), WebhookHandler)
        log.info("Listening on port %d", PORT)
        server.serve_forever()
    else:
        # Polling mode for local dev
        log.info("Starting in POLLING mode")
        application.run_polling(drop_pending_updates=True)
