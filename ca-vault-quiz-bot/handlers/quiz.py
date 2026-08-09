"""Handlers for quiz commands - /quiz, /quiz Law 10, answer processing."""

import logging
import time

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, ConversationHandler

from config import OWNER_ID
from constants import SUBJECT_ALIASES, QUESTION_TYPES, QTYPE_MCQ, QTYPE_FILL_BLANK, QTYPE_ONE_WORD, QTYPE_MATCH
from database import async_session
from models import User, ActiveQuiz
from permissions import ensure_user_registered
from services import quiz_engine, gamification, leaderboard, ai

log = logging.getLogger(__name__)

# Conversation states
WAITING_ANSWER = 0

# Track per-question correct streaks (in-memory, resets per quiz)
_correct_streaks: dict[int, int] = {}  # user_id -> streak count


async def quiz_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /quiz [subject] [count] or /quiz to use today's schedule."""
    user = update.effective_user
    if not user:
        return

    await ensure_user_registered(user.id, user.username, user.first_name)

    chat = update.effective_chat
    if not chat or chat.type == "private":
        await update.message.reply_text("❌ Yeh command sirf group mein kaam karta hai.")
        return

    # Check if user can start quiz
    async with async_session() as session:
        db_user = await session.get(User, user.id)
        if not db_user:
            return

        # Only owner/admin/trial users can start
        if user.id != OWNER_ID and db_user.role not in ("admin", "mod") and not db_user.can_start_quiz:
            # Send approval request to owner's DM
            try:
                await context.bot.send_message(
                    OWNER_ID,
                    f"📩 Quiz Start Request\n"
                    f"User: {user.first_name} (@{user.username})\n"
                    f"Group: {chat.title}\n"
                    f"Command: {update.message.text}\n\n"
                    f"Approve karne ke liye: /grant {user.id} 1week",
                )
            except Exception:
                pass
            await update.message.reply_text(
                "⏳ Quiz start request owner ko bhej di gayi hai. Approval ka wait karo."
            )
            return

        # Check if already muted
        if db_user.is_muted:
            await update.message.reply_text("🔇 Aap muted hain. Mute lift hone ke baad try karo.")
            return

    # Check if a quiz is already active in this group
    existing = await quiz_engine.get_active_quiz(chat.id)
    if existing:
        await update.message.reply_text(
            f"⚠️ Ek quiz already chal raha hai! (Q{existing.current_index + 1}/{existing.total_questions})"
        )
        return

    # Parse arguments: /quiz [subject] [count] or /quiz
    subject = None
    count = 10
    args = context.args or []

    if args:
        resolved = SUBJECT_ALIASES.get(args[0].lower())
        if resolved:
            subject = resolved
            if len(args) > 1 and args[1].isdigit():
                count = min(int(args[1]), 100)

    # If no subject given, use today's schedule
    if not subject:
        from services.scheduler import get_today_schedule
        sched = await get_today_schedule()
        if sched:
            subject = sched.subject
        else:
            await update.message.reply_text(
                "❌ Subject specify karo ya schedule set karo.\nUsage: /quiz Law 10"
            )
            return

    # Start quiz
    chapter = None
    quiz = await quiz_engine.start_quiz(
        group_id=chat.id,
        subject=subject,
        chapter=chapter,
        quiz_type="chapter",
        count=count,
        started_by=user.id,
    )

    if not quiz:
        await update.message.reply_text(
            f"❌ {subject} ke liye questions bank mein nahi mil paaye. Pehle questions add karo."
        )
        return

    # Send quiz start message
    text = (
        f"📝 <b>QUIZ STARTED!</b>\n"
        f"📚 Subject: {subject}\n"
        f"📊 Questions: {quiz.total_questions}\n"
        f"⏱ Timer: {quiz.timer_seconds}s per question\n"
        f"━━━━━━━━━━━━━━━━━━\n"
        f"Get ready! Pehla question aa raha hai... 🚀"
    )
    await update.message.reply_text(text, parse_mode="HTML")

    # Set group permissions: mute all members (focus mode)
    try:
        await context.bot.set_chat_permissions(
            chat.id,
            {"can_send_messages": False},
        )
        # Allow the bot to send messages
        await context.bot.promote_chat_member(chat.id, context.bot.id, can_post_messages=True)
    except Exception as e:
        log.warning("Could not set focus mode: %s", e)

    # Schedule first question
    context.job_queue.run_once(
        _send_next_question,
        3,  # 3 second delay before first question
        data={"quiz_id": quiz.quiz_id, "chat_id": chat.id},
    )

    # Log
    from services.moderation import add_audit_log
    await add_audit_log(
        admin_id=user.id, target_user_id=None,
        action_type="quiz_start",
        reason=f"{subject} quiz, {count} Qs",
    )


