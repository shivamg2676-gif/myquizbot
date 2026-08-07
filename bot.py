import os
import sys
import time
from datetime import datetime, timedelta
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- CONFIGURATION & API KEYS FROM RENDER ENV ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}" if BOT_TOKEN else None
OWNER_ID = int(os.getenv("OWNER_ID", "8724204988"))

# 5 Free AI Keys
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

scheduled_quizzes = []
active_poll_tracker = {}
active_quiz_sessions = {}
quiz_builder_state = {}

print("🦅 CA Vault Direct Execution Quiz Bot Starting...")

# --- DUMMY WEB SERVER FOR RENDER FREE WEB SERVICE ---
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Telegram Bot is Live and Healthy!")

def run_dummy_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    print(f"🌐 Dummy Web Server listening on port {port}")
    server.serve_forever()

# --- TELEGRAM API HELPER FUNCTIONS ---

def send_message(chat_id, text, reply_markup=None):
    if not BASE_URL: return {}
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        res = requests.post(f"{BASE_URL}/sendMessage", json=payload, timeout=5)
        return res.json()
    except Exception:
        return {}

def edit_message(chat_id, message_id, text, reply_markup=None):
    if not BASE_URL: return
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    try:
        requests.post(f"{BASE_URL}/editMessageText", json=payload, timeout=5)
    except Exception:
        pass

def pin_message(chat_id, message_id):
    if not BASE_URL: return
    try:
        requests.post(f"{BASE_URL}/pinChatMessage", json={"chat_id": chat_id, "message_id": message_id}, timeout=5)
    except Exception:
        pass

def is_group_chat(chat_id):
    return str(chat_id).startswith("-")

def is_user_admin_or_owner(message):
    user_id = message["from"]["id"]
    if user_id == OWNER_ID:
        return True
    if "sender_chat" in message:
        return True
    chat_id = message["chat"]["id"]
    if is_group_chat(chat_id):
        try:
            res = requests.get(f"{BASE_URL}/getChatMember", params={"chat_id": chat_id, "user_id": user_id}, timeout=5)
            data = res.json()
            if data.get("ok"):
                return data["result"]["status"] in ["creator", "administrator"]
        except Exception:
            return False
        return False
    return True

# --- REST AI CALLS ---

def call_gemini(prompt):
    if not GEMINI_API_KEY: return None
    try:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
        payload = {"contents": [{"parts": [{"text": prompt}]}]}
        res = requests.post(url, json=payload, timeout=5)
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
        payload = {"model": "llama-3.3-70b-versatile", "messages": [{"role": "user", "content": prompt}]}
        res = requests.post(url, json=payload, headers=headers, timeout=5)
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
        res = requests.post(url, json=payload, headers=headers, timeout=5)
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
        res = requests.post(url, json=payload, headers=headers, timeout=5)
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
        res = requests.post(url, json=payload, headers=headers, timeout=5)
        if res.status_code == 200:
            return res.json()["choices"][0]["message"]["content"]
    except Exception:
        pass
    return None

def fetch_fastest_ai_response(prompt):
    ai_funcs = [call_groq, call_gemini, call_cerebras, call_mistral, call_openrouter]
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(func, prompt) for func in ai_funcs]
        for future in as_completed(futures):
            result = future.result()
            if result and len(result.strip()) > 20:
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
        f"Difficulty Level Mandate: {diff_prompt}\n"
        f"Format strictly as:\n"
        f"Q: [Question text]\n"
        f"O1: [Option 1]\n"
        f"O2: [Option 2]\n"
        f"O3: [Option 3]\n"
        f"O4: [Option 4]\n"
        f"Correct: 1\n"
        f"Explanation: [1-line precise ICAI logic explanation]"
    )

    raw_text = fetch_fastest_ai_response(prompt)
    return parse_single_ai_output(raw_text, subject)

