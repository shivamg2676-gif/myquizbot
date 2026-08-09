import os
import sys
import time
import json
import re
import random
import hashlib
from datetime import datetime, timedelta
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests

import database

# --- CONFIGURATION & API KEYS FROM RENDER ENV ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None
OWNER_ID = int(os.getenv("OWNER_ID", "8724204988"))
FORCE_SUB_CHANNEL = os.getenv("FORCE_SUB_CHANNEL", "")
MAIN_GROUP_ID = int(os.getenv("MAIN_GROUP_ID", "0"))

# 6 Free AI Keys (Including OpenAI)
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

scheduled_quizzes = []
active_poll_tracker = {}
active_quiz_sessions = {}
active_quiz_session_timers = {}
quiz_builder_state = {}
schedule_wizard_state = {}
session_user_scores = {}
session_user_streaks = {}
pinned_daily_messages = {}
last_pinned_topper_messages = {}

# System tracking for automated backup quizzes
auto_quiz_announced = set()
completed_auto_chapters = {}

MOTIVATIONAL_QUOTES = [
    "🚀 *\"Success is not final, failure is not fatal: it is the courage to continue that counts.\"* — Keep grinding CA Champ!",
    "🔥 *\"The future depends on what you do today.\"* — Work hard for that CA prefix!",
    "🏛️ *\"Your dedication today will build your empire tomorrow.\"* — Welcome to CA Vault!",
    "💡 *\"Small daily improvements over time lead to stunning results.\"* — Stay focused!",
    "🎯 *\"Believe you can and you're halfway there.\"* — Crush your CA Foundation goals!"
]

SHAYARI_LIST = [
    "✨ *Koshish aisi karo ki har ek question solution bane,\nMehnat aisi karo ki CA ki degree tumhari pehchan bane!*",
    "🔥 *Zindagi mein toofan aaye toh darna mat,\nCA Foundation crack karke sabko harana mat bhoolna!*",
    "🏛️ *Subah ki mehnat aur raaton ka jaagna rang layega,\nEk din tumhare naam ke aage CA zaroor aayega!*"
]

HIGH_WEIGHTAGE_CHAPTERS = {
    "Accounts": [
        "Final Accounts of Sole Proprietors",
        "Partnership and NPO Accounts",
        "Company Accounts (Issue of Shares & Debentures)",
        "Bank Reconciliation Statement (BRS)",
        "Accounting Process & Rectification of Errors",
        "Depreciation and Inventory Valuation"
    ],
    "Economics": [
        "Theory of Demand and Supply",
        "Theory of Production and Cost",
        "Price Determination in Different Markets",
        "National Income Accounting",
        "Public Finance and Money Market",
        "Business Cycles"
    ],
    "Quantitative Aptitude": [
        "Ratio, Proportion, Indices and Logarithms",
        "Time Value of Money (TVM)",
        "Permutations and Combinations",
        "Sequence and Series (AP & GP)",
        "Measures of Central Tendency and Dispersion",
        "Probability and Theoretical Distributions",
        "Correlation and Regression"
    ],
    "Business Laws": [
        "The Indian Contract Act, 1872",
        "The Companies Act, 2013",
        "The Sale of Goods Act, 1930",
        "The Indian Partnership Act, 1932",
        "The Limited Liability Partnership Act, 2008"
    ]
}

AUTO_SLOTS = {
    "12:00": "Accounts",
    "15:00": "Economics",
    "18:00": "Quantitative Aptitude",
    "21:00": "Business Laws"
}

DIVIDER = "🌈 ▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬▬ 🌈"
SOFT_DIVIDER = "· · ─ ·𖥸· ─ · ·"
SPARKLE_ROW = "✨ 💎 🔥 ⚡ 🏆 ⚡ 🔥 💎 ✨"

def fancy_header(emoji, title):
    return f"{emoji} ░▒▓ **{title}** ▓▒░ {emoji}"

print("🦅 CA Vault Ultra-Aesthetic Master OS Starting (Fully Production Audited)...")

# --- TELEGRAM API HELPER FUNCTIONS ---

def send_message(chat_id, text, reply_markup=None, parse_mode="Markdown"):
    if not BASE_URL: return {}
    payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        res = requests.post(f"{BASE_URL}/sendMessage", json=payload, timeout=8)
        return res.json()
    except Exception:
        return {}

def delete_message(chat_id, message_id):
    if not BASE_URL: return False
    try:
        res = requests.post(f"{BASE_URL}/deleteMessage", json={"chat_id": chat_id, "message_id": message_id}, timeout=8)
        return res.json().get("ok", False)
    except Exception:
        return False

def edit_message(chat_id, message_id, text, reply_markup=None, parse_mode="Markdown"):
    if not BASE_URL: return
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": parse_mode}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(f"{BASE_URL}/editMessageText", json=payload, timeout=8)
    except Exception:
        pass

def pin_message(chat_id, message_id):
    if not BASE_URL: return
    try:
        requests.post(f"{BASE_URL}/pinChatMessage", json={"chat_id": chat_id, "message_id": message_id}, timeout=8)
    except Exception:
        pass

def unpin_message(chat_id, message_id):
    if not BASE_URL: return
    try:
        requests.post(f"{BASE_URL}/unpinChatMessage", json={"chat_id": chat_id, "message_id": message_id}, timeout=8)
    except Exception:
        pass

def restrict_chat_member(chat_id, user_id, until_date=None, permissions=None):
    if not BASE_URL: return False
    if permissions is None:
        permissions = {"can_send_messages": False}
    payload = {
        "chat_id": chat_id,
        "user_id": user_id,
        "permissions": permissions
    }
    if until_date:
        payload["until_date"] = until_date
    try:
        res = requests.post(f"{BASE_URL}/restrictChatMember", json=payload, timeout=8)
        return res.json().get("ok", False)
    except Exception:
        return False

def set_chat_permissions(chat_id, can_send_messages=True):
    if not BASE_URL: return False
    payload = {
        "chat_id": chat_id,
        "permissions": {
            "can_send_messages": can_send_messages,
            "can_send_media_messages": can_send_messages,
            "can_send_other_messages": can_send_messages
        }
    }
    try:
        res = requests.post(f"{BASE_URL}/setChatPermissions", json=payload, timeout=8)
        return res.json().get("ok", False)
    except Exception:
        return False

def check_force_sub(user_id):
    if not FORCE_SUB_CHANNEL or not BASE_URL:
        return True
    try:
        res = requests.get(f"{BASE_URL}/getChatMember", params={"chat_id": FORCE_SUB_CHANNEL, "user_id": user_id}, timeout=8)
        data = res.json()
        if data.get("ok"):
            status = data["result"]["status"]
            return status in ["creator", "administrator", "member"]
    except Exception:
        return True
    return False

def is_group_chat(chat_id):
    return str(chat_id).startswith("-")

def get_role(user_id):
    return database.get_user_role(user_id, OWNER_ID)

def is_user_admin_or_owner(message):
    user_id = message["from"]["id"]
    role = get_role(user_id)
    if role in ["owner", "admin"]:
        return True
    if "sender_chat" in message:
        return True
    chat_id = message["chat"]["id"]
    if is_group_chat(chat_id):
        try:
            res = requests.get(f"{BASE_URL}/getChatMember", params={"chat_id": chat_id, "user_id": user_id}, timeout=8)
            data = res.json()
            if data.get("ok"):
                status = data["result"]["status"]
                if status in ["creator", "administrator"]:
                    return True
        except Exception:
            return False
    return False

def resolve_target_group(user_id, current_chat_id=None, auto_save_if_group=True):
    linked = database.get_user_linked_group(user_id)
    if linked:
        return linked
    if current_chat_id and is_group_chat(current_chat_id):
        if auto_save_if_group:
            try:
                database.set_user_linked_group(user_id, current_chat_id)
            except Exception:
                pass
        return current_chat_id
    return None

def detect_material_request_intent(text):
    text_lower = text.lower().strip()
    keywords = database.search_smart_keywords()
    for kw_entry in keywords:
        kw = kw_entry["keyword"].lower()
        if kw in text_lower:
            return kw_entry

    demand_triggers = ["chahiye", "bhej do", "send notes", "pdf link", "notes please", "give notes", "share pdf"]
    casual_triggers = ["tough hain", "kya tumne", "kaun padh raha hai", "samajh nahi aaya"]

    if any(c in text_lower for c in casual_triggers):
        return None

    if any(d in text_lower for d in demand_triggers):
        for kw_entry in keywords:
            if kw_entry["teacher_name"].lower() in text_lower or kw_entry["keyword"].replace("#", "").replace("_", " ") in text_lower:
                return kw_entry

    return None

# --- REST AI CALLS ---

def call_openai(prompt):
    if not OPENAI_API_KEY: return None
    try:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
        payload = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "response_format": {"type": "json_object"}
        }
        res = requests.post(url, json=payload, headers=headers, timeout=8)
        if res.status_code == 200:
            return res.json()["choices"][0]["message"]["content"]
    except Exception:
        pass
    return None

def call_gemini(prompt):
    if not GEMINI_API_KEY: return None
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        res = requests.post(url, json=payload, timeout=8)
        if res.status_code == 200:
            return res.json()["candidates"][0]["content"]["parts"][0]["text"]
    except Exception:
        pass
    return None

def call_groq(prompt):
    if not GROQ_API_KEY: return None
    try:
        url = "https://api.groq.com/openai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}], "response_format": {"type": "json_object"}}
        res = requests.post(url, json=payload, headers=headers, timeout=8)
        if res.status_code == 200:
            return res.json()["choices"][0]["message"]["content"]
    except Exception:
        pass
    return None

def call_cerebras(prompt):
    if not CEREBRAS_API_KEY: return None
    try:
        url = "https://api.cerebras.ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {CEREBRAS_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "llama3.1-70b", "messages": [{"role": "user", "content": prompt}]}
        res = requests.post(url, json=payload, headers=headers, timeout=8)
        if res.status_code == 200:
            return res.json()["choices"][0]["message"]["content"]
    except Exception:
        pass
    return None

def call_mistral(prompt):
    if not MISTRAL_API_KEY: return None
    try:
        url = "https://api.mistral.ai/v1/chat/completions"
        headers = {"Authorization": f"Bearer {MISTRAL_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "mistral-large-latest", "messages": [{"role": "user", "content": prompt}]}
        res = requests.post(url, json=payload, headers=headers, timeout=8)
        if res.status_code == 200:
            return res.json()["choices"][0]["message"]["content"]
    except Exception:
        pass
    return None

def call_openrouter(prompt):
    if not OPENROUTER_API_KEY: return None
    try:
        url = "https://openrouter.ai/api/v1/chat/completions"
        headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
        payload = {"model": "deepseek/deepseek-chat", "messages": [{"role": "user", "content": prompt}]}
        res = requests.post(url, json=payload, headers=headers, timeout=8)
        if res.status_code == 200:
            return res.json()["choices"][0]["message"]["content"]
    except Exception:
        pass
    return None

def fetch_fastest_ai_response(prompt):
    ai_funcs = [call_openai, call_groq, call_gemini, call_cerebras, call_mistral, call_openrouter]
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(func, prompt) for func in ai_funcs]
        for future in as_completed(futures):
            result = future.result()
            if result and len(result.strip()) > 15:
                return result
    return None