async def _send_next_question(context: ContextTypes.DEFAULT_TYPE):
    """Job: send the next question in an active quiz."""
    data = context.job.data
    quiz_id = data["quiz_id"]
    chat_id = data["chat_id"]

    async with async_session() as session:
        quiz = await session.get(ActiveQuiz, quiz_id)
        if not quiz or quiz.status != "active":
            return

    question = await quiz_engine.get_current_question(quiz)
    if not question:
        # Quiz is over, show results
        await _finish_quiz(context, quiz_id, chat_id)
        return

    # Format and send the question
    msg_text = quiz_engine._format_question_message(
        question, quiz.current_index, quiz.total_questions, quiz.timer_seconds
    )

    # Build poll for MCQ/True-False/Match
    if question.question_type in (QTYPE_MCQ, QTYPE_TRUE_FALSE, QTYPE_MATCH):
        options = quiz_engine._build_poll_options(question)
        if options:
            # Send as poll
            poll_msg = await context.bot.send_poll(
                chat_id=chat_id,
                question=msg_text,
                options=options,
                type="quiz",
                correct_option_id=_get_correct_option_index(question, options),
                is_anonymous=False,
                open_period=quiz.timer_seconds,
            )
            # Store poll_id in quiz context for answer tracking
            context.user_data[f"poll_{poll_msg.poll.id}"] = {
                "quiz_id": quiz_id,
                "question_idx": quiz.current_index,
                "question_id": question.question_id,
                "correct": question.correct_answer.strip().upper(),
                "start_time": time.time(),
            }
            # Schedule timer expiry + next question
            context.job_queue.run_once(
                _question_timer_expired,
                quiz.timer_seconds + 1,
                data={"quiz_id": quiz_id, "chat_id": chat_id},
            )
            return

    # For fill-in-the-blank and one-word: send as text message
    sent = await context.bot.send_message(chat_id=chat_id, text=msg_text)
    context.user_data[f"textq_{sent.message_id}"] = {
        "quiz_id": quiz_id,
        "question_idx": quiz.current_index,
        "question_id": question.question_id,
        "correct": question.correct_answer.strip().upper(),
        "question_type": question.question_type,
        "start_time": time.time(),
    }

    # Timer for text-based questions
    context.job_queue.run_once(
        _question_timer_expired,
        quiz.timer_seconds + 1,
        data={"quiz_id": quiz_id, "chat_id": chat_id},
    )


def _get_correct_option_index(question, options: list[str]) -> int:
    """Get the correct option index for Telegram poll."""
    correct = question.correct_answer.strip().upper()
    for i, opt in enumerate(options):
        if opt.strip().upper().startswith(f"{correct})"):
            return i
    return 0


async def poll_answer_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle poll answer updates for quiz scoring."""
    poll_answer = update.poll_answer
    if not poll_answer or not poll_answer.user:
        return

    user_id = poll_answer.user.id
    poll_id = poll_answer.poll_id

    # Look up the poll context
    poll_key = f"poll_{poll_id}"
    poll_data = context.user_data.get(poll_key)
    if not poll_data:
        return

    quiz_id = poll_data["quiz_id"]
    question_idx = poll_data["question_idx"]
    correct = poll_data["correct"]
    start_time = poll_data["start_time"]

    # Determine if correct
    if poll_answer.option_ids:
        selected_idx = poll_answer.option_ids[0]
        # Map option index to letter
        letters = ["A", "B", "C", "D"]
        selected_letter = letters[selected_idx] if selected_idx < len(letters) else "?"
        is_correct = selected_letter == correct
    else:
        selected_letter = None
        is_correct = False

    time_taken_ms = int((time.time() - start_time) * 1000)

    # Record response and award XP
    await quiz_engine.record_response(
        quiz_id=quiz_id, user_id=user_id, question_index=question_idx,
        selected_answer=selected_letter, is_correct=is_correct,
        time_taken_ms=time_taken_ms,
    )

    # Update streak
    if is_correct:
        _correct_streaks[user_id] = _correct_streaks.get(user_id, 0) + 1
        xp, level, leveled_up = await gamification.award_xp(user_id, True)
        await gamification.update_streak(user_id)

        feedback = gamification.get_correct_feedback(_correct_streaks[user_id])
        streak_info = f" 🔥 {_correct_streaks[user_id]} Streak!" if _correct_streaks.get(user_id, 0) >= 3 else ""
        level_msg = f" | 🎉 Level Up! Lv.{level}" if leveled_up else ""

        try:
            await context.bot.send_message(
                chat_id=user_id,
                text=f"✅ {feedback}{streak_info}{level_msg}",
            )
        except Exception:
            pass
    else:
        _correct_streaks[user_id] = 0
        xp, level, leveled_up = await gamification.award_xp(user_id, False)

        # Send explanation in DM
        async with async_session() as session:
            from models import Question
            q = await session.get(Question, poll_data["question_id"])
            explanation = q.explanation if q else None
            q_text = q.question_text if q else ""

        expl = await ai.explain_answer(q_text, correct, selected_letter or "No answer", explanation)
        if expl:
            try:
                await context.bot.send_message(
                    chat_id=user_id,
                    text=f"❌ Galat jawab!\n\n💡 {expl}",
                )
            except Exception:
                pass


async def _question_timer_expired(context: ContextTypes.DEFAULT_TYPE):
    """Job: called when a question's timer expires. Advance to next question."""
    data = context.job.data
    quiz_id = data["quiz_id"]
    chat_id = data["chat_id"]

    async with async_session() as session:
        quiz = await session.get(ActiveQuiz, quiz_id)
        if not quiz or quiz.status != "active":
            return

        # Check if this is a mega quiz break point
        if quiz.is_mega:
            from constants import MEGA_QUIZ_CONFIG
            break_interval = MEGA_QUIZ_CONFIG["break_minutes"] * 60
            questions_per_subject = list(MEGA_QUIZ_CONFIG.values())
            # Simple break check: every 40/60 questions, take a 10 min break
            subject_counts = [40, 40, 60, 60]  # Acc, Quant, Law, Eco
            cumulative = 0
            for sc in subject_counts:
                cumulative += sc
                if quiz.current_index + 1 == cumulative:
                    # Send break message
                    await context.bot.send_message(
                        chat_id=chat_id,
                        text=f"☕ BREAK TIME — 10 Minutes\nNext subject starts soon. Relax!"
                    )
                    # Unmute group during break
                    try:
                        await context.bot.set_chat_permissions(chat_id, {"can_send_messages": True})
                    except Exception:
                        pass
                    # Schedule re-mute and continue
                    context.job_queue.run_once(
                        _resume_after_break,
                        break_interval,
                        data={"quiz_id": quiz_id, "chat_id": chat_id},
                    )
                    return

    # Advance to next question
    next_q = await quiz_engine.advance_quiz(quiz)
    if next_q is None:
        await _finish_quiz(context, quiz_id, chat_id)
        return

    # Send next question after 3s delay
    context.job_queue.run_once(
        _send_next_question,
        3,
        data={"quiz_id": quiz_id, "chat_id": chat_id},
    )


