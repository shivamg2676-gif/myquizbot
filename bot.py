import logging
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    PollAnswerHandler,
    filters,
    ContextTypes,
)

import config
import database
import moderation
import ai_engine
import quiz_engine

logging.basicConfig(level=logging.INFO)

# --- Command Handlers ---

async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await database.get_or_create_user(update.effective_user.id, update.effective_user.username or "")
    await update.message.reply_text(
        "🏛️ **Welcome to CA Vault Quiz Bot!**\n\nYour All-in-One CA Foundation Practice Companion."
    )

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    user = await database.get_or_create_user(user_id)
    
    help_text = "📜 **Super Admin Master Help Menu**\n\n"
    help_text += "• `/dashboard` - Open Interactive Admin Control Panel\n"
    help_text += "• `/mute @user` - Mute a user instantly\n"
    help_text += "• `/unmute @user` - Unmute a user\n"
    help_text += "• `/grant @user [1week/fullfree]` - Grant quiz access\n"
    help_text += "• `/settime [HH:MM]` - Change today's quiz timing\n"
    help_text += "• `/addpdf` - Reply to a PDF to index it to Vault\n"
    
    await update.message.reply_text(help_text)

async def dashboard_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != config.OWNER_ID:
        return
    
    keyboard = [
        [InlineKeyboardButton("🛡️ Moderation", callback_data="dash_mod"),
         InlineKeyboardButton("👥 Access & Trials", callback_data="dash_access")],
        [InlineKeyboardButton("📊 Audit Logs", callback_data="dash_logs"),
         InlineKeyboardButton("⚙️ Settings", callback_data="dash_settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("🎛️ **CA Vault Owner Dashboard:**", reply_markup=reply_markup)

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    # 1. Force Sub Enforcement
    allowed = await moderation.enforce_force_sub(update, context)
    if not allowed:
        return

    # 2. Smart Context Check for Study Materials
    text = update.message.text
    if "#" in text or "pdf" in text.lower() or "notes" in text.lower():
        is_demand = await ai_engine.ai_engine.analyze_context(text)
        if is_demand:
            await update.message.reply_text(
                "📚 **Study Material Request Detected!**\nAccess our official channel repository:",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("📖 Open Study Vault Channel", url=f"https://t.me/{config.STUDY_CHANNEL_ID.replace('@', '')}")]
                ])
            )

# --- Web Server for Render 24/7 Health Check ---
async def handle_health(request):
    return web.Response(text="CA Vault Bot is running live 24/7!")

# --- Async Lifecycle Hook (Initializes DB & Web Server cleanly inside PTB Loop) ---
async def post_init(app: Application):
    # 1. Database Initialize
    await database.init_db()
    logging.info("Database initialized successfully.")

    # 2. Start Aiohttp Server for Render 24/7 Ping
    web_app = web.Application()
    web_app.router.add_get("/", handle_health)
    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", config.PORT)
    await site.start()
    logging.info(f"Health check server running on port {config.PORT}")

def main():
    # Build Application with post_init Hook
    app = (
        Application.builder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .build()
    )

    # Register Handlers
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(CommandHandler("dashboard", dashboard_cmd))
    
    app.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, moderation.handle_new_member))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))
    app.add_handler(PollAnswerHandler(quiz_engine.quiz_engine.handle_poll_answer))

    logging.info("Starting Telegram Bot Polling...")
    app.run_polling()

if __name__ == "__main__":
    main()
    