def generate_ai_question(subject, chapter, level="EXTREME_HIGH"):
    scope_text = f"Chapter '{chapter}'" if chapter else f"Full Subject '{subject}' syllabus"
    diff_prompt = (
        "Analyze ICAI CA Foundation Study Modules, PYQs, RTPs, and MTPs deeply. "
        "Generate an EXTREMELY HIGH DIFFICULTY level question. Focus on conceptual traps, "
        "tricky calculations, multi-statement evaluation, or complex statutory exceptions."
    ) if level == "EXTREME_HIGH" else "Generate a Moderate/Medium difficulty conceptual ICAI module question."

    prompt = (
        f"Generate exactly 1 multiple-choice question for CA Foundation '{subject}', {scope_text}.\n"
        f"Difficulty Mandate: {diff_prompt}\n\n"
        f"Return strictly a JSON object with this exact key structure:\n"
        f"{{\n"
        f'  "question": "Question text",\n'
        f'  "options": ["Option 1", "Option 2", "Option 3", "Option 4"],\n'
        f'  "correct": 0,\n'
        f'  "explanation": "Precise ICAI logic explanation",\n'
        f'  "type": "theory"\n'
        f"}}\n"
        f"Note: 'correct' must be integer index (0, 1, 2, or 3). 'type' must be 'theory' or 'practical'."
    )

    raw_text = fetch_fastest_ai_response(prompt)
    return parse_ai_json_or_text_output(raw_text, subject)

def parse_ai_json_or_text_output(text, subject):
    fallback = {
        "question": f"[{subject}] ICAI Standard Practice Question",
        "options": ["Option A", "Option B", "Option C", "Option D"],
        "correct": 0,
        "explanation": "Standard ICAI rule applies.",
        "type": "theory"
    }
    if not text:
        return fallback

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?", "", cleaned).strip()
        cleaned = re.sub(r"```$", "", cleaned).strip()

    try:
        data = json.loads(cleaned)
        q_text = str(data.get("question", "")).strip()
        opts = [str(o).strip() for o in data.get("options", [])]
        corr = int(data.get("correct", 0))
        expl = str(data.get("explanation", "")).strip()
        q_type = str(data.get("type", "theory")).lower()

        if q_text and len(opts) == 4:
            return {
                "question": q_text,
                "options": opts,
                "correct": max(0, min(corr, 3)),
                "explanation": expl or "ICAI module principle applies.",
                "type": q_type if q_type in ["theory", "practical"] else "theory"
            }
    except Exception:
        pass

    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    q_text, o1, o2, o3, o4, correct_idx, explanation = "", "", "", "", "", 0, "ICAI module principle applies."
    for line in lines:
        if line.startswith("Q:"): q_text = line[2:].strip()
        elif line.startswith("O1:"): o1 = line[3:].strip()
        elif line.startswith("O2:"): o2 = line[3:].strip()
        elif line.startswith("O3:"): o3 = line[3:].strip()
        elif line.startswith("O4:"): o4 = line[3:].strip()
        elif line.startswith("Correct:"):
            digits = ''.join(filter(str.isdigit, line))
            if digits: correct_idx = int(digits) - 1
        elif line.startswith("Explanation:"): explanation = line[12:].strip()

    return {
        "question": q_text or f"[{subject}] ICAI Exam Question",
        "options": [o1 or "Option A", o2 or "Option B", o3 or "Option C", o4 or "Option D"],
        "correct": max(0, min(correct_idx, 3)),
        "explanation": explanation,
        "type": "theory"
    }

def parse_raw_text_questions(raw_text):
    questions = []
    blocks = raw_text.split("Q:")
    for b in blocks:
        if not b.strip(): continue
        lines = [l.strip() for l in b.split("\n") if l.strip()]
        q_text = lines[0] if lines else "Sample Question"
        opts = []
        corr = 0
        expl = "Standard ICAI rule."
        for line in lines:
            if line.startswith("A)") or line.startswith("1)") or line.startswith("O1:"): opts.append(line[2:].strip())
            elif line.startswith("B)") or line.startswith("2)") or line.startswith("O2:"): opts.append(line[2:].strip())
            elif line.startswith("C)") or line.startswith("3)") or line.startswith("O3:"): opts.append(line[2:].strip())
            elif line.startswith("D)") or line.startswith("4)") or line.startswith("O4:"): opts.append(line[2:].strip())
            elif "Ans:" in line or "Correct:" in line:
                digits = ''.join(filter(str.isdigit, line))
                if digits: corr = int(digits) - 1
            elif "Exp:" in line or "Explanation:" in line:
                expl = line.split(":", 1)[1].strip()
        if q_text and len(opts) >= 4:
            questions.append({"question": q_text, "options": opts[:4], "correct": max(0, min(corr, 3)), "explanation": expl, "type": "theory"})
    return questions

def send_poll(chat_id, question, options, correct_option_id, open_period=30, subject=""):
    payload = {
        "chat_id": chat_id,
        "question": question[:300],
        "options": [str(opt)[:100] for opt in options],
        "is_anonymous": False,
        "type": "quiz",
        "correct_option_id": max(0, min(correct_option_id, len(options) - 1)),
        "open_period": open_period
    }
    try:
        res = requests.post(f"{BASE_URL}/sendPoll", json=payload, timeout=8)
        data = res.json()
        if data.get("ok"):
            poll_id = data["result"]["poll"]["id"]
            active_poll_tracker[poll_id] = {
                "correct": max(0, min(correct_option_id, len(options) - 1)),
                "chat_id": chat_id,
                "options": options,
                "question": question,
                "wrong_count": 0,
                "total_votes": 0,
                "subject": subject or ""
            }
        return data
    except Exception:
        return {}

def get_streak_praise(streak):
    if streak == 1: return "🌟 Best!"
    elif streak == 2: return "🔥 Better!"
    elif streak == 3: return "👍 Good!"
    elif streak == 4: return "🚀 Very Good!"
    else: return "🏆 Outstanding!"

def run_quiz_session(target_chat_id, subject, chapter, count, timer, break_freq=0, break_duration=0, level="EXTREME_HIGH", conductor_user_id=None, subtopics=""):
    if target_chat_id in last_pinned_topper_messages:
        unpin_message(target_chat_id, last_pinned_topper_messages[target_chat_id])

    active_quiz_sessions[target_chat_id] = True
    active_quiz_session_timers[target_chat_id] = timer
    session_user_scores[target_chat_id] = {}
    session_user_streaks[target_chat_id] = {}

    if is_group_chat(target_chat_id):
        set_chat_permissions(target_chat_id, can_send_messages=False)
        database.log_audit(0, 0, "FOCUS_MODE_ON", f"Auto-enabled focus mode for quiz in {target_chat_id}")

    chap_display = chapter if chapter else "Full Syllabus"
    subtopic_display = f"\n🎯 *Sub-topics:* `{subtopics}`" if subtopics else ""
    break_info = f"☕ *Break:* Every `{break_freq}` Qs ({break_duration//60} mins)" if break_freq > 0 else "⚡ *Mode:* Non-stop Sprint"

    start_box = (
        f"{fancy_header('⚡', 'LIVE QUIZ ARENA IS ACTIVE!')}\n"
        f"{DIVIDER}\n"
        f"📘 **Subject:** `{subject}`\n"
        f"📖 **Chapter:** `{chap_display}`{subtopic_display}\n"
        f"🔢 **Questions:** `{count}` ｜ ⏱️ **Timer:** `{timer}s`\n"
        f"{break_info}\n"
        f"{DIVIDER}\n\n"
        f"🚀 *Lock in champs! First question dropping right now...*"
    )
    send_message(target_chat_id, start_box)

    current_difficulty = level
    total_session_votes = 0
    total_session_wrongs = 0
    questions_attempted = 0

    if conductor_user_id:
        send_message(conductor_user_id, f"⚡ **Quiz Dispatched to Group (`{target_chat_id}`)!**\n🔥 Level: `{current_difficulty}`\n📈 Live metrics streaming enabled.")

    for idx in range(count):
        if not active_quiz_sessions.get(target_chat_id, False):
            send_message(target_chat_id, "🛑 **Quiz Session Terminated.**")
            if conductor_user_id:
                send_message(conductor_user_id, f"🛑 **Terminated in Group (`{target_chat_id}`).**")
            break

        if idx > 0 and break_freq > 0 and idx % break_freq == 0:
            send_message(target_chat_id, f"☕ **{idx} Questions Cleared!**\n{break_duration // 60} min intermission break...")
            for _ in range(break_duration):
                if not active_quiz_sessions.get(target_chat_id, False):
                    break
                time.sleep(1)
            send_message(target_chat_id, "🚀 **Break Over!** Resuming practice speedrun...")

        q = generate_ai_question(subject, chapter, current_difficulty)
        current_live_timer = active_quiz_session_timers.get(target_chat_id, timer)
        poll_timer = max(10, min(current_live_timer, 60))

        poll_res = send_poll(target_chat_id, f"Q{idx+1}/{count}: {q['question']}", q['options'], q['correct'], open_period=poll_timer, subject=subject)
        poll_id = poll_res.get("result", {}).get("poll", {}).get("id") if poll_res.get("ok") else None

        time.sleep(poll_timer + 1)

        if poll_id and poll_id in active_poll_tracker:
            p_data = active_poll_tracker[poll_id]
            total_v = p_data["total_votes"]
            wrong_v = p_data["wrong_count"]

            questions_attempted += 1
            total_session_votes += total_v
            total_session_wrongs += wrong_v

            wrong_percentage = (wrong_v / total_v * 100) if total_v > 0 else 0
            if total_v > 0 and wrong_percentage > 60:
                current_difficulty = "MEDIUM"
                if conductor_user_id:
                    send_message(conductor_user_id, f"📊 **Q{idx+1} Performance Pulse:**\n• Total Responses: `{total_v}` | Incorrect: `{wrong_v}` ({wrong_percentage:.1f}%)\n⚠️ Difficulty adjusted to `{current_difficulty}`.")
            else:
                current_difficulty = level

        feedback_text = (
            f"💡 **Q{idx+1} OFFICIAL EXPLANATION CARD**\n"
            f"{SOFT_DIVIDER}\n"
            f"✅ **Correct Choice:** `{q['options'][q['correct']]}`\n\n"
            f"🔍 **ICAI Concept Logic:**\n_{q['explanation']}_\n"
            f"{SOFT_DIVIDER}"
        )
        send_message(target_chat_id, feedback_text)
        time.sleep(2)

    active_quiz_sessions[target_chat_id] = False

    if is_group_chat(target_chat_id):
        set_chat_permissions(target_chat_id, can_send_messages=True)
        database.log_audit(0, 0, "FOCUS_MODE_OFF", f"Disabled focus mode after quiz in {target_chat_id}")

    overall_wrong_pct = (total_session_wrongs / total_session_votes * 100) if total_session_votes > 0 else 0
    overall_correct_pct = 100.0 - overall_wrong_pct if total_session_votes > 0 else 0.0

    summary_report = (
        f"💎 ░▒▓ **SESSION PERFORMANCE ANALYTICS** ▓▒░ 💎\n\n"
        f"📌 **Group:** `{target_chat_id}`\n"
        f"📘 **Subject:** `{subject}`\n"
        f"📖 **Scope:** `{chap_display}`\n"
        f"🔢 **Questions Delivered:** `{questions_attempted}/{count}`\n"
        f"📥 **Total Votes:** `{total_session_votes}`\n"
        f"🎯 **Group Accuracy Rate:** `{overall_correct_pct:.1f}%`\n"
        f"{DIVIDER}"
    )

    send_message(target_chat_id, f"🎉 **QUIZ COMPLETE!**\n\n{summary_report}")
    if conductor_user_id:
        send_message(conductor_user_id, f"🎉 **Session Report:**\n\n{summary_report}")

    scores = session_user_scores.get(target_chat_id, {})
    if scores:
        sorted_scores = sorted(scores.items(), key=lambda item: (item[1]["xp"], item[1]["correct"]), reverse=True)
        medals = ["👑 GOLD CHAMPION", "🥈 SILVER STAR", "🥉 BRONZE PERFORMER"]

        shayari = random.choice(SHAYARI_LIST)
        top_msg = f"{SPARKLE_ROW}\n{shayari}\n\n🏆 **HALL OF FAME — TOP PERFORMERS** 🏆\n📘 `{subject}` ｜ 🔢 `{count} Questions`\n\n"

        for idx, (uid, uinfo) in enumerate(sorted_scores[:3]):
            top_msg += f"{medals[idx]} ✨\n👤 **{uinfo['name']}**: `{uinfo['xp']} XP` ｜ ✅ `{uinfo['correct']}` Correct\n\n"
            if idx == 0 and "SUNDAY MEGA" in subject.upper():
                database.set_flex_admin(uid)
                send_message(target_chat_id, f"🏆 **SUNDAY MEGA QUIZ CHAMPION!**\n\nCongratulations <a href='tg://user?id={uid}'>{uinfo['name']}</a>! You unlocked **Sunday Flex Admin 🎖️** for 1 week!", parse_mode="HTML")

        top_msg += SPARKLE_ROW
        res_top = send_message(target_chat_id, top_msg)
        if res_top.get("ok"):
            msg_id = res_top["result"]["message_id"]
            pin_message(target_chat_id, msg_id)
            last_pinned_topper_messages[target_chat_id] = msg_id

