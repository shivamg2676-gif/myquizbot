"""CA Vault Quiz Bot - Constants"""

# ── CA Foundation Subjects ──
SUBJECTS = ["Accounts", "Law", "Economics", "Quantitative Aptitude"]
SUBJECT_ALIASES = {
    "accounts": "Accounts",
    "acc": "Accounts",
    "law": "Law",
    "economics": "Economics",
    "eco": "Economics",
    "quant": "Quantitative Aptitude",
    "qa": "Quantitative Aptitude",
    "maths": "Quantitative Aptitude",
    "math": "Quantitative Aptitude",
}

# ── Chapter mapping (default ICAI syllabus) ──
DEFAULT_SYLLABUS: dict[str, list[str]] = {
    "Accounts": [
        "Theoretical Framework",
        "Accounting Process",
        "Bank Reconciliation Statement",
        "Depreciation",
        "Bills of Exchange",
        "Rectification of Errors",
        "Financial Statements",
        "Partnership Accounts",
        "Company Accounts",
    ],
    "Law": [
        "Indian Contract Act 1872",
        "Sale of Goods Act 1930",
        "Indian Partnership Act 1932",
        "Companies Act 2013",
        "The Negotiable Instruments Act 1881",
    ],
    "Economics": [
        "Nature & Scope of Economics",
        "Theory of Demand & Supply",
        "Theory of Production & Cost",
        "Price Determination",
        "Business Cycles",
        "Money & Banking",
        "Economic Reforms",
        "Indian Economy",
    ],
    "Quantitative Aptitude": [
        "Ratio & Proportion",
        "Indices & Logarithms",
        "Equations",
        "Inequalities",
        "Time Value of Money",
        "Permutations & Combinations",
        "Sequence & Series",
        "Sets & Functions",
        "Differential Calculus",
        "Integral Calculus",
        "Statistical Description of Data",
        "Measures of Central Tendency",
        "Correlation & Regression",
        "Probability",
    ],
}

# ── Question Types ──
QTYPE_MCQ = "mcq"
QTYPE_TRUE_FALSE = "true_false"
QTYPE_FILL_BLANK = "fill_blank"
QTYPE_MATCH = "match_following"
QTYPE_ONE_WORD = "one_word"
QUESTION_TYPES = [QTYPE_MCQ, QTYPE_TRUE_FALSE, QTYPE_FILL_BLANK, QTYPE_MATCH, QTYPE_ONE_WORD]

THEORY_TYPES = {QTYPE_MCQ, QTYPE_TRUE_FALSE, QTYPE_MATCH, QTYPE_ONE_WORD}
PRACTICAL_TYPES = {QTYPE_FILL_BLANK}

# ── Quiz Types ──
QUIZ_CHAPTER = "chapter"
QUIZ_TOPIC = "topic"
QUIZ_MOCK = "mock"
QUIZ_DAILY = "daily"
QUIZ_PYQ = "pyq"
QUIZ_MEGA = "mega"

# ── Badge Definitions ──
BADGES: dict[str, dict] = {
    "quiz_master": {"emoji": "👑", "name": "Quiz Master", "desc": "Score 100% in any quiz (10+ Qs)"},
    "streak_7": {"emoji": "🔥", "name": "7-Day Streak", "desc": "Maintain 7-day quiz streak"},
    "streak_30": {"emoji": "⚡", "name": "30-Day Streak", "desc": "Maintain 30-day quiz streak"},
    "speed_demon": {"emoji": "⚡", "name": "Speed Demon", "desc": "Answer 5 questions in <5s each"},
    "first_quiz": {"emoji": "🌟", "name": "First Steps", "desc": "Complete your first quiz"},
    "topper_daily": {"emoji": "🥇", "name": "Daily Topper", "desc": "Rank #1 on daily leaderboard"},
    "mega_winner": {"emoji": "🏆", "name": "Mega Quiz Champion", "desc": "Win Sunday Mega Quiz"},
    "referral_king": {"emoji": "🤝", "name": "Referral King", "desc": "Refer 10+ active friends"},
    "xp_500": {"emoji": "💎", "name": "XP Collector", "desc": "Accumulate 500+ XP"},
    "xp_1000": {"emoji": "🏅", "name": "XP Legend", "desc": "Accumulate 1000+ XP"},
}

