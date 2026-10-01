from fastapi import FastAPI, Response, Cookie, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from dotenv import load_dotenv
from pathlib import Path
from openai import OpenAI

import os, json, httpx, sqlite3, uuid, random, hashlib
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

@app.get("/")
def home():
    return FileResponse(FRONTEND_DIR / "index.html")

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
DB_PATH = BASE_DIR / "app.db"

def db():
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    return con

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

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
    existing_admin = con.execute("SELECT 1 FROM admins LIMIT 1").fetchone()
    if not existing_admin:
        admin_id = str(uuid.uuid4())
        admin_password = hash_password("admin123")
        today = date.today().isoformat()
        con.execute("INSERT INTO admins(id, username, password, created_at) VALUES(?,?,?,?)",
                    (admin_id, "admin", admin_password, today))
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
def signup(req: SignupRequest):
    con = db()
    try:
        existing = con.execute("SELECT 1 FROM users WHERE username=?", (req.username,)).fetchone()
        if existing:
            raise HTTPException(status_code=400, detail="Username already exists")

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
def login(req: LoginRequest, response: Response):
    """
    ✅ FIX: Support both hashed passwords AND legacy plaintext passwords.
    If legacy plaintext matches, we auto-migrate to sha256 hash.
    """
    con = db()
    try:
        password_hash = hash_password(req.password)

        user = con.execute(
            "SELECT id, username, password FROM users WHERE username=?",
            (req.username,)
        ).fetchone()

        if not user:
            raise HTTPException(status_code=401, detail="Invalid username or password")

        stored = user["password"] or ""

        # Accept hashed OR plaintext (legacy)
        if stored == password_hash:
            ok = True
        elif stored == req.password:
            ok = True
            # migrate plaintext -> hash
            con.execute("UPDATE users SET password=? WHERE id=?", (password_hash, user["id"]))
        else:
            ok = False

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
def forgot_password(req: ForgotPasswordRequest):
    email = req.email.strip().lower()
    con = db()
    user = con.execute("SELECT id FROM users WHERE LOWER(email)=?", (email,)).fetchone()
    if not user:
        con.close()
        # Return success to avoid email enumeration
        return {"success": True, "message": "If that email exists, a code has been sent."}

    # Generate 6-digit OTP
    code = str(random.randint(100000, 999999))
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
def resend_otp(req: ResendOTPRequest):
    email = req.email.strip().lower()
    con = db()
    user = con.execute("SELECT id FROM users WHERE LOWER(email)=?", (email,)).fetchone()
    con.close()
    if not user:
        return {"success": True}  # silent — don't leak email existence

    # Reuse the forgot-password flow
    return forgot_password(ForgotPasswordRequest(email=email))

@app.post("/auth/reset-password")
def reset_password(req: ResetPasswordRequest):
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
            max_tokens=800,
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


