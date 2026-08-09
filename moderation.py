import asyncio
from telegram import Update, ChatPermissions
from telegram.ext import ContextTypes
import config
import database

MOTIVATIONAL_QUOTES = [
    "“The future depends on what you do today.” — CA Aspirant",
    "“Hard work beats talent when talent doesn't work hard!”",
    "“Focus on your goal, ICAI Foundation is yours to conquer! 🚀”"
]

async def handle_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Greets new members and auto-purges welcome message after 60 seconds."""
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        
        await database.get_or_create_user(member.id, member.username or "")
        
        quote = MOTIVATIONAL_QUOTES[hash(member.id) % len(MOTIVATIONAL_QUOTES)]
        msg = await update.message.reply_text(
            f"Welcome @{member.username or member.first_name}! 🔥\n\n{quote}"
        )
        
        # Schedule message deletion after 60 seconds
        context.job_queue.run_once(
            delete_message_job, 
            60, 
            data={"chat_id": msg.chat_id, "message_id": msg.message_id}
        )

async def delete_message_job(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    try:
        await context.bot.delete_message(
            chat_id=job.data["chat_id"], 
            message_id=job.data["message_id"]
        )
    except Exception:
        pass

async def enforce_force_sub(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Restricts users if they haven't joined the main channel."""
    user = update.effective_user
    if not user or user.id == config.OWNER_ID:
        return True

    try:
        member = await context.bot.get_chat_member(config.MAIN_CHANNEL_ID, user.id)
        if member.status in ['creator', 'administrator', 'member']:
            return True
    except Exception:
        pass

    # Restrict User Permissions
    try:
        await context.bot.restrict_chat_member(
            chat_id=update.effective_chat.id,
            user_id=user.id,
            permissions=ChatPermissions(can_send_messages=False)
        )
        await update.message.reply_text(
            f"⚠️ @{user.username or user.first_name}, Please join our main channel {config.MAIN_CHANNEL_ID} to unmute yourself!"
        )
    except Exception:
        pass
    return False
