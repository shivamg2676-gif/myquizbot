"""Quiz Engine - Question selection, quiz session management, timers.

Active quizzes are tracked in the `active_quizzes` table so they survive restarts.
"""

import json
import logging
import random
import uuid
from datetime import datetime, timezone, timedelta

from sqlalchemy import select, and_, delete, func

from constants import (
    QUESTION_TYPES, QTYPE_MCQ, QTYPE_TRUE_FALSE, QTYPE_FILL_BLANK,
    QTYPE_MATCH, QTYPE_ONE_WORD, TYPE_TIMERS, THEORY_TYPES, PRACTICAL_TYPES,
    SUBJECTS, SUBJECT_ALIASES, DEFAULT_SYLLABUS, MEGA_QUIZ_CONFIG,
    QUIZ_CHAPTER, QUIZ_TOPIC, QUIZ_MOCK, QUIZ_DAILY, QUIZ_PYQ, QUIZ_MEGA,
)
from database import async_session
from models import Question, ActiveQuiz, QuizResponse, User
from services import gamification, leaderboard, ai

log = logging.getLogger(__name__)


# ── Helpers ──

def _resolve_subject(raw: str) -> str | None:
    raw_lower = raw.lower().strip()
    for alias, canonical in SUBJECT_ALIASES.items():
        if alias == raw_lower or canonical.lower() == raw_lower:
            return canonical
    # Direct match
    for s in SUBJECTS:
        if s.lower() == raw_lower:
            return s
    return None


def _default_timer(question_type: str) -> int:
    return TYPE_TIMERS.get(question_type, 25)


def _generate_quiz_id() -> str:
    return uuid.uuid4().hex[:12]


# ── Question Selection ──

async def select_questions(
    subject: str, chapter: str | None = None, count: int = 10,
    question_type: str | None = None, difficulty: str | None = None,
    source: str | None = None,
) -> list[Question]:
    """Select random questions from the bank."""
    async with async_session() as session:
        query = select(Question).where(
            and_(
                Question.subject == subject,
                Question.is_active == True,
            )
        )
        if chapter:
            query = query.where(Question.chapter == chapter)
        if question_type:
            query = query.where(Question.question_type == question_type)
        if difficulty:
            query = query.where(Question.difficulty == difficulty)
        if source:
            query = query.where(Question.source == source)

        result = await session.execute(query)
        questions = list(result.scalars().all())

    if len(questions) <= count:
        return questions
    return random.sample(questions, count)


def _build_poll_options(q: Question) -> list[str]:
    """Build option list for a poll based on question type."""
    if q.question_type == QTYPE_MCQ:
        opts = []
        if q.option_a: opts.append(f"A) {q.option_a}")
        if q.option_b: opts.append(f"B) {q.option_b}")
        if q.option_c: opts.append(f"C) {q.option_c}")
        if q.option_d: opts.append(f"D) {q.option_d}")
        return opts
    elif q.question_type == QTYPE_TRUE_FALSE:
        return ["True", "False"]
    elif q.question_type == QTYPE_FILL_BLANK:
        return []  # Text answer, no poll
    elif q.question_type == QTYPE_MATCH:
        opts = []
        if q.option_a: opts.append(f"A) {q.option_a}")
        if q.option_b: opts.append(f"B) {q.option_b}")
        if q.option_c: opts.append(f"C) {q.option_c}")
        if q.option_d: opts.append(f"D) {q.option_d}")
        return opts
    elif q.question_type == QTYPE_ONE_WORD:
        return []  # Text answer
    return []


def _format_question_message(q: Question, index: int, total: int, timer: int) -> str:
    """Format a question for sending in the group."""
    q_type_label = q.question_type.replace("_", " ").title()
    lines = [
        f"📝 Q{index + 1}/{total}  [{q_type_label}]  ⏱ {timer}s",
        f"📚 {q.subject}" + (f" › {q.chapter}" if q.chapter else ""),
        "",
        q.question_text,
    ]
    if q.question_type == QTYPE_FILL_BLANK:
        lines.append("")
        lines.append("📝 Type your answer below (fill in the blank).")
    elif q.question_type == QTYPE_ONE_WORD:
        lines.append("")
        lines.append("📝 Type the one-word answer below.")
    elif q.question_type == QTYPE_MATCH:
        lines.append("")
        lines.append("🔗 Match the following and type your answer as: A-1, B-2, C-3, D-4")
    return "\n".join(lines)