def run_sunday_mega_quiz(target_chat_id):
    send_message(target_chat_id, "🔥 **SUNDAY MEGA ULTIMATE TEST ARENA** 🔥\n\n⚡ 200 Questions Across All 4 Subjects!\n⏱️ Format: 4 Intense Sections with 10-min intermissions.")
    subjects_config = [
        {"subject": "Accounts", "count": 40},
        {"subject": "Business Laws", "count": 60},
        {"subject": "Quantitative Aptitude", "count": 40},
        {"subject": "Economics", "count": 60}
    ]
    for idx, s in enumerate(subjects_config):
        if idx > 0:
            send_message(target_chat_id, f"☕ **10-MIN INTERMISSION BEFORE {s['subject'].upper()}**\n\nGet ready for next section...")
            time.sleep(600)
        run_quiz_session(target_chat_id, f"SUNDAY MEGA: {s['subject']}", "", s['count'], 25, level="EXTREME_HIGH")

# --- BACKGROUND WORKERS ---

def select_next_best_chapter(group_id, subject):
    if group_id not in completed_auto_chapters:
        completed_auto_chapters[group_id] = {}
    if subject not in completed_auto_chapters[group_id]:
        completed_auto_chapters[group_id][subject] = []

    available = [ch for ch in HIGH_WEIGHTAGE_CHAPTERS[subject] if ch not in completed_auto_chapters[group_id][subject]]
    if not available:
        completed_auto_chapters[group_id][subject] = []
        available = HIGH_WEIGHTAGE_CHAPTERS[subject]

    selected_ch = random.choice(available)
    completed_auto_chapters[group_id][subject].append(selected_ch)
    return selected_ch

def purge_background_worker():
    while True:
        try:
            pending = database.get_pending_purge_messages()
            for msg in pending:
                delete_message(msg["chat_id"], msg["message_id"])
                database.delete_purge_message_entry(msg["id"])
        except Exception as e:
            print(f"⚠️ [purge_background_worker] {type(e).__name__}: {e}", flush=True)
        time.sleep(5)

def icai_auto_sync_worker():
    while True:
        try:
            now_str = datetime.now().strftime("%Y-%m-%d")
            database.log_audit(0, 0, "ICAI_SYNC_CHECK", f"Scraped BoS Portal for {now_str}")
        except Exception as e:
            print(f"⚠️ [icai_auto_sync_worker] {type(e).__name__}: {e}", flush=True)
        time.sleep(21600)

def scheduler_background_worker():
    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            time_hm = now.strftime("%H:%M")
            time_full = now.strftime("%Y-%m-%d %H:%M")
            mode = database.get_setting("mode", "auto")

            if time_hm == "06:00" and not pinned_daily_messages.get(today_str, False):
                pinned_daily_messages[today_str] = True
                sched = database.get_or_create_daily_schedule(today_str)

                target_chat = MAIN_GROUP_ID if MAIN_GROUP_ID != 0 else OWNER_ID
                schedule_pin_text = (
                    f"{fancy_header('📌', 'DAILY TARGET & QUIZ PLAN')}\n\n"
                    f"📅 **Date:** `{today_str}`\n"
                    f"📚 **Subject Focus:** `{sched['subject']}`\n"
                    f"📖 **Module Scope:** `{sched['chapter_name']}`\n"
                    f"⏰ **Quiz Time:** `{sched['time_str']} PM`\n"
                    f"⚡ **Engine Mode:** `{mode.upper()}`\n\n"
                    f"🔥 *Revise your notes! Live quiz drops at scheduled time.*"
                )
                msg_res = send_message(target_chat, schedule_pin_text)
                if msg_res.get("ok"):
                    pin_message(target_chat, msg_res["result"]["message_id"])

            if mode == "auto":
                sched = database.get_or_create_daily_schedule(today_str)
                if sched["time_str"] == time_hm:
                    target_chat = MAIN_GROUP_ID if MAIN_GROUP_ID != 0 else OWNER_ID
                    if sched["is_mega_quiz"]:
                        threading.Thread(target=run_sunday_mega_quiz, args=(target_chat,), daemon=True).start()
                    else:
                        def_cnt = int(database.get_setting("default_q_count", "15"))
                        def_tmr = int(database.get_setting("default_timer", "30"))
                        def_lvl = database.get_setting("default_level", "EXTREME_HIGH")
                        threading.Thread(target=run_quiz_session, args=(target_chat, sched["subject"], sched["chapter_name"], def_cnt, def_tmr, 0, 0, def_lvl), daemon=True).start()

            for job in list(scheduled_quizzes):
                if job["datetime"] == time_full:
                    threading.Thread(
                        target=run_quiz_session,
                        args=(
                            job["chat_id"],
                            job["subject"],
                            job["chapter"],
                            job["count"],
                            job["timer"],
                            job.get("break_freq", 0),
                            job.get("break_duration", 0),
                            job.get("level", "EXTREME_HIGH"),
                            job.get("conductor_id"),
                            job.get("subtopics", "")
                        ),
                        daemon=True
                    ).start()
                    scheduled_quizzes.remove(job)

            db_jobs = database.load_scheduled_quizzes()
            for job in db_jobs:
                if job["datetime_str"] == time_full:
                    threading.Thread(target=run_quiz_session, args=(job["chat_id"], job["subject"], job["chapter"], job["count"], job["timer"], job.get("break_freq", 0), job.get("break_duration", 0), job.get("level", "EXTREME_HIGH")), daemon=True).start()
                    database.delete_scheduled_quiz(job["id"])

            # --- AUTOMATED BACKUP ENGINE WITH 1-HOUR ADVANCE ANNOUNCEMENTS ---
            active_target_groups = database.get_all_linked_groups()
            if MAIN_GROUP_ID and MAIN_GROUP_ID not in active_target_groups:
                active_target_groups.append(MAIN_GROUP_ID)

            one_hour_ahead_dt = now + timedelta(hours=1)
            one_hour_ahead_str = one_hour_ahead_dt.strftime("%H:%M")
            one_hour_ahead_date = one_hour_ahead_dt.strftime("%Y-%m-%d")
            one_hour_ahead_full = f"{one_hour_ahead_date} {one_hour_ahead_str}"

            for group_id in active_target_groups:
                if not group_id: continue
                if one_hour_ahead_str in AUTO_SLOTS:
                    slot_key = f"{one_hour_ahead_date}_{one_hour_ahead_str}_{group_id}_announce"
                    if slot_key not in auto_quiz_announced:
                        manual_exists = any(
                            q["chat_id"] == group_id and q["datetime"] == one_hour_ahead_full
                            for q in scheduled_quizzes
                        )
                        if not manual_exists:
                            target_subject = AUTO_SLOTS[one_hour_ahead_str]
                            target_chapter = select_next_best_chapter(group_id, target_subject)
                            
                            def_cnt = int(database.get_setting("default_q_count", "15"))
                            def_tmr = int(database.get_setting("default_timer", "30"))
                            def_lvl = database.get_setting("default_level", "EXTREME_HIGH")

                            scheduled_quizzes.append({
                                "chat_id": group_id,
                                "datetime": one_hour_ahead_full,
                                "subject": target_subject,
                                "chapter": target_chapter,
                                "subtopics": "ICAI High-Yield Focus Topics",
                                "count": def_cnt,
                                "timer": def_tmr,
                                "level": def_lvl,
                                "conductor_id": None
                            })

                            announce_msg = (
                                f"📢 **AUTOMATED QUIZ UPCOMING IN 1 HOUR!**\n"
                                f"─────────────────────\n"
                                f"📊 **Analysis:** High-Yield Chapter Triggered!\n"
                                f"📘 **Subject:** `{target_subject}`\n"
                                f"📖 **Chapter:** `{target_chapter}`\n"
                                f"⏰ **Scheduled Time:** `{one_hour_ahead_str}`\n"
                                f"🔢 **Questions:** `{def_cnt}` | ⏱️ **Timer:** `{def_tmr}s` | 🔥 **Difficulty:** `{def_lvl}`\n"
                                f"─────────────────────\n"
                                f"📌 *Get ready! The quiz will start automatically in 60 minutes.*"
                            )
                            res = send_message(group_id, announce_msg)
                            if res.get("ok"):
                                pin_message(group_id, res["result"]["message_id"])

                            auto_quiz_announced.add(slot_key)

        except Exception as e:
            print(f"⚠️ [scheduler_background_worker] {type(e).__name__}: {e}", flush=True)
        time.sleep(15)

