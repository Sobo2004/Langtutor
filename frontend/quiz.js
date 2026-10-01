/*******************************************************
 * LangTutor MCQ-only Duolingo Quiz
 * - AI MCQ questions (/api/quiz/generate)
 * - Hearts (3 lives)
 * - XP earned on submit (/api/quiz/submit)
 *******************************************************/

let quizConfig = {
  category: "greetings",
  difficulty: "beginner",
  questionCount: 10,
  languageMode: localStorage.getItem("languageMode") || "en-ru"  
};

let quizState = {
  questions: [],
  currentIndex: 0,
  answers: [],
  correct: [],
  score: 0,

  hearts: 3,
  xpMini: 0,

  startTime: 0,
  timeRemaining: 0,
  timerInterval: null,
  timeExpired: false,
  finished: false,
  serverXpEarned: 0
};

// Elements (these IDs must exist in quiz.html)
const setupScreen = document.getElementById("setupScreen");
const quizScreen = document.getElementById("quizScreen");
const resultsScreen = document.getElementById("resultsScreen");
const reviewScreen = document.getElementById("reviewScreen");

const timerDisplay = document.getElementById("timerDisplay");
const timerFill = document.getElementById("timerFill");

const questionNumber = document.getElementById("questionNumber");
const questionCategory = document.getElementById("questionCategory");
const promptText = document.getElementById("promptText");
const questionText = document.getElementById("questionText");
const hintBtn = document.getElementById("hintBtn");
const hintText = document.getElementById("hintText");

const answerGrid = document.getElementById("answerGrid");
const feedbackArea = document.getElementById("feedbackArea");

const xpMiniEl = document.getElementById("xpMini");
const heartEls = [
  document.getElementById("heart1"),
  document.getElementById("heart2"),
  document.getElementById("heart3")
];

// Results
const scorePercentage = document.getElementById("scorePercentage");
const correctCount = document.getElementById("correctCount");
const incorrectCount = document.getElementById("incorrectCount");
const timeTaken = document.getElementById("timeTaken");
const xpEarnedEl = document.getElementById("xpEarned");

// Review
const reviewList = document.getElementById("reviewList");

window.addEventListener("DOMContentLoaded", () => {
  quizConfig.languageMode = localStorage.getItem("languageMode") || "ru-en";

  document.querySelectorAll(".category-card").forEach(card => {
    card.addEventListener("click", function () {
      document.querySelectorAll(".category-card").forEach(c => c.classList.remove("active"));
      this.classList.add("active");
      quizConfig.category = this.dataset.category;
    });
  });

  document.querySelectorAll(".difficulty-btn").forEach(btn => {
    btn.addEventListener("click", function () {
      document.querySelectorAll(".difficulty-btn").forEach(b => b.classList.remove("active"));
      this.classList.add("active");
      quizConfig.difficulty = this.dataset.difficulty;
    });
  });

  hintBtn?.addEventListener("click", () => {
    if (!hintText.textContent) return;
    hintText.style.display = (hintText.style.display === "none" || !hintText.style.display) ? "inline" : "none";
  });

  updateHeartsUI();
  updateXpMini();
});

function changeCount(delta) {
  const el = document.getElementById("questionCount");
  const current = parseInt(el.textContent, 10);
  const next = Math.max(5, Math.min(30, current + delta));
  el.textContent = next;
  quizConfig.questionCount = next;
}

async function startQuiz() {
  quizConfig.languageMode = localStorage.getItem("languageMode") || "ru-en";

  quizState = {
    questions: [],
    currentIndex: 0,
    answers: [],
    correct: [],
    score: 0,
    hearts: 3,
    xpMini: 0,
    startTime: Date.now(),
    timeRemaining: 0,
    timerInterval: null,
    timeExpired: false,
    finished: false,
    serverXpEarned: 0
  };

  updateHeartsUI();
  updateXpMini();

  const questions = await fetchQuizFromAPI();
  if (!questions || !questions.length) {
    alert("Quiz generation failed. Please try again.");
    return;
  }

  quizState.questions = questions.slice(0, quizConfig.questionCount);
  quizState.answers = new Array(quizState.questions.length).fill(null);
  quizState.correct = new Array(quizState.questions.length).fill(false);

  quizState.timeRemaining = quizState.questions.length * 60;

  setupScreen.style.display = "none";
  quizScreen.classList.add("active");
  resultsScreen.classList.remove("active");
  reviewScreen.classList.remove("active");

  startTimer();
  renderQuestion();
}