def _check_answer(q: Question, user_answer: str) -> bool:
    """Check if the user's answer is correct."""
    if not user_answer:
        return False
    user_clean = user_answer.strip().upper()
    correct_clean = q.correct_answer.strip().upper()
    return user_clean == correct_clean


# ── Quiz Session Management ──

async def start_quiz(
    group_id: int, subject: str, chapter: str | None,
    quiz_type: str, count: int = 10, timer: int | None = None,
    started_by: int = 0, is_mega: bool = False,
) -> ActiveQuiz | None:
    """Create a new active quiz session."""
    questions = await select_questions(
        subject=subject, chapter=chapter, count=count
    )

    if not questions:
        # If no questions in bank, try AI generation (if available)
        return None

    # Determine timer
    if timer is None:
        # Default timer based on first question type
        timer = _default_timer(questions[0].question_type)

    quiz = ActiveQuiz(
        quiz_id=_generate_quiz_id(),
        group_id=group_id,
        subject=subject,
        chapter=chapter,
        quiz_type=quiz_type,
        total_questions=len(questions),
        timer_seconds=timer,
        started_by=started_by,
        is_mega=is_mega,
        question_ids=json.dumps([q.question_id for q in questions]),
    )

    async with async_session() as session:
        session.add(quiz)
        await session.commit()
        await session.refresh(quiz)

    log.info("Quiz %s started: %s Qs, timer=%ds", quiz.quiz_id, quiz.total_questions, timer)
    return quiz


async def get_active_quiz(group_id: int) -> ActiveQuiz | None:
    async with async_session() as session:
        result = await session.execute(
            select(ActiveQuiz).where(
                and_(
                    ActiveQuiz.group_id == group_id,
                    ActiveQuiz.status == "active",
                )
            )
        )
        return result.scalar_one_or_none()


async def get_current_question(quiz: ActiveQuiz) -> Question | None:
    """Get the current question for an active quiz."""
    q_ids = json.loads(quiz.question_ids) if quiz.question_ids else []
    if quiz.current_index >= len(q_ids):
        return None

    async with async_session() as session:
        return await session.get(Question, q_ids[quiz.current_index])


async def advance_quiz(quiz: ActiveQuiz) -> Question | None:
    """Move to next question. Returns next question or None if quiz ended."""
    async with async_session() as session:
        quiz = await session.get(ActiveQuiz, quiz.quiz_id)
        if not quiz:
            return None

        quiz.current_index += 1

        if quiz.current_index >= quiz.total_questions:
            quiz.status = "completed"
            await session.commit()
            return None

        await session.commit()
        await session.refresh(quiz)

    return await get_current_question(quiz)


async def record_response(
    quiz_id: str, user_id: int, question_index: int,
    selected_answer: str | None, is_correct: bool, time_taken_ms: int = 0,
) -> int:
    """Record a user's response. Returns XP earned."""
    xp = 0
    if is_correct:
        xp = 4  # XP_CORRECT
    else:
        xp = -1  # XP_WRONG

    async with async_session() as session:
        session.add(QuizResponse(
            quiz_id=quiz_id,
            user_id=user_id,
            question_index=question_index,
            selected_answer=selected_answer,
            is_correct=is_correct,
            time_taken_ms=time_taken_ms,
            xp_earned=xp,
        ))
        await session.commit()

    return xp