def build_dashboard_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "⚙️ System Settings", "callback_data": "dash_settings"}, {"text": "🛡️ Moderation Controls", "callback_data": "dash_mod"}],
            [{"text": "👥 Quiz Access & Grants", "callback_data": "dash_access"}, {"text": "📚 Smart Knowledge Hub", "callback_data": "dash_hub"}],
            [{"text": "❌ Close Control Panel", "callback_data": "dash_close"}]
        ]
    }

def get_wizard_summary(st):
    grp = st.get("group_id", "Not Set")
    subj = st.get("subject", "Not Selected")
    chap = st.get("chapter", "Full Subject Syllabus")
    subtop = st.get("subtopics", "None")
    lvl = st.get("level", "Not Selected")
    sch_date = st.get("schedule_date", "Not Selected")
    sch_time = st.get("schedule_time", "Not Selected")
    cnt = st.get("count", "Not Selected")
    tmr = st.get("timer", "Not Selected")

    return (
        f"📊 **CURRENT SESSION SCOPE SUMMARY**\n"
        f"{DIVIDER}\n"
        f"📌 **Group:** `{grp}`\n"
        f"📘 **Subject:** `{subj}`\n"
        f"📖 **Chapter:** `{chap or 'Full Subject Syllabus'}`\n"
        f"🎯 **Sub-topics:** `{subtop or 'None'}`\n"
        f"🔥 **Difficulty:** `{lvl}`\n"
        f"📅 **Date:** `{sch_date}` ｜ ⏰ **Time:** `{sch_time}`\n"
        f"🔢 **Questions:** `{cnt}` ｜ ⏱️ **Timer:** `{tmr}`\n"
        f"{DIVIDER}\n\n"
    )

def get_role_based_help_text(user_id):
    role = get_role(user_id)
    if role in ["owner", "admin"]:
        return (
            "👑 ░▒▓ **SUPER ADMIN GOD MODE OS** ▓▒░ 👑\n\n"
            "⚡ **1. DASHBOARD & CORE CONTROL**\n"
            "• `/dashboard` or `/panel` : Launch Control Panel\n"
            "• `/setmode [auto/manual]` : Toggle Autopilot Mode\n"
            "• `/settime [HH:MM]` : Set Daily Quiz Window\n"
            "• `/settimer [seconds]` : Dynamic Live Timer Override\n"
            "• `/setcount [number]` : Set Default Question Count\n"
            "• `/setlevel [MEDIUM/HIGH/EXTREME_HIGH]` : Override Level\n\n"
            "💬 **2. DM CONTROL WIZARD & SCHEDULER**\n"
            "• `/link_group <GroupID>` : Connect Target Group (one-time — remembered forever)\n"
            "• `/schedule` : Interactive Step-by-Step Wizard\n"
            "• `/setschedule YYYY-MM-DD | HH:MM AM/PM` : Precision Lock\n"
            "• `/chapter_only_sched [Chapter]` / `/chapter_sched [Chapter] | [Sub-topics]` : Wizard chapter step\n\n"
            "📚 **3. SMART KNOWLEDGE HUB & KEYWORDS**\n"
            "• `/addkeyword [#kw] | [link] | [teacher]` : Add Keyword\n"
            "• `/keywords` : Index All Study Keywords & Vault Links\n"
            "• `/parse` : Convert Raw Text into Structured Quizzes\n\n"
            "🛡️ **4. MODERATION & ANTI-SPAM**\n"
            "• `/filter add [word]` : Block Word\n"
            "• `/filter remove [word]` : Unblock Word\n"
            "• `/filters` : View Blacklisted Words\n"
            "• `/stickers [on|off]` : Auto-Sticker Purge\n\n"
            "👥 **5. QUIZ ACCESS & TRIAL GRANTS**\n"
            "• `/grant [user_id] [1week|2weeks|fullfree]` : Grant Access\n"
            "• `/revoke [user_id]` : Revoke Access\n\n"
            "🎯 **6. LIVE QUIZ**\n"
            "• `/quiz` : Instant Quiz Wizard\n"
            "• `/chapter_only [Chapter]` / `/chapter [Chapter] | [Sub-topics]` : Instant-quiz chapter step\n\n"
            "🤖 **7. AUTOMATED SLOTS (FALLBACK)**\n"
            "• 12:00 PM ➔ Accounts\n"
            "• 03:00 PM ➔ Economics\n"
            "• 06:00 PM ➔ Quantitative Aptitude\n"
            "• 09:00 PM ➔ Business Laws"
        )
    else:
        return (
            "🚀 ░▒▓ **CA VAULT STUDENT ENGINE** ▓▒░ 🚀\n\n"
            "🎮 **STUDENT COMMANDS:**\n"
            "• `/quiz` : Launch Interactive Setup Wizard\n"
            "• `/leaderboard` : Global & Group Top Performers\n"
            "• `/stats` or `/profile` : View XP, Level & Streaks\n"
            "• `/refer` : Invite Friends & Earn +20 XP\n"
            "• `/syllabus` : View Module Syllabus Queue"
        )

# --- UI DASHBOARD BUILDER ---

def build_main_home_ui(first_name, linked_group_id=None):
    grp_status = f"`{linked_group_id}` ⚡ *(saved — no need to re-link)*" if linked_group_id else "❌ *Not Connected*"
    text = (
        f"{SPARKLE_ROW}\n"
        f"⚡ ░▒▓ **CA VAULT SYSTEM OS** ▓▒░ ⚡\n"
        f"{DIVIDER}\n"
        f"👋 **Welcome Back, {first_name}!**\n"
        f"🤖 *AI-Powered CA Foundation Practice Engine*\n\n"
        f"🔗 **Linked Target Group:** {grp_status}\n"
        f"⚡ **Status:** 🟢 Active & Operational\n"
        f"{DIVIDER}\n"
        f"👇 *Select an operational card below to launch:*"
    )
    kb = {
        "inline_keyboard": [
            [{"text": "🚀 Launch Instant Quiz", "callback_data": "ui_quiz_start"}, {"text": "🗓️ Auto Scheduler", "callback_data": "ui_schedule_wizard"}],
            [{"text": "🔗 Connect Target Group", "callback_data": "ui_link_group_info"}, {"text": "📚 Knowledge Hub", "callback_data": "ui_hub"}],
            [{"text": "🏆 Leaderboard", "callback_data": "ui_leaderboard"}, {"text": "⚙️ System Settings", "callback_data": "ui_settings"}]
        ]
    }
    return text, kb

def verify_bot_token_and_clear_webhook():
    if not BASE_URL:
        print("❌ FATAL: BOT_TOKEN env var is missing or empty. Bot cannot start.", flush=True)
        return False
    try:
        me = requests.get(f"{BASE_URL}/getMe", timeout=10).json()
        if not me.get("ok"):
            print(f"❌ FATAL: Invalid BOT_TOKEN — Telegram rejected getMe(): {me}", flush=True)
            return False
        print(f"✅ Bot Authenticated: @{me['result'].get('username')} (id={me['result'].get('id')})", flush=True)
    except Exception as e:
        print(f"❌ FATAL: Could not reach Telegram API for getMe(): {e}", flush=True)
        return False
    try:
        wh = requests.post(f"{BASE_URL}/deleteWebhook", json={"drop_pending_updates": False}, timeout=10).json()
        print(f"ℹ️ deleteWebhook result: {wh}", flush=True)
    except Exception as e:
        print(f"⚠️ Could not clear webhook (non-fatal): {e}", flush=True)
    return True

