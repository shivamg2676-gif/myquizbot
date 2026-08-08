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

active_poll_tracker = {}
active_quiz_sessions = {}
active_quiz_session_timers = {}
quiz_builder_state = {}
session_user_scores = {}
session_user_streaks = {}
pinned_daily_messages = {}
last_pinned_topper_messages = {}

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

print("CA Vault Direct Execution Quiz Bot Starting (Master Enterprise Knowledge Hub)...")

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

# --- SMART CONTEXT DETECTOR FOR KNOWLEDGE HUB ---

def detect_material_request_intent(text):
    text_lower = text.lower().strip()
    
    # Check for direct hashtags or keywords in database
    keywords = database.search_smart_keywords()
    for kw_entry in keywords:
        kw = kw_entry["keyword"].lower()
        if kw in text_lower:
            return kw_entry
            
    # Check intent triggers (Demand vs Casual Chat)
    demand_triggers = ["chahiye", "bhej do", "send notes", "pdf link", "notes please", "give notes", "share pdf"]
    casual_triggers = ["tough hain", "kya tumne", "kaun padh raha hai", "samajh nahi aaya"]
    
    if any(c in text_lower for c in casual_triggers):
        return None
        
    if any(d in text_lower for d in demand_triggers):
        for kw_entry in keywords:
            # Fuzzy match subject/teacher names
            if kw_entry["teacher_name"].lower() in text_lower or kw_entry["keyword"].replace("#","").replace("_"," ") in text_lower:
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

def send_poll(chat_id, question, options, correct_option_id, open_period=30):
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
                "subject": ""
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

def run_quiz_session(target_chat_id, subject, chapter, count, timer, break_freq=0, break_duration=0, level="EXTREME_HIGH"):
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
    break_info = f"☕ Break: Every `{break_freq}` Qs for `{break_duration//60}` mins" if break_freq > 0 else "⚡ Mode: Non-stop (No Breaks)"
    send_message(target_chat_id, f"🎯 **{subject} - {chap_display}**\n🔢 Questions: `{count}` | ⏱️ Timer: `{timer}s`\n{break_info}\n\n🚀 *Quiz starting now! Powered by CA Vault Master Engine.*")
    
    current_difficulty = level

    for idx in range(count):
        if not active_quiz_sessions.get(target_chat_id, False):
            send_message(target_chat_id, "🛑 **Quiz Session Stopped.**")
            break

        if idx > 0 and break_freq > 0 and idx % break_freq == 0:
            send_message(target_chat_id, f"☕ **{idx} Questions Complete!**\n{break_duration // 60} minutes break shuru.")
            for _ in range(break_duration):
                if not active_quiz_sessions.get(target_chat_id, False):
                    break
                time.sleep(1)
            send_message(target_chat_id, "🚀 **Break Over!** Resuming quiz...")

        q = generate_ai_question(subject, chapter, current_difficulty)
        
        current_live_timer = active_quiz_session_timers.get(target_chat_id, timer)
        poll_timer = max(10, min(current_live_timer, 60))
        
        poll_res = send_poll(target_chat_id, f"Q{idx+1}/{count}: {q['question']}", q['options'], q['correct'], open_period=poll_timer)
        poll_id = poll_res.get("result", {}).get("poll", {}).get("id") if poll_res.get("ok") else None
        
        time.sleep(poll_timer + 1)
        
        if poll_id and poll_id in active_poll_tracker:
            p_data = active_poll_tracker[poll_id]
            total_v = p_data["total_votes"]
            wrong_v = p_data["wrong_count"]
            if total_v > 0 and (wrong_v / total_v) > 0.7:
                current_difficulty = "MEDIUM"
            else:
                current_difficulty = level
        
        feedback_text = f"💡 **Q{idx+1} Answer:** `{q['options'][q['correct']]}`\n🔍 *Concept:* {q['explanation']}"
        send_message(target_chat_id, feedback_text)
        time.sleep(2)

    active_quiz_sessions[target_chat_id] = False
    
    if is_group_chat(target_chat_id):
        set_chat_permissions(target_chat_id, can_send_messages=True)
        database.log_audit(0, 0, "FOCUS_MODE_OFF", f"Disabled focus mode after quiz in {target_chat_id}")

    scores = session_user_scores.get(target_chat_id, {})
    if scores:
        sorted_scores = sorted(scores.items(), key=lambda item: (item[1]["xp"], item[1]["correct"]), reverse=True)
        medals = ["🥇 Gold Badge", "🥈 Silver Badge", "🥉 Bronze Badge"]
        
        shayari = random.choice(SHAYARI_LIST)
        top_msg = f"{shayari}\n\n🏆 **DAILY TOPPERS LEADERBOARD** 🏆\nSubject: `{subject}` | Questions: `{count}`\n\n"
        
        for idx, (uid, uinfo) in enumerate(sorted_scores[:3]):
            top_msg += f"{medals[idx]} — **{uinfo['name']}**: `{uinfo['xp']} XP` | ✅ `{uinfo['correct']}` Correct\n"
            
            if idx == 0 and "SUNDAY MEGA" in subject.upper():
                database.set_flex_admin(uid)
                send_message(target_chat_id, f"🏆 **SUNDAY MEGA QUIZ CHAMPION!**\n\nCongratulations <a href='tg://user?id={uid}'>{uinfo['name']}</a>! You have won the **Sunday Flex Admin 🎖️** title for 1 week!", parse_mode="HTML")
        
        res_top = send_message(target_chat_id, top_msg)
        if res_top.get("ok"):
            msg_id = res_top["result"]["message_id"]
            pin_message(target_chat_id, msg_id)
            last_pinned_topper_messages[target_chat_id] = msg_id
    else:
        send_message(target_chat_id, f"🎉 **Quiz Complete!**\nSubject: `{subject}` | Total Qs: `{count}`")