def extract_difficulty(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"\bdifficulty\s*=\s*(beginner|intermediate|advanced)\b", text, re.I)
    if m:
        return m.group(1).lower()
    return None

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

    # ── System prompts ────────────────────────────────────────────────────────
    if language_mode == "ru-en":
        if difficulty == "beginner":
            system_prompt = (
                "Ты AI репетитор АНГЛИЙСКОГО языка для русскоговорящих студентов.\n\n"
                "🔴 КРИТИЧЕСКИ ВАЖНО - МАКСИМАЛЬНАЯ СТРОГОСТЬ:\n"
                "▶ В КАЖДОМ сообщении учи ТОЛЬКО ОДНО английское слово!\n"
                "▶ ЗАПРЕЩЕНО учить 2, 3, 4+ слов в одном сообщении!\n"
                "▶ СТОП после обучения одному слову - ЖДИ ответа студента!\n"
                "▶ НЕ продолжай учить следующее слово пока студент не ответит!\n\n"
                "✅ ПРАВИЛЬНО (одно слово):\n"
                "**Hello** 🔊 (хэ-ЛОУ) - Привет\n"
                "Example: 🔊 Hello! How are you? — Привет! Как дела?\n"
                "Попробуй использовать это слово в предложении!\n\n"
                "❌ НЕПРАВИЛЬНО (несколько слов - ЗАПРЕЩЕНО!):\n"
                "**Hello** - Привет\n"
                "**Friend** - Друг ← НЕТ! Это уже второе слово!\n"
                "**Thanks** - Спасибо ← НЕТ! Это третье слово!\n\n"
                "📖 ПОШАГОВЫЙ ПРОЦЕСС:\n\n"
                "ШАГ 1 - ОДНО НОВОЕ СЛОВО (точный формат):\n"
                "**ENGLISH WORD** 🔊 (транскрипция) - русский перевод\n"
                "Example: English sentence 🔊 — Русский перевод\n"
                "Попробуй использовать это слово!\n"
                ">>> СТОП! ЖДИ ответа студента! НЕ учи следующее слово!\n\n"
                "ШАГ 2 - СТУДЕНТ ПИШЕТ ПРЕДЛОЖЕНИЕ:\n"
                "Дай отзыв: 'Отлично! ✓' или 'Хорошо, но...'\n"
                "Задай тест: 'Как сказать \"[фраза]\" используя это слово?'\n"
                ">>> СТОП! ЖДИ ответа на тест!\n\n"
                "ШАГ 3 - СТУДЕНТ ОТВЕЧАЕТ НА ТЕСТ:\n"
                "Оцени ответ\n"
                "Если правильно: 'Отлично! ✓ Ты освоил это слово!'\n"
                ">>> ТОЛЬКО СЕЙЧАС можешь учить следующее слово!\n\n"
                "🚫 АБСОЛЮТНЫЙ ЗАПРЕТ:\n"
                "- НЕ учи Hello, Friend, Thanks в одном сообщении!\n"
                "- НЕ пиши списки слов!\n"
                "- НЕ пропускай ожидание ответа студента!\n"
                "- ОДНО слово = ОДНО сообщение → ЖДИ → следующее слово"
            )
        elif difficulty == "intermediate":
            system_prompt = (
                "Ты AI репетитор АНГЛИЙСКОГО (средний уровень).\n\n"
                "🔴 СТРОГО: ОДНО слово в сообщении - НЕ БОЛЬШЕ!\n\n"
                "Формат: **ENGLISH WORD** + грамматика + пример\n"
                "СТОП! Жди практики студента → отзыв → тест\n"
                "ТОЛЬКО после правильного ответа → следующее слово\n\n"
                "ЗАПРЕЩЕНО учить несколько слов подряд!\n"
                "ОДНО слово → СТОП → ЖДИ ответа → следующее"
            )
        else:
            system_prompt = (
                "Ты AI репетитор АНГЛИЙСКОГО (продвинутый).\n\n"
                "🔴 СТРОГО: ОДНА концепция в сообщении!\n\n"
                "Учи ОДНУ идиому/фразу → СТОП → практика → тест → следующая\n"
                "ЗАПРЕЩЕНО несколько концепций подряд!\n"
                "Проверяй историю - не повторяй изученное!"
            )
        tutor_prompt = (
            f"Студент просит: {user_msg}\n\n"
            "⚠️ КРИТИЧЕСКИ ВАЖНО:\n"
            "- Учи ТОЛЬКО ОДНО английское слово в этом сообщении!\n"
            "- НЕ учи 2, 3, 4 слова одновременно!\n"
            "- После обучения одному слову - СТОП, ЖДИ ответа студента!\n"
            "- НЕ начинай следующее слово пока студент не попрактикуется!\n\n"
            "НАЧНИ с ОДНОГО английского слова (не русского)!"
        )

    else:
        # Teaching Russian to English speakers
        level_guide = {
            "beginner": (
                "You are an AI Russian tutor teaching ENGLISH-speaking students.\n\n"
                "⚠️ CRITICAL RULES:\n"
                "1. Teach ONLY ONE WORD per message - NEVER multiple words!\n"
                "2. ALL explanations = ENGLISH ONLY (except the Russian word itself)\n"
                "3. WAIT for student to practice before teaching next word\n"
                "4. ALWAYS put 🔊 icon before example sentences for audio practice!\n\n"
                "📖 TEACHING FLOW - EXACT FORMAT TO FOLLOW:\n\n"
                "STEP 1 - TEACH ONE NEW WORD:\n"
                "**RUSSIAN WORD** 🔊 (pronunciation) - English meaning\n"
                "Example: Russian sentence 🔊 — English translation\n"
                "Try using this word in a sentence!\n\n"
                "STEP 2 - STUDENT PRACTICES (writes their sentence):\n"
                "Give feedback: 'Great pronunciation! ✓' or 'Good try, but...'\n"
                "Correct any mistakes\n"
                "Ask a test question: 'How would you say \"[English phrase]\" using this word?'\n\n"
                "STEP 3 - STUDENT ANSWERS TEST:\n"
                "Give feedback on their answer\n"
                "If correct: 'Perfect! ✓ You've mastered this word!'\n"
                "ONLY NOW → Teach the NEXT word (go back to STEP 1)\n\n"
                "🚫 NEVER teach 2+ words in one message!\n"
                "🚫 NEVER skip waiting for student practice!\n"
                "✅ ONE word → practice → test → feedback → NEXT word"
            ),
            "intermediate": (
                "You are an AI Russian tutor for ENGLISH-speaking students (intermediate).\n\n"
                "⚠️ CRITICAL: Teach ONE word at a time!\n"
                "ALL text = ENGLISH except the Russian word being taught!\n\n"
                "Format: **RUSSIAN WORD** + grammar notes + 1 example\n"
                "Wait for student to practice → give feedback → test with question\n"
                "ONLY after student answers correctly → teach next word\n"
                "Never teach multiple words in one message!"
            ),
            "advanced": (
                "You are an AI Russian tutor for ENGLISH-speaking students (advanced).\n\n"
                "⚠️ ONE concept at a time (idiom/phrase/aspect)\n"
                "Explain EVERYTHING in ENGLISH! Only Russian in Russian.\n\n"
                "Teach → student practices → test → feedback → next concept\n"
                "Never teach multiple concepts in one message!\n"
                "All explanations = ENGLISH ONLY!"
            )
        }
        system_prompt = (
            f"You are an expert Russian language tutor for ENGLISH speakers. Topic: {lesson_topic}. "
            f"{level_guide[difficulty]} "
            "\n\n🔒 ABSOLUTE RULES:\n"
            "1. Teach ONLY ONE WORD per message - NEVER multiple words at once!\n"
            "2. ALL explanations, feedback, questions = ENGLISH ONLY!\n"
            "3. ONLY the Russian word itself is in Russian\n"
            "4. WAIT for student to practice before teaching next word\n"
            "5. Test student's understanding with a question\n"
            "6. ONLY after student answers correctly → teach next word\n"
            "7. FORMAT: **Привет** 🔊 (pree-VYET) - Hello\n"
            "8. Example format: Example: Привет! Как дела? 🔊 — Hello! How are you?\n"
            "9. NEVER write instructions in Russian (like 'Теперь попробуй...')\n"
            "10. ONE word → practice → test → next word (strict sequential order!)\n"
            "11. Check conversation history - don't teach what was already taught"
        )
        tutor_prompt = f"Student: {user_msg}"

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

            # Save taught word/phrase for recap (best-effort)
            try:
                _save_taught_word(user_id, full, lesson_key, difficulty, language_mode)
            except Exception as _e:
                pass

            # Track word completion: Count every bold word as a taught word
            if re.search(r'\*\*[^\*]{2,}\*\*', full):
                # Log word completion for any message with bold words
                update_xp(user_id, 3, "word_complete")
            else:
                # Regular message XP (feedback, questions, etc)
                update_xp(user_id, 3, "message")
            uu = get_user(user_id)

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
    return (FRONTEND_DIR / "quiz.html").read_text(encoding="utf-8")

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
def admin_login(req: AdminLoginRequest, response: Response):
    con = db()
    try:
        password_hash = hash_password(req.password)
        admin = con.execute(
            "SELECT id, username FROM admins WHERE username=? AND password=?",
            (req.username, password_hash)
        ).fetchone()
        
        if not admin:
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
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