async function fetchQuizFromAPI() {
  try {
    const res = await fetch("/api/quiz/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        language_mode: quizConfig.languageMode,
        category: quizConfig.category,
        difficulty: quizConfig.difficulty,
        count: quizConfig.questionCount
      })
    });

    if (!res.ok) {
      console.error("Quiz API error:", await res.text());
      return null;
    }

    const data = await res.json();
    if (!data || !Array.isArray(data.questions)) return null;
    return data.questions;
  } catch (e) {
    console.error("Quiz API fetch failed:", e);
    return null;
  }
}

function startTimer() {
  clearInterval(quizState.timerInterval);
  updateTimerUI();

  quizState.timerInterval = setInterval(() => {
    if (quizState.timeExpired || quizState.finished) return;

    quizState.timeRemaining -= 1;
    if (quizState.timeRemaining <= 0) {
      quizState.timeRemaining = 0;
      quizState.timeExpired = true;
      clearInterval(quizState.timerInterval);
      finishQuiz(true);
    }
    updateTimerUI();
  }, 1000);
}

function updateTimerUI() {
  const total = quizState.questions.length * 60;
  const remaining = quizState.timeRemaining;

  const min = Math.floor(remaining / 60);
  const sec = remaining % 60;
  timerDisplay.textContent = `${min}:${String(sec).padStart(2, "0")}`;

  const pct = total > 0 ? Math.max(0, Math.min(100, (remaining / total) * 100)) : 0;
  timerFill.style.width = `${pct}%`;
}

function renderQuestion() {
  feedbackArea.innerHTML = "";
  hintText.textContent = "";
  hintText.style.display = "none";

  const q = quizState.questions[quizState.currentIndex];
  if (!q) return;

  questionNumber.textContent = `Question ${quizState.currentIndex + 1} of ${quizState.questions.length}`;
  questionCategory.textContent = formatCategory(quizConfig.category);

  promptText.textContent = q.prompt || "";
  questionText.textContent = q.q || "";
  hintText.textContent = q.explanation || ""; // use explanation as hint text

  answerGrid.innerHTML = "";

  (q.options || []).slice(0, 4).forEach((opt, idx) => {
    const btn = document.createElement("button");
    btn.className = "answer-option";
    btn.type = "button";
    btn.textContent = opt;
    btn.onclick = () => gradeMCQ(q, idx);
    answerGrid.appendChild(btn);
  });
}

function gradeMCQ(q, chosenIdx) {
  if (quizState.answers[quizState.currentIndex] !== null) return;

  const correctIdx = typeof q.correct === "number" ? q.correct : -1;
  quizState.answers[quizState.currentIndex] = chosenIdx;

  const buttons = [...answerGrid.querySelectorAll(".answer-option")];
  buttons.forEach((b, i) => {
    b.disabled = true;
    if (i === correctIdx) b.classList.add("correct");
    if (i === chosenIdx && chosenIdx !== correctIdx) b.classList.add("wrong");
  });

  const isCorrect = chosenIdx === correctIdx;
  quizState.correct[quizState.currentIndex] = isCorrect;

  if (isCorrect) {
    quizState.score += 1;
    quizState.xpMini += 10;
    updateXpMini();
  } else {
    quizState.hearts -= 1;
    updateHeartsUI();
  }

  const correctText = (q.options && q.options[correctIdx]) ? q.options[correctIdx] : "";
  showFeedback(isCorrect, correctText, q.explanation || "", () => {
    if (quizState.hearts <= 0) {
      finishQuiz(false, true);
      return;
    }
    if (quizState.currentIndex < quizState.questions.length - 1) {
      quizState.currentIndex += 1;
      renderQuestion();
    } else {
      finishQuiz(false);
    }
  });
}

function showFeedback(isCorrect, correctAnswer, explanation, onContinue) {
  feedbackArea.innerHTML = "";

  const wrap = document.createElement("div");
  wrap.className = "feedback " + (isCorrect ? "ok" : "bad");

  const left = document.createElement("div");
  left.className = "fb-left";

  const title = document.createElement("div");
  title.className = "fb-title";
  title.textContent = isCorrect ? "✅ Correct!" : "❌ Not quite";

  const sub = document.createElement("div");
  sub.className = "fb-sub";
  sub.innerHTML = `<strong>Answer:</strong> ${escapeHtml(correctAnswer)}${explanation ? `<br>${escapeHtml(explanation)}` : ""}`;

  left.appendChild(title);
  left.appendChild(sub);

  const btn = document.createElement("button");
  btn.className = "continue-btn";
  btn.type = "button";
  btn.textContent = (quizState.currentIndex === quizState.questions.length - 1 || quizState.hearts <= 0)
    ? "Finish"
    : "Continue";
  btn.onclick = onContinue;

  wrap.appendChild(left);
  wrap.appendChild(btn);
  feedbackArea.appendChild(wrap);
}