async def _resume_after_break(context: ContextTypes.DEFAULT_TYPE):
    """Resume mega quiz after break."""
    data = context.job.data
    quiz_id = data["quiz_id"]
    chat_id = data["chat_id"]

    # Re-mute
    try:
        await context.bot.set_chat_permissions(chat_id, {"can_send_messages": False})
    except Exception:
        pass

    await context.bot.send_message(chat_id=chat_id, text="⏰ Break over! Quiz resumes...")

    context.job_queue.run_once(
        _send_next_question,
        3,
        data={"quiz_id": quiz_id, "chat_id": chat_id},
    )


async def _finish_quiz(context: ContextTypes.DEFAULT_TYPE, quiz_id: str, chat_id: int):
    """End the quiz, show results, unmute group."""
    # Unmute group
    try:
        await context.bot.set_chat_permissions(chat_id, {"can_send_messages": True})
    except Exception as e:
        log.warning("Could not unmute group: %s", e)

    results = await quiz_engine.end_quiz(quiz_id)
    if not results:
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Quiz results nahi mil paaye.")
        return

    # Format results
    participants = results["participants"]
    if not participants:
        await context.bot.send_message(chat_id=chat_id, text="⚠️ Kisi ne quiz participate nahi kiya.")
        return

    lines = [
        "🏆 <b>QUIZ RESULTS</b>",
        f"📚 {results['subject']}" + (f" › {results['chapter']}" if results['chapter'] else ""),
        f"📊 {results['total_questions']} Questions",
        "━" * 30,
    ]

    medal = {0: "🥇", 1: "🥈", 2: "🥉"}
    for i, (uid, stats) in enumerate(participants[:10]):
        icon = medal.get(i, f"  {i+1}.")
        async with async_session() as session:
            u = await session.get(User, uid)
            name = f"@{u.username}" if u and u.username else (f"{u.first_name}" if u else f"User#{uid}")
        pct = int(stats["correct"] / results["total_questions"] * 100) if results["total_questions"] > 0 else 0
        lines.append(f"{icon} {name}: {stats['correct']}/{results['total_questions']} ({pct}%)")

    await context.bot.send_message(chat_id=chat_id, text="\n".join(lines), parse_mode="HTML")

    # Award badges for topper
    if participants:
        top_user_id = participants[0][0]
        await gamification.check_and_award_badges(top_user_id, daily_topper=True)

        # If mega quiz, award flex admin
        if results.get("quiz_type") == "mega" and participants:
            from datetime import datetime, timezone, timedelta
            async with async_session() as session:
                winner = await session.get(User, top_user_id)
                if winner:
                    winner.flex_admin_until = datetime.now(timezone.utc) + timedelta(days=7)
                    await session.commit()
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"👑 @{winner.username if winner else top_user_id} ne Sunday Mega Quiz jeeta! Flex Admin title mil gaya — 1 hafte ke liye! 🏆",
                parse_mode="HTML",
            )

    # Clean up streaks
    _correct_streaks.clear()

    # Clear poll data
    keys_to_remove = [k for k in context.user_data.keys() if k.startswith("poll_") or k.startswith("textq_")]
    for k in keys_to_remove:
        context.user_data.pop(k, None)