async def end_quiz(quiz_id: str) -> dict | None:
    """End a quiz and return results summary."""
    async with async_session() as session:
        quiz = await session.get(ActiveQuiz, quiz_id)
        if not quiz:
            return None

        quiz.status = "completed"
        await session.commit()

        # Get all responses
        result = await session.execute(
            select(QuizResponse).where(QuizResponse.quiz_id == quiz_id)
        )
        responses = result.scalars().all()

    # Aggregate per user
    user_stats: dict[int, dict] = {}
    for r in responses:
        uid = r.user_id
        if uid not in user_stats:
            user_stats[uid] = {"correct": 0, "wrong": 0, "total_time": 0, "xp": 0, "count": 0}
        if r.is_correct:
            user_stats[uid]["correct"] += 1
        else:
            user_stats[uid]["wrong"] += 1
        user_stats[uid]["total_time"] += r.time_taken_ms
        user_stats[uid]["xp"] += r.xp_earned
        user_stats[uid]["count"] += 1

    # Update gamification for each user
    from datetime import datetime, timezone
    for uid, stats in user_stats.items():
        await gamification.update_streak(uid)
        await gamification.award_xp(uid, is_correct=True)  # net already handled per-question
        # Update user XP totals
        async with async_session() as session:
            user = await session.get(User, uid)
            if user:
                user.xp += stats["xp"]
                user.level = gamification._level_from_xp(user.xp)
                user.total_quizzes += 1
                user.total_correct += stats["correct"]
                user.total_wrong += stats["wrong"]
                user.last_quiz_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")
                await session.commit()

        # Record score in leaderboard
        score = stats["correct"] * 10  # 10 points per correct answer
        await leaderboard.record_quiz_score(
            user_id=uid,
            subject=quiz.subject,
            chapter=quiz.chapter,
            quiz_type=quiz.quiz_type,
            score=score,
            total=quiz.total_questions,
            correct=stats["correct"],
            wrong=stats["wrong"],
            time_taken=stats["total_time"] // 1000,
        )

        # Check badges
        if stats["correct"] == quiz.total_questions and quiz.total_questions >= 10:
            await gamification.check_and_award_badges(uid, perfect_score=True, total_questions=quiz.total_questions)
        if stats["count"] >= 5 and all(True for _ in range(5)):  # placeholder for speed demon
            pass

    # Sort by score
    sorted_users = sorted(user_stats.items(), key=lambda x: x[1]["correct"], reverse=True)

    return {
        "quiz_id": quiz_id,
        "subject": quiz.subject,
        "chapter": quiz.chapter,
        "quiz_type": quiz.quiz_type,
        "total_questions": quiz.total_questions,
        "participants": sorted_users,
    }


async def set_live_timer(quiz_id: str, new_timer: int) -> bool:
    """Change timer for an active quiz (live override)."""
    async with async_session() as session:
        quiz = await session.get(ActiveQuiz, quiz_id)
        if not quiz or quiz.status != "active":
            return False
        quiz.timer_seconds = new_timer
        await session.commit()
        return True


async def add_questions_from_ai(
    questions_data: list[dict], subject: str, chapter: str, source: str = "ai"
) -> int:
    """Bulk-insert AI-generated questions into the question bank."""
    added = 0
    async with async_session() as session:
        for q_data in questions_data:
            q = Question(
                subject=subject,
                chapter=chapter,
                question_text=q_data.get("question", ""),
                question_type=q_data.get("type", "mcq"),
                option_a=q_data.get("options", {}).get("A"),
                option_b=q_data.get("options", {}).get("B"),
                option_c=q_data.get("options", {}).get("C"),
                option_d=q_data.get("options", {}).get("D"),
                correct_answer=q_data.get("correct", ""),
                explanation=q_data.get("explanation"),
                hint=q_data.get("hint"),
                difficulty=q_data.get("difficulty", "medium"),
                source=source,
            )
            session.add(q)
            added += 1
        await session.commit()
    return added


async def get_question_count(subject: str | None = None, chapter: str | None = None) -> int:
    """Get total question count in the bank."""
    async with async_session() as session:
        query = select(func.count(Question.question_id)).where(Question.is_active == True)
        if subject:
            query = query.where(Question.subject == subject)
        if chapter:
            query = query.where(Question.chapter == chapter)
        result = await session.execute(query)
        return result.scalar_one() or 0


# end of file
