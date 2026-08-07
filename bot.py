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
schedule_wizard_state = {}

# Permanent mapping: user_id -> linked_group_id
user_linked_groups = {}

SUBJECTS = ["Accounts", "Business Laws", "Quantitative Aptitude", "Economics"]

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

def is_user_admin_owner_or_anonymous(message):
    user_id = message.get("from", {}).get("id", 0)
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

# --- REST AI CALLS (5 LAYERS) ---

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

def generate_ai_question(subject, chapter, subtopics="", level="EXTREME_HIGH"):
    scope_text = f"Chapter '{chapter}'" if chapter else f"Full Subject '{subject}' syllabus"
    if subtopics:
        scope_text += f" (Focus Sub-topics: '{subtopics}')"
    
    if level == "EXTREME_HIGH":
        diff_instruction = "Difficulty: EXTREME HIGH. Focus on conceptual traps, multi-statement evaluations, and complex ICAI module exceptions."
    elif level == "HIGH":
        diff_instruction = "Difficulty: HIGH. Focus on tricky ICAI exam-level standard logic and calculations."
    else:
        diff_instruction = "Difficulty: MEDIUM. Focus on fundamental ICAI module conceptual questions."

    tag_instruction = ""
    if subject in ["Quantitative Aptitude", "Economics"]:
        tag_instruction = (
            "IMPORTANT: If this question/logic appeared in an actual past ICAI PYQ, RTP, or MTP (2018-2025), specify the source tag strictly in Tag line.\n"
            "Format Tag line as: 'Tag: [ICAI PYQ Nov 2022]' or 'Tag: [ICAI RTP May 2023]'.\n"
            "DO NOT write 'ICAI Module Standard'. If no specific exam year applies, write 'Tag: None'.\n"
        )
    else:
        tag_instruction = "Write 'Tag: None'\n"

    prompt = (
        f"Generate exactly 1 multiple-choice question for CA Foundation '{subject}', {scope_text}.\n"
        f"{diff_instruction}\n"
        f"{tag_instruction}\n"
        f"Format strictly as:\n"
        f"Tag: [Source tag or None]\n"
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
            "tag": "",
            "question": f"[{subject}] ICAI Practice Question",
            "options": ["Option A", "Option B", "Option C", "Option D"],
            "correct": 0,
            "explanation": "Standard ICAI rule applies."
        }
    lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
    tag_text, q_text, o1, o2, o3, o4, correct_idx, explanation = "", "", "", "", "", "", 0, "ICAI module principle applies."
    
    for line in lines:
        if line.startswith("Tag:"):
            val = line[4:].strip()
            if val and val.lower() != "none" and "module standard" not in val.lower() and subject in ["Quantitative Aptitude", "Economics"]:
                tag_text = val
        elif line.startswith("Q:"): q_text = line[2:].strip()
        elif line.startswith("O1:"): o1 = line[3:].strip()
        elif line.startswith("O2:"): o2 = line[3:].strip()
        elif line.startswith("O3:"): o3 = line[3:].strip()
        elif line.startswith("O4:"): o4 = line[3:].strip()
        elif line.startswith("Correct:"):
            digits = ''.join(filter(str.isdigit, line))
            if digits: correct_idx = int(digits) - 1
        elif line.startswith("Explanation:"): explanation = line[12:].strip()
    
    return {
        "tag": tag_text,
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

def run_quiz_session(target_chat_id, subject, chapter, count, timer, break_freq=0, break_duration=0, level="EXTREME_HIGH", conductor_user_id=None, subtopics=""):
    # Ensure quiz ONLY runs in a group
    if not is_group_chat(target_chat_id):
        if conductor_user_id:
            send_message(conductor_user_id, "⚠️ **Quiz Error:** Quizzes can ONLY be conducted inside Telegram Groups, not in DM.")
        return

    active_quiz_sessions[target_chat_id] = True
    
    chap_display = chapter if chapter else "Full Syllabus"
    subtopic_display = f"\n🎯 **Sub-topics:** `{subtopics}`" if subtopics else ""
    break_info = f"☕ Break: Every `{break_freq}` Qs for `{break_duration//60}` mins" if break_freq > 0 else "⚡ Mode: Non-stop (No Breaks)"
    
    start_msg = (
        f"🎯 **CA VAULT LIVE QUIZ SESSION**\n"
        f"─────────────────────\n"
        f"📘 **Subject:** `{subject}`\n"
        f"📖 **Chapter:** `{chap_display}`{subtopic_display}\n"
        f"🔢 **Questions:** `{count}` | ⏱️ **Timer:** `{timer}s`\n"
        f"{break_info}\n"
        f"─────────────────────\n"
        f"🚀 *Quiz starting now! All the best!*"
    )
    send_message(target_chat_id, start_msg)
    
    current_difficulty = level

    if conductor_user_id:
        send_message(conductor_user_id, f"🚀 **Quiz Started in Group (`{target_chat_id}`)!**\nInitial Set Level: `{current_difficulty}`\nYou will receive live performance metrics here in DM.")

    for idx in range(count):
        if not active_quiz_sessions.get(target_chat_id, False):
            send_message(target_chat_id, "🛑 **Quiz Session Stopped.**")
            if conductor_user_id:
                send_message(conductor_user_id, f"🛑 **Quiz Session Stopped in Group (`{target_chat_id}`).**")
            break

        if idx > 0 and break_freq > 0 and idx % break_freq == 0:
            send_message(target_chat_id, f"☕ **{idx} Questions Complete!**\n`{break_duration // 60}` minutes break starting now...")
            for _ in range(break_duration):
                if not active_quiz_sessions.get(target_chat_id, False):
                    break
                time.sleep(1)
            send_message(target_chat_id, "🚀 **Break Over!** Resuming quiz...")

        q = generate_ai_question(subject, chapter, subtopics, current_difficulty)
        
        # Public Display: No level publically, only PYQ/RTP year tag if present
        question_header = f"Q{idx+1}/{count}"
        if q["tag"]:
            question_header += f" {q['tag']}"
            
        full_q_text = f"{question_header}: {q['question']}"
        
        poll_res = send_poll(target_chat_id, full_q_text, q['options'], q['correct'], open_period=timer)
        poll_id = poll_res.get("result", {}).get("poll", {}).get("id") if poll_res.get("ok") else None
        
        time.sleep(timer + 1)
        
        # Public group gets NO explanation block post-poll (Clean Group).
        # Dynamic check for >60% wrong answers & Conductor DM updates
        if poll_id and poll_id in active_poll_tracker:
            p_data = active_poll_tracker[poll_id]
            total_v = p_data["total_votes"]
            wrong_v = p_data["wrong_count"]
            
            wrong_percentage = (wrong_v / total_v * 100) if total_v > 0 else 0
            
            # >60% wrong answer level drop logic
            if total_v > 0 and wrong_percentage > 60:
                if current_difficulty == "EXTREME_HIGH":
                    current_difficulty = "HIGH"
                elif current_difficulty == "HIGH":
                    current_difficulty = "MEDIUM"
                
                if conductor_user_id:
                    send_message(
                        conductor_user_id,
                        f"📊 **Q{idx+1} Performance Alert:**\n"
                        f"• Total Votes: `{total_v}` | Wrong Votes: `{wrong_v}` ({wrong_percentage:.1f}%)\n"
                        f"⚠️ Over 60% users answered incorrectly. **Difficulty automatically lowered to `{current_difficulty}`** for next question."
                    )
            else:
                if conductor_user_id and total_v > 0:
                    send_message(
                        conductor_user_id,
                        f"📊 **Q{idx+1} Analytics:** Total Votes: `{total_v}` | Wrong Votes: `{wrong_v}` ({wrong_percentage:.1f}%)\nCurrent Active Difficulty: `{current_difficulty}`"
                    )

        time.sleep(2)

    active_quiz_sessions[target_chat_id] = False
    send_message(target_chat_id, f"🎉 **QUIZ COMPLETE!**\n\n📘 **Subject:** `{subject}`\n🔢 **Total Questions:** `{count}`")
    if conductor_user_id:
        send_message(conductor_user_id, f"🎉 **Quiz Complete in Group (`{target_chat_id}`)!**\nTotal Questions Conducted: `{count}`.")

# --- BACKGROUND SCHEDULER WORKER ---

def scheduler_background_worker():
    while True:
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        for job in list(scheduled_quizzes):
            if job["datetime"] == current_time_str:
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
        time.sleep(15)

def get_help_text():
    return (
        "📚 **CA VAULT QUIZ BOT CONTROL PANEL**\n\n"
        "👥 **GROUP COMMANDS**\n"
        "• `/quiz` — Launch Interactive Setup\n"
        "• `/stopquiz` — Stop active quiz\n"
        "• `/myid` — Check Group ID\n\n"
        "💬 **DM CONTROL WIZARD (BOT DM ONLY)**\n"
        "• `/link_group <GroupID>` — Link your group permanently\n"
        "• `/schedule` — Step-by-Step Guided Scheduler Wizard\n"
        "  *(Set Subject, Chapter, Sub-topics, Level, Time Slots, Qs & Timer)*"
    )

def handle_updates():
    offset = 0
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
                            
                            # ONLY users who give WRONG answer get explanation in DM
                            if correct_idx not in chosen_options:
                                info["wrong_count"] += 1
                                wrong_dm_text = (
                                    f"❌ **Aapka jawab galat tha:**\n\n"
                                    f"❓ _{info['question']}_\n\n"
                                    f"✅ **Sahi Option:** `{info['options'][correct_idx]}`\n"
                                    f"🔍 **ICAI Logic/Explanation:** _{info.get('explanation', 'ICAI module principle applies.')}_"
                                )
                                send_message(user_id, wrong_dm_text)

                    if "message" in result:
                        message = result["message"]
                        chat_id = message["chat"]["id"]
                        user_id = message.get("from", {}).get("id", 0)
                        text = message.get("text", "").strip()
                        
                        if text.startswith("/start"):
                            welcome_msg = (
                                "👋 **Welcome to CA Vault Quiz Engine!**\n\n"
                                "⚡ *High-yield AI Generated Practice Quizzes for CA Foundation.*\n\n"
                                "Click below to open the control menu!"
                            )
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "📖 Open Help Menu", "callback_data": "show_help_menu"}]
                                ]
                            }
                            send_message(chat_id, welcome_msg, reply_markup=keyboard)
                        
                        elif text.startswith("/help"):
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "📅 Schedule Wizard (DM)", "callback_data": "sched_wiz_start"}]
                                ]
                            }
                            send_message(chat_id, get_help_text(), reply_markup=keyboard)

                        elif text.startswith("/myid"):
                            send_message(chat_id, f"🆔 **Chat ID:** `{chat_id}`")

                        elif text == "/stopquiz":
                            if is_user_admin_owner_or_anonymous(message):
                                if active_quiz_sessions.get(chat_id, False):
                                    active_quiz_sessions[chat_id] = False
                                    send_message(chat_id, "🛑 **Stopping active quiz...**")
                                else:
                                    send_message(chat_id, "⚠️ No active quiz running.")
                            else:
                                send_message(chat_id, "🔒 **Permission Denied.**")

                        # /quiz COMMAND: Must be in group
                        elif text == "/quiz":
                            if not is_group_chat(chat_id):
                                send_message(chat_id, "⚠️ **Notice:** Live Quizzes are conducted ONLY inside Telegram Groups.\nLink your group using `/link_group <GroupID>` and use `/schedule` in DM!")
                                continue

                            if not is_user_admin_owner_or_anonymous(message):
                                send_message(chat_id, "🔒 **Permission Denied:** Only Admins or Owners can start quizzes.")
                                continue
                            
                            quiz_builder_state[chat_id] = {"subject": "Accounts", "chapter": "", "subtopics": "", "level": "EXTREME_HIGH", "break_freq": 0, "break_duration": 0, "conductor_id": user_id}
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "📊 Accounts", "callback_data": "sub_Accounts"}],
                                    [{"text": "📜 Business Laws", "callback_data": "sub_Business Laws"}],
                                    [{"text": "📈 Quantitative Aptitude", "callback_data": "sub_Quantitative Aptitude"}],
                                    [{"text": "💼 Economics", "callback_data": "sub_Economics"}]
                                ]
                            }
                            send_message(chat_id, "🎯 **Step 1:** Select Subject:", reply_markup=keyboard)

                        elif text.startswith("/chapter"):
                            target_chat_id = chat_id
                            if text.startswith("/chapter_sched"):
                                raw_input = text.replace("/chapter_sched", "").strip()
                                parts = raw_input.split("|")
                                chap_val = parts[0].strip()
                                subtopic_val = parts[1].strip() if len(parts) > 1 else ""
                                
                                schedule_wizard_state[user_id]["chapter"] = chap_val
                                schedule_wizard_state[user_id]["subtopics"] = subtopic_val
                                
                                keyboard = {
                                    "inline_keyboard": [
                                        [{"text": "⚡ MEDIUM", "callback_data": "swiz_lvl_MEDIUM"}],
                                        [{"text": "🔥 HIGH", "callback_data": "swiz_lvl_HIGH"}],
                                        [{"text": "💀 EXTREME HIGH", "callback_data": "swiz_lvl_EXTREME_HIGH"}]
                                    ]
                                }
                                send_message(chat_id, f"✅ **Chapter set:** `{chap_val}`\n🎯 **Sub-topics:** `{subtopic_val or 'All'}`\n\n🎯 **Step 3:** Select Quiz Difficulty Level (For Conductor):", reply_markup=keyboard)
                            else:
                                raw_input = text.replace("/chapter", "").strip()
                                parts = raw_input.split("|")
                                chap_val = parts[0].strip()
                                subtopic_val = parts[1].strip() if len(parts) > 1 else ""
                                
                                if target_chat_id in quiz_builder_state:
                                    quiz_builder_state[target_chat_id]["chapter"] = chap_val
                                    quiz_builder_state[target_chat_id]["subtopics"] = subtopic_val
                                    
                                    keyboard = {
                                        "inline_keyboard": [
                                            [{"text": "⚡ MEDIUM", "callback_data": "lvl_MEDIUM"}],
                                            [{"text": "🔥 HIGH", "callback_data": "lvl_HIGH"}],
                                            [{"text": "💀 EXTREME HIGH", "callback_data": "lvl_EXTREME_HIGH"}]
                                        ]
                                    }
                                    send_message(target_chat_id, f"✅ **Chapter set:** `{chap_val}`\n🎯 **Sub-topics:** `{subtopic_val or 'All'}`\n\n🎯 **Step 3:** Select Difficulty Level:", reply_markup=keyboard)

                        # PERMANENT LINK GROUP (DM ONLY)
                        elif text.startswith("/link_group"):
                            if is_group_chat(chat_id):
                                send_message(chat_id, "⚠️ Send `/link_group` in **Bot DM**!")
                                continue

                            try:
                                target_group_id = int(text.replace("/link_group", "").strip())
                                user_linked_groups[user_id] = target_group_id
                                send_message(chat_id, f"✅ **Group Linked Successfully!**\n\n🆔 **Group ID:** `{target_group_id}`\n\nNow type `/schedule` to start the guided scheduler wizard!")
                            except Exception:
                                send_message(chat_id, "⚠️ **Invalid Format!**\nUse: `/link_group -100123456789`\n\n*(Tip: Send `/myid` in group to copy Group ID)*")

                        # GUIDED SCHEDULER WIZARD (DM ONLY)
                        elif text == "/schedule":
                            if is_group_chat(chat_id):
                                send_message(chat_id, "⚠️ Please use `/schedule` in **Bot DM**.")
                                continue

                            if user_id not in user_linked_groups:
                                send_message(chat_id, "⚠️ **No group linked yet!**\nFirst send: `/link_group <GroupID>`")
                                continue

                            schedule_wizard_state[user_id] = {"group_id": user_linked_groups[user_id]}
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "📊 Accounts", "callback_data": "swiz_sub_Accounts"}],
                                    [{"text": "📜 Business Laws", "callback_data": "swiz_sub_Business Laws"}],
                                    [{"text": "📈 Quantitative Aptitude", "callback_data": "swiz_sub_Quantitative Aptitude"}],
                                    [{"text": "💼 Economics", "callback_data": "swiz_sub_Economics"}]
                                ]
                            }
                            send_message(chat_id, f"🗓️ **AUTOMATED QUIZ SCHEDULER WIZARD**\nLinked Group: `{user_linked_groups[user_id]}`\n\n📘 **Step 1:** Select Subject:", reply_markup=keyboard)

                        elif text.startswith("/slots"):
                            if user_id in schedule_wizard_state:
                                slots_val = text.replace("/slots", "").strip()
                                slots_list = [s.strip() for s in slots_val.split(",") if s.strip()]
                                schedule_wizard_state[user_id]["slots"] = slots_list
                                
                                keyboard = {
                                    "inline_keyboard": [
                                        [{"text": "10 Qs", "callback_data": "swiz_cnt_10"}, {"text": "20 Qs", "callback_data": "swiz_cnt_20"}],
                                        [{"text": "30 Qs", "callback_data": "swiz_cnt_30"}, {"text": "50 Qs", "callback_data": "swiz_cnt_50"}]
                                    ]
                                }
                                send_message(chat_id, f"✅ **Slots Saved:** `{', '.join(slots_list)}`\n\n🔢 **Step 5:** Select Question Count per Quiz:", reply_markup=keyboard)

                    elif "callback_query" in result:
                        query = result["callback_query"]
                        query_chat_id = query["message"]["chat"]["id"]
                        message_id = query["message"]["message_id"]
                        data_cb = query["data"]
                        
                        requests.post(f"{BASE_URL}/answerCallbackQuery", json={"callback_query_id": query["id"]}, timeout=5)

                        if data_cb == "show_help_menu":
                            edit_message(query_chat_id, message_id, get_help_text())

                        elif data_cb.startswith("sub_"):
                            subj = data_cb.split("_", 1)[1]
                            quiz_builder_state[query_chat_id]["subject"] = subj
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "⏩ Full Syllabus (Skip)", "callback_data": "chap_skip"}],
                                    [{"text": "✍️ Enter Chapter & Sub-topics", "callback_data": "chap_custom"}],
                                    [{"text": "⬅️ Back", "callback_data": "show_help_menu"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"✅ Subject: **{subj}**\n\n📖 **Step 2:** Select Scope:", reply_markup=keyboard)

                        elif data_cb == "chap_custom":
                            edit_message(query_chat_id, message_id, "✍️ Send command to set Chapter and Sub-topics:\n`/chapter Chapter Name | Subtopic 1, Subtopic 2`")

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
                            edit_message(query_chat_id, message_id, "🔢 **Step 4:** Select Question Count:", reply_markup=keyboard)

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
                            edit_message(query_chat_id, message_id, "⚡ Mode: **Non-stop**\n\n⏱️ **Step 6:** Select Timer per question:", reply_markup=keyboard)

                        elif data_cb.startswith("timer_"):
                            tmr = int(data_cb.split("_")[1])
                            state = quiz_builder_state.get(query_chat_id, {})
                            subj = state.get("subject", "Accounts")
                            chap = state.get("chapter", "")
                            subtop = state.get("subtopics", "")
                            cnt = state.get("count", 10)
                            bf = state.get("break_freq", 0)
                            bd = state.get("break_duration", 0)
                            lvl = state.get("level", "EXTREME_HIGH")
                            cond_id = state.get("conductor_id")
                            
                            edit_message(query_chat_id, message_id, f"🚀 **Starting Quiz...**\n\n📘 Subject: `{subj}`\n🔢 Questions: `{cnt}`\n⏱️ Timer: `{tmr}s`")
                            threading.Thread(target=run_quiz_session, args=(query_chat_id, subj, chap, cnt, tmr, bf, bd, lvl, cond_id, subtop), daemon=True).start()

                        # --- SCHEDULER WIZARD CALLBACKS ---
                        elif data_cb == "sched_wiz_start":
                            if query_chat_id not in user_linked_groups:
                                edit_message(query_chat_id, message_id, "⚠️ **No group linked!**\nFirst send: `/link_group <GroupID>`")
                                continue
                            schedule_wizard_state[query_chat_id] = {"group_id": user_linked_groups[query_chat_id]}
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "📊 Accounts", "callback_data": "swiz_sub_Accounts"}],
                                    [{"text": "📜 Business Laws", "callback_data": "swiz_sub_Business Laws"}],
                                    [{"text": "📈 Quantitative Aptitude", "callback_data": "swiz_sub_Quantitative Aptitude"}],
                                    [{"text": "💼 Economics", "callback_data": "swiz_sub_Economics"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "🗓️ **SCHEDULER WIZARD**\n\n📘 **Step 1:** Select Subject:", reply_markup=keyboard)

                        elif data_cb.startswith("swiz_sub_"):
                            subj = data_cb.split("swiz_sub_")[1]
                            schedule_wizard_state[query_chat_id]["subject"] = subj
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "⏩ Full Syllabus (Skip)", "callback_data": "swiz_chap_skip"}],
                                    [{"text": "✍️ Custom Chapter & Subtopics", "callback_data": "swiz_chap_custom"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"✅ Subject: **{subj}**\n\n📖 **Step 2:** Choose Chapter Scope:", reply_markup=keyboard)

                        elif data_cb == "swiz_chap_custom":
                            edit_message(query_chat_id, message_id, "✍️ Send command for scheduled chapter & subtopics:\n`/chapter_sched Chapter Name | Subtopic 1, Subtopic 2`")

                        elif data_cb == "swiz_chap_skip":
                            schedule_wizard_state[query_chat_id]["chapter"] = ""
                            schedule_wizard_state[query_chat_id]["subtopics"] = ""
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "⚡ MEDIUM", "callback_data": "swiz_lvl_MEDIUM"}],
                                    [{"text": "🔥 HIGH", "callback_data": "swiz_lvl_HIGH"}],
                                    [{"text": "💀 EXTREME HIGH", "callback_data": "swiz_lvl_EXTREME_HIGH"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "🎯 **Step 3:** Select Starting Difficulty Level:", reply_markup=keyboard)

                        elif data_cb.startswith("swiz_lvl_"):
                            lvl = data_cb.split("swiz_lvl_")[1]
                            schedule_wizard_state[query_chat_id]["level"] = lvl
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "09:00, 15:00, 21:00", "callback_data": "slot_preset_1"}],
                                    [{"text": "10:00, 14:00, 18:00, 22:00", "callback_data": "slot_preset_2"}],
                                    [{"text": "✍️ Custom Slots", "callback_data": "slot_custom"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "⏰ **Step 4:** Choose Daily Time Slots:", reply_markup=keyboard)

                        elif data_cb == "slot_preset_1":
                            schedule_wizard_state[query_chat_id]["slots"] = ["09:00", "15:00", "21:00"]
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "10 Qs", "callback_data": "swiz_cnt_10"}, {"text": "20 Qs", "callback_data": "swiz_cnt_20"}],
                                    [{"text": "30 Qs", "callback_data": "swiz_cnt_30"}, {"text": "50 Qs", "callback_data": "swiz_cnt_50"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "🔢 **Step 5:** Select Question Count:", reply_markup=keyboard)

                        elif data_cb == "slot_preset_2":
                            schedule_wizard_state[query_chat_id]["slots"] = ["10:00", "14:00", "18:00", "22:00"]
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "10 Qs", "callback_data": "swiz_cnt_10"}, {"text": "20 Qs", "callback_data": "swiz_cnt_20"}],
                                    [{"text": "30 Qs", "callback_data": "swiz_cnt_30"}, {"text": "50 Qs", "callback_data": "swiz_cnt_50"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "🔢 **Step 5:** Select Question Count:", reply_markup=keyboard)

                        elif data_cb == "slot_custom":
                            edit_message(query_chat_id, message_id, "✍️ Send command for slots:\n`/slots 09:00, 13:00, 18:00, 21:00`")

                        elif data_cb.startswith("swiz_cnt_"):
                            cnt = int(data_cb.split("swiz_cnt_")[1])
                            schedule_wizard_state[query_chat_id]["count"] = cnt
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "20s", "callback_data": "swiz_tmr_20"}, {"text": "30s", "callback_data": "swiz_tmr_30"}],
                                    [{"text": "45s", "callback_data": "swiz_tmr_45"}, {"text": "60s", "callback_data": "swiz_tmr_60"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"✅ Questions: **{cnt}**\n\n⏱️ **Step 6:** Select Timer per Question:", reply_markup=keyboard)

                        elif data_cb.startswith("swiz_tmr_"):
                            tmr = int(data_cb.split("swiz_tmr_")[1])
                            st = schedule_wizard_state.get(query_chat_id, {})
                            target_grp = st.get("group_id")
                            subj = st.get("subject", "Accounts")
                            chap = st.get("chapter", "")
                            subtop = st.get("subtopics", "")
                            lvl = st.get("level", "EXTREME_HIGH")
                            slots = st.get("slots", ["09:00", "15:00", "21:00"])
                            cnt = st.get("count", 10)

                            today = datetime.now()
                            added = 0
                            chap_text = chap if chap else "Full Syllabus"
                            subtop_text = f" (Subtopics: {subtop})" if subtop else ""

                            for day in range(30):
                                f_date = (today + timedelta(days=day)).strftime("%Y-%m-%d")
                                for slot in slots:
                                    scheduled_quizzes.append({
                                        "chat_id": target_grp,
                                        "datetime": f"{f_date} {slot}",
                                        "subject": subj,
                                        "chapter": chap,
                                        "subtopics": subtop,
                                        "count": cnt,
                                        "timer": tmr,
                                        "level": lvl,
                                        "conductor_id": query_chat_id
                                    })
                                    added += 1

                            # ANNOUNCEMENT IN GROUP
                            announcement_text = (
                                f"📢 **SCHEDULED QUIZ ANNOUNCEMENT**\n"
                                f"─────────────────────\n"
                                f"📘 **Subject:** `{subj}`\n"
                                f"📖 **Scope:** `{chap_text}`{subtop_text}\n"
                                f"⏰ **Daily Time Slots:** `{', '.join(slots)}`\n"
                                f"🔢 **Questions/Quiz:** `{cnt}` | ⏱️ **Timer:** `{tmr}s`\n"
                                f"─────────────────────\n"
                                f"📌 *Quizzes will start automatically at scheduled times!*"
                            )
                            res_msg = send_message(target_grp, announcement_text)
                            if res_msg.get("ok"):
                                pin_message(target_grp, res_msg["result"]["message_id"])

                            edit_message(query_chat_id, message_id, f"🎉 **Schedule Created & Announced!**\n\n📌 Group ID: `{target_grp}`\n📘 Subject: `{subj}` (`{chap_text}`)\n⏰ Slots: `{', '.join(slots)}`\n\n_Group announcement pinned successfully!_")

        except Exception as e:
            time.sleep(2)

if __name__ == "__main__":
    # Start Dummy Web Server for Render Free Tier Web Service
    threading.Thread(target=run_dummy_server, daemon=True).start()
    
    # Start Bot Tasks
    threading.Thread(target=scheduler_background_worker, daemon=True).start()
    handle_updates()