# ── Motivational Quotes (Hindi + English) ──
WELCOME_QUOTES = [
    "Dream big, work hard, stay focused.",
    "Success is not final, failure is not fatal.",
    "CA ka sapna dekho, mehnat karo, result apne aap aayega.",
    "Every expert was once a beginner.",
    "Mushkilein insaan ko mazboot banati hain.",
    "The only way to do great work is to love what you do.",
    "Consistency is the key to success.",
    "CA Foundation is just the beginning of your journey.",
    "Padhai ka koi shortcut nahi hota, lekin mehnat zaroori hai.",
    "Believe you can and you're halfway there.",
    "Koshish karo, mehnat karo, result apne aap aayega.",
    "Hard work beats talent when talent doesn't work hard.",
    "Sapne wo nahi jo neend mein aaye, sapne wo hain jo neend na aane de.",
    "Your limitation—it's only your imagination.",
    "Thoda aur mehnat, CA ki tayyari mein aage badho!",
    "The future belongs to those who believe in the beauty of their dreams.",
    "Har bada kaam chhote chhote kadam se shuru hota hai.",
    "Winners never quit, and quitters never win.",
    "Abhi nahi toh kabhi nahi — start karo, CA ban ne ka!",
    "Champions keep playing until they get it right.",
]

SHAYARI_LINES = [
    "MeHNAT Ka PHaal mEetha Hota HaI, PaR PaT A nE tO DHiRaj Se CHaKhA KaRO",
    "Udne ke liye parwaz ki zaroorat hoti hai, aur CA banne ke liye mehnat ki.",
    "Safar mein thake hua pyala milta hai, manzil unhein milti hai jinke sapno mein jaan hoti hai.",
    "Taqdeer ko badalne ke liye mehnat karo, taqdeer badalne ka koi shortcut nahi hota.",
    "Hausla rakho, waqt badlega. Aaj ki mehnat kal ka result degi.",
    "Jo log raat ko sote hain, woh subah sapne dekhte hain. Jo raat jagte hain, woh subah sapne poore karte hain.",
    "Mushkilon se bhaagna ek kamzori hai, unse ladna hi sabse badi bahaaduri hai.",
    "Zindagi mein do hi cheezein hain — ya toh tum khud change bano, ya duniya badalne ka intezaar karo.",
    "Kamyaabi un hi ko milti hai jinke sapno mein jaan hoti hai aur mehnat mein asli junoon.",
    "CA ka rasta mushkil hai, lekin manzil khoobsurat hai. Bas ruko mat, chalte raho!",
]

# ── Timers per question type (seconds) ──
TYPE_TIMERS: dict[str, int] = {
    QTYPE_MCQ: 25,
    QTYPE_TRUE_FALSE: 15,
    QTYPE_FILL_BLANK: 45,
    QTYPE_MATCH: 40,
    QTYPE_ONE_WORD: 20,
}

# ── Mega Quiz Structure ──
MEGA_QUIZ_CONFIG = {
    "Accounts": {"questions": 40},
    "Quantitative Aptitude": {"questions": 40},
    "Law": {"questions": 60},
    "Economics": {"questions": 60},
    "break_minutes": 10,
    "total_questions": 200,
}

# ── Days of Week ──
DAYS_OF_WEEK = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

# ── Trial durations (days) ──
TRIAL_DURATIONS = {"1week": 7, "2weeks": 14, "3weeks": 21, "fullfree": 3650}

# ── Feedback messages for correct answers ──
CORRECT_FEEDBACK = [
    ("🌟 Best!", 1),
    ("🔥 Better!", 2),
    ("👍 Good!", 3),
    ("🚀 Very Good!", 4),
    ("🏆 Outstanding!", 5),
]