def _quiz_system_prompt_mcq(language_mode: str, category: str, difficulty: str, count: int) -> str:
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

    return f"""
You are a quiz generator. Output STRICT JSON ONLY. No markdown. No extra text.

{mode_rules}

TOPIC: {category_guide}
DIFFICULTY: {diff_guide}
COUNT: {count}

Make the quiz feel like Duolingo BUT MCQ ONLY. Use a mix of these MCQ styles:
1) "Выберите перевод" / "Choose the translation"
2) "Выберите правильный ответ" / "Choose the correct reply"
3) "Заполните пропуск" / "Fill the blank" (still MCQ options)
4) "Что это означает?" / "What does this mean?"

Return JSON with this schema:
{{
  "questions": [
    {{
      "prompt": "instruction in UI language",
      "q": "question text in UI language",
      "options": ["A","B","C","D"],   // target language
      "correct": 0,  // INDEX (0-3) of the CORRECT answer in options array
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

def _llm_generate_quiz_json(system_prompt: str) -> dict:
    """Generate quiz JSON using LLM (synchronous for OpenAI, async handled at call site for Ollama)"""
    if LLM_PROVIDER == "openai":
        client = openai_client()
        resp = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": "Generate the quiz JSON now."}
            ],
            max_tokens=1400,
            temperature=0.7,
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

        cleaned.append({
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
    count = max(5, min(30, count))

    system_prompt = _quiz_system_prompt_mcq(language_mode, category, difficulty, count)

    try:
        payload = _llm_generate_quiz_json(system_prompt)
        return _validate_mcq_payload(payload, count)
    except Exception as e:
        print("QUIZ GENERATION ERROR:", e)
        raise HTTPException(status_code=500, detail="Quiz generation failed")

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
    if category not in ("greetings", "travel", "food", "mixed"):
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