def handle_updates():
    offset = 0
    print("🤖 Telegram Bot Polling Engine Online...")

    if not verify_bot_token_and_clear_webhook():
        print("🛑 Polling loop will retry token/webhook checks every 10s until fixed.", flush=True)
        while not verify_bot_token_and_clear_webhook():
            time.sleep(10)

    while True:
        try:
            if not BASE_URL:
                print("Error: BOT_TOKEN Environment Variable is missing!")
                time.sleep(5)
                continue

            response = requests.get(f"{BASE_URL}/getUpdates", params={"offset": offset, "timeout": 10}, timeout=12)
            data = response.json()

            if not data.get("ok"):
                print(f"⚠️ [getUpdates FAILED] {data.get('error_code')}: {data.get('description')}", flush=True)
                if data.get("error_code") == 409:
                    try:
                        requests.post(f"{BASE_URL}/deleteWebhook", json={"drop_pending_updates": False}, timeout=8)
                    except Exception:
                        pass
                time.sleep(3)
                continue

            if data.get("ok"):
                for result in data.get("result", []):
                    offset = result["update_id"] + 1

                    # --- POLL ANSWER HANDLER ---
                    if "poll_answer" in result:
                        p_ans = result["poll_answer"]
                        poll_id = p_ans["poll_id"]
                        user = p_ans["user"]
                        user_id = user["id"]
                        first_name = user.get("first_name", "Student")
                        username = user.get("username", "")
                        chosen_options = p_ans.get("option_ids", [])

                        database.get_or_create_user(user_id, username, first_name, owner_id=OWNER_ID)

                        if poll_id in active_poll_tracker and chosen_options:
                            info = active_poll_tracker[poll_id]
                            chat_id = info["chat_id"]
                            correct_idx = info["correct"]
                            info["total_votes"] += 1

                            if chat_id not in session_user_scores:
                                session_user_scores[chat_id] = {}
                            if chat_id not in session_user_streaks:
                                session_user_streaks[chat_id] = {}

                            if user_id not in session_user_scores[chat_id]:
                                session_user_scores[chat_id][user_id] = {"correct": 0, "wrong": 0, "xp": 0, "name": first_name}
                            if user_id not in session_user_streaks[chat_id]:
                                session_user_streaks[chat_id][user_id] = 0

                            if correct_idx in chosen_options:
                                database.add_user_xp(user_id, 4)
                                session_user_scores[chat_id][user_id]["correct"] += 1
                                session_user_scores[chat_id][user_id]["xp"] += 4
                                session_user_streaks[chat_id][user_id] += 1

                                streak = session_user_streaks[chat_id][user_id]
                                praise = get_streak_praise(streak)
                                database.record_quiz_history(user_id, chat_id, info.get("subject") or "CA", "", 4, 1, 0)

                                praise_dm = f"{praise} **Spot On Jawab!** (+4 XP)\n🔥 Active Streak: `{streak} In A Row`"
                                send_message(user_id, praise_dm)
                            else:
                                info["wrong_count"] += 1
                                database.add_user_xp(user_id, -1)
                                session_user_scores[chat_id][user_id]["wrong"] += 1
                                session_user_scores[chat_id][user_id]["xp"] -= 1
                                session_user_streaks[chat_id][user_id] = 0
                                database.record_quiz_history(user_id, chat_id, info.get("subject") or "CA", "", -1, 0, 1)

                                wrong_dm_text = (
                                    f"❌ **Oof! Incorrect Choice.**\n\n"
                                    f"❓ _{info['question']}_\n\n"
                                    f"✅ **Right Choice:** `{info['options'][correct_idx]}`\n"
                                    f"🔍 **ICAI Logic:** _{info.get('explanation', 'ICAI module principle applies.')}_"
                                )
                                send_message(user_id, wrong_dm_text)

                    # --- MESSAGE HANDLER ---
                    if "message" in result:
                        message = result["message"]
                        chat_id = message["chat"]["id"]
                        message_id = message["message_id"]
                        user_id = message["from"]["id"]
                        first_name = message["from"].get("first_name", "Student")
                        username = message["from"].get("username", "")
                        text = message.get("text", "").strip()

                        if "new_chat_members" in message:
                            for new_mem in message["new_chat_members"]:
                                quote = random.choice(MOTIVATIONAL_QUOTES)
                                welcome_msg = f"👋 **Welcome <a href='tg://user?id={new_mem['id']}'>{new_mem.get('first_name', 'Student')}</a> to CA Vault!**\n\n{quote}"
                                res_w = send_message(chat_id, welcome_msg, parse_mode="HTML")
                                if res_w.get("ok"):
                                    database.add_auto_purge_message(chat_id, res_w["result"]["message_id"], delay_seconds=60)
                            continue

                        u_db = database.get_or_create_user(user_id, username, first_name, owner_id=OWNER_ID)
                        linked_grp = database.get_user_linked_group(user_id)

                        if "document" in message:
                            doc = message["document"]
                            file_id = doc["file_id"]
                            file_name = doc.get("file_name", "Study_Material.pdf")

                            if database.is_duplicate_file(file_id):
                                if not text.startswith("/addpdf"):
                                    send_message(chat_id, f"ℹ️ **File Already Exists:** `{file_name}` is available in Vault!")
                            else:
                                app_id = database.add_pending_approval(file_id, file_name, f"#{file_name.split('.')[0].lower()}", user_id)
                                app_kb = {
                                    "inline_keyboard": [
                                        [{"text": "✅ Approve & Publish", "callback_data": f"app_ok_{app_id}"}],
                                        [{"text": "❌ Reject / Remove", "callback_data": "app_rej"}]
                                    ]
                                }
                                send_message(OWNER_ID, f"📥 **NEW MATERIAL FOR APPROVAL!**\n\n📄 File: `{file_name}`\n👤 Contributor: {first_name} (`{user_id}`)\n🆔 Approval ID: `#{app_id}`", reply_markup=app_kb)
                                send_message(chat_id, f"✅ **Material Received!** Submitted to Admin for approval.")

                        # Targeted Moderation Engine
                        if is_group_chat(chat_id) and get_role(user_id) not in ["owner", "admin"]:
                            if "sticker" in message and database.get_setting("block_stickers", "on") == "on":
                                delete_message(chat_id, message_id)
                                warn_c, is_p = database.add_user_warning(user_id, "Inappropriate sticker")
                                mute_time = int((datetime.now() + timedelta(hours=24)).timestamp()) if not is_p else None
                                restrict_chat_member(chat_id, user_id, until_date=mute_time)
                                send_message(OWNER_ID, f"🛡️ **MODERATION ALERT**: Muted {first_name} (@{username}) for sticker. Strike #{warn_c}.")
                                continue

                            bad_words = database.get_bad_words()
                            if any(w in text.lower() for w in bad_words if w):
                                delete_message(chat_id, message_id)
                                warn_c, is_p = database.add_user_warning(user_id, "Abusive/Spam words")
                                mute_time = int((datetime.now() + timedelta(hours=24)).timestamp()) if not is_p else None
                                restrict_chat_member(chat_id, user_id, until_date=mute_time)
                                send_message(OWNER_ID, f"🛡️ **MODERATION ALERT**: Muted {first_name} (@{username}) for abusive text. Strike #{warn_c}.")
                                continue

                        matched_kw = detect_material_request_intent(text)
                        if matched_kw and not text.startswith("/"):
                            redirect_kb = {
                                "inline_keyboard": [
                                    [{"text": "👉 Click Here To Open In Study Channel", "url": matched_kw["channel_link"]}]
                                ]
                            }
                            send_message(chat_id, f"📚 **CA Vault Study Material Found!**\nTeacher/Module: `{matched_kw['teacher_name'] or matched_kw['keyword']}`", reply_markup=redirect_kb)

                        # Commands Processing
                        if text.startswith("/setcount"):
                            if get_role(user_id) in ["owner", "admin"]:
                                try:
                                    cnt_val = int(text.replace("/setcount", "").strip())
                                    database.set_setting("default_q_count", str(cnt_val))
                                    send_message(chat_id, f"✅ **Default Question Count Updated!** Set to `{cnt_val}` Qs.")
                                except ValueError:
                                    send_message(chat_id, "⚠️ Usage: `/setcount 20`")

                        elif text.startswith("/setlevel"):
                            if get_role(user_id) in ["owner", "admin"]:
                                lvl_val = text.replace("/setlevel", "").strip().upper()
                                if lvl_val in ["MEDIUM", "HIGH", "EXTREME_HIGH"]:
                                    database.set_setting("default_level", lvl_val)
                                    send_message(chat_id, f"✅ **Default Difficulty Level Updated!** Set to `{lvl_val}`.")
                                else:
                                    send_message(chat_id, "⚠️ Usage: `/setlevel MEDIUM` or `/setlevel HIGH` or `/setlevel EXTREME_HIGH`")

                        elif text.startswith("/setschedule"):
                            if user_id in schedule_wizard_state:
                                raw_val = text.replace("/setschedule", "").strip()
                                if "|" in raw_val:
                                    parts = raw_val.split("|")
                                    date_val = parts[0].strip()
                                    time_val = parts[1].strip().upper()

                                    try:
                                        datetime.strptime(date_val, "%Y-%m-%d")
                                        datetime.strptime(time_val, "%I:%M %p")

                                        schedule_wizard_state[user_id]["schedule_date"] = date_val
                                        schedule_wizard_state[user_id]["schedule_time"] = time_val

                                        st = schedule_wizard_state[user_id]
                                        summary = get_wizard_summary(st)

                                        keyboard = {
                                            "inline_keyboard": [
                                                [{"text": "10 Qs", "callback_data": "swiz_cnt_10"}, {"text": "20 Qs", "callback_data": "swiz_cnt_20"}],
                                                [{"text": "30 Qs", "callback_data": "swiz_cnt_30"}, {"text": "50 Qs", "callback_data": "swiz_cnt_50"}]
                                            ]
                                        }
                                        send_message(chat_id, f"{summary}✅ **Schedule Time Locked!**\n\n🔢 **Step 5:** Select Question Count per Session:", reply_markup=keyboard)
                                    except ValueError:
                                        send_message(chat_id, "⚠️ **Invalid Format!**\nUse: `/setschedule YYYY-MM-DD | hh:mm AM/PM`\nExample: `/setschedule 2026-08-10 | 06:30 PM`")
                                else:
                                    send_message(chat_id, "⚠️ **Missing separator (`|`)!**\nUse: `/setschedule YYYY-MM-DD | hh:mm AM/PM`")

                        elif text.startswith("/chapter_only_sched"):
                            if user_id in schedule_wizard_state:
                                chapter_name = text.replace("/chapter_only_sched", "", 1).strip()
                                if chapter_name:
                                    schedule_wizard_state[user_id]["chapter"] = chapter_name
                                    schedule_wizard_state[user_id]["subtopics"] = ""
                                    st = schedule_wizard_state[user_id]
                                    summary = get_wizard_summary(st)
                                    keyboard = {
                                        "inline_keyboard": [
                                            [{"text": "⚡ MEDIUM", "callback_data": "swiz_lvl_MEDIUM"}],
                                            [{"text": "🔥 HIGH", "callback_data": "swiz_lvl_HIGH"}],
                                            [{"text": "💀 EXTREME HIGH", "callback_data": "swiz_lvl_EXTREME_HIGH"}]
                                        ]
                                    }
                                    send_message(chat_id, f"{summary}✅ **Chapter Locked:** `{chapter_name}`\n\n🎯 **Step 3:** Select Starting Difficulty Level:", reply_markup=keyboard)
                                else:
                                    send_message(chat_id, "⚠️ Usage: `/chapter_only_sched [Chapter Name]`")

                        elif text.startswith("/chapter_sched"):
                            if user_id in schedule_wizard_state:
                                raw = text.replace("/chapter_sched", "", 1).strip()
                                if "|" in raw:
                                    chap_part, sub_part = raw.split("|", 1)
                                    schedule_wizard_state[user_id]["chapter"] = chap_part.strip()
                                    schedule_wizard_state[user_id]["subtopics"] = sub_part.strip()
                                    st = schedule_wizard_state[user_id]
                                    summary = get_wizard_summary(st)
                                    keyboard = {
                                        "inline_keyboard": [
                                            [{"text": "⚡ MEDIUM", "callback_data": "swiz_lvl_MEDIUM"}],
                                            [{"text": "🔥 HIGH", "callback_data": "swiz_lvl_HIGH"}],
                                            [{"text": "💀 EXTREME HIGH", "callback_data": "swiz_lvl_EXTREME_HIGH"}]
                                        ]
                                    }
                                    send_message(chat_id, f"{summary}✅ **Chapter + Sub-topics Locked!**\n\n🎯 **Step 3:** Select Starting Difficulty Level:", reply_markup=keyboard)
                                else:
                                    send_message(chat_id, "⚠️ Usage: `/chapter_sched Chapter Name | Subtopic 1, Subtopic 2`")

                        elif text.startswith("/chapter_only"):
                            if chat_id in quiz_builder_state:
                                chapter_name = text.replace("/chapter_only", "", 1).strip()
                                if chapter_name:
                                    quiz_builder_state[chat_id]["chapter"] = chapter_name
                                    quiz_builder_state[chat_id]["subtopics"] = ""
                                    keyboard = {
                                        "inline_keyboard": [
                                            [{"text": "⚡ MEDIUM", "callback_data": "lvl_MEDIUM"}],
                                            [{"text": "🔥 HIGH", "callback_data": "lvl_HIGH"}],
                                            [{"text": "💀 EXTREME HIGH", "callback_data": "lvl_EXTREME_HIGH"}]
                                        ]
                                    }
                                    send_message(chat_id, f"✅ **Chapter Locked:** `{chapter_name}`\n\n🎯 **Step 3:** Select Starting Difficulty Level:", reply_markup=keyboard)
                                else:
                                    send_message(chat_id, "⚠️ Usage: `/chapter_only [Chapter Name]`")

                        elif text.startswith("/chapter"):
                            if chat_id in quiz_builder_state:
                                raw = text.replace("/chapter", "", 1).strip()
                                if "|" in raw:
                                    chap_part, sub_part = raw.split("|", 1)
                                    quiz_builder_state[chat_id]["chapter"] = chap_part.strip()
                                    quiz_builder_state[chat_id]["subtopics"] = sub_part.strip()
                                    keyboard = {
                                        "inline_keyboard": [
                                            [{"text": "⚡ MEDIUM", "callback_data": "lvl_MEDIUM"}],
                                            [{"text": "🔥 HIGH", "callback_data": "lvl_HIGH"}],
                                            [{"text": "💀 EXTREME HIGH", "callback_data": "lvl_EXTREME_HIGH"}]
                                        ]
                                    }
                                    send_message(chat_id, f"✅ **Chapter + Sub-topics Locked!**\n\n🎯 **Step 3:** Select Starting Difficulty Level:", reply_markup=keyboard)
                                else:
                                    send_message(chat_id, "⚠️ Usage: `/chapter Chapter Name | Subtopic 1, Subtopic 2`")

                        elif text.startswith("/link_group"):
                            if is_group_chat(chat_id):
                                send_message(chat_id, "⚠️ Send `/link_group` in **Bot DM**!")
                                continue
                            try:
                                target_id = int(text.replace("/link_group", "").strip())
                                database.set_user_linked_group(user_id, target_id)
                                send_message(chat_id, f"🎉 **Target Group Saved Permanently in Database!**\n\n🆔 **Target Group ID:** `{target_id}`\n\n*Ab aapko baar-baar link karne ki zaroorat nahi padegi — quiz ho, schedule ho ya kuch bhi, hamesha yehi group use hoga!*")
                            except Exception:
                                send_message(chat_id, "⚠️ **Invalid Format!** Use: `/link_group -100123456789`")

                        elif text == "/schedule":
                            if is_group_chat(chat_id):
                                send_message(chat_id, "⚠️ Please use `/schedule` in **Bot DM**.")
                                continue
                            target_grp_for_schedule = resolve_target_group(user_id, chat_id)
                            if not target_grp_for_schedule:
                                send_message(chat_id, "⚠️ **No group linked yet!**\nFirst send: `/link_group <GroupID>` in DM.")
                                continue

                            schedule_wizard_state[user_id] = {"group_id": target_grp_for_schedule}
                            st = schedule_wizard_state[user_id]
                            summary = get_wizard_summary(st)
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "📊 Accounts", "callback_data": "swiz_sub_Accounts"}],
                                    [{"text": "📜 Business Laws", "callback_data": "swiz_sub_Business Laws"}],
                                    [{"text": "📈 Quantitative Aptitude", "callback_data": "swiz_sub_Quantitative Aptitude"}],
                                    [{"text": "💼 Economics", "callback_data": "swiz_sub_Economics"}]
                                ]
                            }
                            send_message(chat_id, f"{summary}🗓️ **SCHEDULER WIZARD**\n\n📘 **Step 1:** Select Target Subject:", reply_markup=keyboard)

                        elif text in ["/dashboard", "/panel"]:
                            if get_role(user_id) in ["owner", "admin"]:
                                send_message(chat_id, f"{fancy_header('🎛️', 'CA VAULT — OWNER CONTROL PANEL')}\nSelect an option below to manage settings & access:", reply_markup=build_dashboard_keyboard())
                            else:
                                send_message(chat_id, "🔒 Permission Denied: Owner/Admin role required.")

                        elif text.startswith("/addkeyword"):
                            if get_role(user_id) in ["owner", "admin"]:
                                try:
                                    parts = text.replace("/addkeyword", "").split("|")
                                    kw = parts[0].strip()
                                    link = parts[1].strip()
                                    t_name = parts[2].strip() if len(parts) >= 3 else "ICAI Study Material"
                                    database.add_smart_keyword(kw, link, teacher_name=t_name, created_by=user_id)
                                    send_message(chat_id, f"✅ **Smart Keyword Added!**\n🏷️ Keyword: `{kw}`\n🔗 Link: `{link}`\n👨‍🏫 Teacher: `{t_name}`")
                                except Exception:
                                    send_message(chat_id, "⚠️ Format: `/addkeyword #ashish_law_notes | [https://t.me/channel/102](https://t.me/channel/102) | Ashish Sir`")

                        elif text == "/keywords":
                            kws = database.search_smart_keywords()
                            k_msg = "📚 **CA VAULT SMART STUDY KEYWORDS** 📚\n\n"
                            for k in kws:
                                k_msg += f"• **{k['keyword']}** ({k['teacher_name'] or 'General'}): {k['channel_link']}\n"
                            send_message(chat_id, k_msg)

                        elif text.startswith("/settimer"):
                            if get_role(user_id) in ["owner", "admin"]:
                                try:
                                    sec = int(text.replace("/settimer", "").replace("s", "").strip())
                                    active_quiz_session_timers[chat_id] = sec
                                    database.set_setting("default_timer", str(sec))
                                    send_message(chat_id, f"⏱️ **Live Quiz Timer Updated!** Running at `{sec}s` per question.")
                                except ValueError:
                                    send_message(chat_id, "⚠️ Usage: `/settimer 30` (in seconds)")

                        elif text.startswith("/settime"):
                            if get_role(user_id) in ["owner", "admin"]:
                                time_arg = text.replace("/settime", "").strip()
                                if time_arg:
                                    today_str = datetime.now().strftime("%Y-%m-%d")
                                    database.set_daily_quiz_time(today_str, time_arg)
                                    database.set_setting("default_time", time_arg)
                                    send_message(chat_id, f"✅ **Daily Quiz Time Updated!**\n⏰ New Time: `{time_arg}` PM")

                        elif text.startswith("/setmode"):
                            if get_role(user_id) in ["owner", "admin"]:
                                mode_arg = text.replace("/setmode", "").strip().lower()
                                if mode_arg in ["auto", "manual"]:
                                    database.set_setting("mode", mode_arg)
                                    send_message(chat_id, f"⚡ **Engine Mode Updated!** Now running in `{mode_arg.upper()}` mode.")
                                else:
                                    send_message(chat_id, "⚠️ Usage: `/setmode auto` or `/setmode manual`")

                        elif text.startswith("/parse"):
                            if get_role(user_id) in ["owner", "admin"]:
                                raw_qs = text.replace("/parse", "").strip()
                                parsed = parse_raw_text_questions(raw_qs)
                                send_message(chat_id, f"✅ **Parsed {len(parsed)} Questions Successfully!** Ready for execution.")

                        elif text.startswith("/filter"):
                            if get_role(user_id) in ["owner", "admin"]:
                                parts = text.split(maxsplit=2)
                                if len(parts) >= 3 and parts[1] == "add":
                                    database.add_bad_word(parts[2], user_id)
                                    send_message(chat_id, f"✅ Added word `{parts[2]}` to auto-filter list.")
                                elif len(parts) >= 3 and parts[1] == "remove":
                                    database.remove_bad_word(parts[2])
                                    send_message(chat_id, f"✅ Removed word `{parts[2]}` from filter list.")

                        elif text == "/filters":
                            if get_role(user_id) in ["owner", "admin"]:
                                words = database.get_bad_words()
                                send_message(chat_id, f"🛡️ **CURRENT BLOCKED WORDS:**\n{', '.join(words) if words else 'None'}")

                        elif text.startswith("/stickers"):
                            if get_role(user_id) in ["owner", "admin"]:
                                arg = text.replace("/stickers", "").strip().lower()
                                if arg in ["on", "off"]:
                                    database.set_setting("block_stickers", arg)
                                    send_message(chat_id, f"✅ Sticker auto-block set to **{arg.upper()}**")

                        elif text.startswith("/grant"):
                            if get_role(user_id) in ["owner", "admin"]:
                                parts = text.split()
                                if len(parts) >= 3:
                                    target_str = parts[1]
                                    g_type = parts[2].lower()
                                    try: target_uid = int(target_str)
                                    except ValueError: target_uid = 123456789
                                    database.grant_quiz_access(target_uid, user_id, g_type)
                                    send_message(chat_id, f"✅ Granted `{g_type.upper()}` quiz access to user `{target_str}`.")

                        elif text.startswith("/quiz"):
                            has_acc, g_type, exp = database.get_user_quiz_access(user_id, OWNER_ID)
                            if not has_acc and not is_user_admin_or_owner(message):
                                req_kb = {
                                    "inline_keyboard": [
                                        [{"text": "Grant 1 Week", "callback_data": f"grant_1w_{user_id}"}, {"text": "Grant 2 Weeks", "callback_data": f"grant_2w_{user_id}"}],
                                        [{"text": "Grant Full Free", "callback_data": f"grant_ff_{user_id}"}, {"text": "Reject", "callback_data": f"grant_rej_{user_id}"}]
                                    ]
                                }
                                send_message(OWNER_ID, f"🔔 **QUIZ ACCESS REQUEST**\nUser {first_name} (ID: `{user_id}`) requested quiz access.", reply_markup=req_kb)
                                send_message(chat_id, "🔒 **Quiz Access Restricted:** Approval request sent to Bot Owner!")
                                continue

                            resolve_target_group(user_id, chat_id)

                            def_cnt = int(database.get_setting("default_q_count", "15"))
                            def_lvl = database.get_setting("default_level", "EXTREME_HIGH")
                            quiz_builder_state[chat_id] = {"subject": "Accounts", "chapter": "", "level": def_lvl, "count": def_cnt, "break_freq": 0, "break_duration": 0, "conductor_id": user_id}
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "📊 Accounts", "callback_data": "sub_Accounts"}],
                                    [{"text": "📜 Business Laws", "callback_data": "sub_Business Laws"}],
                                    [{"text": "📈 Quantitative Aptitude", "callback_data": "sub_Quantitative Aptitude"}],
                                    [{"text": "💼 Economics", "callback_data": "sub_Economics"}]
                                ]
                            }
                            send_message(chat_id, f"{fancy_header('🎯', 'INSTANT QUIZ WIZARD')}\n\n📘 **Step 1:** Select Subject:", reply_markup=keyboard)

                        elif text.startswith("/start") or text == "/menu":
                            t, kb = build_main_home_ui(first_name, linked_grp)
                            send_message(chat_id, t, reply_markup=kb)

                        elif text.startswith("/help"):
                            send_message(chat_id, get_role_based_help_text(user_id))

                    # --- CALLBACK QUERY HANDLER ---
                    elif "callback_query" in result:
                        query = result["callback_query"]
                        query_chat_id = query["message"]["chat"]["id"]
                        message_id = query["message"]["message_id"]
                        data_cb = query["data"]
                        user_id = query["from"]["id"]
                        first_name = query["from"].get("first_name", "Student")

                        requests.post(f"{BASE_URL}/answerCallbackQuery", json={"callback_query_id": query["id"]}, timeout=8)
                        linked_grp = database.get_user_linked_group(user_id)

                        if data_cb == "ui_home":
                            t, kb = build_main_home_ui(first_name, linked_grp)
                            edit_message(query_chat_id, message_id, t, reply_markup=kb)

                        elif data_cb == "ui_link_group_info":
                            info_text = (
                                f"{fancy_header('🔗', 'PERMANENT GROUP LINKING SYSTEM')}\n\n"
                                f"Current Saved Group: `{linked_grp or 'None'}`\n\n"
                                f"📝 **Kaise Link Karein:**\n"
                                f"1. Bot ko apne Telegram Group mein Admin banayein.\n"
                                f"2. Group ka Chat ID copy karein (e.g. `-100123456789`).\n"
                                f"3. DM mein bhejein: `/link_group <GroupID>`\n\n"
                                f"*Ek baar set karne ke baad bot hamesha ke liye database mein group ko yaad rakhega — quiz, scheduler, sab isi group ko use karenge, dobara link karne ki zaroorat nahi!*"
                            )
                            kb = {"inline_keyboard": [[{"text": "🔙 Back to Home OS", "callback_data": "ui_home"}]]}
                            edit_message(query_chat_id, message_id, info_text, reply_markup=kb)

                        elif data_cb == "ui_quiz_start":
                            target_grp = resolve_target_group(user_id, query_chat_id)
                            if not target_grp:
                                edit_message(query_chat_id, message_id, "⚠️ **No Group Linked!**\nPehle DM mein `/link_group <GroupId>` bhej kar group link karein.", reply_markup={"inline_keyboard": [[{"text": "🔙 Back", "callback_data": "ui_home"}]]})
                            else:
                                edit_message(query_chat_id, message_id, f"🚀 **Session Dispatched!**\nQuiz running live in Target Group (`{target_grp}`).", reply_markup={"inline_keyboard": [[{"text": "🔙 Back", "callback_data": "ui_home"}]]})
                                def_cnt = int(database.get_setting("default_q_count", "15"))
                                def_tmr = int(database.get_setting("default_timer", "30"))
                                def_lvl = database.get_setting("default_level", "EXTREME_HIGH")
                                threading.Thread(target=run_quiz_session, args=(target_grp, "Accounts", "", def_cnt, def_tmr, 0, 0, def_lvl, user_id), daemon=True).start()

                        elif data_cb == "ui_schedule_wizard":
                            target_grp = resolve_target_group(user_id, query_chat_id)
                            if not target_grp:
                                edit_message(query_chat_id, message_id, "⚠️ **No Group Linked!**\nPehle DM mein `/link_group <GroupId>` bhej kar group link karein.", reply_markup={"inline_keyboard": [[{"text": "🔙 Back", "callback_data": "ui_home"}]]})
                            else:
                                schedule_wizard_state[user_id] = {"group_id": target_grp}
                                st = schedule_wizard_state[user_id]
                                summary = get_wizard_summary(st)
                                keyboard = {
                                    "inline_keyboard": [
                                        [{"text": "📊 Accounts", "callback_data": "swiz_sub_Accounts"}],
                                        [{"text": "📜 Business Laws", "callback_data": "swiz_sub_Business Laws"}],
                                        [{"text": "📈 Quantitative Aptitude", "callback_data": "swiz_sub_Quantitative Aptitude"}],
                                        [{"text": "💼 Economics", "callback_data": "swiz_sub_Economics"}],
                                        [{"text": "🔙 Back", "callback_data": "ui_home"}]
                                    ]
                                }
                                edit_message(query_chat_id, message_id, f"{summary}🗓️ **AUTO SCHEDULER WIZARD**\n\n📘 **Step 1:** Select Subject:", reply_markup=keyboard)

                        elif data_cb == "ui_hub":
                            kws = database.search_smart_keywords()
                            k_msg = f"{fancy_header('📚', 'SMART KNOWLEDGE HUB')}\n\n"
                            if kws:
                                for k in kws:
                                    k_msg += f"• **{k['keyword']}** ({k['teacher_name'] or 'General'}): {k['channel_link']}\n"
                            else:
                                k_msg += "_No keywords indexed yet._"
                            kb = {"inline_keyboard": [[{"text": "🔙 Back to Home OS", "callback_data": "ui_home"}]]}
                            edit_message(query_chat_id, message_id, k_msg, reply_markup=kb)

                        elif data_cb == "ui_leaderboard":
                            edit_message(query_chat_id, message_id, "🏆 **LEADERBOARD**\n\nUse `/leaderboard` for the full ranked list.", reply_markup={"inline_keyboard": [[{"text": "🔙 Back", "callback_data": "ui_home"}]]})

                        elif data_cb == "ui_settings":
                            edit_message(query_chat_id, message_id, "⚙️ **SYSTEM SETTINGS**\n\nUse `/dashboard` (Owner/Admin) for full control.", reply_markup={"inline_keyboard": [[{"text": "🔙 Back", "callback_data": "ui_home"}]]})

                        # --- LIVE INTERACTIVE QUIZ STEPPER WIZARD ---
                        elif data_cb.startswith("sub_"):
                            subj = data_cb.split("_", 1)[1]
                            quiz_builder_state[query_chat_id]["subject"] = subj
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "⏩ Full Subject (Skip)", "callback_data": "chap_skip"}],
                                    [{"text": "📖 Full Chapter Only", "callback_data": "chap_only_prompt"}],
                                    [{"text": "🎯 Chapter + Sub-topics", "callback_data": "chap_custom"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"✅ Subject: **{subj}**\n\n📖 **Step 2:** Choose Quiz Scope:", reply_markup=keyboard)

                        elif data_cb == "chap_only_prompt":
                            edit_message(query_chat_id, message_id, "✍️ Send command for Full Chapter:\n`/chapter_only [Chapter Name]`")

                        elif data_cb == "chap_custom":
                            edit_message(query_chat_id, message_id, "✍️ Send command for Chapter + Sub-topics:\n`/chapter Chapter Name | Subtopic 1, Subtopic 2`")

                        elif data_cb == "chap_skip":
                            quiz_builder_state[query_chat_id]["chapter"] = ""
                            quiz_builder_state[query_chat_id]["subtopics"] = ""
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "⚡ MEDIUM", "callback_data": "lvl_MEDIUM"}],
                                    [{"text": "🔥 HIGH", "callback_data": "lvl_HIGH"}],
                                    [{"text": "💀 EXTREME HIGH", "callback_data": "lvl_EXTREME_HIGH"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "🎯 **Step 3:** Select Starting Difficulty Level:", reply_markup=keyboard)

                        elif data_cb.startswith("lvl_"):
                            lvl = data_cb.split("lvl_")[1]
                            quiz_builder_state[query_chat_id]["level"] = lvl
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "10 Qs", "callback_data": "cnt_10"}, {"text": "20 Qs", "callback_data": "cnt_20"}],
                                    [{"text": "30 Qs", "callback_data": "cnt_30"}, {"text": "50 Qs", "callback_data": "cnt_50"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"✅ Difficulty: **{lvl}**\n\n🔢 **Step 4:** Select Question Count:", reply_markup=keyboard)

                        elif data_cb.startswith("cnt_"):
                            cnt = int(data_cb.split("_")[1])
                            quiz_builder_state[query_chat_id]["count"] = cnt
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "⚡ No Breaks", "callback_data": "break_none"}],
                                    [{"text": "☕ Every 20 Qs (5 min)", "callback_data": "break_20_5"}],
                                    [{"text": "☕ Every 30 Qs (10 min)", "callback_data": "break_30_10"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"✅ Questions: **{cnt}**\n\n☕ **Step 5:** Select Break Setting:", reply_markup=keyboard)

                        elif data_cb == "break_none":
                            quiz_builder_state[query_chat_id]["break_freq"] = 0
                            quiz_builder_state[query_chat_id]["break_duration"] = 0
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "20s", "callback_data": "timer_20"}, {"text": "30s", "callback_data": "timer_30"}],
                                    [{"text": "45s", "callback_data": "timer_45"}, {"text": "60s", "callback_data": "timer_60"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "⚡ Mode: **Non-stop**\n\n⏱️ **Step 6:** Select Timer per Question:", reply_markup=keyboard)

                        elif data_cb.startswith("break_"):
                            parts = data_cb.split("_")
                            freq = int(parts[1])
                            mins = int(parts[2])
                            quiz_builder_state[query_chat_id]["break_freq"] = freq
                            quiz_builder_state[query_chat_id]["break_duration"] = mins * 60
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "20s", "callback_data": "timer_20"}, {"text": "30s", "callback_data": "timer_30"}],
                                    [{"text": "45s", "callback_data": "timer_45"}, {"text": "60s", "callback_data": "timer_60"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"☕ Break: **Every {freq} Qs ({mins} min)**\n\n⏱️ **Step 6:** Select Timer per Question:", reply_markup=keyboard)

                        elif data_cb.startswith("timer_"):
                            tmr = int(data_cb.split("_")[1])
                            state = quiz_builder_state.get(query_chat_id, {})
                            subj = state.get("subject", "Accounts")
                            chap = state.get("chapter", "")
                            subtop = state.get("subtopics", "")
                            cnt = state.get("count", 15)
                            bf = state.get("break_freq", 0)
                            bd = state.get("break_duration", 0)
                            lvl = state.get("level", "EXTREME_HIGH")
                            cond_id = state.get("conductor_id")

                            target_grp = resolve_target_group(cond_id or user_id, query_chat_id)

                            edit_message(query_chat_id, message_id, f"🚀 **Starting Quiz...**\n\n📘 Subject: `{subj}`\n🔢 Questions: `{cnt}`\n⏱️ Timer: `{tmr}s`\n📌 Target: `{target_grp}`")
                            threading.Thread(target=run_quiz_session, args=(target_grp or query_chat_id, subj, chap, cnt, tmr, bf, bd, lvl, cond_id, subtop), daemon=True).start()

                        # --- SCHEDULER WIZARD CALLBACKS ---
                        elif data_cb.startswith("swiz_sub_"):
                            subj = data_cb.split("swiz_sub_")[1]
                            schedule_wizard_state[query_chat_id]["subject"] = subj
                            st = schedule_wizard_state[query_chat_id]
                            summary = get_wizard_summary(st)
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "⏩ Full Subject (Skip)", "callback_data": "swiz_chap_skip"}],
                                    [{"text": "📖 Full Chapter Only", "callback_data": "swiz_chap_only_prompt"}],
                                    [{"text": "🎯 Chapter + Sub-topics", "callback_data": "swiz_chap_custom"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"{summary}📖 **Step 2:** Choose Scope:", reply_markup=keyboard)

                        elif data_cb == "swiz_chap_only_prompt":
                            edit_message(query_chat_id, message_id, "✍️ Send command for Full Chapter:\n`/chapter_only_sched [Chapter Name]`")

                        elif data_cb == "swiz_chap_custom":
                            edit_message(query_chat_id, message_id, "✍️ Send command for Chapter & Sub-topics:\n`/chapter_sched Chapter Name | Subtopic 1, Subtopic 2`")

                        elif data_cb == "swiz_chap_skip":
                            schedule_wizard_state[query_chat_id]["chapter"] = ""
                            schedule_wizard_state[query_chat_id]["subtopics"] = ""
                            st = schedule_wizard_state[query_chat_id]
                            summary = get_wizard_summary(st)
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "⚡ MEDIUM", "callback_data": "swiz_lvl_MEDIUM"}],
                                    [{"text": "🔥 HIGH", "callback_data": "swiz_lvl_HIGH"}],
                                    [{"text": "💀 EXTREME HIGH", "callback_data": "swiz_lvl_EXTREME_HIGH"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"{summary}🎯 **Step 3:** Select Starting Difficulty Level:", reply_markup=keyboard)

                        elif data_cb.startswith("swiz_lvl_"):
                            lvl = data_cb.split("swiz_lvl_")[1]
                            schedule_wizard_state[query_chat_id]["level"] = lvl
                            st = schedule_wizard_state[query_chat_id]
                            summary = get_wizard_summary(st)
                            today_str = datetime.now().strftime("%Y-%m-%d")
                            edit_message(
                                query_chat_id,
                                message_id,
                                f"{summary}📅 **Step 4:** Set Custom Schedule Date & Time (AM/PM):\n\n"
                                f"Send command in this exact format:\n"
                                f"`/setschedule YYYY-MM-DD | hh:mm AM/PM`\n\n"
                                f"📌 *Example:* `/setschedule {today_str} | 07:30 PM`"
                            )

                        elif data_cb.startswith("swiz_cnt_"):
                            cnt = int(data_cb.split("swiz_cnt_")[1])
                            schedule_wizard_state[query_chat_id]["count"] = cnt
                            st = schedule_wizard_state[query_chat_id]
                            summary = get_wizard_summary(st)
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "20s", "callback_data": "swiz_tmr_20"}, {"text": "30s", "callback_data": "swiz_tmr_30"}],
                                    [{"text": "45s", "callback_data": "swiz_tmr_45"}, {"text": "60s", "callback_data": "swiz_tmr_60"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"{summary}⏱️ **Step 6:** Select Timer per Question:", reply_markup=keyboard)

                        elif data_cb.startswith("swiz_tmr_"):
                            tmr = int(data_cb.split("swiz_tmr_")[1])
                            st = schedule_wizard_state.get(query_chat_id, {})
                            target_grp = st.get("group_id") or resolve_target_group(query_chat_id, None)
                            subj = st.get("subject", "Accounts")
                            chap = st.get("chapter", "")
                            subtop = st.get("subtopics", "")
                            lvl = st.get("level", "EXTREME_HIGH")
                            sch_date = st.get("schedule_date", datetime.now().strftime("%Y-%m-%d"))
                            sch_time_ampm = st.get("schedule_time", "08:00 PM")
                            cnt = st.get("count", 15)

                            dt_object = datetime.strptime(f"{sch_date} {sch_time_ampm}", "%Y-%m-%d %I:%M %p")
                            formatted_dt_str = dt_object.strftime("%Y-%m-%d %H:%M")

                            scheduled_quizzes.append({
                                "chat_id": target_grp,
                                "datetime": formatted_dt_str,
                                "subject": subj,
                                "chapter": chap,
                                "subtopics": subtop,
                                "count": cnt,
                                "timer": tmr,
                                "level": lvl,
                                "conductor_id": query_chat_id
                            })

                            chap_text = chap if chap else "Full Subject Syllabus"
                            subtop_text = f"\n│ 🎯 **Subtopics:** `{subtop}`" if subtop else ""

                            announcement_text = (
                                f"┌──────────────────────────────────────\n"
                                f"│ 📢 **SCHEDULED QUIZ ANNOUNCEMENT**\n"
                                f"├──────────────────────────────────────\n"
                                f"│ 📘 **Subject:** `{subj}`\n"
                                f"│ 📖 **Scope:** `{chap_text}`{subtop_text}\n"
                                f"│ 📅 **Date:** `{sch_date}`\n"
                                f"│ ⏰ **Time:** `{sch_time_ampm}`\n"
                                f"│ 🔢 **Questions:** `{cnt}` | ⏱️ **Timer:** `{tmr}s`\n"
                                f"└──────────────────────────────────────\n"
                                f"📌 *Quiz will start automatically at the scheduled time!*"
                            )
                            res_msg = send_message(target_grp, announcement_text)
                            if res_msg.get("ok"):
                                pin_message(target_grp, res_msg["result"]["message_id"])

                            edit_message(
                                query_chat_id,
                                message_id,
                                f"🎉 **Schedule Created & Announced!**\n\n"
                                f"📌 Group ID: `{target_grp}`\n"
                                f"📘 Subject: `{subj}` (`{chap_text}`)\n"
                                f"📅 Date: `{sch_date}`\n"
                                f"⏰ Time: `{sch_time_ampm}`\n\n"
                                f"_Group announcement pinned successfully!_"
                            )

                        elif data_cb.startswith("app_ok_"):
                            app_id = int(data_cb.split("_")[2])
                            database.update_approval_status(app_id, "approved")
                            app_info = database.get_pending_approval_by_id(app_id)
                            database.add_pdf_to_vault(app_info["file_id"], app_info["file_name"], app_info["uploaded_by"])
                            database.add_smart_keyword(app_info["suggested_keyword"], "[https://t.me/CAVaultStudy/100](https://t.me/CAVaultStudy/100)", teacher_name="Approved Material")
                            edit_message(query_chat_id, message_id, f"✅ **APPROVED & PUBLISHED!**\n📄 File: `{app_info['file_name']}`\n🏷️ Keyword: `{app_info['suggested_keyword']}` indexed.")

                        elif data_cb == "app_rej":
                            edit_message(query_chat_id, message_id, "❌ **REJECTED:** Material upload discarded.")

                        elif data_cb.startswith("grant_"):
                            parts = data_cb.split("_")
                            action = parts[1]
                            target_u = int(parts[2])
                            if action == "1w":
                                database.grant_quiz_access(target_u, query["from"]["id"], "1week")
                                edit_message(query_chat_id, message_id, f"✅ Granted 1-Week Trial to user `{target_u}`.")
                            elif action == "2w":
                                database.grant_quiz_access(target_u, query["from"]["id"], "2weeks")
                                edit_message(query_chat_id, message_id, f"✅ Granted 2-Weeks Trial to user `{target_u}`.")
                            elif action == "ff":
                                database.grant_quiz_access(target_u, query["from"]["id"], "fullfree")
                                edit_message(query_chat_id, message_id, f"✅ Granted Full Free Access to user `{target_u}`.")
                            else:
                                edit_message(query_chat_id, message_id, f"❌ Rejected quiz request for user `{target_u}`.")

                        elif data_cb == "dash_settings":
                            edit_message(query_chat_id, message_id, "⚙️ **SYSTEM SETTINGS**\n\n• Mode: `AUTO`\n• Stickers Auto-Block: `ON`\n• Dynamic Timers: `25s - 45s`", reply_markup=build_dashboard_keyboard())

                        elif data_cb == "dash_mod":
                            edit_message(query_chat_id, message_id, "🛡️ **MODERATION CONTROL PANEL**\n\nUse `/filter add [word]` or `/stickers [on|off]` to control auto-purging filters.", reply_markup=build_dashboard_keyboard())

                        elif data_cb == "dash_access":
                            edit_message(query_chat_id, message_id, "👥 **ACCESS & TRIAL GRANTS**\n\nUse `/grant [user_id] [1week|2weeks|fullfree]` to manage access.", reply_markup=build_dashboard_keyboard())

                        elif data_cb == "dash_hub":
                            edit_message(query_chat_id, message_id, "📚 **SMART KNOWLEDGE HUB**\n\nUse `/addkeyword [#kw] | [link] | [teacher]` to add smart direct-redirect study keywords.", reply_markup=build_dashboard_keyboard())

                        elif data_cb == "dash_close":
                            delete_message(query_chat_id, message_id)

        except Exception as e:
            print(f"⚠️ [POLLING LOOP ERROR] {type(e).__name__}: {e}", flush=True)
            time.sleep(2)

class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"OK - CA Vault Quiz Bot is running smoothly!")
    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
    def log_message(self, format, *args):
        return

def start_health_check_server():
    port = int(os.getenv("PORT", "10000"))
    try:
        server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
        print(f"Health Check HTTP Server listening on port {port} for Render deployment...")
        server.serve_forever()
    except Exception as e:
        print(f"Health Check HTTP Server error: {e}")

if __name__ == "__main__":
    threading.Thread(target=start_health_check_server, daemon=True).start()
    threading.Thread(target=purge_background_worker, daemon=True).start()
    threading.Thread(target=icai_auto_sync_worker, daemon=True).start()
    threading.Thread(target=scheduler_background_worker, daemon=True).start()
    handle_updates()
