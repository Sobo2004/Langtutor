from fastapi import FastAPI, Response, Cookie, HTTPException, Request
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from pathlib import Path
from openai import OpenAI

import os, json, httpx, sqlite3, uuid, random, hashlib, secrets, hmac
import bcrypt
from typing import Optional, Generator
from datetime import date, timedelta, datetime
import re
load_dotenv()
from contextlib import asynccontextmanager

app = FastAPI()


# ---------------- ONBOARDING + RECAP ----------------
# These features are session-based (uses the same session_id cookie as the rest of the app).

def _require_user(session_id: Optional[str]) -> str:
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = get_user_from_session(session_id)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session")
    return user_id

def _ensure_user_columns():
    # Ensures new columns exist on users table (safe to call multiple times)
    con = db()
    cols = {row["name"] for row in con.execute("PRAGMA table_info(users)").fetchall()}
    alters = []
    if "has_completed_onboarding" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN has_completed_onboarding INTEGER DEFAULT 0")
    if "last_recap_date" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN last_recap_date TEXT")
    if "study_reason" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN study_reason TEXT")
    if "study_goal" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN study_goal TEXT")
    if "study_level" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN study_level TEXT")
    if "recap_difficulty_bias" not in cols:
        # -1 easier, 0 neutral, +1 harder
        alters.append("ALTER TABLE users ADD COLUMN recap_difficulty_bias INTEGER DEFAULT 0")
    if "avatar" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN avatar TEXT")
    if "daily_goal" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN daily_goal INTEGER DEFAULT 10")
    if "has_seen_tour" not in cols:
        alters.append("ALTER TABLE users ADD COLUMN has_seen_tour INTEGER DEFAULT 0")
        # Users who signed up before the tour existed aren't shown it automatically
        alters.append("UPDATE users SET has_seen_tour=1 WHERE has_completed_onboarding=1")
    for sql in alters:
        try:
            con.execute(sql)
        except Exception:
            pass
    con.commit()
    con.close()

def _init_recap_tables():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS taught_words (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        word TEXT NOT NULL,
        pronunciation TEXT,
        meaning TEXT,
        lesson TEXT,
        difficulty TEXT,
        language_mode TEXT,
        created_at TEXT,
        UNIQUE(user_id, word, meaning, lesson, difficulty, language_mode)
    );
    CREATE TABLE IF NOT EXISTS recap_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        total_questions INTEGER NOT NULL,
        correct_answers INTEGER NOT NULL,
        score_percentage INTEGER NOT NULL,
        xp_awarded INTEGER NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS recap_feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        rating TEXT NOT NULL, -- too_easy | just_right | too_hard
        comment TEXT,
        created_at TEXT NOT NULL
    );
    """)
    con.commit()
    con.close()

def _extract_taught_word(assistant_text: str):
    """Best-effort extractor for the ONE word/phrase taught in a response.
    Looks for: **WORD** (pronunciation) and a meaning line.
    """
    if not assistant_text:
        return None
    # New format: structured word card
    card = _parse_word_card(assistant_text)
    if card:
        return {"word": str(card["word"]).strip()[:60],
                "pronunciation": str(card.get("pron", "")).strip()[:60],
                "meaning": str(card.get("meaning", "")).strip()[:120]}
    # Prefer the first bolded token/phrase
    m = re.search(r"\*\*([^*]{1,60})\*\*\s*(?:\(([^)]{1,60})\))?", assistant_text)
    if not m:
        return None
    word = m.group(1).strip()
    pron = (m.group(2) or "").strip()
    # Meaning: try to find 'Meaning:' or a dash after the word line
    meaning = ""
    mm = re.search(r"Meaning\s*:\s*([^\n]{1,120})", assistant_text, re.I)
    if mm:
        meaning = mm.group(1).strip()
    else:
        # Try " - meaning" on same line as word
        line = assistant_text.splitlines()[0:6]
        joined = "\n".join(line)
        dm = re.search(r"\*\*[^*]+\*\*[^\n]*[-—]\s*([^\n]{1,120})", joined)
        if dm:
            meaning = dm.group(1).strip()
    return {"word": word, "pronunciation": pron, "meaning": meaning}

def _save_taught_word(user_id: str, assistant_text: str, lesson: str, difficulty: str, language_mode: str):
    item = _extract_taught_word(assistant_text)
    if not item:
        return
    con = db()
    try:
        con.execute(
            """INSERT OR IGNORE INTO taught_words(user_id, word, pronunciation, meaning, lesson, difficulty, language_mode, created_at)
                 VALUES(?,?,?,?,?,?,?,?)""",
            (user_id, item["word"], item.get("pronunciation"), item.get("meaning"), lesson, difficulty, language_mode, date.today().isoformat())
        )
        con.commit()
    finally:
        con.close()

def _pick_recap_questions(user_id: str, n: int = 5):
    """Build MCQs from real taught_words history."""
    con = db()
    rows = con.execute(
        """SELECT word, meaning, lesson, difficulty, language_mode
             FROM taught_words
             WHERE user_id=?
             ORDER BY id DESC
             LIMIT 30""",
        (user_id,)
    ).fetchall()
    con.close()
    items = [{"word": r["word"], "meaning": r["meaning"] or "", "lesson": r["lesson"] or "", "difficulty": r["difficulty"] or "", "language_mode": r["language_mode"] or ""} for r in rows]
    # Filter: must have meaning to make a good MCQ
    items = [x for x in items if x["meaning"].strip()]
    if len(items) < 3:
        return []

    # Choose up to n unique words
    random.shuffle(items)
    chosen = items[:n]

    # Build options pool
    meanings_pool = list({x["meaning"] for x in items})
    questions = []
    for it in chosen:
        correct = it["meaning"]
        distractors = [m for m in meanings_pool if m != correct]
        random.shuffle(distractors)
        opts = [correct] + distractors[:3]
        random.shuffle(opts)
        questions.append({
            "prompt": f"What does '{it['word']}' mean?",
            "word": it["word"],
            "options": opts,
            "answer": correct
        })
    return questions

class OnboardingData(BaseModel):
    reason: str
    goal: str
    level: str
    avatar: Optional[str] = None
    daily_goal: Optional[int] = 10

@app.get("/onboarding/status")
def onboarding_status(session_id: Optional[str] = Cookie(default=None)):
    user_id = _require_user(session_id)
    _ensure_user_columns()
    con = db()
    row = con.execute("SELECT has_completed_onboarding FROM users WHERE id=?", (user_id,)).fetchone()
    con.close()
    return {"show": (row is not None and int(row["has_completed_onboarding"] or 0) == 0)}

@app.get("/tour/status")
def tour_status(session_id: Optional[str] = Cookie(default=None)):
    """Show Mila's website tour to users who finished onboarding but haven't completed/skipped the tour."""
    user_id = _require_user(session_id)
    _ensure_user_columns()
    con = db()
    row = con.execute("SELECT has_completed_onboarding, has_seen_tour FROM users WHERE id=?", (user_id,)).fetchone()
    con.close()
    show = row is not None and int(row["has_completed_onboarding"] or 0) == 1 and int(row["has_seen_tour"] or 0) == 0
    return {"show": show}

@app.post("/tour/done")
def tour_done(session_id: Optional[str] = Cookie(default=None)):
    user_id = _require_user(session_id)
    _ensure_user_columns()
    con = db()
    con.execute("UPDATE users SET has_seen_tour=1 WHERE id=?", (user_id,))
    con.commit()
    con.close()
    return {"ok": True}

@app.post("/onboarding/submit")
def submit_onboarding(data: OnboardingData, session_id: Optional[str] = Cookie(default=None)):
    user_id = _require_user(session_id)
    _ensure_user_columns()
    con = db()
    con.execute(
        """UPDATE users
             SET has_completed_onboarding=1,
                 study_reason=?,
                 study_goal=?,
                 study_level=?,
                 avatar=?,
                 daily_goal=?
             WHERE id=?""",
        (data.reason.strip(), data.goal.strip(), data.level.strip(), data.avatar, data.daily_goal, user_id)
    )
    con.commit()
    con.close()
    return {"success": True}

@app.get("/recap/status")
def recap_status(session_id: Optional[str] = Cookie(default=None)):
    user_id = _require_user(session_id)
    _ensure_user_columns()
    _init_recap_tables()

    today = date.today().isoformat()
    con = db()
    row = con.execute("SELECT last_recap_date FROM users WHERE id=?", (user_id,)).fetchone()
    con.close()
    last = (row["last_recap_date"] if row else None)
    show = (last != today)
    # Only show if we have at least a few taught words
    questions = _pick_recap_questions(user_id, n=3)
    return {"show": (show and len(questions) >= 3), "available": len(questions)}

@app.get("/recap/questions")
def recap_questions(session_id: Optional[str] = Cookie(default=None)):
    user_id = _require_user(session_id)
    _ensure_user_columns()
    _init_recap_tables()
    questions = _pick_recap_questions(user_id, n=5)
    return {"questions": questions}

class RecapPayload(BaseModel):
    answers: list[str]              # selected option texts
    ratings: Optional[str] = None   # too_easy | just_right | too_hard
    comment: Optional[str] = None

@app.post("/recap/submit")
def recap_submit(payload: RecapPayload, session_id: Optional[str] = Cookie(default=None)):
    user_id = _require_user(session_id)
    _ensure_user_columns()
    _init_recap_tables()

    today = date.today().isoformat()
    questions = _pick_recap_questions(user_id, n=max(3, len(payload.answers)))

    # Score
    correct = 0
    total = min(len(questions), len(payload.answers))
    for i in range(total):
        if payload.answers[i] == questions[i]["answer"]:
            correct += 1
    score_pct = int(round((correct / total) * 100)) if total else 0

    # XP reward (tweak as you like)
    xp_awarded = correct * 2
    if score_pct >= 80:
        xp_awarded += 4
    elif score_pct >= 60:
        xp_awarded += 2

    if xp_awarded > 0:
        update_xp(user_id, xp_awarded, "recap")

    # Save recap + mark as done for today
    con = db()
    con.execute("UPDATE users SET last_recap_date=? WHERE id=?", (today, user_id))
    con.execute(
        "INSERT INTO recap_attempts(user_id,total_questions,correct_answers,score_percentage,xp_awarded,created_at) VALUES(?,?,?,?,?,?)",
        (user_id, total, correct, score_pct, xp_awarded, today)
    )

    # Feedback → difficulty scaling
    rating = (payload.ratings or "").strip()
    comment = (payload.comment or "").strip()
    if rating in ("too_easy", "just_right", "too_hard"):
        con.execute(
            "INSERT INTO recap_feedback(user_id,rating,comment,created_at) VALUES(?,?,?,?)",
            (user_id, rating, comment, today)
        )
        # Update bias
        bias_row = con.execute("SELECT recap_difficulty_bias FROM users WHERE id=?", (user_id,)).fetchone()
        bias = int(bias_row["recap_difficulty_bias"] or 0) if bias_row else 0
        if rating == "too_easy" and score_pct >= 70:
            bias = min(2, bias + 1)
        elif rating == "too_hard" or score_pct < 50:
            bias = max(-2, bias - 1)
        else:
            # drift toward 0
            if bias > 0: bias -= 1
            elif bias < 0: bias += 1
        con.execute("UPDATE users SET recap_difficulty_bias=? WHERE id=?", (bias, user_id))

        # Apply to lesson difficulty immediately (light touch)
        st = get_lesson_state(user_id)
        current = st.get("difficulty", "beginner")
        if bias >= 1 and current == "beginner":
            st["difficulty"] = "intermediate"
        elif bias >= 2 and current in ("beginner", "intermediate"):
            st["difficulty"] = "advanced"
        elif bias <= -1 and current == "advanced":
            st["difficulty"] = "intermediate"
        elif bias <= -2 and current in ("advanced", "intermediate"):
            st["difficulty"] = "beginner"
        save_lesson_state(user_id, st)

    con.commit()
    con.close()

    u = get_user(user_id)
    return {
        "success": True,
        "score": {"correct": correct, "total": total, "pct": score_pct},
        "xp_awarded": xp_awarded,
        "progress": {"xp": u["xp"], "level": u["level"], "streak": u["streak"]}
    }

# ---------------- CONFIG ----------------
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "ollama")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


# Mila is the tutor character across the whole app (chat, quiz, voice)
MILA_PERSONA = {
    "ru-en": (
        "Тебя зовут Мила (Mila). Ты дружелюбный, тёплый и весёлый репетитор английского языка в приложении LangTutor. "
        "Говори от первого лица как Мила, хвали за успехи, мягко исправляй ошибки и подбадривай. "
        "Если спрашивают, кто ты — ты Мила, репетитор LangTutor. Не используй эмодзи."
    ),
    "en-ru": (
        "Your name is Mila. You are a warm, upbeat and encouraging Russian tutor in the LangTutor app. "
        "Speak in the first person as Mila, celebrate progress, correct mistakes gently and keep the learner motivated. "
        "If asked who you are, you are Mila, LangTutor's tutor. Do not use emojis."
    ),
}

# New words are sent as a structured card the chat page turns into an interactive
# lesson (word card → quick check → pronunciation practice → reply buttons).
WORD_CARD_FORMAT = {
    "en-ru": """OUTPUT FORMAT — this OVERRIDES any formatting rules above:
When you teach a NEW Russian word or phrase, write ONE short friendly sentence in English, then on its own line a word card exactly like this:
[[WORD {"word": "Спасибо", "pron": "spa-SEE-ba", "meaning": "Thank you", "say": "Спасибо! That's how you say thank you. Listen again: Спасибо. You can use it with anyone, friends or strangers. For example: Спасибо за помощь! Thanks for the help!", "example": "Спасибо за помощь!", "example_meaning": "Thanks for the help!", "check": {"question": "Which one means \\"Thank you\\"?", "options": ["Пожалуйста", "Спасибо", "Привет"], "answer": 1}}]]
Card rules:
- Valid JSON on ONE line. Nothing after the closing ]].
- "say": what you say OUT LOUD while showing the card, like a warm tutor talking to a beginner: 2-4 short spoken sentences in English that include the Russian word (say it twice), when to use it, and the example with its meaning. No emojis, no brackets, no romanisation.
- "check": a quick question about the new word with exactly 3 Russian options, one correct; "answer" is its index (0-2). Vary where the right answer is.
- Do NOT add "try using it in a sentence" — the app runs the practice.
- Never mention the card, JSON or any format in your sentence (never write "Here's the word card").
- One new word per message, never one already taught in this conversation.
When the student asks for the next word, teach it straight away with a card.
When the student is NOT asking for a new word (a question, a practice sentence, "I don't understand", "another example"), reply in short, friendly plain text WITHOUT a word card.
For "another example": write ONE short friendly sentence in English, then on its own line an example card exactly like this (nothing after it):
[[EXAMPLE {"sentence": "Спасибо, что пришёл!", "translation": "Thanks for coming!"}]]""",
    "ru-en": """ФОРМАТ ОТВЕТА — он ВАЖНЕЕ любых правил форматирования выше:
Когда учишь НОВОЕ английское слово или фразу, напиши ОДНО короткое дружелюбное предложение по-русски, а затем отдельной строкой карточку слова точно так:
[[WORD {"word": "Thank you", "pron": "сэнк ю", "meaning": "Спасибо", "say": "Thank you! Так по-английски говорят спасибо. Послушай ещё раз: Thank you. Это можно сказать кому угодно. Например: Thank you for your help! Спасибо за помощь!", "example": "Thank you for your help!", "example_meaning": "Спасибо за помощь!", "check": {"question": "Что значит «Спасибо» по-английски?", "options": ["Please", "Thank you", "Hello"], "answer": 1}}]]
Правила карточки:
- Корректный JSON в ОДНУ строку. После ]] ничего не пиши.
- "say": что ты говоришь ВСЛУХ, показывая карточку, как тёплый репетитор новичку: 2-4 коротких разговорных предложения по-русски, где английское слово звучит дважды, сказано когда его использовать, и пример с переводом. Без эмодзи, скобок и транскрипции.
- "check": быстрый вопрос по новому слову, ровно 3 варианта на английском, один правильный; "answer" — его индекс (0-2). Меняй позицию правильного ответа.
- НЕ добавляй «попробуй составить предложение» — практику проводит приложение.
- Никогда не упоминай карточку, JSON или формат (не пиши «вот карточка слова»).
- Одно новое слово за сообщение, никогда не повторяй уже изученные в этом разговоре.
Когда студент просит следующее слово — сразу учи его с карточкой.
Если студент НЕ просит новое слово (вопрос, своё предложение, «не понимаю», «ещё пример»), отвечай коротко и дружелюбно обычным текстом БЕЗ карточки слова.
На «ещё пример»: напиши ОДНО короткое дружелюбное предложение по-русски, а затем отдельной строкой карточку примера точно так (после неё ничего):
[[EXAMPLE {"sentence": "Thank you for coming!", "translation": "Спасибо, что пришёл!"}]]""",
}

# Added to the student's message so the reply buttons get the right kind of answer
CHAT_INTENT_NOTES = {
    "en-ru": {
        "default": "(If you teach a new word, you must include the [[WORD ...]] card.)",
        "next": "(The student wants the NEXT new word: teach one new word now, with a [[WORD ...]] card.)",
        "example": "(Give ONE new example sentence using the word the student mentions, as an [[EXAMPLE ...]] card with its English translation. Do NOT teach a new word and do NOT include a [[WORD ...]] card.)",
        "explain": "(Explain the word the student mentions more simply, in 2-3 short sentences, maybe with a memory tip. Do NOT teach a new word and do NOT include a card.)",
        "build": "(Give the student ONE new sentence to build for the grammar point they mention: one short encouraging sentence, then on its own line [[BUILD {\"translation\": \"<English meaning>\", \"parts\": [{\"t\": \"<Russian block>\", \"role\": \"subject\"}, ...]}]] with 3-6 blocks in the neutral order. No other card.)",
    },
    "ru-en": {
        "default": "(Если учишь новое слово — обязательно добавь карточку [[WORD ...]].)",
        "next": "(Студент хочет СЛЕДУЮЩЕЕ новое слово: научи одному новому слову сейчас, с карточкой [[WORD ...]].)",
        "example": "(Дай ОДИН новый пример предложения с упомянутым словом в виде карточки [[EXAMPLE ...]] с переводом на русский. НЕ учи новое слово и НЕ добавляй карточку [[WORD ...]].)",
        "explain": "(Объясни упомянутое слово проще, в 2-3 коротких предложениях, можно с подсказкой для запоминания. НЕ учи новое слово и НЕ добавляй карточку.)",
        "build": "(Дай студенту ОДНО новое предложение для сборки по упомянутой теме грамматики: одна короткая ободряющая фраза, затем отдельной строкой [[BUILD {\"translation\": \"<перевод на русский>\", \"parts\": [{\"t\": \"<английский блок>\", \"role\": \"subject\"}, ...]}]] из 3-6 блоков. Других карточек не добавляй.)",
    },
}

# Grammar lessons: Mila's "Colour Blocks" method. Every sentence is made of coloured
# blocks (one colour per part of speech); the chat page draws them and runs a
# sentence builder where the learner taps the blocks into the right order.
_ROLES = "subject, verb, object, adjective, adverb, article, pronoun, preposition, place, time, question, negation, connector, other"
GRAMMAR_CARD_FORMAT = {
    "ru-en": f"""GRAMMAR LESSON FORMAT (Mila's Colour Blocks method). Teach ENGLISH grammar to a Russian speaker in detail, step by step, like a patient tutor, always comparing with Russian: what is the same, what is different, and the simple pattern for building sentences. Every sentence is built from coloured blocks; block roles are: {_ROLES}.
Write ONE short friendly sentence in Russian, then on its own line a grammar card like this example (valid JSON on ONE line, nothing after it):
[[GRAMMAR {{"title": "Существительные в английском", "explain": "В английском у существительных нет рода и нет падежей, поэтому они почти не меняются. Зато перед ними обычно стоит артикль a/an или the, которого в русском нет.", "points": [{{"head": "Нет рода", "text": "table, book, window — просто 'it', без мужского и женского рода", "examples": "a table, a book, a window"}}, {{"head": "Множественное число", "text": "обычно добавляем -s или -es", "examples": "cats, books, boxes"}}, {{"head": "Артикли", "text": "a/an — какой-то один предмет, the — конкретный, известный", "examples": "a cat, the cat"}}], "rule": [{{"t": "Article", "role": "article"}}, {{"t": "Noun", "role": "subject"}}, {{"t": "Verb", "role": "verb"}}], "compare": {{"target": "I see a cat. The cat is black.", "native": "Я вижу кошку. Кошка чёрная.", "note": "По-русски «кошку» меняет окончание, а в английском cat не меняется — его роль показывает место в предложении и артикль."}}, "examples": [{{"parts": [{{"t": "The dog", "role": "subject"}}, {{"t": "likes", "role": "verb"}}, {{"t": "the ball", "role": "object"}}], "translation": "Собака любит мяч.", "note": "the dog и the ball не меняются, хотя в русском было бы «собака» и «мяч»."}}, {{"parts": [{{"t": "I", "role": "pronoun"}}, {{"t": "have", "role": "verb"}}, {{"t": "two cats", "role": "object"}}], "translation": "У меня две кошки.", "note": "Множественное число: cat → cats, просто добавили -s."}}, {{"parts": [{{"t": "An apple", "role": "subject"}}, {{"t": "is", "role": "verb"}}, {{"t": "on the table", "role": "place"}}], "translation": "Яблоко на столе.", "note": "an перед гласным звуком (an apple), a перед согласным (a table)."}}], "tip": "Запомни: английское существительное почти никогда не меняется — меняются только -s во множественном числе и артикль перед ним.", "check": {{"question": "Как правильно: «Я вижу кошку»?", "options": ["I see cats a.", "I see a cat.", "I a cat see."], "answer": 1}}, "build": {{"translation": "У моего брата есть собака.", "parts": [{{"t": "My brother", "role": "subject"}}, {{"t": "has", "role": "verb"}}, {{"t": "a dog", "role": "object"}}]}}}}]]
Rules:
- Explanations, "points" text, notes, tip and translations in Russian; "points" examples, "rule" blocks, "compare.target", example "parts", "check" options and "build" parts in English.
- "explain": 2-3 clear sentences. "points": 2-4 key rules, each with real examples. "examples": exactly 3 sentences, each with a "note" explaining WHY it is built that way. "tip": one memory trick.
- "rule" is the sentence PATTERN for this lesson as 2-6 blocks (e.g. Subject + Verb + Object, Article + Noun, Subject + do/does + not + Verb) — never a list of categories.
- Give every block its true role; use "other" only when nothing else fits. "parts" in order make the full sentence.
- "build": 3-6 blocks with exactly one correct order. Never mention the card or JSON.
- The card above only shows the FORMAT: write fresh content for the lesson you are teaching and never copy its sentences or examples.""",
    "en-ru": f"""GRAMMAR LESSON FORMAT (Mila's Colour Blocks method). Teach RUSSIAN grammar to an English speaker in detail, step by step, like a patient tutor, always comparing with English: what is the same, what is different, and the simple pattern for building sentences. Every sentence is built from coloured blocks; block roles are: {_ROLES}.
Write ONE short friendly sentence in English, then on its own line a grammar card like this example (valid JSON on ONE line, nothing after it):
[[GRAMMAR {{"title": "Russian nouns have gender", "explain": "Every Russian noun is masculine, feminine or neuter. English nouns have no gender, so this is new for you. The good news: the last letter of the word usually tells you the gender.", "points": [{{"head": "Masculine", "text": "usually ends in a consonant", "examples": "стол, дом, брат"}}, {{"head": "Feminine", "text": "usually ends in -а or -я", "examples": "книга, мама, неделя"}}, {{"head": "Neuter", "text": "usually ends in -о or -е", "examples": "окно, море, молоко"}}], "rule": [{{"t": "Adjective", "role": "adjective"}}, {{"t": "Noun", "role": "subject"}}, {{"t": "Verb", "role": "verb"}}], "compare": {{"target": "Новый стол. Новая книга. Новое окно.", "native": "A new table. A new book. A new window.", "note": "In Russian the adjective changes its ending to match the noun's gender; in English 'new' never changes."}}, "examples": [{{"parts": [{{"t": "Мой брат", "role": "subject"}}, {{"t": "читает", "role": "verb"}}, {{"t": "книгу", "role": "object"}}], "translation": "My brother is reading a book.", "note": "брат is masculine (ends in a consonant); книга is feminine and becomes книгу because it is the object."}}, {{"parts": [{{"t": "Новое", "role": "adjective"}}, {{"t": "окно", "role": "subject"}}, {{"t": "очень большое", "role": "adjective"}}], "translation": "The new window is very big.", "note": "окно is neuter (-о), so both adjectives end in -ое."}}, {{"parts": [{{"t": "Мама", "role": "subject"}}, {{"t": "любит", "role": "verb"}}, {{"t": "кофе", "role": "object"}}], "translation": "Mum loves coffee.", "note": "мама ends in -а like a feminine noun; кофе is a famous exception: it is masculine."}}], "tip": "Look at the last letter: a consonant means 'he', -а or -я means 'she', -о or -е means 'it'.", "check": {{"question": "Which noun is feminine?", "options": ["стол", "книга", "окно"], "answer": 1}}, "build": {{"translation": "My sister has a new car.", "parts": [{{"t": "У моей сестры", "role": "subject"}}, {{"t": "есть", "role": "verb"}}, {{"t": "новая машина", "role": "object"}}]}}}}]]
Rules:
- Explanations, "points" text, notes, tip and translations in English; "points" examples, "rule" blocks may be English labels, "compare.target", example "parts", "check" options and "build" parts in Russian.
- "explain": 2-3 clear sentences. "points": 2-4 key rules, each with real examples. "examples": exactly 3 sentences, each with a "note" explaining WHY it is built that way. "tip": one memory trick.
- "rule" is the sentence PATTERN for this lesson as 2-6 blocks (e.g. Subject + Verb + Object, Adjective + Noun) — never a list of categories.
- Give every block its true role; use "other" only when nothing else fits. "parts" in order make the full sentence. "build" uses the neutral, most natural order, 3-6 blocks.
- Never mention the card or JSON.
- The card above only shows the FORMAT: write fresh content for the lesson you are teaching and never copy its sentences or examples.""",
}

_GRAMMAR_CARD_RE = re.compile(r"\[\[GRAMMAR\s*(\{.*\})\s*\]\]", re.S)

def _parse_grammar_card(text: str) -> Optional[dict]:
    m = _GRAMMAR_CARD_RE.search(text or "")
    if not m:
        return None
    try:
        card = json.loads(m.group(1))
    except Exception:
        return None
    return card if isinstance(card, dict) and str(card.get("title", "")).strip() else None

# Added to the student's message when the course decides which word comes next
COURSE_NOTES = {
    "en-ru": {
        "teach": "(Course lesson, topic «{topic}». Teach EXACTLY this next item now: «{word}» (meaning: {meaning}), with a [[WORD ...]] card whose \"word\" is exactly «{word}». Teach nothing else.)",
        "topic_done": "(The student has just learnt every word in the topic «{topic}». Congratulate them warmly in 1-2 sentences and tell them they can take the final quiz or start the next topic. Do NOT teach a new word and do NOT include a card.)",
        "grammar": "(Course grammar lesson, topic «{topic}»: «{title}». Cover: {focus} Teach it now with a [[GRAMMAR ...]] card using the Colour Blocks method. Teach nothing else.)",
    },
    "ru-en": {
        "teach": "(Урок курса, тема «{topic}». Научи РОВНО этому следующему слову: «{word}» (значение: {meaning}), с карточкой [[WORD ...]], где \"word\" — ровно «{word}». Больше ничему не учи.)",
        "topic_done": "(Студент выучил все слова темы «{topic}». Тепло поздравь его в 1-2 предложениях и скажи, что можно пройти итоговый тест или начать следующую тему. НЕ учи новое слово и НЕ добавляй карточку.)",
        "grammar": "(Урок грамматики курса, тема «{topic}»: «{title}». Содержание: {focus} Объясни это сейчас с карточкой [[GRAMMAR ...]] по методу цветных блоков. Больше ничему не учи.)",
    },
}

_WORD_CARD_RE = re.compile(r"\[\[WORD\s*(\{.*\})\s*\]\]", re.S)

def _parse_word_card(text: str) -> Optional[dict]:
    m = _WORD_CARD_RE.search(text or "")
    if not m:
        return None
    try:
        card = json.loads(m.group(1))
    except Exception:
        return None
    return card if isinstance(card, dict) and str(card.get("word", "")).strip() else None

OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1:8b")
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")

# ---------------- EMAIL ----------------
SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER     = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_FROM     = os.getenv("SMTP_FROM", SMTP_USER)

def send_email(to_email: str, subject: str, body_html: str):
    """Send an email via SMTP. Falls back to console log if not configured."""
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText as _MIMEText

    if not SMTP_USER or not SMTP_PASSWORD:
        print(f"\n[DEV EMAIL] To: {to_email}\nSubject: {subject}\n{body_html}\n")
        return

    msg = MIMEMultipart("alternative")
    msg["From"]    = SMTP_FROM
    msg["To"]      = to_email
    msg["Subject"] = subject
    msg.attach(_MIMEText(body_html, "html"))

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(SMTP_USER, SMTP_PASSWORD)
        server.sendmail(SMTP_FROM, to_email, msg.as_string())

# ---------------- FRONTEND ----------------

BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend"

# ✅ because your JS/CSS are inside frontend/ directly
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")

@app.middleware("http")
async def revalidate_static(request, call_next):
    """Make browsers check for updated JS/CSS instead of running a stale cached copy."""
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response

def _versioned_page(filename: str) -> HTMLResponse:
    """Serve an HTML page with its /static/*.js and *.css URLs versioned by file
    modification time, so browsers never run a stale cached copy."""
    html = (FRONTEND_DIR / filename).read_text(encoding="utf-8")

    def stamp(m):
        asset = FRONTEND_DIR / m.group(2)
        version = int(asset.stat().st_mtime) if asset.exists() else 0
        return f'{m.group(1)}="/static/{m.group(2)}?v={version}"'

    html = re.sub(r'(src|href)="/static/([\w.-]+\.(?:js|css))(?:\?v=[^"]*)?"', stamp, html)
    return HTMLResponse(html, headers={"Cache-Control": "no-cache"})

@app.get("/")
def home():
    return _versioned_page("index.html")

@app.get("/api/version")
def api_version():
    """Changes whenever a frontend file changes, so open pages can offer a refresh."""
    files = [f for f in FRONTEND_DIR.iterdir() if f.suffix in (".js", ".css", ".html")]
    return {"version": max(int(f.stat().st_mtime) for f in files)}

@app.get("/admin", response_class=HTMLResponse)
def admin_page():
    try:
        admin_html_path = FRONTEND_DIR / "admin.html"
        if not admin_html_path.exists():
            return HTMLResponse(content="<h1>Admin panel files not found.</h1>", status_code=404)
        return admin_html_path.read_text(encoding="utf-8")
    except Exception as e:
        return HTMLResponse(content=f"<h1>Error: {str(e)}</h1>", status_code=500)

@app.get("/favicon.ico")
def favicon():
    return FileResponse(FRONTEND_DIR / "favicon.ico")

# ---------------- DB ----------------
DB_PATH = Path(os.getenv("LANGTUTOR_DB", str(BASE_DIR / "app.db")))  # tests use a temporary database

def db():
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con

def hash_password(password: str) -> str:
    """bcrypt: salted and deliberately slow, so leaked hashes are hard to crack."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")

def verify_password(password: str, stored: str):
    """Returns (matches, needs_upgrade). Accounts created before bcrypt stored an
    unsalted SHA-256 hash (or, earlier still, plain text); those still log in and are
    upgraded to bcrypt on their next successful login."""
    stored = stored or ""
    if stored.startswith("$2"):
        try:
            return bcrypt.checkpw(password.encode("utf-8"), stored.encode("ascii")), False
        except ValueError:
            return False, False
    legacy_sha = hashlib.sha256(password.encode("utf-8")).hexdigest()
    ok = hmac.compare_digest(stored, legacy_sha) or hmac.compare_digest(stored, password)
    return ok, ok

# ---------------- RATE LIMITS ----------------
# Sliding-window limits kept in memory (per server process). They stop one user from
# running up the OpenAI bill and slow down password guessing.
RATE_LIMITS = {
    "auth": (10, 60),     # sign-up / login / password reset attempts per IP per minute
    "chat": (20, 60),     # messages to Mila per user per minute
    "quiz": (40, 60),     # quiz batches per user per minute (one quiz = up to 8 batches)
    "tts": (150, 60),     # voice clips per user per minute (a grammar lesson can need ~30)
}
_rate_hits: dict = {}

def rate_limit(bucket: str, key: str):
    limit, window = RATE_LIMITS[bucket]
    now = datetime.now().timestamp()
    hits = [t for t in _rate_hits.get((bucket, key), []) if now - t < window]
    if len(hits) >= limit:
        retry = int(window - (now - hits[0])) + 1
        raise HTTPException(status_code=429, detail="Too many requests, please slow down.",
                            headers={"Retry-After": str(retry)})
    hits.append(now)
    _rate_hits[(bucket, key)] = hits

def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"

def check_password_rules(password: str):
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if len(password.encode("utf-8")) > 72:   # bcrypt's limit
        raise HTTPException(status_code=400, detail="Password is too long (max 72 bytes)")

def init_db():
    con = db()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        username TEXT UNIQUE,
        password TEXT,
        email TEXT,
        xp INTEGER DEFAULT 0,
        streak INTEGER DEFAULT 0,
        last_active TEXT,
        level TEXT DEFAULT 'A1',
        current_lesson TEXT,
        step INTEGER DEFAULT 0,
        created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS xp_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT, ts TEXT, xp_delta INTEGER, xp_total INTEGER, event TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS sessions (
        session_id TEXT PRIMARY KEY, user_id TEXT, created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS chat_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT, role TEXT, content TEXT, timestamp TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS admins (
        id TEXT PRIMARY KEY, username TEXT UNIQUE, password TEXT, created_at TEXT
    );
    CREATE TABLE IF NOT EXISTS admin_sessions (
        session_id TEXT PRIMARY KEY, admin_id TEXT, created_at TEXT,
        FOREIGN KEY(admin_id) REFERENCES admins(id)
    );
    CREATE TABLE IF NOT EXISTS quiz_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT,
        category TEXT,
        difficulty TEXT,
        language_mode TEXT,
        total_questions INTEGER,
        correct_answers INTEGER,
        score_percentage INTEGER,
        time_taken INTEGER,
        created_at TEXT,
        FOREIGN KEY(user_id) REFERENCES users(id)
    );
    CREATE TABLE IF NOT EXISTS password_reset_otps (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL,
        code TEXT NOT NULL,
        expires_at TEXT NOT NULL,
        used INTEGER DEFAULT 0
    );
    """)
    # Admin password comes from ADMIN_PASSWORD in .env. Without it, a random one is
    # generated for a new database and printed once to the server console.
    env_admin_password = os.getenv("ADMIN_PASSWORD", "").strip()
    existing_admin = con.execute("SELECT id, password FROM admins WHERE username='admin'").fetchone()
    if not existing_admin:
        admin_password = env_admin_password or secrets.token_urlsafe(12)
        if not env_admin_password:
            print(f"\n*** Admin account created: username 'admin', password '{admin_password}'. "
                  f"Set ADMIN_PASSWORD in .env to choose your own. ***\n")
        con.execute("INSERT INTO admins(id, username, password, created_at) VALUES(?,?,?,?)",
                    (str(uuid.uuid4()), "admin", hash_password(admin_password), date.today().isoformat()))
    elif env_admin_password and not verify_password(env_admin_password, existing_admin["password"])[0]:
        # ADMIN_PASSWORD changed in .env: apply it
        con.execute("UPDATE admins SET password=? WHERE id=?", (hash_password(env_admin_password), existing_admin["id"]))
    con.commit()
    con.close()

init_db()
# Migrate DB for onboarding/recap reminders (safe no-op if already applied)
try:
    _ensure_user_columns()
    _init_recap_tables()
except Exception as _e:
    pass

# ============== SIMPLE AUTH ==============
class SignupRequest(BaseModel):
    username: str
    password: str
    email: Optional[str] = None

class LoginRequest(BaseModel):
    username: str
    password: str

@app.post("/auth/signup")
def signup(req: SignupRequest, request: Request):
    rate_limit("auth", client_ip(request))
    con = db()
    try:
        existing = con.execute("SELECT 1 FROM users WHERE username=?", (req.username,)).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="Username already exists")
        check_password_rules(req.password)

        user_id = str(uuid.uuid4())
        password_hash = hash_password(req.password)
        today = date.today().isoformat()

        con.execute(
            "INSERT INTO users(id, username, password, email, created_at, last_active) VALUES(?,?,?,?,?,?)",
            (user_id, req.username, password_hash, req.email, today, today)
        )
        con.commit()
        return {"success": True, "message": "Account created! Please login."}
    except HTTPException as e:
        raise e
    except Exception as e:
        con.rollback()
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        con.close()

@app.post("/auth/login")
def login(req: LoginRequest, response: Response, request: Request):
    """Checks the password with bcrypt; older SHA-256/plain-text accounts are
    upgraded to bcrypt on a successful login."""
    rate_limit("auth", client_ip(request))
    con = db()
    try:
        user = con.execute(
            "SELECT id, username, password FROM users WHERE username=?",
            (req.username,)
        ).fetchone()

        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password")

        ok, needs_upgrade = verify_password(req.password, user["password"])
        if ok and needs_upgrade:
            con.execute("UPDATE users SET password=? WHERE id=?", (hash_password(req.password), user["id"]))

        if not ok:
            raise HTTPException(status_code=401, detail="Invalid username or password")

        session_id = str(uuid.uuid4())
        today = date.today().isoformat()

        con.execute(
            "INSERT INTO sessions(session_id, user_id, created_at) VALUES(?,?,?)",
            (session_id, user["id"], today)
        )
        con.execute("UPDATE users SET last_active=? WHERE id=?", (today, user["id"]))
        con.commit()

        response.set_cookie(
            "session_id",
            session_id,
            httponly=True,
            samesite="lax",
            max_age=30 * 24 * 60 * 60,
            path="/",
        )

        return {"success": True, "message": "Login successful", "username": user["username"]}
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        con.close()

@app.post("/auth/logout")
def logout(response: Response, session_id: Optional[str] = Cookie(default=None)):
    if session_id:
        con = db()
        con.execute("DELETE FROM sessions WHERE session_id=?", (session_id,))
        con.commit()
        con.close()
    response.delete_cookie("session_id", path="/")
    return {"success": True}

class ForgotPasswordRequest(BaseModel):
    email: str

class ResetPasswordRequest(BaseModel):
    email: str
    code: str
    new_password: str

class ResendOTPRequest(BaseModel):
    email: str
    purpose: str = "forgot_password"

@app.post("/auth/forgot-password")
def forgot_password(req: ForgotPasswordRequest, request: Request):
    rate_limit("auth", client_ip(request))
    return _issue_reset_code(req.email.strip().lower())

def _issue_reset_code(email: str):
    """Create a 10-minute reset code and email it (or return it in dev mode, when SMTP isn't set up)."""
    con = db()
    user = con.execute("SELECT id FROM users WHERE LOWER(email)=?", (email,)).fetchone()
    if not user:
        con.close()
        # Return success to avoid email enumeration
        return {"success": True, "message": "If that email exists, a code has been sent."}

    # Generate 6-digit OTP
    code = f"{secrets.randbelow(1_000_000):06d}"   # cryptographically secure, always 6 digits
    expires_at = (datetime.utcnow() + timedelta(minutes=10)).isoformat()

    # Invalidate old OTPs for this email
    con.execute("UPDATE password_reset_otps SET used=1 WHERE email=?", (email,))
    con.execute(
        "INSERT INTO password_reset_otps (email, code, expires_at) VALUES (?,?,?)",
        (email, code, expires_at)
    )
    con.commit()
    con.close()

    subject = "LangTutor — Your password reset code"
    body = f"""
    <div style="font-family:Inter,sans-serif;max-width:480px;margin:0 auto;padding:32px;background:#f5f7fa;">
      <div style="background:#fff;border-radius:14px;padding:32px;box-shadow:0 2px 10px rgba(0,0,0,0.07);">
        <h2 style="color:#667eea;margin-top:0;">🔒 Reset Your Password</h2>
        <p style="color:#555;">Use the code below to reset your LangTutor password. It expires in <strong>10 minutes</strong>.</p>
        <div style="background:#f0f2ff;border-radius:10px;padding:24px;text-align:center;margin:24px 0;">
          <span style="font-size:36px;font-weight:700;letter-spacing:8px;color:#667eea;">{code}</span>
        </div>
        <p style="color:#888;font-size:13px;">If you didn't request this, you can safely ignore this email.</p>
      </div>
    </div>
    """
    dev_mode = not (SMTP_USER and SMTP_PASSWORD)
    if dev_mode:
        print(f"\n[DEV EMAIL] To: {email} | OTP: {code}\n")
        return {"success": True, "message": "Code sent.", "dev_code": code}

    try:
        send_email(email, subject, body)
    except Exception as e:
        print(f"Email send error: {e}")
        raise HTTPException(status_code=500, detail="Failed to send email. Please try again.")

    return {"success": True, "message": "Code sent."}

@app.post("/auth/resend-otp")
def resend_otp(req: ResendOTPRequest, request: Request):
    rate_limit("auth", client_ip(request))
    email = req.email.strip().lower()
    con = db()
    user = con.execute("SELECT id FROM users WHERE LOWER(email)=?", (email,)).fetchone()
    con.close()
    if not user:
        return {"success": True}  # silent — don't leak email existence

    # Same as forgot-password (the rate limit above already counted this request)
    return _issue_reset_code(email)

@app.post("/auth/reset-password")
def reset_password(req: ResetPasswordRequest, request: Request):
    rate_limit("auth", client_ip(request))
    email = req.email.strip().lower()
    code  = req.code.strip()

    if len(req.new_password) < 8:
        raise HTTPException(status_code=400, detail="Password must be at least 8 characters")

    con = db()
    row = con.execute(
        """SELECT id, expires_at, used FROM password_reset_otps
           WHERE email=? AND code=?
           ORDER BY id DESC LIMIT 1""",
        (email, code)
    ).fetchone()

    if not row:
        con.close()
        raise HTTPException(status_code=400, detail="Invalid code. Please check and try again.")
    if row["used"]:
        con.close()
        raise HTTPException(status_code=400, detail="This code has already been used.")
    if datetime.utcnow() > datetime.fromisoformat(row["expires_at"]):
        con.close()
        raise HTTPException(status_code=400, detail="Code has expired. Please request a new one.")

    check_password_rules(req.new_password)
    new_hash = hash_password(req.new_password)
    con.execute("UPDATE users SET password=? WHERE LOWER(email)=?", (new_hash, email))
    con.execute("UPDATE password_reset_otps SET used=1 WHERE email=? AND code=?", (email, code))
    con.commit()
    con.close()

    return {"success": True, "message": "Password updated successfully."}

@app.get("/auth/check")
def check_auth(session_id: Optional[str] = Cookie(default=None)):
    if not session_id:
        return {"authenticated": False}
    user_id = get_user_from_session(session_id)
    if not user_id:
        return {"authenticated": False}
    u = get_user(user_id)
    if u:
        return {
            "authenticated": True,
            "username": u["username"],
            "email": u["email"] if "email" in u.keys() else "",
            "xp": u["xp"],
            "level": u["level"],
            "streak": u["streak"],
            "created_at": u["created_at"] if "created_at" in u.keys() else "",
            "avatar": u["avatar"] if "avatar" in u.keys() else None
        }
    return {"authenticated": False}

def get_user_from_session(session_id: str) -> Optional[str]:
    con = db()
    row = con.execute("SELECT user_id FROM sessions WHERE session_id=?", (session_id,)).fetchone()
    con.close()
    return row["user_id"] if row else None

def get_user(user_id: str):
    con = db()
    row = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    con.close()
    return row

# ═══════════════════════════════════════════════════════════════════
# Dynamic content generation for personalized learning
# based on conversation history and the selected topic/difficulty.
# ═══════════════════════════════════════════════════════════════════

# ---------------- HELPERS ----------------
def update_xp(user_id: str, delta: int, event="xp"):
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    con = db()
    u = con.execute("SELECT xp, streak, last_active FROM users WHERE id=?", (user_id,)).fetchone()
    xp = (u["xp"] if u else 0) + delta
    
    # Better level calculation
    if xp < 100:
        level = "A1"
    elif xp < 300:
        level = "A2"
    elif xp < 600:
        level = "B1"
    elif xp < 1000:
        level = "B2"
    elif xp < 1500:
        level = "C1"
    else:
        level = "C2"

    # Streak logic
    streak = u["streak"] if u else 0
    last_active = u["last_active"] if u else None

    if last_active == today:
        pass  # already active today, streak unchanged
    elif last_active == yesterday:
        streak += 1  # active yesterday → extend streak
        print(f"✅ Streak increased to {streak} for user {user_id}")
    else:
        streak = 1  # missed a day → reset to 1
        print(f"🔄 Streak reset to 1 for user {user_id} (was inactive)")

    con.execute(
        "UPDATE users SET xp=?, level=?, streak=?, last_active=? WHERE id=?",
        (xp, level, streak, today, user_id)
    )
    con.execute(
        "INSERT INTO xp_log(user_id, ts, xp_delta, xp_total, event) VALUES(?,?,?,?,?)",
        (user_id, today, delta, xp, event)
    )
    con.commit()
    con.close()

def save_chat_message(user_id: str, role: str, content: str):
    today = date.today().isoformat()
    con = db()
    con.execute(
        "INSERT INTO chat_history(user_id, role, content, timestamp) VALUES(?,?,?,?)",
        (user_id, role, content, today)
    )
    con.commit()
    con.close()

def get_chat_history(user_id: str, limit: int = 10):
    con = db()
    rows = con.execute(
        "SELECT role, content FROM chat_history WHERE user_id=? ORDER BY id DESC LIMIT ?",
        (user_id, limit)
    ).fetchall()
    con.close()
    # Reverse to get chronological order
    messages = [{"role": row["role"], "content": row["content"]} for row in reversed(rows)]
    return messages

# ---------------- LESSON STATE ----------------
# Stored as JSON in users.current_lesson column:
#   { "lesson": "greetings", "word_idx": 0, "stage": "learn", "attempts": 0, "difficulty": "beginner" }

def get_lesson_state(user_id: str) -> dict:
    con = db()
    row = con.execute("SELECT current_lesson FROM users WHERE id=?", (user_id,)).fetchone()
    con.close()
    raw = row["current_lesson"] if row and row["current_lesson"] else None
    if raw:
        try:
            state = json.loads(raw)
            # Add difficulty if not present (for backwards compatibility)
            if "difficulty" not in state:
                state["difficulty"] = "beginner"
            return state
        except:
            pass
    # Default: start at greetings, word 0, learn stage, beginner difficulty
    return {"lesson": "greetings", "word_idx": 0, "stage": "learn", "attempts": 0, "difficulty": "beginner"}

def save_lesson_state(user_id: str, state: dict):
    con = db()
    con.execute("UPDATE users SET current_lesson=? WHERE id=?", (json.dumps(state), user_id))
    con.commit()
    con.close()

# Content is generated dynamically based on user progress

# ---------------- LLM ----------------
_openai_client = None
def openai_client():
    global _openai_client
    if not _openai_client:
        _openai_client = OpenAI(api_key=OPENAI_API_KEY)
    return _openai_client

def llm_complete(system_prompt: str, user_prompt: str) -> str:
    """Non-streaming single-turn LLM call. Returns the full response text."""
    if LLM_PROVIDER == "openai":
        resp = openai_client().chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt}
            ],
            max_tokens=80,
            temperature=0
        )
        return resp.choices[0].message.content.strip()
    else:
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt}
            ],
            "stream": False
        }
        with httpx.Client(timeout=30) as c:
            resp = c.post(f"{OLLAMA_URL}/api/chat", json=payload)
            return resp.json().get("message", {}).get("content", "").strip()

def llm_stream(system_prompt, messages):
    """
    messages should be a list of dicts: [{"role": "user", "content": "..."}, ...]
    """
    if LLM_PROVIDER == "openai":
        try:
            # Build message list with system prompt
            api_messages = [{"role":"system","content":system_prompt}]
            api_messages.extend(messages)
            
            stream = openai_client().chat.completions.create(
            model=OPENAI_MODEL,
            messages=api_messages,
            max_tokens=1800,   # grammar lessons are long cards
            temperature=0.6,
            stream=True
            )

            full=""
            for chunk in stream:
                if chunk.choices[0].delta.content:
                    text = chunk.choices[0].delta.content
                    full += text
                    yield sse("delta",{"text":text})
            yield sse("done",{"text":full})
        except Exception as e:
            print(f"OpenAI Error: {e}")
            yield sse("done",{"text":"Sorry, I encountered an error. Please try again."})
    else:
        # For Ollama
        api_messages = [{"role":"system","content":system_prompt}]
        api_messages.extend(messages)
        
        payload={
            "model":OLLAMA_MODEL,
            "messages":api_messages,
            "stream":True
        }
        with httpx.Client(timeout=120) as c:
            with c.stream("POST",f"{OLLAMA_URL}/api/chat",json=payload) as r:
                full=""
                for line in r.iter_lines():
                    if not line: continue
                    d=json.loads(line)
                    t=d.get("message",{}).get("content","")
                    if t:
                        full+=t
                        yield sse("delta",{"text":t})
                yield sse("done",{"text":full})

def sse(event,data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"

# ---------------- API ----------------
class ChatRequest(BaseModel):
    message: str
    language_mode: Optional[str] = 'en-ru'
    difficulty: Optional[str] = None
    intent: Optional[str] = None   # set by the chat's reply buttons: next | example | explain
    topic: Optional[str] = None    # course topic picked in the sidebar


def extract_difficulty(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"\bdifficulty\s*=\s*(beginner|intermediate|advanced)\b", text, re.I)
    if m:
        return m.group(1).lower()
    return None

# ================== COURSE (fixed word lists per topic, see course.json) ==================
COURSE_FILE = BASE_DIR / "course.json"
ROUND_SIZE = 5
_course_cache = {"mtime": None, "data": None}

def load_course() -> dict:
    """course.json, reloaded automatically when the file is edited."""
    mtime = COURSE_FILE.stat().st_mtime
    if _course_cache["mtime"] != mtime:
        _course_cache["data"] = json.loads(COURSE_FILE.read_text(encoding="utf-8"))
        _course_cache["mtime"] = mtime
    return _course_cache["data"]

def _init_course_table():
    con = db()
    con.execute("""
        CREATE TABLE IF NOT EXISTS course_learnt (
            user_id TEXT NOT NULL,
            language_mode TEXT NOT NULL,
            level_id TEXT NOT NULL,
            topic_id TEXT NOT NULL,
            item_idx INTEGER NOT NULL,
            learnt_at TEXT NOT NULL,
            UNIQUE(user_id, language_mode, level_id, topic_id, item_idx)
        )""")
    con.commit()
    con.close()

def _is_grammar(item: dict) -> bool:
    return "focus" in item

def _target_and_meaning(item: dict, language_mode: str):
    """English speakers learn the Russian; Russian speakers learn the English.
    Grammar items: (lesson title in the learner's language, what the lesson covers)."""
    if _is_grammar(item):
        return item["title"][_ui_lang(language_mode)], item["focus"][language_mode]
    return (item["ru"], item["en"]) if language_mode == "en-ru" else (item["en"], item["ru"])

def _ui_lang(language_mode: str) -> str:
    return "en" if language_mode == "en-ru" else "ru"

def _learnt_indexes(user_id: str, language_mode: str) -> dict:
    """{(level_id, topic_id): set(item_idx)}"""
    _init_course_table()
    con = db()
    rows = con.execute(
        "SELECT level_id, topic_id, item_idx FROM course_learnt WHERE user_id=? AND language_mode=?",
        (user_id, language_mode),
    ).fetchall()
    con.close()
    learnt = {}
    for r in rows:
        learnt.setdefault((r["level_id"], r["topic_id"]), set()).add(r["item_idx"])
    return learnt

def _find_topic(level_id: str, topic_id: str):
    for level in load_course()["levels"]:
        if level["id"] == level_id:
            for topic in level["topics"]:
                if topic["id"] == topic_id:
                    return level, topic
    return None, None

def _course_overview(user_id: str, language_mode: str, difficulty: str) -> dict:
    """Every level/topic with progress. A level unlocks when the previous one is done,
    or straight away if the learner's chosen difficulty is at least that level's style."""
    rank = {"beginner": 0, "intermediate": 1, "advanced": 2}
    learnt = _learnt_indexes(user_id, language_mode)
    ui = _ui_lang(language_mode)
    levels, prev_done = [], True
    for i, level in enumerate(load_course()["levels"]):
        topics = []
        for topic in level["topics"]:
            n = len(learnt.get((level["id"], topic["id"]), set()))
            total = len(topic["items"])
            topics.append({"id": topic["id"], "emoji": topic.get("emoji", ""), "name": topic["name"][ui],
                           "learnt": min(n, total), "total": total, "done": n >= total})
        unlocked = i == 0 or prev_done or rank.get(difficulty, 0) >= rank.get(level.get("style"), 0)
        done = all(t["done"] for t in topics)
        levels.append({"id": level["id"], "name": level["name"][ui], "unlocked": unlocked, "done": done,
                       "grammar": level.get("kind") == "grammar", "topics": topics})
        prev_done = done
    return {"levels": levels}

def _active_topic(user_id: str, language_mode: str, difficulty: str, requested: Optional[str] = None):
    """The topic being studied: the one the user picked, else the saved one, else the first unfinished one."""
    state = get_lesson_state(user_id)
    course_state = state.setdefault("course", {})
    overview = _course_overview(user_id, language_mode, difficulty)

    def find(topic_id):
        for level in overview["levels"]:
            if level["unlocked"]:
                for t in level["topics"]:
                    if t["id"] == topic_id:
                        return level["id"], topic_id
        return None

    choice = find(requested) if requested else None
    if not choice and course_state.get(language_mode):
        choice = find(course_state[language_mode])
    if not choice:
        for level in overview["levels"]:
            if level["unlocked"]:
                for t in level["topics"]:
                    if not t["done"]:
                        choice = (level["id"], t["id"])
                        break
            if choice:
                break
    if choice and course_state.get(language_mode) != choice[1]:
        course_state[language_mode] = choice[1]
        save_lesson_state(user_id, state)
    return choice

def _course_snapshot(user_id: str, language_mode: str, difficulty: str, topic_hint: Optional[tuple] = None) -> Optional[dict]:
    """Progress of the active topic, for the chat header and the end-of-round/topic/level cards."""
    choice = topic_hint or _active_topic(user_id, language_mode, difficulty)
    if not choice:
        return None
    level, topic = _find_topic(*choice)
    if not topic:
        return None
    ui = _ui_lang(language_mode)
    learnt = sorted(_learnt_indexes(user_id, language_mode).get((level["id"], topic["id"]), set()))
    total = len(topic["items"])
    n = len(learnt)
    round_idx = (n - 1) // ROUND_SIZE if n else 0
    round_words = [_target_and_meaning(topic["items"][i], language_mode)[0]
                   for i in learnt if round_idx * ROUND_SIZE <= i < (round_idx + 1) * ROUND_SIZE]

    overview = _course_overview(user_id, language_mode, difficulty)
    this_level = next(l for l in overview["levels"] if l["id"] == level["id"])
    next_topic = next((t for t in this_level["topics"] if not t["done"] and t["id"] != topic["id"]), None)
    level_pos = [l["id"] for l in overview["levels"]].index(level["id"])
    next_level = overview["levels"][level_pos + 1] if level_pos + 1 < len(overview["levels"]) else None

    return {
        "level": {"id": level["id"], "name": level["name"][ui], "done": this_level["done"]},
        "topic": {"id": topic["id"], "name": topic["name"][ui], "emoji": topic.get("emoji", "")},
        "grammar": level.get("kind") == "grammar",
        "learnt": n, "total": total,
        "round": round_idx + 1, "rounds": -(-total // ROUND_SIZE),
        "in_round": (n - 1) % ROUND_SIZE + 1 if n else 0,
        "round_words": round_words,
        "topic_words": [_target_and_meaning(it, language_mode)[0] for it in topic["items"]],
        "topic_done": n >= total,
        "next_topic": next_topic,
        "next_level": ({"id": next_level["id"], "name": next_level["name"],
                        "first_topic": next_level["topics"][0] if next_level["topics"] else None}
                       if next_level and this_level["done"] else None),
    }

def _next_course_item(user_id: str, language_mode: str, level_id: str, topic_id: str):
    level, topic = _find_topic(level_id, topic_id)
    if not topic:
        return None
    done = _learnt_indexes(user_id, language_mode).get((level_id, topic_id), set())
    for idx, item in enumerate(topic["items"]):
        if idx not in done:
            return idx, item, level, topic
    return None

def _mark_learnt(user_id: str, language_mode: str, level_id: str, topic_id: str, idx: int):
    _init_course_table()
    con = db()
    con.execute(
        "INSERT OR IGNORE INTO course_learnt(user_id, language_mode, level_id, topic_id, item_idx, learnt_at) VALUES(?,?,?,?,?,?)",
        (user_id, language_mode, level_id, topic_id, idx, datetime.now().isoformat(timespec="seconds")),
    )
    con.commit()
    con.close()

@app.get("/api/course")
def api_course(language_mode: str = "en-ru", difficulty: str = "beginner", session_id: Optional[str] = Cookie(default=None)):
    """The course map (sidebar) and the active topic's progress (chat header)."""
    user_id = _require_user(session_id)
    language_mode = language_mode if language_mode in ("en-ru", "ru-en") else "en-ru"
    overview = _course_overview(user_id, language_mode, difficulty)
    snapshot = _course_snapshot(user_id, language_mode, difficulty)
    return {**overview, "active": snapshot}

@app.post("/chat/stream")
def chat_stream(req: ChatRequest, response: Response, session_id: Optional[str]=Cookie(default=None)):
    try:
        if not session_id:
            raise HTTPException(status_code=401, detail="Not authenticated")
        user_id = get_user_from_session(session_id)
        if not user_id:
            raise HTTPException(status_code=401, detail="Invalid session")
        u = get_user(user_id)
        if not u:
            raise HTTPException(status_code=404, detail="User not found")
        rate_limit("chat", user_id)

        state = get_lesson_state(user_id)
        user_msg = (req.message or "").strip()
        lower_msg = user_msg.lower()
    except HTTPException:
        raise
    except Exception as e:
        print(f"ERROR in chat_stream setup: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}")

    # ── Difficulty ────────────────────────────────────────────────────────────
    if req.difficulty in ('beginner', 'intermediate', 'advanced'):
        state["difficulty"] = req.difficulty
    else:
        for d in ('beginner', 'intermediate', 'advanced'):
            if d in lower_msg:
                state["difficulty"] = d
                break
    if "difficulty" not in state:
        state["difficulty"] = "beginner"
    save_lesson_state(user_id, state)

    # ── Language mode ─────────────────────────────────────────────────────────
    language_mode = (req.language_mode or "en-ru").strip().lower()
    if language_mode not in ("ru-en", "en-ru"):
        language_mode = "en-ru"

    # ── Lesson topic detection ────────────────────────────────────────────────
    lesson_map = {"greetings": "greetings", "travel": "travel", "food": "food"}
    for key in lesson_map:
        if key in lower_msg:
            state["lesson"] = key
            save_lesson_state(user_id, state)
            break

    difficulty   = state.get("difficulty", "beginner")
    lesson_key   = state.get("lesson", "greetings")
    # Content generated dynamically based on conversation context
    topic_names = {
        "greetings": "Greetings & Basic Phrases",
        "travel": "Travel & Transportation",
        "food": "Food & Dining"
    }
    lesson_topic = topic_names.get(lesson_key, lesson_key.title())

    # ── Course: "Next word" or a topic picked in the sidebar → the next word from course.json ──
    user_difficulty = difficulty          # unlocks levels; `difficulty` may switch to the level's style
    course_topic = None                   # (level_id, topic_id) being studied
    course_item = None                    # (idx, item, level, topic) Mila must teach now
    course_note = None
    if req.topic or req.intent == "next":
        course_topic = _active_topic(user_id, language_mode, user_difficulty, req.topic)
        if course_topic:
            level, topic = _find_topic(*course_topic)
            course_item = _next_course_item(user_id, language_mode, *course_topic)
            lesson_key, lesson_topic = topic["id"], topic["name"]["en"]
            difficulty = level.get("style", difficulty)
            topic_name = topic["name"][_ui_lang(language_mode)]
            if course_item and _is_grammar(course_item[1]):
                title, focus = _target_and_meaning(course_item[1], language_mode)
                course_note = COURSE_NOTES[language_mode]["grammar"].format(title=title, focus=focus, topic=topic_name)
            elif course_item:
                target, meaning = _target_and_meaning(course_item[1], language_mode)
                course_note = COURSE_NOTES[language_mode]["teach"].format(word=target, meaning=meaning, topic=topic_name)
            else:
                course_note = COURSE_NOTES[language_mode]["topic_done"].format(topic=topic_name)

    # ── System prompts: Mila's persona + level guide + word-card format ──────
    # The chat page turns each new word into a card with a quick check, so the
    # prompts only define what to teach; WORD_CARD_FORMAT defines how.
    if language_mode == "ru-en":
        level_guide = {
            "beginner": "Уровень: начинающий. Учи простые частые английские слова и короткие фразы. Объясняй очень просто.",
            "intermediate": "Уровень: средний. Учи полезные фразы и короткие предложения; если нужно, добавь короткую грамматическую подсказку.",
            "advanced": "Уровень: продвинутый. Учи идиомы, устойчивые выражения и тонкие различия в значении.",
        }[difficulty]
        system_prompt = (
            f"Ты учишь русскоговорящего студента АНГЛИЙСКОМУ языку. Тема урока: {lesson_topic}.\n"
            f"{level_guide}\n"
            "Правила:\n"
            "- Объяснения, отзывы и вопросы — по-русски; по-английски только изучаемые слова и примеры.\n"
            "- Одно новое слово за сообщение. Никаких списков слов.\n"
            "- Если студент пишет своё предложение — похвали, мягко исправь ошибки и коротко объясни.\n"
            "- Смотри историю разговора и не повторяй уже изученные слова."
        )
        tutor_prompt = f"Студент: {user_msg}\n\n{course_note or CHAT_INTENT_NOTES['ru-en'].get(req.intent, CHAT_INTENT_NOTES['ru-en']['default'])}"

    else:
        level_guide = {
            "beginner": "Level: beginner. Teach simple, very common Russian words and short phrases. Keep explanations very simple.",
            "intermediate": "Level: intermediate. Teach useful phrases and short sentences; add a brief grammar tip when it helps.",
            "advanced": "Level: advanced. Teach idioms, set expressions and subtle differences in meaning.",
        }[difficulty]
        system_prompt = (
            f"You teach RUSSIAN to an English-speaking student. Lesson topic: {lesson_topic}.\n"
            f"{level_guide}\n"
            "Rules:\n"
            "- Explanations, feedback and questions in ENGLISH; only the Russian words and examples are in Russian.\n"
            "- One new word per message. Never write word lists.\n"
            "- If the student writes their own sentence, praise them, gently correct mistakes and explain briefly.\n"
            "- Check the conversation history and never re-teach a word."
        )
        tutor_prompt = f"Student: {user_msg}\n\n{course_note or CHAT_INTENT_NOTES['en-ru'].get(req.intent, CHAT_INTENT_NOTES['en-ru']['default'])}"

    # Grammar lessons (and "build another sentence") use Mila's Colour Blocks format
    grammar_lesson = bool(course_item and _is_grammar(course_item[1])) or req.intent == "build"
    system_prompt = (
        MILA_PERSONA.get(language_mode, MILA_PERSONA["en-ru"]) + "\n\n"
        + system_prompt + "\n\n"
        + WORD_CARD_FORMAT.get(language_mode, WORD_CARD_FORMAT["en-ru"])
        + ("\n\n" + GRAMMAR_CARD_FORMAT[language_mode] if grammar_lesson else "")
    )

    # ── Stream with conversation history ──────────────────────────────────────
    def gen():
        try:
            full = ""
            save_chat_message(user_id, "user", user_msg)

            # Full conversation history for personalized learning
            raw_history = get_chat_history(user_id, limit=12)
            history = [{"role": h["role"], "content": h["content"]} for h in raw_history[:-1]]
            history.append({"role": "user", "content": tutor_prompt})

            for ev in llm_stream(system_prompt, history):
                if ev.startswith("event: delta"):
                    payload = json.loads(ev.split("data:")[1])
                    full += payload["text"]
                    yield ev

            # No post-processing needed - JavaScript handles speaker buttons
            save_chat_message(user_id, "assistant", full)

            # Save taught word/phrase for recap (best-effort; grammar lessons aren't vocabulary)
            grammar_card = _parse_grammar_card(full)
            try:
                if not grammar_card:
                    _save_taught_word(user_id, full, lesson_key, difficulty, language_mode)
            except Exception as _e:
                pass

            # Track word completion: a word card (or, in older replies, a bold word) means a new word
            if grammar_card or _parse_word_card(full) or re.search(r'\*\*[^\*]{2,}\*\*', full):
                # Log word completion for any message with bold words
                update_xp(user_id, 3, "word_complete")
            else:
                # Regular message XP (feedback, questions, etc)
                update_xp(user_id, 3, "message")
            uu = get_user(user_id)

            # Course progress: the taught course word is now learnt
            course = None
            try:
                taught_card = _parse_word_card(full) or grammar_card
                if course_item and taught_card:
                    idx, _item, level, topic = course_item
                    _mark_learnt(user_id, language_mode, level["id"], topic["id"], idx)
                course = _course_snapshot(user_id, language_mode, user_difficulty, course_topic)
                if course:
                    course["just_learnt"] = bool(course_item and taught_card)
                    course["topic_done_reply"] = bool(course_topic and not course_item)
            except Exception as _e:
                print("COURSE ERROR:", _e)

            # Count completed words
            con = db()
            words_count = con.execute(
                "SELECT COUNT(*) as cnt FROM xp_log WHERE user_id=? AND event='word_complete'",
                (user_id,)
            ).fetchone()["cnt"]
            con.close()

            yield sse("done", {
                "text": full,
                "progress": {"xp": uu["xp"], "level": uu["level"],
                             "streak": uu["streak"],
                             "words_completed": words_count},
                "course": course,
                "quiz_ready": False,
                "quiz": []
            })
        except Exception as e:
            import traceback; traceback.print_exc()
            error_msg = "Sorry, I encountered an error. Please try again."
            yield sse("delta", {"text": error_msg})
            yield sse("done", {
                "text": error_msg,
                "progress": {"xp": u["xp"], "level": u["level"],
                             "streak": u["streak"]},
                "quiz_ready": False, "quiz": []
            })

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.get("/api/welcome")
def get_welcome_data(session_id: Optional[str] = Cookie(default=None)):
    """Returns data for the welcome-back popup."""
    if not session_id:
        return {"error": "Not authenticated"}
    user_id = get_user_from_session(session_id)
    if not user_id:
        return {"error": "Invalid session"}

    import re

    con = db()
    u = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not u:
        con.close()
        return {"error": "User not found"}

    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()

    # --- extract taught words from chat history ---
    taught = []

    # Try yesterday first
    rows = con.execute(
        "SELECT content FROM chat_history WHERE user_id=? AND role='assistant' AND date(timestamp)=? ORDER BY id DESC LIMIT 6",
        (user_id, yesterday)
    ).fetchall()

    for row in rows:
        matches = re.findall(r'\*{0,2}([А-Яа-яЁё]+)\*{0,2}\s*\(([^)]+)\)', row["content"])
        for cyrillic, pronunciation in matches:
            if not any(t["word"] == cyrillic for t in taught):
                taught.append({"word": cyrillic, "pronunciation": pronunciation})

    # If nothing from yesterday, fall back to all-time history
    if not taught:
        rows = con.execute(
            "SELECT content FROM chat_history WHERE user_id=? AND role='assistant' ORDER BY id DESC LIMIT 20",
            (user_id,)
        ).fetchall()
        for row in rows:
            matches = re.findall(r'\*{0,2}([А-Яа-яЁё]+)\*{0,2}\s*\(([^)]+)\)', row["content"])
            for cyrillic, pronunciation in matches:
                if not any(t["word"] == cyrillic for t in taught):
                    taught.append({"word": cyrillic, "pronunciation": pronunciation})
            if len(taught) >= 3:
                break

    con.close()

    # brand new = never earned any XP at all
    is_brand_new = (u["xp"] == 0 and not taught)
    # returning = has been active before but not today
    is_returning = bool(u["last_active"]) and u["last_active"] < today

    quiz_items = taught[:3] if taught else []

    return {
        "username":     u["username"],
        "streak":       u["streak"],
        "xp":           u["xp"],
        "is_returning": is_returning,
        "is_brand_new": is_brand_new,
        "taught_words": taught,
        "quiz":         quiz_items
    }

@app.get("/api/progress/history")
def get_progress_history(days: int = 30, session_id: Optional[str] = Cookie(default=None)):
    if not session_id:
        return {"error": "Not authenticated"}
    
    user_id = get_user_from_session(session_id)
    if not user_id:
        return {"error": "Invalid session"}
    
    con = db()
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    rows = con.execute(
        "SELECT ts as date, xp_delta as xp_gained, xp_total FROM xp_log WHERE user_id=? AND ts>=? ORDER BY ts",
        (user_id, cutoff)
    ).fetchall()
    con.close()
    
    return {"history": [dict(row) for row in rows]}

@app.get("/api/progress")
def get_progress_snapshot(session_id: Optional[str] = Cookie(default=None)):
    if not session_id:
        return {"error": "Not authenticated"}
    user_id = get_user_from_session(session_id)
    if not user_id:
        return {"error": "Invalid session"}
    u = get_user(user_id)
    if not u:
        return {"error": "User not found"}

    # count completed words (word_complete events)
    con = db()
    completed = con.execute(
        "SELECT COUNT(*) as cnt FROM xp_log WHERE user_id=? AND event='word_complete'",
        (user_id,)
    ).fetchone()["cnt"]
    con.close()

    return {
        "xp":        u["xp"],
        "level":     u["level"],
        "streak":    u["streak"],
        "words_completed": completed
    }

# Dynamic chat-based learning system

class PronunciationCheckRequest(BaseModel):
    spoken_text: str
    target_word: str
    pronunciation_guide: str
    attempt_number: int = 1
    language_mode: str = "en-ru"

@app.post("/api/lesson/check-pronunciation")
def check_pronunciation(req: PronunciationCheckRequest, session_id: Optional[str] = Cookie(default=None)):
    """Check if user's pronunciation is correct"""
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = get_user_from_session(session_id)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session")
    
    # Simple check: does the spoken text contain the target word?
    # For a more sophisticated check, you could use phonetic matching or AI
    spoken_lower = req.spoken_text.lower().strip()
    target_lower = req.target_word.lower().strip()
    
    # Check for exact match or close match
    is_correct = (
        target_lower in spoken_lower or 
        spoken_lower in target_lower or
        len(set(spoken_lower) & set(target_lower)) > len(target_lower) * 0.6
    )
    
    if is_correct:
        feedback = "Great job! Your pronunciation is correct! ✓"
        encouragement = [
            "Excellent work!",
            "Perfect!",
            "You nailed it!",
            "Wonderful pronunciation!",
            "Keep it up!"
        ]
        import random
        message = random.choice(encouragement)
    else:
        feedback = f"Not quite. You said '{req.spoken_text}', but try saying '{req.target_word}' ({req.pronunciation_guide})"
        message = "Try again! Listen carefully and repeat."
    
    return {
        "is_correct": is_correct,
        "feedback": feedback,
        "message": message,
        "spoken_text": req.spoken_text,
        "attempt_number": req.attempt_number
    }

@app.get("/api/learning-feedback")
def get_learning_feedback(session_id: Optional[str] = Cookie(default=None)):
    if not session_id:
        return {"error": "Not authenticated"}
    user_id = get_user_from_session(session_id)
    if not user_id:
        return {"error": "Invalid session"}
    
    u = get_user(user_id)
    if not u:
        return {"error": "User not found"}
    
    xp = u["xp"]
    
    # Determine proficiency level with thresholds
    if xp < 100:
        proficiency = "Beginner"
        emoji = "🌱"
        message = "Just getting started! Keep practicing daily."
        next_level = "Learner"
        next_threshold = 100
    elif xp < 300:
        proficiency = "Learner"
        emoji = "📚"
        message = "Making great progress! You're building a solid foundation."
        next_level = "Intermediate"
        next_threshold = 300
    elif xp < 600:
        proficiency = "Intermediate"
        emoji = "🎯"
        message = "You're getting good! Keep up the momentum."
        next_level = "Upper Intermediate"
        next_threshold = 600
    elif xp < 1000:
        proficiency = "Upper Intermediate"
        emoji = "🏆"
        message = "Almost fluent! You're doing amazing."
        next_level = "Advanced"
        next_threshold = 1000
    elif xp < 1500:
        proficiency = "Advanced"
        emoji = "💎"
        message = "Outstanding! You're mastering the language."
        next_level = "Expert"
        next_threshold = 1500
    else:
        proficiency = "Expert"
        emoji = "👑"
        message = "You're a language master! Incredible achievement."
        next_level = "Master"
        next_threshold = xp + 500  # Always have a goal
    
    # Calculate progress to next level
    if xp < 1500:
        current_level_start = 0 if xp < 100 else (100 if xp < 300 else (300 if xp < 600 else (600 if xp < 1000 else 1000)))
        progress_percentage = int(((xp - current_level_start) / (next_threshold - current_level_start)) * 100)
    else:
        progress_percentage = 100
    
    xp_to_next = max(0, next_threshold - xp)
    
    # Get quiz performance
    con = db()
    quiz_stats = con.execute("""
        SELECT 
            AVG(score_percentage) as avg_score,
            COUNT(*) as total_quizzes,
            category,
            AVG(score_percentage) as cat_avg
        FROM quiz_scores 
        WHERE user_id = ?
        GROUP BY category
        ORDER BY cat_avg DESC
    """, (user_id,)).fetchall()
    
    best_category = None
    weak_category = None
    
    if quiz_stats:
        best_category = {"name": quiz_stats[0]["category"].capitalize(), "score": int(quiz_stats[0]["cat_avg"])}
        if len(quiz_stats) > 1:
            weak_category = {"name": quiz_stats[-1]["category"].capitalize(), "score": int(quiz_stats[-1]["cat_avg"])}
    
    # Calculate learning pace (XP per day)
    days_since_join = con.execute("""
        SELECT JULIANDAY('now') - JULIANDAY(created_at) as days
        FROM users WHERE id = ?
    """, (user_id,)).fetchone()["days"]
    
    learning_pace = int(xp / max(1, days_since_join))
    
    # Get longest streak
    longest_streak = con.execute("""
        SELECT MAX(streak) as max_streak FROM (
            SELECT streak FROM users WHERE id = ?
            UNION
            SELECT 0
        )
    """, (user_id,)).fetchone()["max_streak"] or u["streak"]
    
    con.close()
    
    return {
        "proficiency": proficiency,
        "emoji": emoji,
        "message": message,
        "next_level": next_level,
        "progress_percentage": progress_percentage,
        "xp_to_next": xp_to_next,
        "current_xp": xp,
        "next_threshold": next_threshold,
        "best_category": best_category,
        "weak_category": weak_category,
        "learning_pace": learning_pace,
        "longest_streak": longest_streak,
        "current_streak": u["streak"]
    }

@app.get("/api/leaderboard")
def get_leaderboard():
    con = db()
    rows = con.execute(
        "SELECT username, xp, level, streak, avatar FROM users ORDER BY xp DESC LIMIT 20"
    ).fetchall()
    con.close()
    return {"leaderboard": [dict(r) for r in rows]}

@app.post("/api/update-email")
def update_email(data: dict, session_id: Optional[str] = Cookie(default=None)):
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = get_user_from_session(session_id)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session")

    email = data.get("email", "").strip().lower()
    if not email:
        raise HTTPException(status_code=400, detail="Email is required")

    import re as _re
    if not _re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
        raise HTTPException(status_code=400, detail="Invalid email format")

    con = db()
    existing = con.execute("SELECT id FROM users WHERE email=? AND id!=?", (email, user_id)).fetchone()
    if existing:
        con.close()
        raise HTTPException(status_code=409, detail="This email is already in use by another account")

    con.execute("UPDATE users SET email=? WHERE id=?", (email, user_id))
    con.commit()
    con.close()

    return {"success": True, "email": email}

# Known legitimate email providers — exact matches are always valid
_KNOWN_PROVIDERS = [
    'gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'icloud.com',
    'protonmail.com', 'aol.com', 'mail.com', 'zoho.com', 'gmx.com',
    'yandex.com', 'mail.ru', 'live.com', 'msn.com', 'qq.com',
    'googlemail.com', 'me.com', 'mac.com', 'pm.me', 'proton.me',
    'ymail.com', 'rocketmail.com', 'fastmail.com', 'tutanota.com',
]

def _levenshtein(s1: str, s2: str) -> int:
    """Compute edit distance between two strings."""
    m, n = len(s1), len(s2)
    dp = list(range(n + 1))
    for i in range(1, m + 1):
        prev, dp[0] = dp[0], i
        for j in range(1, n + 1):
            temp = dp[j]
            dp[j] = prev if s1[i-1] == s2[j-1] else 1 + min(prev, dp[j], dp[j-1])
            prev = temp
    return dp[n]

@app.post("/api/validate-email-domain")
def validate_email_domain(data: dict):
    domain = data.get("domain", "").strip().lower()
    if not domain:
        raise HTTPException(status_code=400, detail="Domain required")

    # Step 1 — exact match: definitely valid
    if domain in _KNOWN_PROVIDERS:
        return {"is_typo": False}

    # Step 2 — fuzzy match: edit distance ≤ 2 from a known provider flags as typo
    best_provider, best_dist = None, float('inf')
    for provider in _KNOWN_PROVIDERS:
        d = _levenshtein(domain, provider)
        if d < best_dist:
            best_dist, best_provider = d, provider

    if best_dist <= 2:
        return {"is_typo": True, "suggestion": best_provider}

    # Step 3 — AI fallback for edge cases the fuzzy check missed
    system = (
        "You are an email address validator. "
        "Reply ONLY with a raw JSON object — no markdown, no extra text whatsoever."
    )
    prompt = (
        f'Is the email domain "{domain}" a misspelling of a well-known provider '
        f'(gmail.com, yahoo.com, hotmail.com, outlook.com, icloud.com, etc.)? '
        f'Reply ONLY: {{"is_typo": true, "suggestion": "correct.com"}} or {{"is_typo": false}}'
    )

    try:
        raw = llm_complete(system, prompt).strip()
        # Strip any markdown code fences the LLM might add
        raw = re.sub(r'^```(?:json)?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw).strip()
        # Extract the first JSON object if there's surrounding text
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            raw = m.group(0)
        result = json.loads(raw)
        return {
            "is_typo": bool(result.get("is_typo", False)),
            "suggestion": result.get("suggestion")
        }
    except Exception as e:
        print(f"AI domain validation error: {e}")
        return {"is_typo": False}   # fail open — don't block the user

@app.post("/api/update-avatar")
def update_avatar(data: dict, session_id: Optional[str] = Cookie(default=None)):
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = get_user_from_session(session_id)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session")

    avatar = data.get("avatar", "").strip()
    if not avatar:
        raise HTTPException(status_code=400, detail="Avatar required")

    con = db()
    con.execute("UPDATE users SET avatar = ? WHERE id = ?", (avatar, user_id))
    con.commit()
    con.close()

    return {"success": True, "avatar": avatar}

@app.get("/progress", response_class=HTMLResponse)
def progress_page():
    return (FRONTEND_DIR / "progress.html").read_text(encoding="utf-8")

@app.get("/leaderboard", response_class=HTMLResponse)
def leaderboard_page():
    return (FRONTEND_DIR / "leaderboard.html").read_text(encoding="utf-8")

@app.get("/profile", response_class=HTMLResponse)
def profile_page():
    return (FRONTEND_DIR / "profile.html").read_text(encoding="utf-8")

@app.get("/quiz", response_class=HTMLResponse)
def quiz_page():
    return _versioned_page("quiz.html")

@app.get("/test-tts.html", response_class=HTMLResponse)
def test_tts_page():
    return (FRONTEND_DIR / "test-tts.html").read_text(encoding="utf-8")

# ---------------- ADMIN APIs ----------------
@app.get("/admin/dashboard")
def admin_dashboard(admin_session_id: Optional[str] = Cookie(default=None)):
    require_admin(admin_session_id)
    
    con = db()
    
    # Get statistics
    total_users = con.execute("SELECT COUNT(*) as count FROM users").fetchone()["count"]
    total_messages = con.execute("SELECT COUNT(*) as count FROM chat_history").fetchone()["count"]
    total_xp = con.execute("SELECT SUM(xp) as total FROM users").fetchone()["total"] or 0
    active_today = con.execute(
        "SELECT COUNT(*) as count FROM users WHERE last_active=?",
        (date.today().isoformat(),)
    ).fetchone()["count"]
    
    # Get recent users
    recent_users = con.execute(
        "SELECT username, xp, level, streak, created_at FROM users ORDER BY created_at DESC LIMIT 5"
    ).fetchall()
    
    con.close()
    
    return {
        "stats": {
            "total_users": total_users,
            "total_messages": total_messages,
            "total_xp": total_xp,
            "active_today": active_today
        },
        "recent_users": [dict(row) for row in recent_users]
    }

@app.get("/admin/users")
def admin_get_users(admin_session_id: Optional[str] = Cookie(default=None)):
    require_admin(admin_session_id)

    con = db()
    users_raw = con.execute(
        """SELECT id, username, email, xp, level, streak, last_active, created_at,
                  avatar, daily_goal, study_reason, study_goal, study_level
           FROM users ORDER BY created_at DESC"""
    ).fetchall()

    users = []
    for row in users_raw:
        user_dict = dict(row)

        # Get quiz stats for this user
        quiz_stats = con.execute(
            """SELECT COUNT(*) as total_quizzes,
                      AVG(score_percentage) as avg_score,
                      MAX(score_percentage) as best_score
               FROM quiz_scores
               WHERE user_id = ?""",
            (user_dict['id'],)
        ).fetchone()

        user_dict['total_quizzes'] = quiz_stats['total_quizzes'] if quiz_stats else 0
        user_dict['avg_quiz_score'] = round(quiz_stats['avg_score'], 1) if quiz_stats and quiz_stats['avg_score'] else 0
        user_dict['best_quiz_score'] = quiz_stats['best_score'] if quiz_stats else 0

        users.append(user_dict)

    con.close()

    return {"users": users}

@app.get("/admin/user/{user_id}")
def admin_get_user_detail(user_id: str, admin_session_id: Optional[str] = Cookie(default=None)):
    require_admin(admin_session_id)
    
    con = db()
    
    # Get user info
    user = con.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    # Get XP history
    xp_history = con.execute(
        "SELECT ts, xp_delta, xp_total, event FROM xp_log WHERE user_id=? ORDER BY id DESC LIMIT 20",
        (user_id,)
    ).fetchall()
    
    # Get chat history
    chat_history = con.execute(
        "SELECT role, content, timestamp FROM chat_history WHERE user_id=? ORDER BY id DESC LIMIT 50",
        (user_id,)
    ).fetchall()
    
    con.close()
    
    return {
        "user": dict(user),
        "xp_history": [dict(row) for row in xp_history],
        "chat_history": [dict(row) for row in chat_history]
    }

@app.put("/admin/user/{user_id}")
def admin_update_user(user_id: str, xp: Optional[int] = None, level: Optional[str] = None, 
                      streak: Optional[int] = None, admin_session_id: Optional[str] = Cookie(default=None)):
    require_admin(admin_session_id)
    
    con = db()
    updates = []
    params = []
    
    if xp is not None:
        updates.append("xp=?")
        params.append(xp)
    if level is not None:
        updates.append("level=?")
        params.append(level)
    if streak is not None:
        updates.append("streak=?")
        params.append(streak)
    
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    
    params.append(user_id)
    query = f"UPDATE users SET {', '.join(updates)} WHERE id=?"
    
    con.execute(query, params)
    con.commit()
    con.close()
    
    return {"success": True, "message": "User updated"}

@app.delete("/admin/user/{user_id}")
def admin_delete_user(user_id: str, admin_session_id: Optional[str] = Cookie(default=None)):
    require_admin(admin_session_id)
    
    con = db()
    
    # Delete user and all related data
    con.execute("DELETE FROM chat_history WHERE user_id=?", (user_id,))
    con.execute("DELETE FROM xp_log WHERE user_id=?", (user_id,))
    con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    con.execute("DELETE FROM users WHERE id=?", (user_id,))
    
    con.commit()
    con.close()
    
    return {"success": True, "message": "User deleted"}

# ============== ADMIN AUTH ==============

class AdminLoginRequest(BaseModel):
    username: str
    password: str

@app.post("/admin/login")
def admin_login(req: AdminLoginRequest, response: Response, request: Request):
    rate_limit("auth", client_ip(request))
    con = db()
    try:
        admin = con.execute(
            "SELECT id, username, password FROM admins WHERE username=?", (req.username,)
        ).fetchone()
        ok, needs_upgrade = verify_password(req.password, admin["password"]) if admin else (False, False)
        if not ok:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        if needs_upgrade:
            con.execute("UPDATE admins SET password=? WHERE id=?", (hash_password(req.password), admin["id"]))
        
        admin_session_id = str(uuid.uuid4())
        today = date.today().isoformat()
        con.execute(
            "INSERT INTO admin_sessions(session_id, admin_id, created_at) VALUES(?,?,?)",
            (admin_session_id, admin["id"], today)
        )
        con.commit()
        response.set_cookie("admin_session_id", admin_session_id, httponly=True, max_age=30*24*60*60)
        
        return {"success": True, "username": admin["username"]}
    except HTTPException as e:
        raise e
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        con.close()

@app.post("/admin/logout")
def admin_logout(response: Response, admin_session_id: Optional[str] = Cookie(default=None)):
    if admin_session_id:
        con = db()
        con.execute("DELETE FROM admin_sessions WHERE session_id=?", (admin_session_id,))
        con.commit()
        con.close()
    response.delete_cookie("admin_session_id")
    return {"success": True}

@app.get("/admin/check")
def admin_check(admin_session_id: Optional[str] = Cookie(default=None)):
    if not admin_session_id:
        return {"authenticated": False}
    
    con = db()
    row = con.execute(
        "SELECT admin_id FROM admin_sessions WHERE session_id=?",
        (admin_session_id,)
    ).fetchone()
    con.close()
    
    if not row:
        return {"authenticated": False}
    
    return {"authenticated": True}

def require_admin(admin_session_id: Optional[str]):
    if not admin_session_id:
        raise HTTPException(status_code=401, detail="Admin authentication required")
    
    con = db()
    row = con.execute(
        "SELECT admin_id FROM admin_sessions WHERE session_id=?",
        (admin_session_id,)
    ).fetchone()
    con.close()
    
    if not row:
        raise HTTPException(status_code=401, detail="Invalid admin session")
    
    return row["admin_id"]


# ============== QUIZ APIs ==============

# ================== AI QUIZ GENERATOR (MCQ ONLY) ==================
class QuizGenerateRequest(BaseModel):
    language_mode: str = "ru-en"       # 'ru-en' or 'en-ru'
    category: str = "greetings"        # greetings | travel | food | mixed
    difficulty: str = "beginner"       # beginner | intermediate | advanced
    count: int = 10
    batch: int = 0                     # which parallel batch this is (varies the question styles)
    batch_total: int = 1               # how many batches the quiz is split into
    source: str = "topic"              # "topic" (category) or "lessons" (words taught in chat)
    words: Optional[list] = None       # lessons: only these words (a chat round), else all learnt words
    grammar_topic: Optional[str] = None  # "level_id/topic_id": a grammar topic's final quiz

class QuizSubmitRequest(BaseModel):
    category: str
    difficulty: str
    language_mode: str
    total_questions: int
    correct_answers: int
    time_taken: int
    hearts_left: int = 0
    ended_by_hearts: bool = False
    ended_by_time: bool = False

def _extract_json_object(text: str) -> Optional[dict]:
    if not text:
        return None
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    chunk = text[start:end+1]
    try:
        return json.loads(chunk)
    except Exception:
        return None

# The frontend requests the quiz in small parallel batches; each batch leans on
# different MCQ styles so the batches don't repeat each other.
_QUIZ_BATCH_FOCUS = [
    "Mostly style 1 (translation) and style 4 (meaning).",
    "Mostly style 1 (translation) and style 2 (correct reply).",
    "Mostly style 3 (fill the blank) and style 1 (translation), using different words than usual.",
    "Mostly style 4 (meaning) and style 2 (correct reply), using less obvious everyday phrases.",
]

# Style names in each UI language, so the model doesn't mix languages in "prompt"
_QUIZ_STYLE_NAMES = {
    "ru-en": ['"Выберите перевод"', '"Выберите правильный ответ"', '"Заполните пропуск"', '"Что это означает?"'],
    "en-ru": ['"Choose the translation"', '"Choose the correct reply"', '"Fill in the blank"', '"What does this mean?"'],
}

def _lesson_words(user_id: str, language_mode: str, limit: int = 30) -> list:
    """Words/phrases Mila taught this user in chat (newest first), one entry per word,
    preferring the saved copy that has a meaning."""
    con = db()
    rows = con.execute(
        """SELECT word, meaning, lesson FROM taught_words
             WHERE user_id=? AND language_mode=?
             ORDER BY id DESC LIMIT 200""",
        (user_id, language_mode),
    ).fetchall()
    con.close()

    words = {}
    for r in rows:
        word = (r["word"] or "").strip()
        key = word.lower().rstrip("?!.")
        if not word:
            continue
        meaning = (r["meaning"] or "").strip()
        if key not in words:
            words[key] = {"word": word, "meaning": meaning, "lesson": r["lesson"] or ""}
        elif meaning and not words[key]["meaning"]:
            words[key]["meaning"] = meaning
    return list(words.values())[:limit]

def _prefer_lesson_questions(questions: list, lesson_words: list) -> list:
    """Put questions that practise a learnt word first. Matching is loose (word stem,
    case- and ё-insensitive) because Russian words change their endings."""
    def norm(s: str) -> str:
        return re.sub(r"[^\w\s]", "", (s or "").lower().replace("ё", "е"))

    stems = {norm(w["word"])[:5] for w in lesson_words if norm(w["word"]).strip()}

    def uses_lesson_word(q: dict) -> bool:
        text = norm(q["q"] + " " + q["options"][q["correct"]])
        return any(stem in text for stem in stems)

    on_topic = [q for q in questions if uses_lesson_word(q)]
    return on_topic + [q for q in questions if not uses_lesson_word(q)]

@app.get("/api/export/words")
def api_export_words(language_mode: str = "en-ru", session_id: Optional[str] = Cookie(default=None)):
    """Download every word Mila has taught this user as a CSV file (opens in Excel/Sheets)."""
    import csv, io
    user_id = _require_user(session_id)
    language_mode = language_mode if language_mode in ("en-ru", "ru-en") else "en-ru"
    con = db()
    rows = con.execute(
        """SELECT word, meaning, pronunciation, lesson, MIN(created_at) AS learnt_on
             FROM taught_words WHERE user_id=? AND language_mode=?
             GROUP BY LOWER(word) ORDER BY MIN(id)""",
        (user_id, language_mode),
    ).fetchall()
    con.close()

    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["Word", "Meaning", "Pronunciation", "Topic", "Learnt on"])
    for r in rows:
        writer.writerow([r["word"], r["meaning"] or "", r["pronunciation"] or "", (r["lesson"] or "").replace("_", " "), r["learnt_on"] or ""])
    filename = f"langtutor-words-{language_mode}-{date.today().isoformat()}.csv"
    # The BOM makes Excel read the Russian text correctly
    return Response("﻿" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})

@app.get("/api/quiz/lesson-words")
def api_quiz_lesson_words(language_mode: str = "en-ru", session_id: Optional[str] = Cookie(default=None)):
    """Words the user has learnt in chat — shown on the quiz setup screen."""
    user_id = get_user_from_session(session_id) if session_id else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    words = _lesson_words(user_id, language_mode if language_mode in ("ru-en", "en-ru") else "en-ru")
    return {"count": len(words), "words": words}

def _quiz_system_prompt_mcq(language_mode: str, category: str, difficulty: str, count: int, batch: int = 0,
                            lesson_words: Optional[list] = None) -> str:
    """
    MCQ only, but Duolingo-like variety using MCQ formats.
    ru-en: Russian UI, teach English (questions RU, options EN)
    en-ru: English UI, teach Russian (questions EN, options RU)
    """
    if language_mode == "ru-en":
        mode_rules = """
You are generating a quiz for Russian speakers learning ENGLISH.
- Questions/prompts must be in Russian.
- Options must be in English.
- Exactly ONE correct option.
- Explanations must be short and in Russian.
"""
    else:
        mode_rules = """
You are generating a quiz for English speakers learning RUSSIAN.
- Questions/prompts must be in English.
- Options must be in Russian.
- Exactly ONE correct option.
- Explanations must be short and in English.
"""

    category_guide = {
        "greetings": "Greetings & basic conversation",
        "travel": "Travel phrases & directions",
        "food": "Food & restaurant phrases",
        "mixed": "Mix of greetings, travel, and food",
    }.get(category, "General language practice")

    diff_guide = {
        "beginner": "Beginner: simple words/short phrases, very common meanings.",
        "intermediate": "Intermediate: longer phrases, basic grammar, common mistakes.",
        "advanced": "Advanced: nuanced meaning, near-synonyms, trickier distractors.",
    }.get(difficulty, "Beginner")

    styles = _QUIZ_STYLE_NAMES.get(language_mode, _QUIZ_STYLE_NAMES["en-ru"])

    if lesson_words and lesson_words[0].get("grammar"):
        target = "ENGLISH" if language_mode == "ru-en" else "RUSSIAN"
        point_lines = "\n".join(f"- {w['word']}: {w['meaning']}" for w in lesson_words)
        topic_block = f"""GRAMMAR REVIEW: the learner studied these {target} grammar points:
{point_lines}
- EVERY question must test one of these grammar points, e.g. "Choose the correct sentence", fill the blank with the right form, the right word order, or "Which word is the verb/subject/object?".
- Options are {target} words or sentences; exactly one is correct, the others are typical learner mistakes.
- Spread the questions across the grammar points."""
    elif lesson_words:
        word_lines = "\n".join(
            f"- {w['word']}" + (f" — {w['meaning']}" if w.get("meaning") else "") for w in lesson_words
        )
        topic_block = f"""LESSON REVIEW: the learner was taught these words/phrases in their chat lessons:
{word_lines}
- EVERY question must practise one of these words/phrases (the correct option should be or contain it).
- Spread the questions across different words; only reuse a word if there are fewer words than questions.
- Wrong options can be other common words, but keep them plausible.
- If a meaning is missing above, use the usual meaning of the word."""
    else:
        topic_block = f"TOPIC: {category_guide}"

    return f"""
You are a quiz generator. Output STRICT JSON ONLY. No markdown. No extra text.

{mode_rules}

{topic_block}
DIFFICULTY: {diff_guide}
COUNT: {count}

Make the quiz feel like Duolingo. Use a mix of these question styles
(the "prompt" field is the style name exactly as written here):
1) {styles[0]} — "q" is a word/phrase to translate; options are translations
2) {styles[1]} — "q" is something someone says; options are possible replies
3) {styles[2]} — "q" is a sentence in the TARGET language with "___" for the missing word
4) {styles[3]} — "q" is a phrase; options are possible meanings
FOCUS FOR THIS SET: {_QUIZ_BATCH_FOCUS[batch % len(_QUIZ_BATCH_FOCUS)]}

Return JSON with this schema:
{{
  "questions": [
    {{
      "style": 1,  // which style (1-4) above
      "prompt": "style name, in the UI language",
      "q": "question text",
      "options": ["A","B","C","D"],   // target language
      "correct": 0,  // INDEX (0-3) of the CORRECT answer in options array
      "accepted": ["other correct ways to write the answer, e.g. without punctuation or with a common synonym"],
      "explanation": "helpful hint that DOES NOT reveal the answer"
    }}
  ]
}}

CRITICAL RULES:
1. The "correct" field is the INDEX (0, 1, 2, or 3) of the RIGHT ANSWER in the options array
   - If the correct answer is options[0], then "correct": 0
   - If the correct answer is options[1], then "correct": 1
   - If the correct answer is options[2], then "correct": 2
   - If the correct answer is options[3], then "correct": 3

2. The "explanation" field must be a HINT, not the answer itself.
   - Good hint: "Think about common greetings when leaving"
   - Bad hint: "'До свидания' means 'Goodbye'" (this reveals the answer!)

3. Hard rules:
   - Valid JSON only
   - Exactly 4 unique options
   - One and only one correct answer
   - correct must be 0, 1, 2, or 3 (the index of the right answer)
   - Keep questions short
   - Safe content only
"""

def _llm_generate_quiz_json(system_prompt: str, count: int) -> dict:
    """Generate quiz JSON using LLM (synchronous for OpenAI, async handled at call site for Ollama)"""
    if LLM_PROVIDER == "openai":
        client = openai_client()
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate the quiz JSON now."}
            ],
            max_tokens=250 * count + 200,
            temperature=0.7,
            response_format={"type": "json_object"},
        )
        text = resp.choices[0].message.content or ""
        data = _extract_json_object(text)
        if not data:
            raise ValueError("Model did not return valid JSON")
        return data
    else:
        # Ollama provider - using synchronous httpx client
        payload = {
            "model": OLLAMA_MODEL,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate the quiz JSON now."}
            ],
            "stream": False,
            "options": {"temperature": 0.7}
        }
        with httpx.Client(timeout=120) as c:
            r = c.post(f"{OLLAMA_URL}/api/chat", json=payload)
            r.raise_for_status()
            raw = r.json()
            text = (raw.get("message") or {}).get("content", "") or ""
            data = _extract_json_object(text)
            if not data:
                raise ValueError("Model did not return valid JSON")
            return data

def _validate_mcq_payload(payload: dict, count: int) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Quiz payload is not a dict")
    qs = payload.get("questions")
    if not isinstance(qs, list) or not qs:
        raise ValueError("Quiz payload has no questions")

    cleaned = []
    for item in qs:
        if not isinstance(item, dict):
            continue
        prompt = item.get("prompt", "")
        q = item.get("q")
        options = item.get("options")
        correct = item.get("correct")
        explanation = item.get("explanation", "")

        if not isinstance(q, str) or not q.strip():
            continue
        if not isinstance(options, list) or len(options) != 4:
            continue
        if any((not isinstance(o, str) or not o.strip()) for o in options):
            continue
        if len(set(options)) != 4:
            continue
        if not isinstance(correct, int) or correct < 0 or correct > 3:
            continue

        style = item.get("style")
        accepted = item.get("accepted")
        cleaned.append({
            "style": style if isinstance(style, int) and 1 <= style <= 4 else 0,
            "accepted": [a.strip() for a in accepted if isinstance(a, str) and a.strip()][:6] if isinstance(accepted, list) else [],
            "prompt": str(prompt).strip(),
            "q": q.strip(),
            "options": [o.strip() for o in options],
            "correct": int(correct),
            "explanation": str(explanation).strip(),
        })

    if not cleaned:
        raise ValueError("All generated questions were invalid")

    return {"questions": cleaned[:count]}

@app.post("/api/quiz/generate")
def api_quiz_generate(req: QuizGenerateRequest, session_id: Optional[str] = Cookie(default=None)):
    """Generate quiz questions using AI (OpenAI sync, Ollama would need async wrapper)"""
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = get_user_from_session(session_id)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session")
    rate_limit("quiz", user_id)

    language_mode = (req.language_mode or "ru-en").strip().lower()
    if language_mode not in ("ru-en", "en-ru"):
        language_mode = "ru-en"

    category = (req.category or "greetings").strip().lower()
    if category not in ("greetings", "travel", "food", "mixed"):
        category = "greetings"

    difficulty = (req.difficulty or "beginner").strip().lower()
    if difficulty not in ("beginner", "intermediate", "advanced"):
        difficulty = "beginner"

    count = int(req.count or 10)
    count = max(1, min(30, count))

    batch = max(0, int(req.batch or 0))
    lesson_words = None
    if (req.source or "").strip().lower() == "lessons":
        words = _lesson_words(user_id, language_mode, limit=200)
        if req.grammar_topic:
            # Grammar topic: quiz the grammar points from course.json
            level_id, _, topic_id = req.grammar_topic.partition("/")
            _level, topic = _find_topic(level_id, topic_id)
            words = [{"word": it["title"]["en"], "meaning": it["focus"][language_mode], "grammar": True}
                     for it in (topic or {}).get("items", []) if _is_grammar(it)]
        elif req.words:
            # A chat round: quiz just these words (meanings come from what Mila taught)
            known = {w["word"].lower(): w for w in words}
            words = [known.get(str(w).strip().lower(), {"word": str(w).strip()[:60], "meaning": "", "lesson": ""})
                     for w in req.words[:20] if str(w).strip()]
        else:
            words = words[:30]
        if len(words) < 3:
            raise HTTPException(status_code=400, detail="Not enough lesson words yet")
        # Give each parallel batch its own share of the words so batches don't repeat each other
        batch_total = max(1, int(req.batch_total or 1))
        share = words[batch % batch_total::batch_total]
        lesson_words = share if len(share) >= 2 else words

    # Lesson quizzes ask for one spare question so any that drifts off the learnt words can be dropped
    ask = count + 1 if lesson_words else count
    system_prompt = _quiz_system_prompt_mcq(language_mode, category, difficulty, ask, batch, lesson_words)

    try:
        payload = _llm_generate_quiz_json(system_prompt, ask)
        result = _validate_mcq_payload(payload, ask)
        if lesson_words:
            preferred = result["questions"] if lesson_words[0].get("grammar") else _prefer_lesson_questions(result["questions"], lesson_words)
            result["questions"] = preferred[:count]
        return result
    except Exception as e:
        print("QUIZ GENERATION ERROR:", e)
        raise HTTPException(status_code=500, detail="Quiz generation failed")

# ================== TTS (natural tutor voice) ==================
OPENAI_TTS_MODEL = os.getenv("OPENAI_TTS_MODEL", "gpt-4o-mini-tts")
OPENAI_TTS_VOICE = os.getenv("OPENAI_TTS_VOICE", "coral")
TTS_INSTRUCTIONS = os.getenv(
    "TTS_INSTRUCTIONS",
    "You are Mila, a warm, upbeat and encouraging language tutor. "
    "Speak naturally and clearly, a little slower than normal conversation, "
    "with a friendly smile in your voice. Pronounce the words like a native speaker of that language.",
)
TTS_CACHE_DIR = Path(__file__).parent / "tts_cache"

class TTSRequest(BaseModel):
    text: str

@app.post("/api/tts")
def api_tts(req: TTSRequest, session_id: Optional[str] = Cookie(default=None)):
    """Speak text with OpenAI TTS. Audio is cached on disk so repeated phrases are free."""
    user_id = get_user_from_session(session_id) if session_id else None
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    rate_limit("tts", user_id)
    if LLM_PROVIDER != "openai" or not OPENAI_API_KEY:
        raise HTTPException(status_code=503, detail="TTS not configured")

    text = (req.text or "").strip()
    if not text or len(text) > 400:
        raise HTTPException(status_code=400, detail="Text must be 1-400 characters")

    key = hashlib.sha256(f"{OPENAI_TTS_MODEL}|{OPENAI_TTS_VOICE}|{TTS_INSTRUCTIONS}|{text}".encode("utf-8")).hexdigest()
    cache_file = TTS_CACHE_DIR / f"{key}.mp3"
    if not cache_file.exists():
        extra = {"instructions": TTS_INSTRUCTIONS} if "gpt-4o" in OPENAI_TTS_MODEL else None
        try:
            audio = openai_client().audio.speech.create(
                model=OPENAI_TTS_MODEL,
                voice=OPENAI_TTS_VOICE,
                input=text,
                response_format="mp3",
                extra_body=extra,
            )
        except Exception as e:
            print("TTS ERROR:", e)
            raise HTTPException(status_code=502, detail="TTS failed")
        TTS_CACHE_DIR.mkdir(exist_ok=True)
        cache_file.write_bytes(audio.content)

    return FileResponse(cache_file, media_type="audio/mpeg", headers={"Cache-Control": "private, max-age=604800"})

# ================== QUIZ SUBMIT (AWARD XP + SAVE SCORE) ==================
def _calc_quiz_xp(total_q: int, correct: int, hearts_left: int, ended_early: bool) -> int:
    # Duolingo-ish:
    # - 10 XP per correct
    # - +20 XP completion bonus if finished (not ended early)
    # - +30 XP perfect bonus if finished and perfect
    # - +5 XP per heart remaining
    total_q = max(1, int(total_q))
    correct = max(0, min(int(correct), total_q))
    hearts_left = max(0, min(int(hearts_left), 3))

    xp = correct * 10
    if not ended_early:
        xp += 20
    if correct == total_q and not ended_early:
        xp += 30
    xp += hearts_left * 5
    return max(0, min(xp, 600))

@app.post("/api/quiz/submit")
async def api_quiz_submit(req: QuizSubmitRequest, session_id: Optional[str] = Cookie(default=None)):
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user_id = get_user_from_session(session_id)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid session")

    category = (req.category or "greetings").strip().lower()
    if category not in ("greetings", "travel", "food", "mixed", "lessons"):
        category = "greetings"

    difficulty = (req.difficulty or "beginner").strip().lower()
    if difficulty not in ("beginner", "intermediate", "advanced"):
        difficulty = "beginner"

    language_mode = (req.language_mode or "ru-en").strip().lower()
    if language_mode not in ("ru-en", "en-ru"):
        language_mode = "ru-en"

    total_q = max(1, int(req.total_questions))
    correct = max(0, min(int(req.correct_answers), total_q))
    time_taken = max(0, int(req.time_taken))

    ended_early = bool(req.ended_by_time or req.ended_by_hearts)
    xp_earned = _calc_quiz_xp(total_q, correct, int(req.hearts_left), ended_early)

    # Ensure quiz_scores table exists (safe to run)
    con = db()
    con.execute("""
      CREATE TABLE IF NOT EXISTS quiz_scores (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,
        category TEXT NOT NULL,
        difficulty TEXT NOT NULL,
        language_mode TEXT NOT NULL,
        total_questions INTEGER NOT NULL,
        correct_answers INTEGER NOT NULL,
        score_percentage INTEGER NOT NULL,
        time_taken INTEGER NOT NULL,
        created_at TEXT NOT NULL
      )
    """)
    now = datetime.utcnow().isoformat()
    score_pct = int(round((correct / total_q) * 100))

    con.execute("""
        INSERT INTO quiz_scores(
            user_id, category, difficulty, language_mode,
            total_questions, correct_answers, score_percentage,
            time_taken, created_at
        ) VALUES(?,?,?,?,?,?,?,?,?)
    """, (user_id, category, difficulty, language_mode, total_q, correct, score_pct, time_taken, now))
    con.commit()
    con.close()

    # Award XP using your existing function
    try:
        update_xp(user_id, xp_earned, event="quiz")
    except Exception as e:
        print("XP UPDATE ERROR:", e)

    u = get_user(user_id)
    return {
        "xp_earned": xp_earned,
        "new_total_xp": int(u["xp"]) if u else 0,
        "level": u["level"] if u else "A1",
        "streak": int(u["streak"]) if u else 0
    }
# =========================================================
@app.get("/api/quiz/stats")
def get_quiz_stats(session_id: Optional[str] = Cookie(default=None)):
    if not session_id:
        print("Quiz stats: No session ID")
        return {"error": "Not authenticated"}
    
    user_id = get_user_from_session(session_id)
    if not user_id:
        print("Quiz stats: Invalid session")
        return {"error": "Invalid session"}
    
    con = db()
    try:
        print(f"Getting quiz stats for user: {user_id}")
        
        total_quizzes = con.execute(
            "SELECT COUNT(*) as count FROM quiz_scores WHERE user_id = ?",
            (user_id,)
        ).fetchone()["count"]
        
        avg_score = con.execute(
            "SELECT AVG(score_percentage) as avg FROM quiz_scores WHERE user_id = ?",
            (user_id,)
        ).fetchone()["avg"] or 0
        
        best_score = con.execute(
            "SELECT MAX(score_percentage) as best FROM quiz_scores WHERE user_id = ?",
            (user_id,)
        ).fetchone()["best"] or 0
        
        print(f"Quiz stats: quizzes={total_quizzes}, avg={avg_score}, best={best_score}")
        
        return {
            "total_quizzes": total_quizzes,
            "average_score": round(avg_score, 1),
            "best_score": best_score
        }
    except Exception as e:
        print(f"ERROR getting quiz stats: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}
    finally:
        con.close()

@app.get("/api/quiz/history")
def get_quiz_history(session_id: Optional[str] = Cookie(default=None)):
    if not session_id:
        return {"error": "Not authenticated"}
    
    user_id = get_user_from_session(session_id)
    if not user_id:
        return {"error": "Invalid session"}
    
    con = db()
    try:
        rows = con.execute("""
            SELECT category, difficulty, language_mode, 
                   total_questions, correct_answers, score_percentage,
                   time_taken, created_at
            FROM quiz_scores 
            WHERE user_id = ?
            ORDER BY created_at DESC
            LIMIT 20
        """, (user_id,)).fetchall()
        
        history = []
        for row in rows:
            history.append({
                "category": row["category"],
                "difficulty": row["difficulty"],
                "language_mode": row["language_mode"],
                "total_questions": row["total_questions"],
                "correct_answers": row["correct_answers"],
                "score_percentage": row["score_percentage"],
                "time_taken": row["time_taken"],
                "created_at": row["created_at"]
            })
        
        return {"history": history}
    except Exception as e:
        print(f"ERROR getting quiz history: {str(e)}")
        import traceback
        traceback.print_exc()
        return {"error": str(e)}
    finally:
        con.close()