async function finishQuiz(expired, endedByHearts = false) {
  if (quizState.finished) return;
  quizState.finished = true;

  clearInterval(quizState.timerInterval);

  quizScreen.classList.remove("active");
  resultsScreen.classList.add("active");
  reviewScreen.classList.remove("active");

  const total = quizState.questions.length;
  const correct = quizState.score;
  const incorrect = total - correct;

  const percent = total ? Math.round((correct / total) * 100) : 0;
  scorePercentage.textContent = `${percent}%`;
  correctCount.textContent = String(correct);
  incorrectCount.textContent = String(incorrect);

  const secondsTaken = Math.max(0, Math.floor((Date.now() - quizState.startTime) / 1000));
  timeTaken.textContent = formatTime(secondsTaken);

  // submit for XP
  const xpEarned = await submitQuizResult({
    category: quizConfig.category,
    difficulty: quizConfig.difficulty,
    language_mode: quizConfig.languageMode,
    total_questions: total,
    correct_answers: correct,
    time_taken: secondsTaken,
    ended_by_hearts: endedByHearts,
    ended_by_time: expired,
    hearts_left: quizState.hearts
  });

  quizState.serverXpEarned = xpEarned || 0;
  xpEarnedEl.textContent = String(quizState.serverXpEarned);
}

async function submitQuizResult(payload) {
  try {
    const res = await fetch("/api/quiz/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      console.error("Quiz submit failed:", await res.text());
      return 0;
    }
    const data = await res.json();
    return data?.xp_earned ?? 0;
  } catch (e) {
    console.error("Quiz submit error:", e);
    return 0;
  }
}

function reviewAnswers() {
  resultsScreen.classList.remove("active");
  reviewScreen.classList.add("active");

  reviewList.innerHTML = "";

  quizState.questions.forEach((q, i) => {
    const item = document.createElement("div");
    item.className = "review-item";

    const badge = document.createElement("div");
    badge.className = "review-badge";
    badge.textContent = quizState.correct[i] ? "✅" : "❌";

    const qEl = document.createElement("div");
    qEl.className = "review-q";
    qEl.textContent = `${i + 1}. ${q.q}`;

    const ua = quizState.answers[i];
    const chosen = (ua === null || ua === undefined) ? "No answer" : (q.options?.[ua] || "No answer");

    const userEl = document.createElement("div");
    userEl.className = "review-a";
    userEl.innerHTML = `<strong>Your answer:</strong> ${escapeHtml(chosen)}`;

    const corrEl = document.createElement("div");
    corrEl.className = "review-c";
    const correctText = q.options?.[q.correct] || "";
    corrEl.innerHTML = `<strong>Correct:</strong> ${escapeHtml(correctText)}`;

    item.appendChild(badge);
    item.appendChild(qEl);
    item.appendChild(userEl);
    item.appendChild(corrEl);

    if (q.explanation) {
      const exp = document.createElement("div");
      exp.className = "review-exp";
      exp.textContent = q.explanation;
      item.appendChild(exp);
    }

    reviewList.appendChild(item);
  });
}

function backToResults() {
  reviewScreen.classList.remove("active");
  resultsScreen.classList.add("active");
}

function updateHeartsUI() {
  for (let i = 0; i < 3; i++) {
    heartEls[i].style.opacity = (i < quizState.hearts) ? "1" : "0.25";
  }
}

function updateXpMini() {
  xpMiniEl.textContent = String(quizState.xpMini || 0);
}

function formatCategory(cat) {
  const map = { greetings: "Greetings", travel: "Travel", food: "Food", mixed: "Mixed" };
  return map[cat] || "Quiz";
}

function formatTime(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

function escapeHtml(str) {
  return String(str || "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

// Speaker button function for quiz questions
function speakQuizQuestion() {
  const q = quizState.questions[quizState.currentIndex];
  if (!q || !q.q) return;
  
  if (!('speechSynthesis' in window)) {
    alert('Text-to-speech is not supported in your browser.');
    return;
  }
  
  speechSynthesis.cancel();
  
  const utterance = new SpeechSynthesisUtterance(q.q);
  
  // Determine language based on mode
  // In en-ru mode: questions are in English, so speak English
  // In ru-en mode: questions are in Russian, so speak Russian
  utterance.lang = quizConfig.languageMode === 'ru-en' ? 'ru-RU' : 'en-US';
  utterance.rate = 0.8;
  utterance.pitch = 1;
  utterance.volume = 1;
  
  // Select appropriate voice
  const voices = speechSynthesis.getVoices();
  const lang = utterance.lang.split('-')[0];
  const targetVoice = voices.find(v => v.lang.startsWith(lang));
  if (targetVoice) {
    utterance.voice = targetVoice;
  }
  
  speechSynthesis.speak(utterance);
}