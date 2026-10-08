# Russian-English Language Tutor 🇷🇺 ↔️ 🇬🇧

A full-stack web application for learning Russian and English through interactive AI-powered conversations. Features gamification, progress tracking, quizzes, and an admin dashboard for monitoring user activity.

---

## 🌟 Features

### For Students
- **Interactive AI Tutor**: Real-time conversations with personalized learning
- **Bilingual Learning**: Switch between Russian → English or English → Russian modes
- **Gamification**: Earn XP, level up, and maintain daily streaks
- **Difficulty Levels**: Beginner, Intermediate, and Advanced modes
- **Interactive Quizzes**: Test your knowledge with multiple-choice questions
- **Progress Tracking**: View detailed statistics and learning history
- **Leaderboard**: Compete with other learners
- **Daily Recap**: Review previously learned words and concepts
- **User Profiles**: Customize avatars, set learning goals, and track milestones

### For Administrators
- **User Management**: View and manage all registered users
- **Analytics Dashboard**: Monitor total users, XP, and activity metrics
- **Quiz Performance Tracking**: Compare user scores with visual charts
- **Detailed User Profiles**: Access individual learning data and progress

---

## 🚀 Quick Start

### Prerequisites
- **Python 3.8+**
- **OpenAI API Key** (get one at [platform.openai.com/api-keys](https://platform.openai.com/api-keys))

### Installation

1. **Install Python dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **Create a `.env` file** in the project folder (it is git-ignored, so secrets are never committed):
   ```
   LLM_PROVIDER=openai
   OPENAI_API_KEY=your_openai_api_key
   OPENAI_MODEL=gpt-4o-mini
   ADMIN_PASSWORD=choose_a_strong_password
   ```
   Optional: `OPENAI_TTS_MODEL`, `OPENAI_TTS_VOICE` (Mila's voice), and `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_FROM` for password-reset emails.

3. **Start the server:**
   ```bash
   python -m uvicorn main:app --reload
   ```

4. **Open in browser:**
   ```
   http://127.0.0.1:8000
   ```

---

## 📖 How to Use

### First Time Setup
1. Open the application in your browser
2. Click **"Sign Up"** to create an account
3. Complete the onboarding:
   - Choose your avatar
   - Set your learning goal
   - Select your difficulty level
   - Set your daily practice time
4. Start learning!

### Learning Flow
1. **Chat with the AI tutor** - Ask questions, request lessons, or practice conversations
2. **Complete quizzes** - Test your knowledge after each lesson
3. **Track progress** - View your XP, streak, and words learned
4. **Compete** - Check the leaderboard to see how you rank

### Admin Access
- **URL**: `http://127.0.0.1:8000/admin`
- **Credentials**: username `admin`; set the password with `ADMIN_PASSWORD` in `.env` (if unset, a random one is printed in the server console when the database is first created)
- ⚠️ **Important**: Change the admin password after first login for security

---

## 🎮 Key Concepts

### XP & Levels
- Earn **3 XP** for each message with new vocabulary
- Progress through levels: A1 → A2 → B1 → B2 → C1 → C2
- Every 100 XP = New level

### Streaks
- Practice daily to maintain your streak
- Missing a day resets your streak to 1

### Word Counter
- Tracks cumulative words learned (never resets)
- Counts every new vocabulary word introduced in lessons

### Quizzes
- Multiple-choice questions based on recent lessons
- Scores are tracked and displayed in your progress page
- Compare your performance with other learners

---

## 🛠️ Project Structure

```
projectai3/
├── main.py              # Backend API (FastAPI)
├── requirements.txt     # Python dependencies
├── .env                 # Configuration (API keys)
├── .env                 # Your settings and API key (not committed)
├── README.md            # This file
└── frontend/
    ├── index.html       # Main app UI
    ├── app.js           # Core functionality
    ├── style.css        # Main styles
    ├── admin.html       # Admin dashboard
    ├── profile.html     # User profile page
    ├── progress.html    # Progress tracking page
    ├── leaderboard.html # Leaderboard page
    ├── quiz.html        # Quiz interface
    └── [other assets]
```

---

## 💾 Database

The application uses **SQLite** for data storage. The database file (`app.db`) is automatically created on first run.

### Tables
- **users** - User accounts and progress
- **sessions** - Login sessions
- **chat_history** - Conversation logs
- **xp_log** - XP and learning events
- **quiz_scores** - Quiz performance data
- **admins** - Admin accounts

---

## 🔐 Security Features

- **Password Hashing**: bcrypt (salted, deliberately slow); older SHA-256 accounts are upgraded on their next login
- **Rate Limiting**: login/sign-up attempts per IP, and AI chat, quiz and voice requests per user
- **XSS Protection**: AI replies and stored words are escaped before being shown on the page
- **Session Management**: HttpOnly, SameSite cookies
- **Session Expiry**: Auto-logout after 30 days of inactivity
- **Data Isolation**: Each user's data is completely separate
- **Admin Protection**: Separate authentication; password set with `ADMIN_PASSWORD` in `.env`

---

## 🧪 Tests

```bash
pip install -r requirements-dev.txt
python -m pytest
```

Tests use a temporary database and a fake AI, so they never touch `app.db` or call OpenAI.

- `tests/` (backend): passwords and login, rate limits, card parsers, course content and progress, word export, and a full chat lesson.
- `tests/frontend/` (browser, Playwright): HTML escaping of AI replies, answer marking, what Mila reads aloud, the phone layout and keyboard access. Run `python -m playwright install chromium` once, or use an installed browser with `PW_CHANNEL=msedge`.

GitHub Actions (`.github/workflows/ci.yml`) runs every test on each push, then builds the Docker image and checks the container starts.

---

## 🐳 Docker

```bash
docker build -t langtutor .
docker run -p 8000:8000 --env-file .env -v langtutor-data:/data langtutor
```

The database is kept in the `langtutor-data` volume; `.env` is never copied into the image.

---

## 🎨 Customization

### Change Learning Language
Currently supports:
- **English → Russian** (learn Russian)
- **Russian → English** (learn English)

Toggle in the app using the language switcher in the top-right corner.

### Modify Difficulty
Three levels available:
- **Beginner**: Basic vocabulary and simple sentences
- **Intermediate**: Conversations and grammar practice
- **Advanced**: Complex sentences and idiomatic expressions

Change in your profile settings or during lessons.

---

## 🐛 Troubleshooting

### Server won't start
- Check that Python 3.8+ is installed: `python --version`
- Verify all dependencies are installed: `pip install -r requirements.txt`
- Ensure port 8000 is not already in use

### API errors
- Verify your OpenAI API key is correct in `.env`
- Check you have credits in your OpenAI account
- Ensure you're connected to the internet

### Database issues
- Delete `app.db` to reset the database (all data will be lost)
- The database will be auto-recreated on next server start

---

## 📝 License

This is a custom-built educational application. All rights reserved.

---

## 🆘 Support

For technical support or questions:
- Check the troubleshooting section above
- Review the code comments in `main.py` and frontend files
- Consult the FastAPI documentation: [fastapi.tiangolo.com](https://fastapi.tiangolo.com)
- Consult the OpenAI API documentation: [platform.openai.com/docs](https://platform.openai.com/docs)

---

**Built with:** FastAPI, OpenAI GPT-4, SQLite, Vanilla JavaScript, and HTML/CSS

**Version:** 1.0.0