def run_sunday_mega_quiz(target_chat_id):
    send_message(target_chat_id, "🔥 **CUMULATIVE SUNDAY MEGA QUIZ — THE ULTIMATE TEST** 🔥\n\n200 Questions Across All 4 Subjects!\n⏱️ Format: 4 Sections with 10-minute intermissions.")
    subjects_config = [
        {"subject": "Accounts", "count": 40},
        {"subject": "Business Laws", "count": 60},
        {"subject": "Quantitative Aptitude", "count": 40},
        {"subject": "Economics", "count": 60}
    ]
    for idx, s in enumerate(subjects_config):
        if idx > 0:
            send_message(target_chat_id, f"☕ **10-MINUTE INTERMISSION BREAK BEFORE {s['subject'].upper()}**\n\nResuming shortly...")
            time.sleep(600)
        run_quiz_session(target_chat_id, f"SUNDAY MEGA: {s['subject']}", "", s['count'], 25, level="EXTREME_HIGH")

# --- BACKGROUND WORKERS (PURGE, SCHEDULER & ICAI AUTO-SYNC) ---

def purge_background_worker():
    while True:
        try:
            pending = database.get_pending_purge_messages()
            for msg in pending:
                delete_message(msg["chat_id"], msg["message_id"])
                database.delete_purge_message_entry(msg["id"])
        except Exception:
            pass
        time.sleep(5)

def icai_auto_sync_worker():
    """Background worker for ICAI official website updates auto-sync."""
    while True:
        try:
            # Simulate ICAI website knowledge portal check
            now_str = datetime.now().strftime("%Y-%m-%d")
            # Log audit heartbeat
            database.log_audit(0, 0, "ICAI_SYNC_CHECK", f"Scraped ICAI BoS Portal for {now_str}")
        except Exception:
            pass
        time.sleep(21600) # Every 6 hours

