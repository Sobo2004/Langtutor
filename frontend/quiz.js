/*******************************************************
 * LangTutor Quiz — chat with Mila
 * - Mila asks each question in a chat bubble and speaks (/api/tts)
 * - The learner answers by tapping a choice, typing, or speaking (mic)
 * - Question kinds: choice, listen ("tap what you hear"), type
 * - AI questions (/api/quiz/generate), loaded in parallel batches
 * - "My Lessons" review of words taught in chat, or a topic quiz
 * - Hearts (3 lives), XP earned on submit (/api/quiz/submit)
 *******************************************************/

let quizConfig = {
  category: "lessons",
  difficulty: localStorage.getItem("difficulty") || "beginner",  // same level as the chat
  questionCount: 10,
  languageMode: localStorage.getItem("languageMode") || "en-ru",
  // Words from a chat round (/quiz?words=a|b|c), set by Mila's end-of-round checkpoint
  roundWords: (new URLSearchParams(location.search).get("words") || "").split("|").map(w => w.trim()).filter(Boolean).slice(0, 20),
  // A grammar topic's final quiz (/quiz?words=...&grammar=level/topic)
  grammarTopic: new URLSearchParams(location.search).get("grammar") || null
};

let quizState = newQuizState();

function newQuizState() {
  return {
    questions: [],
    kinds: [],
    expectedTotal: 0,
    pendingBatches: 0,
    phase: "idle",          // greeting | waiting | asking | answering | feedback | done
    waitTyping: null,
    currentIndex: 0,
    answers: [],
    correct: [],
    answered: 0,
    score: 0,
    streak: 0,

    hearts: 3,
    xpMini: 0,

    startTime: 0,
    finished: false,
    serverXpEarned: 0
  };
}

// Elements (these IDs must exist in quiz.html)
const setupScreen = document.getElementById("setupScreen");
const quizScreen = document.getElementById("quizScreen");
const resultsScreen = document.getElementById("resultsScreen");
const reviewScreen = document.getElementById("reviewScreen");
const startBtn = document.getElementById("startBtn");

const progressFill = document.getElementById("progressFill");
const chatLog = document.getElementById("chatLog");
const composer = document.getElementById("composer");
const tutorStatus = document.getElementById("tutorStatus");
const muteBtn = document.getElementById("muteBtn");

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
const resultsTutorSay = document.getElementById("resultsTutorSay");
const resultsTutorSub = document.getElementById("resultsTutorSub");

// Review
const reviewList = document.getElementById("reviewList");

const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

window.addEventListener("DOMContentLoaded", () => {
  quizConfig.languageMode = localStorage.getItem("languageMode") || "en-ru";

  // Setup screen
  document.getElementById("switchLangBtn").addEventListener("click", switchLanguage);
  document.querySelectorAll(".topic-links button").forEach(btn => {
    btn.addEventListener("click", () => startQuiz(btn.dataset.topic));
  });
  renderSetupLabels();
  loadLessonWords();

  muteBtn?.addEventListener("click", () => {
    voice.setMuted(!voice.muted);
    updateMuteUI();
  });

  // Keyboard: 1-4 picks a choice, Enter continues
  document.addEventListener("keydown", e => {
    if (!quizScreen.classList.contains("active") || e.target.tagName === "INPUT") return;
    const n = parseInt(e.key, 10);
    if (n >= 1 && n <= 4) {
      composer.querySelectorAll(".choice")[n - 1]?.click();
    } else if (e.key === "Enter") {
      const cont = composer.querySelector(".continue-btn");
      if (cont) { e.preventDefault(); cont.click(); }
    }
  });

  updateMuteUI();
  updateHeartsUI();
  updateXpMini();
});

/* ================== SETUP SCREEN ================== */

let lessonWordCount = 0;