def parse_single_ai_output(text, subject):
    if not text:
        return {
            "question": f"[{subject}] ICAI Standard Practice Question",
            "options": ["Option A", "Option B", "Option C", "Option D"],
            "correct": 0,
            "explanation": "Standard ICAI rule applies."
        }
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
        "options": [o1 or "A", o2 or "B", o3 or "C", o4 or "D"],
        "correct": max(0, min(correct_idx, 3)),
        "explanation": explanation
    }

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
        res = requests.post(f"{BASE_URL}/sendPoll", json=payload, timeout=5)
        data = res.json()
        if data.get("ok"):
            poll_id = data["result"]["poll"]["id"]
            active_poll_tracker[poll_id] = {
                "correct": max(0, min(correct_option_id, len(options) - 1)),
                "chat_id": chat_id,
                "options": options,
                "question": question,
                "wrong_count": 0,
                "total_votes": 0
            }
        return data
    except Exception:
        return {}

def run_quiz_session(target_chat_id, subject, chapter, count, timer, break_freq=0, break_duration=0, level="EXTREME_HIGH"):
    active_quiz_sessions[target_chat_id] = True
    
    chap_display = chapter if chapter else "Full Syllabus"
    break_info = f"☕ Break: Every `{break_freq}` Qs for `{break_duration//60}` mins" if break_freq > 0 else "⚡ Mode: Non-stop (No Breaks)"
    send_message(target_chat_id, f"🎯 **{subject} - {chap_display}**\n🔢 Questions: `{count}` | ⏱️ Timer: `{timer}s`\n{break_info}\n\n🚀 *Quiz starting now! Powered by CA Vault Engine.*")
    
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
        poll_res = send_poll(target_chat_id, f"Q{idx+1}/{count}: {q['question']}", q['options'], q['correct'], open_period=timer)
        poll_id = poll_res.get("result", {}).get("poll", {}).get("id") if poll_res.get("ok") else None
        
        time.sleep(timer + 1)
        
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
    send_message(target_chat_id, f"🎉 **Quiz Complete!**\nSubject: `{subject}` | Total Questions: `{count}`")

def scheduler_background_worker():
    while True:
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        for job in list(scheduled_quizzes):
            if job["datetime"] == current_time_str:
                run_quiz_session(job["chat_id"], job["subject"], job["chapter"], job["count"], job["timer"], job.get("break_freq", 0), job.get("break_duration", 0), job.get("level", "EXTREME_HIGH"))
                scheduled_quizzes.remove(job)
        time.sleep(15)

def get_help_text():
    return (
        "📖 **CA VAULT QUIZ BOT — MENU** 📖\n\n"
        "┌──────────────────────────────────────\n"
        "│ 🎮 **BASIC COMMANDS**\n"
        "├──────────────────────────────────────\n"
        "│ • `/quiz` : Start step-by-step Interactive Quiz setup\n"
        "│ • `/stopquiz` : Stop an active quiz session (Admins)\n"
        "│ • `/help` : View all features and commands list\n"
        "└──────────────────────────────────────\n\n"
        "┌──────────────────────────────────────\n"
        "│ ✍️ **MANUAL CONFIGURATION COMMANDS**\n"
        "├──────────────────────────────────────\n"
        "│ • `/chapter [Name]` : Set Chapter Name manually\n"
        "│ • `/count [Number]` : Set total questions (e.g. `/count 25`)\n"
        "│ • `/timer [Seconds]` : Set timer per question (e.g. `/timer 20`)\n"
        "│ • `/breaksetting [Qs] | [Mins]` : Custom Break\n"
        "│ • `/setlevel EXTREME_HIGH | MEDIUM | EASY` : Difficulty\n"
        "└──────────────────────────────────────\n\n"
        "┌──────────────────────────────────────\n"
        "│ 📅 **AUTOMATED SCHEDULER**\n"
        "├──────────────────────────────────────\n"
        "│ • `/schedule_month_rotation GroupID | HH:MM | Qs | Timer`\n"
        "└──────────────────────────────────────"
    )