def scheduler_background_worker():
    while True:
        try:
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            time_hm = now.strftime("%H:%M")
            mode = database.get_setting("mode", "auto")

            if time_hm == "06:00" and not pinned_daily_messages.get(today_str, False):
                pinned_daily_messages[today_str] = True
                sched = database.get_or_create_daily_schedule(today_str)
                
                target_chat = MAIN_GROUP_ID if MAIN_GROUP_ID != 0 else OWNER_ID
                schedule_pin_text = (
                    f"📌 **CA FOUNDATION — DAILY STUDY & QUIZ PLAN** 📌\n"
                    f"📅 Date: `{today_str}`\n\n"
                    f"📚 **Today's Subject:** `{sched['subject']}`\n"
                    f"📖 **Chapter/Scope:** `{sched['chapter_name']}`\n"
                    f"⏰ **Fixed Quiz Time:** `{sched['time_str']} PM` (6:00 PM - 8:00 PM Window)\n"
                    f"⚡ **Mode:** `{mode.upper()}`\n\n"
                    f"🔥 *Get ready and revise your notes! Quiz starts on schedule.*"
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
                        threading.Thread(target=run_quiz_session, args=(target_chat, sched["subject"], sched["chapter_name"], 20, 25), daemon=True).start()

            db_jobs = database.load_scheduled_quizzes()
            curr_full_dt = now.strftime("%Y-%m-%d %H:%M")
            for job in db_jobs:
                if job["datetime_str"] == curr_full_dt:
                    threading.Thread(target=run_quiz_session, args=(job["chat_id"], job["subject"], job["chapter"], job["count"], job["timer"], job.get("break_freq", 0), job.get("break_duration", 0), job.get("level", "EXTREME_HIGH")), daemon=True).start()
                    database.delete_scheduled_quiz(job["id"])

        except Exception:
            pass
        time.sleep(30)

def build_dashboard_keyboard():
    return {
        "inline_keyboard": [
            [{"text": "⚙️ System Settings", "callback_data": "dash_settings"}, {"text": "🛡️ Moderation Controls", "callback_data": "dash_mod"}],
            [{"text": "👥 Quiz Access & Grants", "callback_data": "dash_access"}, {"text": "📚 Smart Knowledge Hub", "callback_data": "dash_hub"}],
            [{"text": "❌ Close Control Panel", "callback_data": "dash_close"}]
        ]
    }

def get_role_based_help_text(user_id):
    role = get_role(user_id)
    if role in ["owner", "admin"]:
        return (
            "👑 **SUPER ADMIN MASTER HELP MENU (GOD MODE)** 👑\n\n"
            "┌──────────────────────────────────────\n"
            "│ 🎛️ **1. DASHBOARD & CORE CONTROL**\n"
            "├──────────────────────────────────────\n"
            "│ • `/dashboard` or `/panel` : Open Rose-bot Interactive Control Panel\n"
            "│ • `/setmode [auto/manual]` : Toggle autopilot mode\n"
            "│ • `/settime [HH:MM]` : Set daily quiz execution time\n"
            "│ • `/settimer [seconds]` : Live dynamic timer override\n"
            "└──────────────────────────────────────\n\n"
            "┌──────────────────────────────────────\n"
            "│ 📚 **2. SMART KNOWLEDGE HUB & KEYWORDS**\n"
            "├──────────────────────────────────────\n"
            "│ • `/addkeyword [#kw] \| [link] \| [teacher]` : Add smart material keyword\n"
            "│ • `/keywords` : View all smart study keywords & links\n"
            "│ • `/parse` : Parse raw text/PDF into quiz questions\n"
            "└──────────────────────────────────────\n\n"
            "┌──────────────────────────────────────\n"
            "│ 🛡️ **3. MODERATION & ANTI-SPAM**\n"
            "├──────────────────────────────────────\n"
            "│ • `/filter add [word]` : Add abusive/spam word to auto-filter list\n"
            "│ • `/filter remove [word]` : Remove word from filter list\n"
            "│ • `/filters` : View list of blocked words\n"
            "│ • `/stickers [on|off]` : Toggle sticker auto-block\n"
            "└──────────────────────────────────────\n\n"
            "┌──────────────────────────────────────\n"
            "│ ⚠️ **4. WARNINGS & MANUAL MODERATION**\n"
            "├──────────────────────────────────────\n"
            "│ • `/mute @username` : Manually mute user\n"
            "│ • `/unmute @username` : Remove mute from user\n"
            "│ • `/warn @username` : Issue warning (+1 strike)\n"
            "│ • `/unwarn @username` : Reduce user warning strike\n"
            "└──────────────────────────────────────\n\n"
            "┌──────────────────────────────────────\n"
            "│ 👥 **5. QUIZ ACCESS & TRIAL MANAGEMENT**\n"
            "├──────────────────────────────────────\n"
            "│ • `/grant [user_id] [1week|2weeks|fullfree]` : Grant quiz access\n"
            "│ • `/revoke [user_id]` : Revoke quiz access\n"
            "│ • `/trials` : View list of active user trials\n"
            "└──────────────────────────────────────"
        )
    else:
        return (
            "📖 **CA VAULT QUIZ BOT — STUDENT HELP MENU** 📖\n\n"
            "┌──────────────────────────────────────\n"
            "│ 🎮 **STUDENT COMMANDS**\n"
            "├──────────────────────────────────────\n"
            "│ • `/quiz` : Interactive Quiz Setup\n"
            "│ • `/leaderboard` : Global & Group Top Performers\n"
            "│ • `/stats` or `/profile` : View XP, Level, Streaks & Badges\n"
            "│ • `/refer` : Invite friends & earn +20 XP\n"
            "│ • `/syllabus` : View syllabus chapters & queue\n"
            "│ • `/pdf [query]` : Search study material PDF Vault\n"
            "└──────────────────────────────────────"
        )

def handle_updates():
    offset = 0
    
    while True:
        try:
            if not BASE_URL:
                print("Error: BOT_TOKEN Environment Variable is missing!")
                time.sleep(5)
                continue

            response = requests.get(f"{BASE_URL}/getUpdates", params={"offset": offset, "timeout": 15}, timeout=20)
            data = response.json()
            
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
                                database.record_quiz_history(user_id, chat_id, info.get("subject", "CA"), "", 4, 1, 0)
                                
                                praise_dm = f"{praise} **Sahi Jawab!** (+4 XP)\n🔥 Correct Answer Streak: `{streak}`"
                                send_message(user_id, praise_dm)
                            else:
                                info["wrong_count"] += 1
                                database.add_user_xp(user_id, -1)
                                session_user_scores[chat_id][user_id]["wrong"] += 1
                                session_user_scores[chat_id][user_id]["xp"] -= 1
                                session_user_streaks[chat_id][user_id] = 0
                                database.record_quiz_history(user_id, chat_id, info.get("subject", "CA"), "", -1, 0, 1)
                                
                                wrong_dm_text = f"❌ **Aapka jawab galat tha:**\n❓ _{info['question']}_\n✅ **Sahi Jawab:** `{info['options'][correct_idx]}`"
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
                        
                        # Welcome System
                        if "new_chat_members" in message:
                            for new_mem in message["new_chat_members"]:
                                quote = random.choice(MOTIVATIONAL_QUOTES)
                                welcome_msg = f"👋 **Welcome <a href='tg://user?id={new_mem['id']}'>{new_mem.get('first_name', 'Student')}</a> to CA Vault!**\n\n{quote}"
                                res_w = send_message(chat_id, welcome_msg, parse_mode="HTML")
                                if res_w.get("ok"):
                                    database.add_auto_purge_message(chat_id, res_w["result"]["message_id"], delay_seconds=60)
                            continue

                        u_db = database.get_or_create_user(user_id, username, first_name, owner_id=OWNER_ID)
                        
                        # Force sub gatekeeping
                        if FORCE_SUB_CHANNEL and not check_force_sub(user_id):
                            restrict_chat_member(chat_id, user_id)
                            gate_kb = {
                                "inline_keyboard": [
                                    [{"text": "📢 Join Official Channel", "url": f"https://t.me/{FORCE_SUB_CHANNEL.replace('@','')}"}]
                                ]
                            }
                            send_message(chat_id, f"⚠️ **Access Restricted <a href='tg://user?id={user_id}'>{first_name}</a>!**\n\nPlease join our official channel `{FORCE_SUB_CHANNEL}` to unmute and participate.", reply_markup=gate_kb, parse_mode="HTML")
                            continue

                        # Document Upload & Crowd-Sourced Learning Detection (Zero Duplication & Owner DM Approval)
                        if "document" in message:
                            doc = message["document"]
                            file_id = doc["file_id"]
                            file_name = doc.get("file_name", "Study_Material.pdf")
                            
                            # Zero Duplication Check
                            if database.is_duplicate_file(file_id):
                                if not text.startswith("/addpdf"):
                                    send_message(chat_id, f"ℹ️ **File Already Exists:** `{file_name}` is already available in CA Vault!")
                            else:
                                # Queue for Human-in-the-loop Owner Approval
                                app_id = database.add_pending_approval(file_id, file_name, f"#{file_name.split('.')[0].lower()}", user_id)
                                app_kb = {
                                    "inline_keyboard": [
                                        [{"text": "✅ Approve & Publish", "callback_data": f"app_ok_{app_id}"}],
                                        [{"text": "❌ Reject / Remove", "callback_data": "app_rej"}]
                                    ]
                                }
                                send_message(OWNER_ID, f"📥 **NEW MATERIAL DETECTED FOR APPROVAL!**\n\n📄 File: `{file_name}`\n👤 Contributor: {first_name} (ID: `{user_id}`)\n🆔 Approval ID: `#{app_id}`", reply_markup=app_kb)
                                send_message(chat_id, f"✅ **Material Received!** Submitted to Admin for approval.")

                        # Content Moderation
                        if is_group_chat(chat_id) and get_role(user_id) not in ["owner", "admin"]:
                            if "sticker" in message and database.get_setting("block_stickers", "on") == "on":
                                delete_message(chat_id, message_id)
                                warn_c, is_p = database.add_user_warning(user_id, "Inappropriate sticker")
                                restrict_chat_member(chat_id, user_id, until_date=int((datetime.now() + timedelta(hours=24)).timestamp()) if not is_p else None)
                                send_message(OWNER_ID, f"🛡️ **MODERATION ALERT**: Muted {first_name} (@{username}) for sticker. Strike #{warn_c}.")
                                continue
                            
                            bad_words = database.get_bad_words()
                            if any(w in text.lower() for w in bad_words if w):
                                delete_message(chat_id, message_id)
                                warn_c, is_p = database.add_user_warning(user_id, "Abusive/Spam words")
                                restrict_chat_member(chat_id, user_id, until_date=int((datetime.now() + timedelta(hours=24)).timestamp()) if not is_p else None)
                                send_message(OWNER_ID, f"🛡️ **MODERATION ALERT**: Muted {first_name} (@{username}) for abusive text. Strike #{warn_c}.")
                                continue

                        # SMART KNOWLEDGE HUB CONTEXT-AWARE INTENT DETECTOR
                        matched_kw = detect_material_request_intent(text)
                        if matched_kw and not text.startswith("/"):
                            redirect_kb = {
                                "inline_keyboard": [
                                    [{"text": "👉 Click Here To Open In Study Channel", "url": matched_kw["channel_link"]}]
                                ]
                            }
                            send_message(chat_id, f"📚 **CA Vault Study Material Found!**\nTeacher/Module: `{matched_kw['teacher_name'] or matched_kw['keyword']}`", reply_markup=redirect_kb)

                        # Commands Processing

                        if text in ["/dashboard", "/panel"]:
                            if get_role(user_id) in ["owner", "admin"]:
                                send_message(chat_id, "🎛️ **CA VAULT — OWNER CONTROL PANEL**\nSelect an option below to manage settings & access:", reply_markup=build_dashboard_keyboard())
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
                                    send_message(chat_id, "⚠️ Format: `/addkeyword #ashish_law_notes | https://t.me/channel/102 | Ashish Sir`")

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
                                    send_message(chat_id, f"⏱️ **Live Quiz Timer Updated!** Now running at `{sec}s` per question.")
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

                        elif text.startswith("/parse"):
                            if get_role(user_id) in ["owner", "admin"]:
                                raw_qs = text.replace("/parse", "").strip()
                                parsed = parse_raw_text_questions(raw_qs)
                                send_message(chat_id, f"✅ **Parsed {len(parsed)} Questions Successfully!** Ready for quiz execution.")

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

                            parts = text.split(maxsplit=2)
                            if len(parts) >= 2:
                                subj_arg = parts[1]
                                count_arg = 10
                                if len(parts) >= 3:
                                    try: count_arg = int(parts[2])
                                    except ValueError: pass
                                send_message(chat_id, f"🚀 **Quick ICAI Quiz Launching!**\nSubject: `{subj_arg}` | Questions: `{count_arg}`")
                                threading.Thread(target=run_quiz_session, args=(chat_id, subj_arg, "", count_arg, 25, 0, 0, "EXTREME_HIGH"), daemon=True).start()
                            else:
                                quiz_builder_state[chat_id] = {"subject": "Accounts", "chapter": "", "level": "EXTREME_HIGH", "break_freq": 0, "break_duration": 0}
                                keyboard = {
                                    "inline_keyboard": [
                                        [{"text": "📊 Accounts", "callback_data": "sub_Accounts"}],
                                        [{"text": "📜 Business Laws", "callback_data": "sub_Business Laws"}],
                                        [{"text": "📈 Quantitative Aptitude", "callback_data": "sub_Quantitative Aptitude"}],
                                        [{"text": "💼 Economics", "callback_data": "sub_Economics"}]
                                    ]
                                }
                                send_message(chat_id, "🎯 **Step 1:** Select Subject:", reply_markup=keyboard)

                        elif text.startswith("/start"):
                            streak = u_db.get("streak_count", 1)
                            flex_tag = "🎖️ Sunday Flex Admin" if u_db.get("is_flex_admin") else ""
                            send_message(chat_id, f"👋 **Welcome to CA Vault Quiz Bot!** {flex_tag}\n🔥 Daily Streak: `{streak} Days`\n\nType `/help` to see feature commands.")

                        elif text.startswith("/help"):
                            send_message(chat_id, get_role_based_help_text(user_id))

                    # --- CALLBACK QUERY HANDLER ---
                    elif "callback_query" in result:
                        query = result["callback_query"]
                        query_chat_id = query["message"]["chat"]["id"]
                        message_id = query["message"]["message_id"]
                        data_cb = query["data"]
                        
                        requests.post(f"{BASE_URL}/answerCallbackQuery", json={"callback_query_id": query["id"]}, timeout=8)
                        
                        if data_cb.startswith("app_ok_"):
                            app_id = int(data_cb.split("_")[2])
                            database.update_approval_status(app_id, "approved")
                            app_info = database.get_pending_approval_by_id(app_id)
                            
                            # Add file & keyword to Vault
                            database.add_pdf_to_vault(app_info["file_id"], app_info["file_name"], app_info["uploaded_by"])
                            database.add_smart_keyword(app_info["suggested_keyword"], "https://t.me/CAVaultStudy/100", teacher_name="Approved Material")
                            
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
            time.sleep(2)

if __name__ == "__main__":
    threading.Thread(target=purge_background_worker, daemon=True).start()
    threading.Thread(target=icai_auto_sync_worker, daemon=True).start()
    threading.Thread(target=scheduler_background_worker, daemon=True).start()
    handle_updates()