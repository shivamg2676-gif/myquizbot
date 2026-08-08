import os
import sys
import time
import json
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
quiz_report_tracker = {}  # chat_id -> list of per-question stat dicts (for end-of-quiz report)

# Permanent mapping: user_id -> linked_group_id
user_linked_groups = {}

SUBJECTS = ["Accounts", "Business Laws", "Quantitative Aptitude", "Economics"]

print("CA Vault Direct Execution Quiz Bot Starting...")

# --- DUMMY WEB SERVER FOR RENDER FREE WEB SERVICE ---
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Telegram Bot is Live and Healthy!")

def run_dummy_server():
    port = int(os.getenv("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    print(f"Dummy Web Server listening on port {port}")
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

# --- PERSISTENCE (so linked groups / schedules survive bot restarts) ---
DATA_FILE = "bot_data.json"
_save_lock = threading.Lock()

def load_persisted_data():
    global user_linked_groups, scheduled_quizzes
    if not os.path.exists(DATA_FILE):
        return
    try:
        with open(DATA_FILE, "r") as f:
            data = json.load(f)
        loaded_links = data.get("linked_groups", {})
        user_linked_groups.update({int(k): v for k, v in loaded_links.items()})
        scheduled_quizzes.extend(data.get("scheduled_quizzes", []))
        print(f"Loaded {len(user_linked_groups)} linked group(s) and {len(scheduled_quizzes)} scheduled quiz job(s) from disk.")
    except Exception as e:
        print(f"Could not load persisted data: {e}")

def save_persisted_data():
    with _save_lock:
        try:
            with open(DATA_FILE, "w") as f:
                json.dump({
                    "linked_groups": user_linked_groups,
                    "scheduled_quizzes": scheduled_quizzes
                }, f)
        except Exception as e:
            print(f"Could not save persisted data: {e}")

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
    if not is_group_chat(target_chat_id):
        if conductor_user_id:
            send_message(conductor_user_id, "*Quiz Error*\nQuizzes can ONLY be conducted inside Telegram Groups, not in DM.")
        return

    active_quiz_sessions[target_chat_id] = True
    quiz_report_tracker[target_chat_id] = []

    chap_display = chapter if chapter else "Full Syllabus"
    subtopic_display = f"\nSub-topics: `{subtopics}`" if subtopics else ""
    break_info = f"Break: Every `{break_freq}` Qs for `{break_duration//60}` min" if break_freq > 0 else "Mode: Non-stop (No Breaks)"

    start_msg = (
        f"CA VAULT — LIVE QUIZ SESSION\n"
        f"────────────────────────\n"
        f"Subject: `{subject}`\n"
        f"Chapter: `{chap_display}`{subtopic_display}\n"
        f"Questions: `{count}`  |  Timer: `{timer}s`\n"
        f"{break_info}\n"
        f"────────────────────────\n"
        f"Quiz starting now. All the best!"
    )
    send_message(target_chat_id, start_msg)

    current_difficulty = level

    if conductor_user_id:
        send_message(conductor_user_id, f"*Quiz Started* in group `{target_chat_id}`\nStarting level: `{current_difficulty}`\nA full performance report will be sent here once the quiz ends.")

    for idx in range(count):
        if not active_quiz_sessions.get(target_chat_id, False):
            send_message(target_chat_id, "Quiz session stopped.")
            if conductor_user_id:
                send_message(conductor_user_id, f"Quiz session stopped in group `{target_chat_id}`.")
            break

        if idx > 0 and break_freq > 0 and idx % break_freq == 0:
            send_message(target_chat_id, f"{idx} questions complete. `{break_duration // 60}` minute break starting now...")
            for _ in range(break_duration):
                if not active_quiz_sessions.get(target_chat_id, False):
                    break
                time.sleep(1)
            send_message(target_chat_id, "Break over. Resuming quiz...")

        q = generate_ai_question(subject, chapter, subtopics, current_difficulty)

        question_header = f"Q{idx+1}/{count}"
        if q["tag"]:
            question_header += f" {q['tag']}"

        full_q_text = f"{question_header}: {q['question']}"

        poll_res = send_poll(target_chat_id, full_q_text, q['options'], q['correct'], open_period=timer)
        poll_id = poll_res.get("result", {}).get("poll", {}).get("id") if poll_res.get("ok") else None

        time.sleep(timer + 1)

        if poll_id and poll_id in active_poll_tracker:
            p_data = active_poll_tracker[poll_id]
            total_v = p_data["total_votes"]
            wrong_v = p_data["wrong_count"]

            wrong_percentage = (wrong_v / total_v * 100) if total_v > 0 else 0

            # Record this question's stats for the end-of-quiz report (no live DM anymore)
            quiz_report_tracker.setdefault(target_chat_id, []).append({
                "q_no": idx + 1,
                "difficulty": current_difficulty,
                "total_votes": total_v,
                "wrong_count": wrong_v,
                "wrong_pct": wrong_percentage
            })

            if total_v > 0 and wrong_percentage > 60:
                if current_difficulty == "EXTREME_HIGH":
                    current_difficulty = "HIGH"
                elif current_difficulty == "HIGH":
                    current_difficulty = "MEDIUM"

        time.sleep(2)

    active_quiz_sessions[target_chat_id] = False
    send_message(target_chat_id, f"QUIZ COMPLETE\n\nSubject: `{subject}`\nTotal Questions: `{count}`")

    if conductor_user_id:
        send_message(conductor_user_id, build_performance_report(subject, chap_display, quiz_report_tracker.get(target_chat_id, [])))

    quiz_report_tracker.pop(target_chat_id, None)

def build_performance_report(subject, chapter, report_rows):
    """Builds a single consolidated performance report, sent once the quiz has finished."""
    if not report_rows:
        return "*QUIZ PERFORMANCE REPORT*\nNo votes were recorded for this quiz."

    total_q = len(report_rows)
    total_votes = sum(r["total_votes"] for r in report_rows)
    total_wrong = sum(r["wrong_count"] for r in report_rows)
    overall_wrong_pct = (total_wrong / total_votes * 100) if total_votes > 0 else 0
    overall_accuracy = 100 - overall_wrong_pct
    final_difficulty = report_rows[-1]["difficulty"]
    toughest = max(report_rows, key=lambda r: r["wrong_pct"]) if any(r["total_votes"] > 0 for r in report_rows) else None

    lines = [
        "*QUIZ PERFORMANCE REPORT*",
        "────────────────────────",
        f"Subject: `{subject}` ({chapter})",
        f"Questions Conducted: `{total_q}`",
        f"Final Difficulty Level: `{final_difficulty}`",
        f"Overall Accuracy: `{overall_accuracy:.1f}%`  |  Overall Wrong: `{overall_wrong_pct:.1f}%`",
        "────────────────────────",
        "*Question-wise Breakdown:*"
    ]
    for r in report_rows:
        lines.append(f"Q{r['q_no']}: `{r['total_votes']}` votes, `{r['wrong_count']}` wrong (`{r['wrong_pct']:.1f}%`) — {r['difficulty']}")

    if toughest and toughest["total_votes"] > 0:
        lines.append("────────────────────────")
        lines.append(f"Toughest Question: Q{toughest['q_no']} (`{toughest['wrong_pct']:.1f}%` wrong)")

    return "\n".join(lines)

# --- BACKGROUND SCHEDULER WORKER ---

def scheduler_background_worker():
    while True:
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        fired = False
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
                fired = True
        if fired:
            save_persisted_data()
        time.sleep(15)

def get_help_text():
    return (
        "*CA VAULT QUIZ BOT — CONTROL PANEL*\n\n"
        "*Group Commands*\n"
        "`/quiz` — Launch interactive live quiz setup\n"
        "`/stopquiz` — Stop the active quiz\n"
        "`/myid` — Show this group's Chat ID\n\n"
        "*DM Control Wizard (Bot DM only)*\n"
        "`/link_group <GroupID>` — Link your group once (stays linked)\n"
        "`/schedule` — Guided scheduler wizard\n"
        "     • One-time custom date & time (AM/PM)\n"
        "     • Recurring daily preset/custom slots\n"
        "`/myschedules` — View / cancel upcoming scheduled quizzes"
    )

# --- WIZARD HELPER TO BUILD SUMMARY TEXT ---
def get_wizard_summary(st):
    grp = st.get("group_id", "Not Set")
    subj = st.get("subject", "Not Selected")
    chap = st.get("chapter", "Full Subject Syllabus")
    subtop = st.get("subtopics", "None")
    lvl = st.get("level", "Not Selected")
    mode = st.get("schedule_mode")
    if mode == "onetime":
        schedule_line = f"Date/Time: `{st.get('display_datetime', 'Not Selected')}`"
    else:
        slots = ", ".join(st.get("slots", [])) if st.get("slots") else "Not Selected"
        schedule_line = f"Daily Slots: `{slots}`"
    cnt = st.get("count", "Not Selected")
    tmr = st.get("timer", "Not Selected")

    return (
        f"*CURRENT SCOPE SUMMARY*\n"
        f"────────────────────────\n"
        f"Group: `{grp}`\n"
        f"Subject: `{subj}`\n"
        f"Chapter: `{chap or 'Full Subject Syllabus'}`\n"
        f"Sub-topics: `{subtop or 'None'}`\n"
        f"Difficulty: `{lvl}`\n"
        f"{schedule_line}\n"
        f"Questions: `{cnt}`\n"
        f"Timer/Question: `{tmr}`\n"
        f"────────────────────────\n"
    )

# --- REUSABLE KEYBOARD BUILDERS (preset + manual custom option, everywhere) ---
def build_count_keyboard(prefix, back_cb):
    return {
        "inline_keyboard": [
            [{"text": "10 Qs", "callback_data": f"{prefix}10"}, {"text": "20 Qs", "callback_data": f"{prefix}20"}],
            [{"text": "30 Qs", "callback_data": f"{prefix}30"}, {"text": "40 Qs", "callback_data": f"{prefix}40"}],
            [{"text": "50 Qs", "callback_data": f"{prefix}50"}],
            [{"text": "Custom (type it)", "callback_data": f"{prefix}custom_prompt"}],
            [{"text": "Back", "callback_data": back_cb}]
        ]
    }

def build_timer_keyboard(prefix, back_cb):
    return {
        "inline_keyboard": [
            [{"text": "20s", "callback_data": f"{prefix}20"}, {"text": "30s", "callback_data": f"{prefix}30"}],
            [{"text": "45s", "callback_data": f"{prefix}45"}, {"text": "60s", "callback_data": f"{prefix}60"}],
            [{"text": "Custom (type it)", "callback_data": f"{prefix}custom_prompt"}],
            [{"text": "Back", "callback_data": back_cb}]
        ]
    }

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

                            if correct_idx not in chosen_options:
                                info["wrong_count"] += 1
                                wrong_dm_text = (
                                    f"Your answer was incorrect.\n\n"
                                    f"_{info['question']}_\n\n"
                                    f"Correct Option: `{info['options'][correct_idx]}`\n"
                                    f"Explanation: _{info.get('explanation', 'ICAI module principle applies.')}_"
                                )
                                send_message(user_id, wrong_dm_text)

                    if "message" in result:
                        message = result["message"]
                        chat_id = message["chat"]["id"]
                        user_id = message.get("from", {}).get("id", 0)
                        text = message.get("text", "").strip()

                        if text.startswith("/start"):
                            welcome_msg = (
                                "*Welcome to CA Vault Quiz Engine*\n\n"
                                "High-yield, AI-generated practice quizzes for CA Foundation.\n\n"
                                "Tap below to open the control menu."
                            )
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Open Help Menu", "callback_data": "show_help_menu"}]
                                ]
                            }
                            send_message(chat_id, welcome_msg, reply_markup=keyboard)

                        elif text.startswith("/help"):
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Schedule Wizard (DM)", "callback_data": "sched_wiz_start"}]
                                ]
                            }
                            send_message(chat_id, get_help_text(), reply_markup=keyboard)

                        elif text.startswith("/myid"):
                            send_message(chat_id, f"Chat ID: `{chat_id}`")

                        elif text == "/stopquiz":
                            if is_user_admin_owner_or_anonymous(message):
                                if active_quiz_sessions.get(chat_id, False):
                                    active_quiz_sessions[chat_id] = False
                                    send_message(chat_id, "Stopping active quiz...")
                                else:
                                    send_message(chat_id, "No active quiz running.")
                            else:
                                send_message(chat_id, "Permission denied.")

                        elif text == "/myschedules":
                            if is_group_chat(chat_id):
                                send_message(chat_id, "Please use `/myschedules` in Bot DM.")
                                continue
                            my_jobs = [j for j in scheduled_quizzes if j.get("conductor_id") == user_id]
                            if not my_jobs:
                                send_message(chat_id, "You have no upcoming scheduled quizzes.")
                                continue
                            my_jobs_sorted = sorted(my_jobs, key=lambda j: j["datetime"])[:20]
                            lines = ["*YOUR UPCOMING SCHEDULED QUIZZES*", "────────────────────────"]
                            for j in my_jobs_sorted:
                                lines.append(f"`{j['datetime']}` — {j['subject']} ({j.get('chapter') or 'Full Syllabus'}) — {j['count']} Qs")
                            if len(my_jobs) > 20:
                                lines.append(f"...and {len(my_jobs) - 20} more.")
                            send_message(chat_id, "\n".join(lines))

                        elif text.startswith("/quiz"):
                            if not is_group_chat(chat_id):
                                send_message(chat_id, "Live quizzes can only run inside Telegram Groups.\nLink your group using `/link_group <GroupID>` and use `/schedule` in DM.")
                                continue

                            if not is_user_admin_owner_or_anonymous(message):
                                send_message(chat_id, "Permission denied. Only Admins or Owners can start quizzes.")
                                continue

                            quiz_builder_state[chat_id] = {"subject": "Accounts", "chapter": "", "subtopics": "", "level": "EXTREME_HIGH", "break_freq": 0, "break_duration": 0, "conductor_id": user_id}
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Accounts", "callback_data": "sub_Accounts"}],
                                    [{"text": "Business Laws", "callback_data": "sub_Business Laws"}],
                                    [{"text": "Quantitative Aptitude", "callback_data": "sub_Quantitative Aptitude"}],
                                    [{"text": "Economics", "callback_data": "sub_Economics"}]
                                ]
                            }
                            send_message(chat_id, "*Step 1:* Select Subject", reply_markup=keyboard)

                        elif text.startswith("/customcount_sched"):
                            if user_id in schedule_wizard_state:
                                raw = text.replace("/customcount_sched", "").strip()
                                if raw.isdigit() and int(raw) > 0:
                                    schedule_wizard_state[user_id]["count"] = int(raw)
                                    st = schedule_wizard_state[user_id]
                                    summary = get_wizard_summary(st)
                                    keyboard = build_timer_keyboard("swiz_tmr_", "swiz_back_to_cnt")
                                    send_message(chat_id, f"{summary}Questions set to `{raw}`.\n\n*Step:* Select Timer per Question", reply_markup=keyboard)
                                else:
                                    send_message(chat_id, "Invalid number. Use: `/customcount_sched 25`")

                        elif text.startswith("/customtimer_sched"):
                            if user_id in schedule_wizard_state:
                                raw = text.replace("/customtimer_sched", "").strip()
                                if raw.isdigit() and int(raw) > 0:
                                    finalize_schedule_wizard(chat_id, user_id, int(raw))
                                else:
                                    send_message(chat_id, "Invalid number. Use: `/customtimer_sched 40` (seconds)")

                        elif text.startswith("/customcount"):
                            if chat_id in quiz_builder_state:
                                raw = text.replace("/customcount", "").strip()
                                if raw.isdigit() and int(raw) > 0:
                                    quiz_builder_state[chat_id]["count"] = int(raw)
                                    keyboard = {
                                        "inline_keyboard": [
                                            [{"text": "No Breaks", "callback_data": "break_none"}],
                                            [{"text": "Every 20 Qs (5 min)", "callback_data": "break_20_5"}],
                                            [{"text": "Every 30 Qs (10 min)", "callback_data": "break_30_10"}],
                                            [{"text": "Back", "callback_data": "lvl_EXTREME_HIGH"}]
                                        ]
                                    }
                                    send_message(chat_id, f"Questions set to `{raw}`.\n\n*Step:* Select Break Setting", reply_markup=keyboard)
                                else:
                                    send_message(chat_id, "Invalid number. Use: `/customcount 25`")

                        elif text.startswith("/customtimer"):
                            if chat_id in quiz_builder_state:
                                raw = text.replace("/customtimer", "").strip()
                                if raw.isdigit() and int(raw) > 0:
                                    state = quiz_builder_state.get(chat_id, {})
                                    subj = state.get("subject", "Accounts")
                                    chap = state.get("chapter", "")
                                    subtop = state.get("subtopics", "")
                                    cnt = state.get("count", 10)
                                    bf = state.get("break_freq", 0)
                                    bd = state.get("break_duration", 0)
                                    lvl = state.get("level", "EXTREME_HIGH")
                                    cond_id = state.get("conductor_id")
                                    tmr = int(raw)
                                    send_message(chat_id, f"*Starting Quiz...*\n\nSubject: `{subj}`\nQuestions: `{cnt}`\nTimer: `{tmr}s`")
                                    threading.Thread(target=run_quiz_session, args=(chat_id, subj, chap, cnt, tmr, bf, bd, lvl, cond_id, subtop), daemon=True).start()
                                else:
                                    send_message(chat_id, "Invalid number. Use: `/customtimer 40` (seconds)")

                        elif text.startswith("/chapter_only"):
                            target_chat_id = chat_id
                            chap_val = text.replace("/chapter_only", "").strip()

                            if text.startswith("/chapter_only_sched"):
                                chap_val = text.replace("/chapter_only_sched", "").strip()
                                schedule_wizard_state[user_id]["chapter"] = chap_val
                                schedule_wizard_state[user_id]["subtopics"] = ""
                                st = schedule_wizard_state[user_id]
                                summary = get_wizard_summary(st)

                                keyboard = {
                                    "inline_keyboard": [
                                        [{"text": "MEDIUM", "callback_data": "swiz_lvl_MEDIUM"}],
                                        [{"text": "HIGH", "callback_data": "swiz_lvl_HIGH"}],
                                        [{"text": "EXTREME HIGH", "callback_data": "swiz_lvl_EXTREME_HIGH"}],
                                        [{"text": "Back", "callback_data": "swiz_back_to_chap_choice"}]
                                    ]
                                }
                                send_message(chat_id, f"{summary}\n*Step 3:* Select Starting Difficulty Level", reply_markup=keyboard)
                            else:
                                if target_chat_id in quiz_builder_state:
                                    quiz_builder_state[target_chat_id]["chapter"] = chap_val
                                    quiz_builder_state[target_chat_id]["subtopics"] = ""
                                    keyboard = {
                                        "inline_keyboard": [
                                            [{"text": "MEDIUM", "callback_data": "lvl_MEDIUM"}],
                                            [{"text": "HIGH", "callback_data": "lvl_HIGH"}],
                                            [{"text": "EXTREME HIGH", "callback_data": "lvl_EXTREME_HIGH"}],
                                            [{"text": "Back", "callback_data": "back_to_chap_choice"}]
                                        ]
                                    }
                                    send_message(target_chat_id, f"Chapter set: `{chap_val}`\n\n*Step 3:* Select Difficulty Level", reply_markup=keyboard)

                        elif text.startswith("/chapter"):
                            target_chat_id = chat_id
                            if text.startswith("/chapter_sched"):
                                raw_input = text.replace("/chapter_sched", "").strip()
                                parts = raw_input.split("|")
                                chap_val = parts[0].strip()
                                subtopic_val = parts[1].strip() if len(parts) > 1 else ""

                                schedule_wizard_state[user_id]["chapter"] = chap_val
                                schedule_wizard_state[user_id]["subtopics"] = subtopic_val
                                st = schedule_wizard_state[user_id]
                                summary = get_wizard_summary(st)

                                keyboard = {
                                    "inline_keyboard": [
                                        [{"text": "MEDIUM", "callback_data": "swiz_lvl_MEDIUM"}],
                                        [{"text": "HIGH", "callback_data": "swiz_lvl_HIGH"}],
                                        [{"text": "EXTREME HIGH", "callback_data": "swiz_lvl_EXTREME_HIGH"}],
                                        [{"text": "Back", "callback_data": "swiz_back_to_chap_choice"}]
                                    ]
                                }
                                send_message(chat_id, f"{summary}\n*Step 3:* Select Difficulty Level", reply_markup=keyboard)
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
                                            [{"text": "MEDIUM", "callback_data": "lvl_MEDIUM"}],
                                            [{"text": "HIGH", "callback_data": "lvl_HIGH"}],
                                            [{"text": "EXTREME HIGH", "callback_data": "lvl_EXTREME_HIGH"}],
                                            [{"text": "Back", "callback_data": "back_to_chap_choice"}]
                                        ]
                                    }
                                    send_message(target_chat_id, f"Chapter set: `{chap_val}`\nSub-topics: `{subtopic_val or 'All'}`\n\n*Step 3:* Select Difficulty Level", reply_markup=keyboard)

                        elif text.startswith("/link_group"):
                            if is_group_chat(chat_id):
                                send_message(chat_id, "Send `/link_group` in Bot DM.")
                                continue

                            try:
                                target_group_id = int(text.replace("/link_group", "").strip())
                                user_linked_groups[user_id] = target_group_id
                                save_persisted_data()
                                send_message(chat_id, f"*Group Linked Successfully*\n\nGroup ID: `{target_group_id}`\n\nThis link is saved — you will not need to link again. Type `/schedule` any time to open the scheduler wizard.")
                            except Exception:
                                send_message(chat_id, "Invalid format.\nUse: `/link_group -100123456789`\n\n(Tip: send `/myid` in the group to copy its Group ID)")

                        elif text == "/schedule":
                            if is_group_chat(chat_id):
                                send_message(chat_id, "Please use `/schedule` in Bot DM.")
                                continue

                            if user_id not in user_linked_groups:
                                send_message(chat_id, "No group linked yet.\nFirst send: `/link_group <GroupID>`")
                                continue

                            schedule_wizard_state[user_id] = {"group_id": user_linked_groups[user_id]}
                            st = schedule_wizard_state[user_id]
                            summary = get_wizard_summary(st)

                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Accounts", "callback_data": "swiz_sub_Accounts"}],
                                    [{"text": "Business Laws", "callback_data": "swiz_sub_Business Laws"}],
                                    [{"text": "Quantitative Aptitude", "callback_data": "swiz_sub_Quantitative Aptitude"}],
                                    [{"text": "Economics", "callback_data": "swiz_sub_Economics"}]
                                ]
                            }
                            send_message(chat_id, f"{summary}*SCHEDULER WIZARD*\n\n*Step 1:* Select Subject", reply_markup=keyboard)

                        elif text.startswith("/setschedule"):
                            if user_id in schedule_wizard_state:
                                raw = text.replace("/setschedule", "").strip()
                                try:
                                    parts = raw.split("|")
                                    date_part = parts[0].strip()
                                    time_part = parts[1].strip().upper()
                                    dt_obj = datetime.strptime(f"{date_part} {time_part}", "%Y-%m-%d %I:%M %p")
                                    if dt_obj < datetime.now():
                                        send_message(chat_id, "That date/time is in the past. Please pick a future date & time.")
                                        continue
                                    schedule_wizard_state[user_id]["custom_datetime"] = dt_obj.strftime("%Y-%m-%d %H:%M")
                                    schedule_wizard_state[user_id]["display_datetime"] = dt_obj.strftime("%Y-%m-%d, %I:%M %p")
                                    schedule_wizard_state[user_id]["schedule_mode"] = "onetime"
                                    st = schedule_wizard_state[user_id]
                                    summary = get_wizard_summary(st)
                                    keyboard = build_count_keyboard("swiz_cnt_", "swiz_mode_onetime")
                                    send_message(chat_id, f"{summary}Date & Time set: `{st['display_datetime']}`\n\n*Step 5:* Select Question Count", reply_markup=keyboard)
                                except Exception:
                                    send_message(chat_id, "Invalid format.\nUse: `/setschedule YYYY-MM-DD | hh:mm AM/PM`\nExample: `/setschedule 2026-08-10 | 06:30 PM`")
                            else:
                                send_message(chat_id, "Start the wizard first with `/schedule`.")

                        elif text.startswith("/slots"):
                            if user_id in schedule_wizard_state:
                                slots_val = text.replace("/slots", "").strip()
                                slots_list = [s.strip() for s in slots_val.split(",") if s.strip()]
                                schedule_wizard_state[user_id]["slots"] = slots_list
                                schedule_wizard_state[user_id]["schedule_mode"] = "recurring"
                                st = schedule_wizard_state[user_id]
                                summary = get_wizard_summary(st)

                                keyboard = build_count_keyboard("swiz_cnt_", "swiz_back_to_lvl")
                                send_message(chat_id, f"{summary}\n*Step 5:* Select Question Count per Quiz", reply_markup=keyboard)

                    elif "callback_query" in result:
                        query = result["callback_query"]
                        query_chat_id = query["message"]["chat"]["id"]
                        message_id = query["message"]["message_id"]
                        data_cb = query["data"]
                        cb_user_id = query.get("from", {}).get("id", query_chat_id)

                        requests.post(f"{BASE_URL}/answerCallbackQuery", json={"callback_query_id": query["id"]}, timeout=5)

                        if data_cb == "show_help_menu":
                            edit_message(query_chat_id, message_id, get_help_text())

                        # --- LIVE QUIZ BUILDER BACK NAVIGATION & FLOW ---
                        elif data_cb == "start_interactive_quiz":
                            quiz_builder_state[query_chat_id] = {"subject": "Accounts", "chapter": "", "subtopics": "", "level": "EXTREME_HIGH", "break_freq": 0, "break_duration": 0, "conductor_id": query_chat_id}
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Accounts", "callback_data": "sub_Accounts"}],
                                    [{"text": "Business Laws", "callback_data": "sub_Business Laws"}],
                                    [{"text": "Quantitative Aptitude", "callback_data": "sub_Quantitative Aptitude"}],
                                    [{"text": "Economics", "callback_data": "sub_Economics"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "*Step 1:* Select Subject", reply_markup=keyboard)

                        elif data_cb.startswith("sub_"):
                            subj = data_cb.split("_", 1)[1]
                            quiz_builder_state[query_chat_id]["subject"] = subj
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Full Subject (Skip)", "callback_data": "chap_skip"}],
                                    [{"text": "Full Chapter Only", "callback_data": "chap_only_prompt"}],
                                    [{"text": "Chapter + Sub-topics", "callback_data": "chap_custom"}],
                                    [{"text": "Back", "callback_data": "start_interactive_quiz"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"Subject: *{subj}*\n\n*Step 2:* Choose Quiz Scope", reply_markup=keyboard)

                        elif data_cb == "back_to_chap_choice":
                            subj = quiz_builder_state.get(query_chat_id, {}).get("subject", "Accounts")
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Full Subject (Skip)", "callback_data": "chap_skip"}],
                                    [{"text": "Full Chapter Only", "callback_data": "chap_only_prompt"}],
                                    [{"text": "Chapter + Sub-topics", "callback_data": "chap_custom"}],
                                    [{"text": "Back", "callback_data": "start_interactive_quiz"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"Subject: *{subj}*\n\n*Step 2:* Choose Quiz Scope", reply_markup=keyboard)

                        elif data_cb == "chap_only_prompt":
                            edit_message(query_chat_id, message_id, "Send command for full chapter:\n`/chapter_only [Chapter Name]`")

                        elif data_cb == "chap_custom":
                            edit_message(query_chat_id, message_id, "Send command for chapter + sub-topics:\n`/chapter Chapter Name | Subtopic 1, Subtopic 2`")

                        elif data_cb == "chap_skip":
                            quiz_builder_state[query_chat_id]["chapter"] = ""
                            quiz_builder_state[query_chat_id]["subtopics"] = ""
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "MEDIUM", "callback_data": "lvl_MEDIUM"}],
                                    [{"text": "HIGH", "callback_data": "lvl_HIGH"}],
                                    [{"text": "EXTREME HIGH", "callback_data": "lvl_EXTREME_HIGH"}],
                                    [{"text": "Back", "callback_data": "back_to_chap_choice"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, "*Step 3:* Select Starting Difficulty Level", reply_markup=keyboard)

                        elif data_cb.startswith("lvl_"):
                            lvl = data_cb.split("lvl_")[1]
                            quiz_builder_state[query_chat_id]["level"] = lvl
                            keyboard = build_count_keyboard("cnt_", "chap_skip")
                            edit_message(query_chat_id, message_id, f"Difficulty: *{lvl}*\n\n*Step 4:* Select Question Count (or type `/customcount N`)", reply_markup=keyboard)

                        elif data_cb == "cnt_custom_prompt":
                            edit_message(query_chat_id, message_id, "Send the exact question count as a command:\n`/customcount 25`")

                        elif data_cb.startswith("cnt_"):
                            cnt = int(data_cb.split("_")[1])
                            quiz_builder_state[query_chat_id]["count"] = cnt
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "No Breaks", "callback_data": "break_none"}],
                                    [{"text": "Every 20 Qs (5 min)", "callback_data": "break_20_5"}],
                                    [{"text": "Every 30 Qs (10 min)", "callback_data": "break_30_10"}],
                                    [{"text": "Back", "callback_data": "lvl_EXTREME_HIGH"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"Questions: *{cnt}*\n\n*Step 5:* Select Break Setting", reply_markup=keyboard)

                        elif data_cb == "break_none":
                            quiz_builder_state[query_chat_id]["break_freq"] = 0
                            quiz_builder_state[query_chat_id]["break_duration"] = 0
                            keyboard = build_timer_keyboard("timer_", "cnt_10")
                            edit_message(query_chat_id, message_id, "Mode: *Non-stop*\n\n*Step 6:* Select Timer per Question (or type `/customtimer N`)", reply_markup=keyboard)

                        elif data_cb == "break_20_5":
                            quiz_builder_state[query_chat_id]["break_freq"] = 20
                            quiz_builder_state[query_chat_id]["break_duration"] = 300
                            keyboard = build_timer_keyboard("timer_", "cnt_10")
                            edit_message(query_chat_id, message_id, "Break: *Every 20 Qs (5 min)*\n\n*Step 6:* Select Timer per Question (or type `/customtimer N`)", reply_markup=keyboard)

                        elif data_cb == "break_30_10":
                            quiz_builder_state[query_chat_id]["break_freq"] = 30
                            quiz_builder_state[query_chat_id]["break_duration"] = 600
                            keyboard = build_timer_keyboard("timer_", "cnt_10")
                            edit_message(query_chat_id, message_id, "Break: *Every 30 Qs (10 min)*\n\n*Step 6:* Select Timer per Question (or type `/customtimer N`)", reply_markup=keyboard)

                        elif data_cb == "timer_custom_prompt":
                            edit_message(query_chat_id, message_id, "Send the exact timer (seconds) as a command:\n`/customtimer 40`")

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

                            edit_message(query_chat_id, message_id, f"*Starting Quiz...*\n\nSubject: `{subj}`\nQuestions: `{cnt}`\nTimer: `{tmr}s`")
                            threading.Thread(target=run_quiz_session, args=(query_chat_id, subj, chap, cnt, tmr, bf, bd, lvl, cond_id, subtop), daemon=True).start()

                        # --- SCHEDULER WIZARD WITH FULL BACK NAVIGATION & SCOPE DISPLAY ---
                        elif data_cb == "sched_wiz_start":
                            if cb_user_id not in user_linked_groups:
                                edit_message(query_chat_id, message_id, "No group linked.\nFirst send: `/link_group <GroupID>`")
                                continue
                            schedule_wizard_state[cb_user_id] = {"group_id": user_linked_groups[cb_user_id]}
                            st = schedule_wizard_state[cb_user_id]
                            summary = get_wizard_summary(st)

                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Accounts", "callback_data": "swiz_sub_Accounts"}],
                                    [{"text": "Business Laws", "callback_data": "swiz_sub_Business Laws"}],
                                    [{"text": "Quantitative Aptitude", "callback_data": "swiz_sub_Quantitative Aptitude"}],
                                    [{"text": "Economics", "callback_data": "swiz_sub_Economics"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"{summary}*SCHEDULER WIZARD*\n\n*Step 1:* Select Subject", reply_markup=keyboard)

                        elif data_cb.startswith("swiz_sub_"):
                            subj = data_cb.split("swiz_sub_")[1]
                            schedule_wizard_state[cb_user_id]["subject"] = subj
                            st = schedule_wizard_state[cb_user_id]
                            summary = get_wizard_summary(st)

                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Full Subject (Skip)", "callback_data": "swiz_chap_skip"}],
                                    [{"text": "Full Chapter Only", "callback_data": "swiz_chap_only_prompt"}],
                                    [{"text": "Chapter + Sub-topics", "callback_data": "swiz_chap_custom"}],
                                    [{"text": "Back", "callback_data": "sched_wiz_start"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"{summary}*Step 2:* Choose Scope", reply_markup=keyboard)

                        elif data_cb == "swiz_back_to_chap_choice":
                            st = schedule_wizard_state.get(cb_user_id, {})
                            summary = get_wizard_summary(st)
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "Full Subject (Skip)", "callback_data": "swiz_chap_skip"}],
                                    [{"text": "Full Chapter Only", "callback_data": "swiz_chap_only_prompt"}],
                                    [{"text": "Chapter + Sub-topics", "callback_data": "swiz_chap_custom"}],
                                    [{"text": "Back", "callback_data": "sched_wiz_start"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"{summary}*Step 2:* Choose Scope", reply_markup=keyboard)

                        elif data_cb == "swiz_chap_only_prompt":
                            edit_message(query_chat_id, message_id, "Send command for full chapter:\n`/chapter_only_sched [Chapter Name]`")

                        elif data_cb == "swiz_chap_custom":
                            edit_message(query_chat_id, message_id, "Send command for chapter & sub-topics:\n`/chapter_sched Chapter Name | Subtopic 1, Subtopic 2`")

                        elif data_cb == "swiz_chap_skip":
                            schedule_wizard_state[cb_user_id]["chapter"] = ""
                            schedule_wizard_state[cb_user_id]["subtopics"] = ""
                            st = schedule_wizard_state[cb_user_id]
                            summary = get_wizard_summary(st)

                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "MEDIUM", "callback_data": "swiz_lvl_MEDIUM"}],
                                    [{"text": "HIGH", "callback_data": "swiz_lvl_HIGH"}],
                                    [{"text": "EXTREME HIGH", "callback_data": "swiz_lvl_EXTREME_HIGH"}],
                                    [{"text": "Back", "callback_data": "swiz_back_to_chap_choice"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"{summary}*Step 3:* Select Starting Difficulty Level", reply_markup=keyboard)

                        elif data_cb.startswith("swiz_lvl_"):
                            lvl = data_cb.split("swiz_lvl_")[1]
                            schedule_wizard_state[cb_user_id]["level"] = lvl
                            st = schedule_wizard_state[cb_user_id]
                            summary = get_wizard_summary(st)

                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "One-Time Custom Date & Time", "callback_data": "swiz_mode_onetime"}],
                                    [{"text": "Recurring Daily Slots", "callback_data": "swiz_mode_recurring"}],
                                    [{"text": "Back", "callback_data": "swiz_chap_skip"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"{summary}*Step 4:* Choose Scheduling Mode", reply_markup=keyboard)

                        elif data_cb == "swiz_mode_onetime":
                            schedule_wizard_state[cb_user_id]["schedule_mode"] = "onetime"
                            st = schedule_wizard_state[cb_user_id]
                            summary = get_wizard_summary(st)
                            edit_message(
                                query_chat_id, message_id,
                                f"{summary}*Step 4:* Send the exact date & time (24h date, 12h time with AM/PM):\n\n"
                                f"`/setschedule YYYY-MM-DD | hh:mm AM/PM`\n\n"
                                f"Example: `/setschedule 2026-08-10 | 06:30 PM`"
                            )

                        elif data_cb == "swiz_mode_recurring":
                            schedule_wizard_state[cb_user_id]["schedule_mode"] = "recurring"
                            st = schedule_wizard_state[cb_user_id]
                            summary = get_wizard_summary(st)
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "09:00 AM, 03:00 PM, 09:00 PM", "callback_data": "slot_preset_1"}],
                                    [{"text": "10:00 AM, 02:00 PM, 06:00 PM, 10:00 PM", "callback_data": "slot_preset_2"}],
                                    [{"text": "Custom Slots (type it)", "callback_data": "slot_custom"}],
                                    [{"text": "Back", "callback_data": "swiz_back_to_lvl"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"{summary}*Step 4:* Choose Daily Time Slots (repeats for next 30 days)", reply_markup=keyboard)

                        elif data_cb == "swiz_back_to_lvl":
                            st = schedule_wizard_state.get(cb_user_id, {})
                            summary = get_wizard_summary(st)
                            keyboard = {
                                "inline_keyboard": [
                                    [{"text": "MEDIUM", "callback_data": "swiz_lvl_MEDIUM"}],
                                    [{"text": "HIGH", "callback_data": "swiz_lvl_HIGH"}],
                                    [{"text": "EXTREME HIGH", "callback_data": "swiz_lvl_EXTREME_HIGH"}],
                                    [{"text": "Back", "callback_data": "swiz_back_to_chap_choice"}]
                                ]
                            }
                            edit_message(query_chat_id, message_id, f"{summary}*Step 3:* Select Starting Difficulty Level", reply_markup=keyboard)

                        elif data_cb == "slot_preset_1":
                            schedule_wizard_state[cb_user_id]["slots"] = ["09:00", "15:00", "21:00"]
                            st = schedule_wizard_state[cb_user_id]
                            summary = get_wizard_summary(st)
                            keyboard = build_count_keyboard("swiz_cnt_", "swiz_mode_recurring")
                            edit_message(query_chat_id, message_id, f"{summary}*Step 5:* Select Question Count", reply_markup=keyboard)

                        elif data_cb == "slot_preset_2":
                            schedule_wizard_state[cb_user_id]["slots"] = ["10:00", "14:00", "18:00", "22:00"]
                            st = schedule_wizard_state[cb_user_id]
                            summary = get_wizard_summary(st)
                            keyboard = build_count_keyboard("swiz_cnt_", "swiz_mode_recurring")
                            edit_message(query_chat_id, message_id, f"{summary}*Step 5:* Select Question Count", reply_markup=keyboard)

                        elif data_cb == "slot_custom":
                            edit_message(query_chat_id, message_id, "Send command for custom daily slots (24h time, comma separated):\n`/slots 09:00, 13:00, 18:00, 21:00`")

                        elif data_cb == "swiz_cnt_custom_prompt":
                            mode = schedule_wizard_state.get(cb_user_id, {}).get("schedule_mode")
                            cmd = "/customcount_sched 25" if mode else "/customcount_sched 25"
                            edit_message(query_chat_id, message_id, f"Send the exact question count as a command:\n`{cmd}`")

                        elif data_cb.startswith("swiz_cnt_"):
                            cnt = int(data_cb.split("swiz_cnt_")[1])
                            schedule_wizard_state[cb_user_id]["count"] = cnt
                            st = schedule_wizard_state[cb_user_id]
                            summary = get_wizard_summary(st)

                            back_cb = "swiz_mode_onetime" if st.get("schedule_mode") == "onetime" else "swiz_back_to_lvl"
                            keyboard = build_timer_keyboard("swiz_tmr_", back_cb)
                            edit_message(query_chat_id, message_id, f"{summary}*Step 6:* Select Timer per Question", reply_markup=keyboard)

                        elif data_cb == "swiz_back_to_cnt":
                            st = schedule_wizard_state.get(cb_user_id, {})
                            summary = get_wizard_summary(st)
                            keyboard = build_count_keyboard("swiz_cnt_", "swiz_back_to_lvl")
                            edit_message(query_chat_id, message_id, f"{summary}*Step 5:* Select Question Count", reply_markup=keyboard)

                        elif data_cb == "swiz_tmr_custom_prompt":
                            edit_message(query_chat_id, message_id, "Send the exact timer (seconds) as a command:\n`/customtimer_sched 40`")

                        elif data_cb.startswith("swiz_tmr_"):
                            tmr = int(data_cb.split("swiz_tmr_")[1])
                            finalize_schedule_wizard(query_chat_id, cb_user_id, tmr, message_id=message_id)

        except Exception as e:
            time.sleep(2)


def finalize_schedule_wizard(chat_id, user_id, tmr, message_id=None):
    """Shared finalizer for both one-time and recurring schedule modes."""
    st = schedule_wizard_state.get(user_id, {})
    target_grp = st.get("group_id")
    subj = st.get("subject", "Accounts")
    chap = st.get("chapter", "")
    subtop = st.get("subtopics", "")
    lvl = st.get("level", "EXTREME_HIGH")
    cnt = st.get("count", 10)
    mode = st.get("schedule_mode", "recurring")

    chap_text = chap if chap else "Full Subject Syllabus"
    subtop_text = f"\nSubtopics: `{subtop}`" if subtop else ""

    if mode == "onetime":
        run_dt = st.get("custom_datetime")
        if not run_dt:
            send_message(chat_id, "Missing date/time. Please send `/setschedule YYYY-MM-DD | hh:mm AM/PM` again.")
            return
        scheduled_quizzes.append({
            "chat_id": target_grp,
            "datetime": run_dt,
            "subject": subj,
            "chapter": chap,
            "subtopics": subtop,
            "count": cnt,
            "timer": tmr,
            "level": lvl,
            "conductor_id": user_id
        })
        save_persisted_data()
        schedule_line = f"Date & Time: `{st.get('display_datetime')}`"
        announcement_schedule_line = f"Date & Time: `{st.get('display_datetime')}`"
    else:
        slots = st.get("slots", ["09:00", "15:00", "21:00"])
        today = datetime.now()
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
                    "conductor_id": user_id
                })
        save_persisted_data()
        schedule_line = f"Daily Slots (next 30 days): `{', '.join(slots)}`"
        announcement_schedule_line = f"Daily Time Slots: `{', '.join(slots)}`"

    announcement_text = (
        f"SCHEDULED QUIZ ANNOUNCEMENT\n"
        f"────────────────────────\n"
        f"Subject: `{subj}`\n"
        f"Scope: `{chap_text}`{subtop_text}\n"
        f"{announcement_schedule_line}\n"
        f"Questions/Quiz: `{cnt}`  |  Timer: `{tmr}s`\n"
        f"────────────────────────\n"
        f"Quizzes will start automatically at the scheduled time(s)."
    )
    res_msg = send_message(target_grp, announcement_text)
    if res_msg.get("ok"):
        pin_message(target_grp, res_msg["result"]["message_id"])

    final_text = (
        f"*Schedule Created & Announced*\n\n"
        f"Group ID: `{target_grp}`\n"
        f"Subject: `{subj}` (`{chap_text}`)\n"
        f"{schedule_line}\n\n"
        f"Group announcement pinned successfully. Use `/myschedules` any time to review it."
    )
    if message_id:
        edit_message(chat_id, message_id, final_text)
    else:
        send_message(chat_id, final_text)


if __name__ == "__main__":
    # Load any previously saved links / schedules
    load_persisted_data()

    # Start Dummy Web Server for Render Free Tier Web Service
    threading.Thread(target=run_dummy_server, daemon=True).start()

    # Start Bot Tasks
    threading.Thread(target=scheduler_background_worker, daemon=True).start()
    handle_updates()