const SETUP_TEXT = {
  "en-ru": {
    learning: "Learning Russian",
    switchTo: "switch to English",
    topics: "Or practise a topic:",
    topicNames: { greetings: "Greetings", travel: "Travel", food: "Food" },
    loading: "Getting your words ready…",
    ready: "Ready to review what we learnt?",
    words: n => `${n} words and phrases from our chats`,
    locked: "Learn at least 3 words with me in the chat first!",
    soFar: n => `You've learnt ${n} so far, just ${3 - n} more to go.`,
    start: "▶  Start review with Mila",
    goChat: "Go to chat",
    roundReady: "Let's test this round's words!",
    roundSub: n => `${n} words from our last round`,
    finalReady: "Final quiz time!",
    finalSub: n => `All ${n} ${quizConfig.grammarTopic ? "lessons" : "words"} from this topic`
  },
  "ru-en": {
    learning: "Изучаем английский",
    switchTo: "переключить на русский",
    topics: "Или потренируй тему:",
    topicNames: { greetings: "Приветствия", travel: "Путешествия", food: "Еда" },
    loading: "Готовлю твои слова…",
    ready: "Повторим, что мы выучили?",
    words: n => `${n} слов и фраз из наших чатов`,
    locked: "Сначала выучи со мной хотя бы 3 слова в чате!",
    soFar: n => `Уже выучено: ${n}. Осталось совсем чуть-чуть: ${3 - n}.`,
    start: "▶  Повторить с Милой",
    goChat: "Перейти в чат",
    roundReady: "Проверим слова этого раунда!",
    roundSub: n => `${n} слов из нашего последнего раунда`,
    finalReady: "Итоговый тест!",
    finalSub: n => `Все ${n} ${quizConfig.grammarTopic ? "уроков" : "слов"} этой темы`
  }
};

function setupText() {
  return SETUP_TEXT[quizConfig.languageMode] || SETUP_TEXT["en-ru"];
}

function renderSetupLabels() {
  const t = setupText();
  document.getElementById("learningLabel").textContent = t.learning;
  document.getElementById("switchLangBtn").textContent = t.switchTo;
  document.getElementById("topicsLabel").textContent = t.topics + " ";
  document.querySelectorAll(".topic-links button").forEach(btn => {
    btn.textContent = t.topicNames[btn.dataset.topic];
  });
}

// Same switch as the chat page: en-ru (learning Russian) <-> ru-en (learning English)
function switchLanguage() {
  quizConfig.languageMode = quizConfig.languageMode === "en-ru" ? "ru-en" : "en-ru";
  try { localStorage.setItem("languageMode", quizConfig.languageMode); } catch (e) {}
  renderSetupLabels();
  loadLessonWords();
}