def handle_updates():
    offset = 0
    subjects_rotation = ["Accounts", "Business Laws", "Quantitative Aptitude", "Economics"]
    
    while True:
        try:
            if not BASE_URL:
                print("Error: BOT_TOKEN Environment Variable is missing!")
                time.sleep(5)
                continue

            response = requests.get(f"{BASE_URL}/getUpdates", params={"offset": offset, "timeout": 5}, timeout=10)
            data = response.json()
            
            if data.get("ok"):
                for result in data.get("result", []):
                    offset = result["update_id"] + 1
                    
                    if "poll_answer" in result:
                        p_ans = result["poll_answer"]
                        poll_id = p_ans["poll_id"]
                        user = p_ans["user"]
                        user_id = user["id"]
                        chosen_options = p_ans.get("option_ids", [])
                        
                        if poll_id in active_poll_tracker and chosen_options:
                            info = active_poll_tracker[poll_id]
                            correct_idx = info["correct"]
                            info["total_votes"] += 1
                            
                            if correct_idx not in chosen_options:
                                info["wrong_count"] += 1
                                wrong_dm_text = f"❌ **Aapka jawab galat tha:**\n❓ _{info['question']}_\n✅ **Sahi Jawab:** `{info['options'][correct_idx]}`"
                                send_message(user_id, wrong_dm_text)

                    if "message" in result:
                        message = result["message"]
                        chat_id = message["chat"]["id"]
                        text = message.get("text", "").strip()
                        
                        if text.startswith("/start"):
                            send_message(chat_id, "👋 **CA Vault Quiz Bot Active!**\n\nType `/help` to see all features and commands.")
                        
                        elif text.startswith("/help"):
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "🎯 Start Interactive Quiz", "callback_data": "start_quiz_help"}]
                                ]
                            }
                            send_message(chat_id, get_help_text(), reply_markup=keyboard)

                        elif text == "/stopquiz":
                            if is_user_admin_or_owner(message):
                                if active_quiz_sessions.get(chat_id, False):
                                    active_quiz_sessions[chat_id] = False
                                    send_message(chat_id, "🛑 Stopping quiz...")
                                else:
                                    send_message(chat_id, "⚠️ No active quiz.")
                            else:
                                send_message(chat_id, "🔒 Permission Denied.")

                        elif text == "/quiz":
                            if is_group_chat(chat_id) and not is_user_admin_or_owner(message):
                                send_message(chat_id, "🔒 Permission Denied: Only admins can start quiz.")
                                continue
                            
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

                        elif text.startswith("/setlevel"):
                            if chat_id in quiz_builder_state:
                                lvl = text.replace("/setlevel", "").strip().upper()
                                if lvl in ["EXTREME_HIGH", "MEDIUM", "EASY"]:
                                    quiz_builder_state[chat_id]["level"] = lvl
                                    send_message(chat_id, f"✅ Difficulty Level updated to: **{lvl}**")
                                else:
                                    send_message(chat_id, "⚠️ Use: `/setlevel EXTREME_HIGH` or `/setlevel MEDIUM` or `/setlevel EASY`")

                        elif text.startswith("/count"):
                            if chat_id in quiz_builder_state:
                                try:
                                    cnt = int(text.replace("/count", "").strip())
                                    quiz_builder_state[chat_id]["count"] = cnt
                                    
                                    keyboard = {
                                        "inline_keyboard": [
                                            [{"text": "⚡ No Breaks (Non-stop)", "callback_data": "break_none"}],
                                            [{"text": "☕ Break Every 20 Qs (5 min)", "callback_data": "break_20_5"}],
                                            [{"text": "☕ Break Every 30 Qs (10 min)", "callback_data": "break_30_10"}],
                                            [{"text": "⬅️ Back", "callback_data": "back_to_count"}]
                                        ]
                                    }
                                    send_message(chat_id, f"✅ Questions: **{cnt}**\n\n🎯 **Step 4:** Select Break Option (or `/breaksetting 30 | 10`):", reply_markup=keyboard)
                                except ValueError:
                                    send_message(chat_id, "⚠️ Enter valid number (e.g. `/count 25`)")

                        elif text.startswith("/timer"):
                            if chat_id in quiz_builder_state:
                                try:
                                    tmr = int(text.replace("/timer", "").strip())
                                    state = quiz_builder_state[chat_id]
                                    subj = state.get("subject", "Accounts")
                                    chap = state.get("chapter", "")
                                    cnt = state.get("count", 10)
                                    bf = state.get("break_freq", 0)
                                    bd = state.get("break_duration", 0)
                                    lvl = state.get("level", "EXTREME_HIGH")
                                    
                                    send_message(chat_id, f"🚀 **Starting Quiz...**\nSubject: `{subj}` | Questions: `{cnt}` | Timer: `{tmr}s`\nLevel: `{lvl}`")
                                    threading.Thread(target=run_quiz_session, args=(chat_id, subj, chap, cnt, tmr, bf, bd, lvl), daemon=True).start()
                                except ValueError:
                                    send_message(chat_id, "⚠️ Enter valid seconds (e.g. `/timer 20`)")

                        elif text.startswith("/chapter"):
                            if chat_id in quiz_builder_state:
                                chap = text.replace("/chapter", "").strip()
                                quiz_builder_state[chat_id]["chapter"] = chap
                                
                                keyboard = {
                                    "inline_keyboard": [
                                        [{"text": "10 Qs", "callback_data": "cnt_10"}, {"text": "20 Qs", "callback_data": "cnt_20"}],
                                        [{"text": "30 Qs", "callback_data": "cnt_30"}, {"text": "50 Qs", "callback_data": "cnt_50"}],
                                        [{"text": "⬅️ Back", "callback_data": "back_to_chapter_choice"}]
                                    ]
                                }
                                send_message(chat_id, f"✅ Chapter: **{chap}**\n\n🔢 **Step 3:** Select Question Count or type `/count [number]`:", reply_markup=keyboard)

                        elif text.startswith("/breaksetting"):
                            if chat_id in quiz_builder_state:
                                try:
                                    parts = text.replace("/breaksetting", "").split("|")
                                    bf = int(parts[0].strip())
                                    bd = int(parts[1].strip()) * 60
                                    quiz_builder_state[chat_id]["break_freq"] = bf
                                    quiz_builder_state[chat_id]["break_duration"] = bd
                                    
                                    keyboard = {
                                        "inline_keyboard": [
                                            [{"text": "20s", "callback_data": "timer_20"}, {"text": "30s", "callback_data": "timer_30"}],
                                            [{"text": "45s", "callback_data": "timer_45"}, {"text": "60s", "callback_data": "timer_60"}],
                                            [{"text": "⬅️ Back", "callback_data": "back_to_break"}]
                                        ]
                                    }
                                    send_message(chat_id, f"✅ Break Configured: Every `{bf}` Qs for `{bd//60}` mins.\n\n🎯 **Step 5:** Select Timer or type `/timer [seconds]`:", reply_markup=keyboard)
                                except Exception:
                                    send_message(chat_id, "⚠️ Format: `/breaksetting [QsCount] | [BreakMins]`")

                        elif text.startswith("/schedule_month_rotation"):
                            if is_user_admin_or_owner(message):
                                try:
                                    parts = text.replace("/schedule_month_rotation", "").split("|")
                                    target_group_id = int(parts[0].strip())
                                    time_str = parts[1].strip()
                                    cnt = int(parts[2].strip())
                                    tmr = int(parts[3].strip())

                                    today = datetime.now()
                                    for day_offset in range(30):
                                        future_date = (today + timedelta(days=day_offset)).strftime("%Y-%m-%d")
                                        full_dt = f"{future_date} {time_str}"
                                        rotated_subj = subjects_rotation[day_offset % 4]
                                        
                                        scheduled_quizzes.append({
                                            "chat_id": target_group_id,
                                            "datetime": full_dt,
                                            "subject": rotated_subj,
                                            "chapter": "",
                                            "count": cnt,
                                            "timer": tmr,
                                            "level": "EXTREME_HIGH"
                                        })
                                    
                                    sched_msg = send_message(target_group_id, f"📅 **Rotational Daily Quiz Scheduled for 30 Days!**\n🔥 Level: `EXTREME HIGH`\n🔄 Subjects: `Accounts ➔ Law ➔ Quants ➔ Economics`\n⏰ Time: `{time_str}` Daily\n🔢 Questions: `{cnt}` | Timer: `{tmr}s`")
                                    if sched_msg.get("ok"):
                                        pin_message(target_group_id, sched_msg["result"]["message_id"])
                                    
                                    send_message(chat_id, "✅ 30-Day Rotational Quiz Schedule created and pinned successfully!")
                                except Exception:
                                    send_message(chat_id, "⚠️ Format: `/schedule_month_rotation GroupID | HH:MM | Qs | Timer`")
                            else:
                                send_message(chat_id, "🔒 Sirf admins schedule set kar sakte hain.")

                    elif "callback_query" in result:
                        query = result["callback_query"]
                        query_chat_id = query["message"]["chat"]["id"]
                        message_id = query["message"]["message_id"]
                        data_cb = query["data"]
                        
                        requests.post(f"{BASE_URL}/answerCallbackQuery", json={"callback_query_id": query["id"]}, timeout=5)
                        
                        if data_cb == "start_quiz_help":
                            quiz_builder_state[query_chat_id] = {"subject": "Accounts", "chapter": "", "level": "EXTREME_HIGH", "break_freq": 0, "break_duration": 0}
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "📊 Accounts", "callback_data": "sub_Accounts"}],
                                    [{"text": "📜 Business Laws", "callback_data": "sub_Business Laws"}],
                                    [{"text": "📈 Quantitative Aptitude", "callback_data": "sub_Quantitative Aptitude"}],
                                    [{"text": "💼 Economics", "callback_data": "sub_Economics"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "🎯 **Step 1:** Select Subject:", reply_markup=keyboard)

                        elif data_cb.startswith("sub_"):
                            subj = data_cb.split("_", 1)[1]
                            quiz_builder_state[query_chat_id]["subject"] = subj
                            
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "⏩ Skip (Full Syllabus)", "callback_data": "chap_skip"}],
                                    [{"text": "✍️ Enter Chapter Name", "callback_data": "chap_custom"}],
                                    [{"text": "⬅️ Back", "callback_data": "back_to_subject"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"✅ Subject: **{subj}**\n\n📖 **Step 2:** Choose Chapter or Skip:", reply_markup=keyboard)

                        elif data_cb == "chap_custom":
                            edit_message(query_chat_id, message_id, "✍️ Please type chapter name:\n`/chapter [Chapter Name]`")

                        elif data_cb == "chap_skip":
                            quiz_builder_state[query_chat_id]["chapter"] = ""
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "10 Qs", "callback_data": "cnt_10"}, {"text": "20 Qs", "callback_data": "cnt_20"}],
                                    [{"text": "30 Qs", "callback_data": "cnt_30"}, {"text": "50 Qs", "callback_data": "cnt_50"}],
                                    [{"text": "⬅️ Back", "callback_data": "back_to_subject"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "🔢 **Step 3:** Select Question Count or type `/count [number]`:", reply_markup=keyboard)

                        elif data_cb == "back_to_subject":
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "📊 Accounts", "callback_data": "sub_Accounts"}],
                                    [{"text": "📜 Business Laws", "callback_data": "sub_Business Laws"}],
                                    [{"text": "📈 Quantitative Aptitude", "callback_data": "sub_Quantitative Aptitude"}],
                                    [{"text": "💼 Economics", "callback_data": "sub_Economics"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "🎯 **Step 1:** Select Subject:", reply_markup=keyboard)

                        elif data_cb == "back_to_chapter_choice":
                            subj = quiz_builder_state.get(query_chat_id, {}).get("subject", "Accounts")
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "⏩ Skip (Full Syllabus)", "callback_data": "chap_skip"}],
                                    [{"text": "✍️ Enter Chapter Name", "callback_data": "chap_custom"}],
                                    [{"text": "⬅️ Back", "callback_data": "back_to_subject"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"✅ Subject: **{subj}**\n\n📖 **Step 2:** Choose Chapter or Skip:", reply_markup=keyboard)

                        elif data_cb == "back_to_count":
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "10 Qs", "callback_data": "cnt_10"}, {"text": "20 Qs", "callback_data": "cnt_20"}],
                                    [{"text": "30 Qs", "callback_data": "cnt_30"}, {"text": "50 Qs", "callback_data": "cnt_50"}],
                                    [{"text": "⬅️ Back", "callback_data": "back_to_chapter_choice"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "🔢 **Step 3:** Select Question Count or type `/count [number]`:", reply_markup=keyboard)

                        elif data_cb.startswith("cnt_"):
                            cnt = int(data_cb.split("_")[1])
                            quiz_builder_state[query_chat_id]["count"] = cnt
                            
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "⚡ No Breaks (Non-stop)", "callback_data": "break_none"}],
                                    [{"text": "☕ Break Every 20 Qs (5 min)", "callback_data": "break_20_5"}],
                                    [{"text": "☕ Break Every 30 Qs (10 min)", "callback_data": "break_30_10"}],
                                    [{"text": "⬅️ Back", "callback_data": "back_to_count"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"✅ Questions: **{cnt}**\n\n☕ **Step 4:** Select Break Option (or `/breaksetting 30 | 10`):", reply_markup=keyboard)

                        elif data_cb == "break_none":
                            quiz_builder_state[query_chat_id]["break_freq"] = 0
                            quiz_builder_state[query_chat_id]["break_duration"] = 0
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "20s", "callback_data": "timer_20"}, {"text": "30s", "callback_data": "timer_30"}],
                                    [{"text": "45s", "callback_data": "timer_45"}, {"text": "60s", "callback_data": "timer_60"}],
                                    [{"text": "⬅️ Back", "callback_data": "back_to_break"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "✅ Mode: **No Breaks (Non-stop)**\n\n🎯 **Step 5:** Select Timer or type `/timer [seconds]`:", reply_markup=keyboard)

                        elif data_cb == "break_20_5":
                            quiz_builder_state[query_chat_id]["break_freq"] = 20
                            quiz_builder_state[query_chat_id]["break_duration"] = 300
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "20s", "callback_data": "timer_20"}, {"text": "30s", "callback_data": "timer_30"}],
                                    [{"text": "45s", "callback_data": "timer_45"}, {"text": "60s", "callback_data": "timer_60"}],
                                    [{"text": "⬅️ Back", "callback_data": "back_to_break"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "✅ Break: **Every 20 Qs / 5 mins**\n\n🎯 **Step 5:** Select Timer or type `/timer [seconds]`:", reply_markup=keyboard)

                        elif data_cb == "break_30_10":
                            quiz_builder_state[query_chat_id]["break_freq"] = 30
                            quiz_builder_state[query_chat_id]["break_duration"] = 600
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "20s", "callback_data": "timer_20"}, {"text": "30s", "callback_data": "timer_30"}],
                                    [{"text": "45s", "callback_data": "timer_45"}, {"text": "60s", "callback_data": "timer_60"}],
                                    [{"text": "⬅️ Back", "callback_data": "back_to_break"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "✅ Break: **Every 30 Qs / 10 mins**\n\n🎯 **Step 5:** Select Timer or type `/timer [seconds]`:", reply_markup=keyboard)

                        elif data_cb == "back_to_break":
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "⚡ No Breaks (Non-stop)", "callback_data": "break_none"}],
                                    [{"text": "☕ Break Every 20 Qs (5 min)", "callback_data": "break_20_5"}],
                                    [{"text": "☕ Break Every 30 Qs (10 min)", "callback_data": "break_30_10"}],
                                    [{"text": "⬅️ Back", "callback_data": "back_to_count"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "☕ **Step 4:** Select Break Setting:", reply_markup=keyboard)

                        elif data_cb.startswith("timer_"):
                            tmr = int(data_cb.split("_")[1])
                            state = quiz_builder_state.get(query_chat_id, {})
                            subj = state.get("subject", "Accounts")
                            chap = state.get("chapter", "")
                            cnt = state.get("count", 10)
                            bf = state.get("break_freq", 0)
                            bd = state.get("break_duration", 0)
                            lvl = state.get("level", "EXTREME_HIGH")
                            
                            edit_message(query_chat_id, message_id, f"🚀 **Starting Quiz...**\nSubject: `{subj}` | Questions: `{cnt}` | Timer: `{tmr}s`\nLevel: `{lvl}` | Break: `{bf} Qs / {bd//60} mins`")
                            threading.Thread(target=run_quiz_session, args=(query_chat_id, subj, chap, cnt, tmr, bf, bd, lvl), daemon=True).start()

        except Exception as e:
            time.sleep(2)

if __name__ == "__main__":
    # Start Dummy Web Server for Render Free Tier Web Service
    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    # Start Bot Tasks
    threading.Thread(target=scheduler_background_worker, daemon=True).start()
    handle_updates()
