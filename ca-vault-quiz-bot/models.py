"""CA Vault Quiz Bot - SQLAlchemy Models
All tables defined here are auto-created on first startup.
"""

import json
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base, utcnow


class User(Base):
    __tablename__ = "users"

    user_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    role: Mapped[str] = mapped_column(String(16), default="student")
    xp: Mapped[int] = mapped_column(Integer, default=0)
    level: Mapped[int] = mapped_column(Integer, default=1)
    streak_count: Mapped[int] = mapped_column(Integer, default=0)
    last_active_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    joined_date: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_subscribed: Mapped[bool] = mapped_column(Boolean, default=False)
    is_muted: Mapped[bool] = mapped_column(Boolean, default=False)
    mute_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    warning_count: Mapped[int] = mapped_column(Integer, default=0)
    is_permanently_muted: Mapped[bool] = mapped_column(Boolean, default=False)
    trial_start_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    trial_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    trial_end_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    can_start_quiz: Mapped[bool] = mapped_column(Boolean, default=False)
    referral_code: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    referred_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    flex_admin_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_quiz_date: Mapped[str | None] = mapped_column(String(10), nullable=True)
    total_quizzes: Mapped[int] = mapped_column(Integer, default=0)
    total_correct: Mapped[int] = mapped_column(Integer, default=0)
    total_wrong: Mapped[int] = mapped_column(Integer, default=0)

    # relationships
    quiz_history: Mapped[list["QuizHistory"]] = relationship(back_populates="user", lazy="noload")
    badges: Mapped[list["Badge"]] = relationship(back_populates="user", lazy="noload")
    received_logs: Mapped[list["AuditLog"]] = relationship(back_populates="target_user", foreign_keys="AuditLog.target_user_id", lazy="noload")


class QuizHistory(Base):
    __tablename__ = "quiz_history"

    attempt_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"))
    subject: Mapped[str] = mapped_column(String(64))
    chapter: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quiz_type: Mapped[str] = mapped_column(String(16))
    score: Mapped[int] = mapped_column(Integer, default=0)
    total_questions: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)
    time_taken: Mapped[int] = mapped_column(Integer, default=0)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="quiz_history")


class Badge(Base):
    __tablename__ = "badges"

    badge_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"))
    badge_key: Mapped[str] = mapped_column(String(32))
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    user: Mapped["User"] = relationship(back_populates="badges")


class PDFIndex(Base):
    __tablename__ = "pdf_index"

    pdf_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    file_id: Mapped[str] = mapped_column(String(256), unique=True)
    file_name: Mapped[str] = mapped_column(String(256))
    subject: Mapped[str | None] = mapped_column(String(64), nullable=True)
    chapter: Mapped[str | None] = mapped_column(String(128), nullable=True)
    keywords: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list
    uploaded_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    channel_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_approved: Mapped[bool] = mapped_column(Boolean, default=False)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    teacher_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LeaderboardCache(Base):
    __tablename__ = "leaderboard_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("users.user_id"))
    period: Mapped[str] = mapped_column(String(16))  # daily / weekly / monthly
    score: Mapped[int] = mapped_column(Integer, default=0)
    rank: Mapped[int | None] = mapped_column(Integer, nullable=True)
    date_key: Mapped[str] = mapped_column(String(16))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    log_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    target_user_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("users.user_id"), nullable=True)
    action_type: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    details: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    target_user: Mapped["User"] = relationship(back_populates="received_logs", foreign_keys=[target_user_id])


class ScheduleConfig(Base):
    __tablename__ = "schedule_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day_of_week: Mapped[str] = mapped_column(String(16))
    subject: Mapped[str] = mapped_column(String(64))
    chapter: Mapped[str] = mapped_column(String(128))
    quiz_time: Mapped[str] = mapped_column(String(8))  # HH:MM
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class Filter(Base):
    __tablename__ = "filters"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    word: Mapped[str] = mapped_column(String(128), unique=True)
    added_by: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    added_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Question(Base):
    __tablename__ = "questions"

    question_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    subject: Mapped[str] = mapped_column(String(64))
    chapter: Mapped[str | None] = mapped_column(String(128), nullable=True)
    question_text: Mapped[str] = mapped_column(Text)
    question_type: Mapped[str] = mapped_column(String(16), default="mcq")
    option_a: Mapped[str | None] = mapped_column(Text, nullable=True)
    option_b: Mapped[str | None] = mapped_column(Text, nullable=True)
    option_c: Mapped[str | None] = mapped_column(Text, nullable=True)
    option_d: Mapped[str | None] = mapped_column(Text, nullable=True)
    correct_answer: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str | None] = mapped_column(Text, nullable=True)
    hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    difficulty: Mapped[str] = mapped_column(String(8), default="medium")
    source: Mapped[str] = mapped_column(String(16), default="custom")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)


class ActiveQuiz(Base):
    __tablename__ = "active_quizzes"

    quiz_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    group_id: Mapped[int] = mapped_column(BigInteger)
    subject: Mapped[str] = mapped_column(String(64))
    chapter: Mapped[str | None] = mapped_column(String(128), nullable=True)
    quiz_type: Mapped[str] = mapped_column(String(16))
    total_questions: Mapped[int] = mapped_column(Integer, default=10)
    current_index: Mapped[int] = mapped_column(Integer, default=0)
    timer_seconds: Mapped[int] = mapped_column(Integer, default=30)
    status: Mapped[str] = mapped_column(String(16), default="active")
    started_by: Mapped[int] = mapped_column(BigInteger)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    is_mega: Mapped[bool] = mapped_column(Boolean, default=False)
    question_ids: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON list of question_ids


class QuizResponse(Base):
    __tablename__ = "quiz_responses"

    response_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    quiz_id: Mapped[str] = mapped_column(String(64), ForeignKey("active_quizzes.quiz_id"))
    user_id: Mapped[int] = mapped_column(BigInteger)
    question_index: Mapped[int] = mapped_column(Integer)
    selected_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)
    time_taken_ms: Mapped[int] = mapped_column(Integer, default=0)
    xp_earned: Mapped[int] = mapped_column(Integer, default=0)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