// "My Lessons": a quiz built from the words Mila taught in chat
async function loadLessonWords() {
  const t = setupText();
  const say = document.getElementById("setupSay");
  const sub = document.getElementById("setupSub");
  const list = document.getElementById("lessonWords");

  say.textContent = t.loading;
  sub.textContent = "";
  list.innerHTML = "";
  startBtn.disabled = true;
  startBtn.textContent = t.start;

  // Quiz on a chat round's words
  if (quizConfig.roundWords.length >= 3) {
    lessonWordCount = quizConfig.roundWords.length;
    // More than one round's worth of words = a topic's final quiz
    const final = lessonWordCount > 5 || !!quizConfig.grammarTopic;
    say.textContent = final ? t.finalReady : t.roundReady;
    sub.textContent = final ? t.finalSub(lessonWordCount) : t.roundSub(lessonWordCount);
    quizConfig.roundWords.forEach(w => list.appendChild(el("span", "", w)));
    startBtn.disabled = false;
    startBtn.classList.remove("go-chat");
    startBtn.onclick = () => startQuiz("lessons");
    Mila.setMood("happy");
    return;
  }

  let words = [];
  try {
    const res = await fetch(`/api/quiz/lesson-words?language_mode=${encodeURIComponent(quizConfig.languageMode)}`);
    if (res.ok) words = (await res.json()).words || [];
  } catch (e) {
    console.warn("Couldn't load lesson words:", e);
  }
  lessonWordCount = words.length;
  startBtn.disabled = false;

  if (words.length < 3) {
    say.textContent = t.locked;
    sub.textContent = words.length ? t.soFar(words.length) : "";
    startBtn.textContent = t.goChat;
    startBtn.classList.add("go-chat");
    startBtn.onclick = () => { location.href = "/"; };
    Mila.setMood("idle");
    return;
  }

  say.textContent = t.ready;
  sub.textContent = t.words(words.length);
  words.slice(0, 12).forEach(w => {
    const chip = el("span", "", w.word);
    if (w.meaning) chip.title = w.meaning;
    list.appendChild(chip);
  });
  if (words.length > 12) list.appendChild(el("span", "", `+${words.length - 12}`));
  startBtn.classList.remove("go-chat");
  startBtn.onclick = () => startQuiz("lessons");
  Mila.setMood("happy");
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

/* ================== LANGUAGE HELPERS ================== */

// ru-en: Russian speakers learning English. en-ru: English speakers learning Russian.
const UI_TEXT = {
  "ru-en": {
    listenPrompt: "Нажмите на то, что услышали",
    writePrompt: "Напишите по-английски",
    blankPrompt: "Впишите пропущенное слово",
    placeholder: "Введите ответ…",
    send: "Ответить",
    showOptions: "Показать варианты",
    enterHint: "Enter ↵ — ответить",
    micHint: "Можно сказать ответ вслух",
    listening: "Слушаю…",
    micError: "Не расслышала. Попробуйте ещё раз.",
    continue: "Продолжить",
    finish: "Результаты",
    hint: "Подсказка",
    replay: "Ещё раз",
    answerIs: "Правильный ответ:",
    spelling: "Почти! Правильное написание:",
    online: "в сети",
    typing: "печатает…",
    speaking: "говорит…",
    failed: "Не получилось загрузить вопросы. Попробуйте ещё раз.",
    retry: "Попробовать снова",
    questionOf: (a, b) => `Вопрос ${a} из ${b}`
  },
  "en-ru": {
    listenPrompt: "Tap what you hear",
    writePrompt: "Write this in Russian",
    blankPrompt: "Type the missing word",
    placeholder: "Type your answer…",
    send: "Check",
    showOptions: "Show options instead",
    enterHint: "Press Enter ↵ to check",
    micHint: "You can also say it out loud",
    listening: "Listening…",
    micError: "I didn't catch that. Try again.",
    continue: "Continue",
    finish: "See results",
    hint: "Hint",
    replay: "Replay",
    answerIs: "Correct answer:",
    spelling: "Almost! Watch the spelling:",
    online: "online",
    typing: "typing…",
    speaking: "speaking…",
    failed: "I couldn't load the questions. Please try again.",
    retry: "Try again",
    questionOf: (a, b) => `Question ${a} of ${b}`
  }
};

function ui() {
  return UI_TEXT[quizConfig.languageMode] || UI_TEXT["ru-en"];
}

function targetLang() {
  return quizConfig.languageMode === "ru-en" ? "en" : "ru";
}

// Is this text in the language being learned? (Only those get spoken aloud.)
function isTargetLanguage(text) {
  return /[а-яё]/i.test(text) === (targetLang() === "ru");
}

function speakable(text) {
  return String(text || "").replace(/_{2,}/g, "…");
}

/* ================== VOICE ================== */

// Mila's voice and face are shared with the rest of the site (mila.js)
const voice = Mila.voice;
const MILA_SVG = Mila.SVG;
Mila.onTalking(on => setStatus(on ? "speaking" : "online"));

function updateMuteUI() {
  if (!muteBtn) return;
  Mila.setIcon(muteBtn, voice.muted ? "mute" : "volume");
  muteBtn.title = voice.muted ? "Turn Mila's voice on" : "Mute Mila";
}

/* ================== TUTOR (Mila) ================== */

// Mila speaks the language being learned; the bubble shows a translation underneath.
const TUTOR_LINES = {
  "ru-en": {
    loading:  [["Hi! I'm Mila. Let's practice!", "Привет! Я Мила. Давай потренируемся!"]],
    review:   [["Let's review what we learnt together!", "Давай повторим, что мы выучили вместе!"]],
    correct:  [["Great job!", "Отлично!"], ["Yes! That's right!", "Да! Верно!"], ["Nice work!", "Молодец!"], ["Perfect!", "Идеально!"]],
    streak:   [["You're on fire!", "Ты в ударе!"], ["Amazing, keep going!", "Потрясающе, продолжай!"]],
    wrong:    [["Almost! Let's keep going.", "Почти! Продолжаем."], ["Don't worry, you've got this.", "Не переживай, у тебя получится."]],
    lastHeart:[["Careful, one heart left!", "Осторожно, осталось одно сердечко!"]],
    endGood:  [["Fantastic result! I'm proud of you!", "Фантастический результат! Я тобой горжусь!"]],
    endOk:    [["Good effort! Practice makes perfect.", "Хорошая попытка! Повторение — мать учения."]],
    endBad:   [["Nice try! Let's practice again soon.", "Неплохо! Давай скоро потренируемся ещё."]]
  },
  "en-ru": {
    loading:  [["Привет! Я Мила. Давай потренируемся!", "Hi! I'm Mila. Let's practice!"]],
    review:   [["Давай повторим, что мы выучили вместе!", "Let's review what we learnt together!"]],
    correct:  [["Отлично!", "Great job!"], ["Да, правильно!", "Yes, that's right!"], ["Молодец!", "Well done!"], ["Идеально!", "Perfect!"]],
    streak:   [["Ты в ударе!", "You're on fire!"], ["Потрясающе, продолжай!", "Amazing, keep going!"]],
    wrong:    [["Почти! Продолжаем.", "Almost! Let's keep going."], ["Не переживай, получится!", "Don't worry, you've got this!"]],
    lastHeart:[["Осторожно, осталось одно сердечко!", "Careful, one heart left!"]],
    endGood:  [["Фантастический результат! Я тобой горжусь!", "Fantastic result! I'm proud of you!"]],
    endOk:    [["Хорошая попытка! Повторение — мать учения.", "Good effort! Practice makes perfect."]],
    endBad:   [["Неплохо! Давай скоро потренируемся ещё.", "Nice try! Let's practice again soon."]]
  }
};

function tutorLines() {
  return TUTOR_LINES[quizConfig.languageMode] || TUTOR_LINES["ru-en"];
}

function pickLine(kind) {
  const list = tutorLines()[kind];
  return list[Math.floor(Math.random() * list.length)];
}

// mood: idle | happy | sad | thinking
function setTutorMood(mood) {
  Mila.setMood(mood);
}

function setStatus(kind) {
  if (tutorStatus) tutorStatus.textContent = ui()[kind] || "";
}

/* ================== CHAT ================== */

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function scrollChat() {
  requestAnimationFrame(() => { chatLog.scrollTop = chatLog.scrollHeight; });
}

// Adds a Mila bubble and returns it so content can be appended
function addMilaBubble() {
  const row = el("div", "msg mila");
  const avatar = el("div", "mini-avatar");
  avatar.innerHTML = MILA_SVG;
  const bubble = el("div", "bubble");
  row.append(avatar, bubble);
  chatLog.appendChild(row);
  scrollChat();
  return bubble;
}

function addUserBubble(text, result) {
  const row = el("div", "msg user " + (result || ""));
  row.appendChild(el("div", "bubble", text));
  chatLog.appendChild(row);
  scrollChat();
}

function showTyping() {
  const bubble = addMilaBubble();
  bubble.classList.add("typing");
  bubble.innerHTML = "<span></span><span></span><span></span>";
  setStatus("typing");
  return bubble.parentElement;
}

// Mila says one of her lines: bubble + voice. Resolves when she's done speaking.
function milaSays(kind, mood) {
  const [say, sub] = pickLine(kind);
  const bubble = addMilaBubble();
  bubble.appendChild(el("div", "", say));
  bubble.appendChild(el("div", "sub", sub));
  setTutorMood(mood);
  return { bubble, spoken: voice.speak(say) };
}

/* ================== QUIZ FLOW ================== */

// Small first batch so question 1 shows fast; the rest load in parallel while the user plays.
function batchSizes(total) {
  const sizes = [Math.min(2, total)];
  let left = total - sizes[0];
  while (left > 0) {
    const n = Math.min(4, left);
    sizes.push(n);
    left -= n;
  }
  return sizes;
}

// Mix of question kinds, like Duolingo
function kindFor(q, i) {
  const answer = q.options[q.correct] || "";
  // Listening/typing only make sense when the answer is in the language being learned
  if (i === 0 || !isTargetLanguage(answer)) return "choice";
  if (i % 3 === 1) return "listen";
  if (i % 3 === 2 && (q.style === 1 || q.style === 3) && answer.split(/\s+/).length <= 4 && answer.length <= 30) return "type";
  return "choice";
}

// What Mila reads aloud when asking a question (null = nothing worth speaking)
function questionSpeech(i) {
  const q = quizState.questions[i];
  if (!q) return null;
  if (quizState.kinds[i] === "listen") return q.options[q.correct];
  return isTargetLanguage(q.q) ? speakable(q.q) : null;
}

async function startQuiz(category) {
  quizConfig.category = category;
  // Lesson reviews: about 2 questions per learnt word, 5-10 in total
  quizConfig.questionCount = category !== "lessons" ? 10
    : quizConfig.roundWords.length >= 3 ? Math.min(10, quizConfig.roundWords.length + 3)  // round: 8, whole topic: 10
    : Math.max(5, Math.min(10, lessonWordCount * 2));

  quizConfig.languageMode = localStorage.getItem("languageMode") || "en-ru";
  if (startBtn) startBtn.disabled = true;

  quizState = newQuizState();
  const s = quizState;
  s.expectedTotal = quizConfig.questionCount;
  s.phase = "greeting";

  setupScreen.style.display = "none";
  quizScreen.classList.add("active");
  resultsScreen.classList.remove("active");
  reviewScreen.classList.remove("active");
  chatLog.innerHTML = "";
  composer.innerHTML = "";
  updateHeartsUI();
  updateXpMini();
  updateProgress();

  loadQuestions(s);

  // Greeting while the first questions load
  const typing = showTyping();
  await sleep(600);
  typing.remove();
  const { spoken } = milaSays(quizConfig.category === "lessons" ? "review" : "loading", "happy");
  await Promise.all([sleep(1200), Promise.race([spoken, sleep(4000)])]);

  if (quizState !== s || s.finished) return;
  askCurrent();
}

function loadQuestions(s) {
  const seen = new Set();
  const sizes = batchSizes(quizConfig.questionCount);
  s.pendingBatches = sizes.length;

  sizes.forEach((size, batch) => {
    fetchQuizBatch(size, batch, sizes.length).then(questions => {
      if (quizState !== s) return; // a newer quiz was started

      for (const q of questions || []) {
        const key = (q.q + "|" + q.options[q.correct]).toLowerCase();
        if (seen.has(key) || s.questions.length >= s.expectedTotal) continue;
        seen.add(key);
        s.kinds.push(kindFor(q, s.questions.length));
        s.questions.push(q);
        s.answers.push(null);
        s.correct.push(false);
      }
      s.pendingBatches -= 1;
      if (s.pendingBatches === 0) {
        // All batches done: the real total is whatever we actually got
        s.expectedTotal = s.questions.length;
        updateProgress();
      }
      if (s.phase === "waiting") askCurrent();
    });
  });
}

async function fetchQuizBatch(count, batch, batchTotal) {
  try {
    const res = await fetch("/api/quiz/generate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        language_mode: quizConfig.languageMode,
        category: quizConfig.category,
        difficulty: quizConfig.difficulty,
        count,
        batch,
        batch_total: batchTotal,
        source: quizConfig.category === "lessons" ? "lessons" : "topic",
        words: quizConfig.category === "lessons" && quizConfig.roundWords.length >= 3 ? quizConfig.roundWords : null,
        grammar_topic: quizConfig.category === "lessons" ? quizConfig.grammarTopic : null
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

async function askCurrent() {
  const s = quizState;
  if (s.finished) return;
  const i = s.currentIndex;

  if (i >= s.questions.length) {
    if (s.pendingBatches > 0) {
      // Next batch hasn't arrived yet — Mila is "typing"
      s.phase = "waiting";
      if (!s.waitTyping) s.waitTyping = showTyping();
      composer.innerHTML = "";
      return;
    }
    if (s.questions.length === 0) return showLoadFailure();
    return finishQuiz(false);
  }

  s.phase = "asking";
  if (s.waitTyping) {
    s.waitTyping.remove();
    s.waitTyping = null;
  } else {
    const typing = showTyping();
    await sleep(450);
    typing.remove();
  }
  if (quizState !== s || s.finished) return;

  if (!s.startTime) s.startTime = Date.now();

  const q = s.questions[i];
  const kind = s.kinds[i];
  renderQuestionBubble(q, kind, i);
  renderAnswerComposer(q, kind);
  s.phase = "answering";
  setStatus("online");

  voice.speak(questionSpeech(i));
  voice.preload([questionSpeech(i + 1)]);

  // Warm up Mila's reactions once the first question is on screen, so they don't
  // compete with the question requests (browsers only run ~6 requests at a time)
  if (i === 0) {
    const lines = tutorLines();
    voice.preload(["correct", "wrong", "streak", "lastHeart"].flatMap(k => lines[k].map(l => l[0])));
  }
}

function renderQuestionBubble(q, kind, i) {
  const t = ui();
  const bubble = addMilaBubble();

  let prompt = q.prompt;
  if (kind === "listen") prompt = t.listenPrompt;
  if (kind === "type") prompt = q.style === 3 ? t.blankPrompt : t.writePrompt;
  bubble.appendChild(el("div", "q-prompt", prompt || t.questionOf(i + 1, quizState.expectedTotal)));

  const speech = questionSpeech(i);
  if (kind === "listen") {
    const play = el("button", "play-big");
    Mila.setIcon(play, "speaker");
    play.setAttribute("aria-label", t.replay);
    play.type = "button";
    play.title = t.replay;
    play.onclick = () => voice.speak(speech, { force: true });
    bubble.appendChild(play);
  } else {
    bubble.appendChild(el("div", "q-text", q.q));
  }

  const actions = el("div", "q-actions");
  if (speech && kind !== "listen") {
    const replay = el("button", "pill-btn", t.replay);
    replay.type = "button";
    replay.onclick = () => voice.speak(speech, { force: true });
    actions.appendChild(replay);
  }
  if (q.explanation) {
    const hint = el("div", "hint", q.explanation);
    hint.hidden = true;
    const hintBtn = el("button", "pill-btn", t.hint);
    hintBtn.type = "button";
    hintBtn.onclick = () => { hint.hidden = !hint.hidden; scrollChat(); };
    actions.appendChild(hintBtn);
    bubble.append(actions, hint);
  } else if (actions.children.length) {
    bubble.appendChild(actions);
  }
}

function renderAnswerComposer(q, kind) {
  composer.innerHTML = "";
  if (kind === "type") return renderTypeComposer(q);

  const grid = el("div", "choice-grid");
  q.options.forEach((opt, idx) => {
    const btn = el("button", "choice");
    btn.type = "button";
    btn.appendChild(el("span", "key", String(idx + 1)));
    btn.appendChild(el("span", "label", opt));
    // Hear each option (not on listening questions — that would give the answer away)
    if (kind !== "listen") {
      const listen = el("span", "listen");
      Mila.setIcon(listen, "speaker");
      listen.title = "Listen";
      listen.onclick = e => { e.stopPropagation(); voice.speak(opt, { force: true }); };
      btn.appendChild(listen);
    }
    btn.onclick = () => submitAnswer(opt, idx);
    grid.appendChild(btn);
  });
  composer.appendChild(grid);
}

function renderTypeComposer(q) {
  const t = ui();
  const row = el("div", "type-row");
  const input = el("input", "type-input");
  input.placeholder = t.placeholder;
  input.autocomplete = "off";
  input.spellcheck = false;
  input.lang = targetLang();
  input.addEventListener("keydown", e => {
    if (e.key === "Enter" && input.value.trim()) { e.preventDefault(); submitAnswer(input.value.trim(), null); }
  });
  row.appendChild(input);

  if (SpeechRecognition) {
    const mic = el("button", "icon-btn");
    Mila.setIcon(mic, "mic");
    mic.setAttribute("aria-label", t.micHint);
    mic.type = "button";
    mic.title = t.micHint;
    mic.onclick = () => listenForAnswer(input, mic);
    row.appendChild(mic);
  }

  const send = el("button", "send-btn", t.send);
  send.type = "button";
  send.onclick = () => { if (input.value.trim()) submitAnswer(input.value.trim(), null); };
  row.appendChild(send);

  const note = el("div", "composer-note");
  note.appendChild(el("span", "", SpeechRecognition ? t.micHint : t.enterHint));
  const swap = el("button", "link-btn", t.showOptions);
  swap.type = "button";
  swap.onclick = () => { stopListening(); renderAnswerComposer(q, "choice"); };
  note.appendChild(swap);

  composer.append(row, note);
  input.focus({ preventScroll: true });
}

/* ---------- Microphone answers ---------- */

let recognition = null;

function listenForAnswer(input, micBtn) {
  if (recognition) return stopListening();
  voice.stop();

  recognition = new SpeechRecognition();
  recognition.lang = targetLang() === "ru" ? "ru-RU" : "en-US";
  recognition.interimResults = true;
  recognition.maxAlternatives = 1;

  const note = composer.querySelector(".composer-note span");
  const original = note?.textContent;
  micBtn.classList.add("recording");
  if (note) note.textContent = ui().listening;

  let finalText = "";
  recognition.onresult = e => {
    const res = e.results[e.results.length - 1];
    input.value = res[0].transcript;
    if (res.isFinal) finalText = res[0].transcript.trim();
  };
  recognition.onerror = () => { if (note) note.textContent = ui().micError; };
  recognition.onend = () => {
    micBtn.classList.remove("recording");
    recognition = null;
    if (finalText) submitAnswer(finalText, null);
    else if (note && note.textContent === ui().listening) note.textContent = original;
  };
  recognition.start();
}

function stopListening() {
  if (recognition) { recognition.onend = null; recognition.abort(); recognition = null; }
}

/* ---------- Grading ---------- */

function normalizeAnswer(str) {
  return String(str || "")
    .toLowerCase()
    .replace(/ё/g, "е")
    .replace(/[.,!?;:"'«»„“”()…\-–—]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function editDistance(a, b) {
  const dp = Array.from({ length: a.length + 1 }, (_, i) => [i]);
  for (let j = 1; j <= b.length; j++) dp[0][j] = j;
  for (let i = 1; i <= a.length; i++) {
    for (let j = 1; j <= b.length; j++) {
      dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
  }
  return dp[a.length][b.length];
}

// "exact" | "typo" | "wrong"
function gradeTyped(text, q) {
  const typed = normalizeAnswer(text);
  const targets = [q.options[q.correct], ...(q.accepted || [])].map(normalizeAnswer).filter(Boolean);
  if (targets.includes(typed)) return "exact";

  // A typo that happens to spell one of the wrong options is still wrong
  const wrongOptions = q.options.filter((_, i) => i !== q.correct).map(normalizeAnswer);
  if (wrongOptions.includes(typed)) return "wrong";

  const allowed = typed.length >= 10 ? 2 : typed.length >= 4 ? 1 : 0;
  return targets.some(t => editDistance(typed, t) <= allowed) ? "typo" : "wrong";
}

async function submitAnswer(text, chosenIdx) {
  const s = quizState;
  if (s.phase !== "answering" || s.finished) return;
  s.phase = "feedback";
  stopListening();
  voice.stop();

  const i = s.currentIndex;
  const q = s.questions[i];
  const answerText = q.options[q.correct];
  const result = chosenIdx !== null ? (chosenIdx === q.correct ? "exact" : "wrong") : gradeTyped(text, q);
  const isCorrect = result !== "wrong";

  composer.innerHTML = "";
  addUserBubble(text, isCorrect ? "correct" : "wrong");

  s.answers[i] = text;
  s.correct[i] = isCorrect;
  s.answered += 1;

  let lineKind;
  if (isCorrect) {
    s.score += 1;
    s.streak += 1;
    s.xpMini += 10;
    updateXpMini();
    lineKind = s.streak >= 3 && s.streak % 3 === 0 ? "streak" : "correct";
  } else {
    s.hearts -= 1;
    s.streak = 0;
    updateHeartsUI();
    lineKind = s.hearts === 1 ? "lastHeart" : "wrong";
  }
  updateProgress();

  await sleep(250);
  if (quizState !== s || s.finished) return;

  const { bubble, spoken } = milaSays(lineKind, isCorrect ? "happy" : "sad");
  const t = ui();
  if (result !== "exact") {
    const line = el("div", "answer-line");
    line.appendChild(el("strong", "", (result === "typo" ? t.spelling : t.answerIs) + " "));
    line.appendChild(document.createTextNode(answerText + " "));
    const hear = el("button", "pill-btn");
    Mila.setIcon(hear, "speaker");
    hear.setAttribute("aria-label", t.replay);
    hear.type = "button";
    hear.onclick = () => voice.speak(answerText, { force: true });
    line.appendChild(hear);
    bubble.appendChild(line);
    if (!isCorrect && q.explanation) bubble.appendChild(el("div", "hint", q.explanation));
    scrollChat();
  }

  const isLast = s.hearts <= 0 || i >= s.expectedTotal - 1;
  const cont = el("button", "continue-btn" + (isCorrect ? "" : " bad"), isLast ? t.finish : t.continue);
  cont.type = "button";
  cont.onclick = () => {
    if (s.phase !== "feedback" || s.currentIndex !== i) return;
    if (isLast) return finishQuiz(false, s.hearts <= 0);
    goToNextQuestion();
  };
  composer.appendChild(cont);
  cont.focus({ preventScroll: true });

  // Correct answers flow straight on to the next question, like a conversation
  if (isCorrect && !isLast) {
    await Promise.all([spoken, sleep(900)]);
    if (quizState === s && s.phase === "feedback" && s.currentIndex === i) goToNextQuestion();
  }
}

function goToNextQuestion() {
  quizState.currentIndex += 1;
  setTutorMood("idle");
  askCurrent();
}

function showLoadFailure() {
  const s = quizState;
  s.phase = "done";
  if (s.waitTyping) { s.waitTyping.remove(); s.waitTyping = null; }
  const t = ui();
  addMilaBubble().textContent = t.failed;
  setTutorMood("sad");
  setStatus("online");
  composer.innerHTML = "";
  const retry = el("button", "continue-btn", t.retry);
  retry.type = "button";
  retry.onclick = () => location.reload();
  composer.appendChild(retry);
}

/* ================== HUD ================== */

function updateProgress() {
  const total = quizState.expectedTotal || 1;
  progressFill.style.width = `${Math.min(100, (quizState.answered / total) * 100)}%`;
}

function updateHeartsUI() {
  for (let i = 0; i < 3; i++) {
    heartEls[i].style.opacity = (i < quizState.hearts) ? "1" : "0.25";
  }
}

function updateXpMini() {
  xpMiniEl.textContent = String(quizState.xpMini || 0);
}

/* ================== RESULTS ================== */

async function finishQuiz(expired, endedByHearts = false) {
  if (quizState.finished) return;
  quizState.finished = true;
  quizState.phase = "done";

  stopListening();

  quizScreen.classList.remove("active");
  resultsScreen.classList.add("active");
  // Results/review have their own "Back to Chat" button, so hide the header one
  document.getElementById("headerBackLink").hidden = true;
  reviewScreen.classList.remove("active");

  const total = Math.max(1, quizState.expectedTotal);
  const correct = quizState.score;
  const incorrect = total - correct;

  const percent = Math.round((correct / total) * 100);
  scorePercentage.textContent = `${percent}%`;
  correctCount.textContent = String(correct);
  incorrectCount.textContent = String(incorrect);

  const secondsTaken = quizState.startTime ? Math.floor((Date.now() - quizState.startTime) / 1000) : 0;
  timeTaken.textContent = formatTime(secondsTaken);

  const kind = percent >= 80 ? "endGood" : percent >= 50 ? "endOk" : "endBad";
  const [say, sub] = pickLine(kind);
  resultsTutorSay.textContent = say;
  resultsTutorSub.textContent = sub;
  setTutorMood(percent >= 50 ? "happy" : "idle");
  voice.speak(say);

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

// Review = the quiz conversation itself, replayed (moved, not copied, so speaker buttons and hints still work)
function reviewAnswers() {
  resultsScreen.classList.remove("active");
  reviewScreen.classList.add("active");

  chatLog.querySelectorAll(".typing").forEach(t => t.closest(".msg")?.remove());
  if (chatLog.parentElement !== reviewList) reviewList.appendChild(chatLog);
  chatLog.scrollTop = 0;

  const wrong = quizState.answered - quizState.score;
  document.getElementById("reviewSummary").textContent =
    `${quizState.score} correct · ${wrong} wrong`;
}

function backToResults() {
  reviewScreen.classList.remove("active");
  resultsScreen.classList.add("active");
}

function formatTime(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}
