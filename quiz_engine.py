import asyncio
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
import database

class QuizEngine:
    def __init__(self):
        self.active_quizzes = {}

    async def send_question(self, chat_id: int, context: ContextTypes.DEFAULT_TYPE, question_data: dict, timer_sec: int = 30):
        """Sends a quiz poll with dynamic open period timer."""
        msg = await context.bot.send_poll(
            chat_id=chat_id,
            question=question_data["question"],
            options=question_data["options"],
            type="quiz",
            correct_option_id=question_data["correct_option"],
            open_period=timer_sec,
            is_anonymous=False,
            explanation=question_data.get("explanation", "Keep revising!")
        )
        return msg.poll.id

    async def handle_poll_answer(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        answer = update.poll_answer
        user_id = answer.user.id
        
        # Award XP for attempting quiz
        xp_gain = 4
        await database.update_user_xp(user_id, xp_gain)

quiz_engine = QuizEngine()
