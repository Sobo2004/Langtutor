const messages = document.getElementById("messages");
const input = document.getElementById("messageInput");
const quizBox = document.getElementById("quiz");
const quizQuestion = document.getElementById("quizQuestion");
const voiceBtn = document.getElementById("voiceBtn");
const listenBtn = document.getElementById("listenBtn");

let quizData = [];
let quizIndex = 0;
let recognition = null;
let isListening = false;
let lastBotMessage = "";




// Language mode toggle
let currentMode = localStorage.getItem('languageMode') || 'en-ru'; // 'en-ru' or 'ru-en'


// Initialize speech recognition
if ('webkitSpeechRecognition' in window || 'SpeechRecognition' in window) {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  recognition = new SpeechRecognition();
  recognition.continuous = false;
  recognition.interimResults = false;
  recognition.lang = 'ru-RU'; // Russian language

  recognition.onresult = (event) => {
    const transcript = event.results[0][0].transcript;
    input.value = transcript;
    isListening = false;
    voiceBtn.textContent = '🎤';
    voiceBtn.style.background = '';
  };

  recognition.onerror = (event) => {
    console.error('Speech recognition error:', event.error);
    isListening = false;
    voiceBtn.textContent = '🎤';
    voiceBtn.style.background = '';
    addMessage(`Voice error: ${event.error}. Try typing instead.`, "bot");
  };

  recognition.onend = () => {
    isListening = false;
    voiceBtn.textContent = '🎤';
    voiceBtn.style.background = '';
  };
}

// Speak individual words from inline speaker buttons — in Mila's voice
function speakWord(element) {
  const word = element.getAttribute('data-word');
  element.classList.add('speaking');
  Mila.voice.speak(word, { force: true }).finally(() => element.classList.remove('speaking'));
}

// Toggle voice input
function toggleVoiceInput() {
  console.log('🎤 Mic button clicked!');
  console.log('recognition available:', !!recognition);
  console.log('isListening:', isListening);
  
  if (!recognition) {
    console.log('❌ Recognition not initialized');
    alert('Speech recognition is not supported in your browser. Please use Chrome or Edge.');
    return;
  }

  if (isListening) {
    console.log('🛑 Stopping mic...');
    recognition.stop();
    isListening = false;
    voiceBtn.textContent = '🎤';
    voiceBtn.style.background = '';
  } else {
    // Set language based on mode before starting
    // In ru-en mode: learning English, so listen for English
    // In en-ru mode: learning Russian, so listen for Russian
    recognition.lang = currentMode === 'ru-en' ? 'en-US' : 'ru-RU';
    console.log('🎤 Starting mic with language:', recognition.lang);
    
    try {
      recognition.start();
      isListening = true;
      voiceBtn.textContent = '⏸️';
      voiceBtn.style.background = '#ff4444';
      console.log('✅ Mic started successfully');
    } catch (e) {
      console.error('❌ Error starting mic:', e);
      alert('Error starting microphone: ' + e.message);
    }
  }
}

// What Mila should say aloud for a message: the [SPEAK:...] marker, else the first bold
// (or, failing that, quoted) word/phrase in the language being learned
function milaSpeechFor(message) {
  const card = window.MilaLesson?.parseCard(message);
  if (card) return card.word;

  const speakMarker = message.match(/\[SPEAK:(.*?)\]/);
  if (speakMarker && speakMarker[1]) return speakMarker[1].trim();

  const bold = currentMode === 'ru-en'
    ? /\*\*([A-Za-z\s,.'!?-]+)\*\*/
    : /\*\*([А-Яа-яЁё\s,.'!?-]+)\*\*/;
  const quoted = currentMode === 'ru-en'
    ? /["«“]([A-Za-z][A-Za-z\s,.'!?-]{0,80})["»”]/
    : /["«“]([А-Яа-яЁё][А-Яа-яЁё\s,.'!?-]{0,80})["»”]/;
  // Last resort: the first run of words in the language being learned
  const plain = currentMode === 'ru-en'
    ? /([A-Za-z][A-Za-z'-]*(?:\s+[A-Za-z][A-Za-z'-]*){0,5})/
    : /([А-Яа-яЁё][А-Яа-яЁё-]*(?:[\s,]+[А-Яа-яЁё][А-Яа-яЁё-]*){0,7}[!?]?)/;
  const match = message.match(bold) || message.match(quoted) || message.match(plain);
  return match ? match[1].trim() : '';
}

// Speaker button: Mila reads the last word she taught
function speakLastMessage() {
  const text = lastBotMessage ? milaSpeechFor(lastBotMessage) : '';
  if (!text) return;
  if (listenBtn) listenBtn.textContent = '⏸️';
  Mila.voice.speak(text, { force: true }).finally(() => {
    if (listenBtn) listenBtn.textContent = '🔊';
  });
}

// Mila's header: status line + mute toggle
const milaStatus = document.getElementById('milaStatus');
const milaMuteBtn = document.getElementById('milaMuteBtn');

function setMilaStatus(kind) {
  if (!milaStatus) return;
  const labels = currentMode === 'ru-en'
    ? { online: 'в сети', typing: 'печатает…', speaking: 'говорит…' }
    : { online: 'online', typing: 'typing…', speaking: 'speaking…' };
  milaStatus.textContent = labels[kind] || labels.online;
}

function updateMilaMuteUI() {
  if (!milaMuteBtn) return;
  milaMuteBtn.textContent = Mila.voice.muted ? '🔇' : '🔈';
  milaMuteBtn.title = Mila.voice.muted ? "Turn Mila's voice on" : 'Mute Mila';
}

Mila.onTalking(on => setMilaStatus(on ? 'speaking' : 'online'));
milaMuteBtn?.addEventListener('click', () => {
  Mila.voice.setMuted(!Mila.voice.muted);
  updateMilaMuteUI();
});
setMilaStatus('online');
updateMilaMuteUI();

// Welcome message is now handled by welcome.js popup

// ── Bot message renderer ───────────────────────────────────────────────────
// Label words: don't put speaker buttons on these
const BOT_LABELS = ['meaning','pronunciation','usage','example','translation',
  'note','grammar','tip','formal','informal','definition'];

function botHTML(text) {
  // Word/example cards (always last) are rendered separately by lesson-flow.js — hide
  // them, including while they are still streaming in
  let t = text.replace(/\[\[(WORD|EXAMPLE|GRAMMAR|BUILD)[\s\S]*$/, '').trimEnd();
  // Strip TTS markers
  t = t.replace(/\[SPEAK:[^\]]+\]/g, '');
  // Strip ### headings
  t = t.replace(/^#{1,3}\s+/gm, '');

  // Remove ALL standalone speaker/microphone emojis (we'll add clickable buttons instead)
  t = t.replace(/🔊/g, '');
  t = t.replace(/🎤/g, '');

  // Process **word** patterns - adds clickable speaker button
  t = t.replace(/\*\*([^*\n]+)\*\*/g, function(_, w) {
    var isLabel = BOT_LABELS.indexOf(w.trim().toLowerCase().replace(/:$/, '')) >= 0;
    if (isLabel) return '<strong>' + w + '</strong>';
    var lang = /[А-Яа-яЁё]/.test(w) ? 'ru' : 'en';
    var safe = w.replace(/"/g, '&quot;');
    return '<strong>' + w + '</strong><button class="spk-btn" data-word="' + safe + '" data-lang="' + lang + '" onclick="speakWord(this)" title="Pronounce">🔊</button>';
  });

  // Make speaker icons in example sentences clickable
  // Pattern: "Example: [sentence] — [translation]" (emojis already removed above)
  t = t.replace(/Example:\s*(.+?)\s*(—)/g, function(_, sentence, dash) {
    var lang = /[А-Яа-яЁё]/.test(sentence) ? 'ru' : 'en';
    var safe = sentence.trim().replace(/"/g, '&quot;');
    return 'Example: ' + sentence + ' <button class="spk-btn" data-word="' + safe + '" data-lang="' + lang + '" onclick="speakWord(this)" title="Pronounce">🔊</button> ' + dash;
  });

  // newlines to <br>
  t = t.replace(/\n/g, '<br>');
  return t;
}

function addMessage(text, sender) {
  const div = document.createElement("div");
  div.className = `message ${sender}`;
  if (sender === "bot") {
    div.innerHTML = botHTML(text);
    lastBotMessage = text;
  } else {
    div.innerText = text;
  }
  messages.appendChild(div);
  messages.scrollTop = messages.scrollHeight;
  return div;
}

// textOverride/intent/topic: message sent by a button
// (intent: next | example | explain; topic: a course topic picked in the sidebar)
async function sendMessage(textOverride, intent, topic) {
  const fromButton = typeof textOverride === "string";
  const text = (fromButton ? textOverride : input.value).trim();
  if (!text) return;
  if (!fromButton) input.value = "";
  Mila.voice.stop();  // never talk over the student
  window.MilaLesson?.interrupt();
  window.MilaLesson?.clearReplies();
  addMessage(text, "user");

  // Mila is "typing" until her reply starts streaming in
  const typingDiv = document.createElement("div");
  typingDiv.className = "message bot typing";
  typingDiv.innerHTML = "<span></span><span></span><span></span>";
  messages.appendChild(typingDiv);
  messages.scrollTop = messages.scrollHeight;
  setMilaStatus('typing');
  Mila.setMood('thinking');
  const stopTyping = () => {
    typingDiv.remove();
    setMilaStatus('online');
    Mila.setMood('idle');
  };

  try {
    const response = await fetch("/chat/stream", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({
        message: text,
        language_mode: currentMode,
        difficulty: localStorage.getItem('difficulty') || 'beginner',
        intent: intent || null,
        topic: topic || null
      })
    });

    if (!response.ok) {
      stopTyping();
      if (response.status === 401) {
        addMessage("Session expired. Please login again.", "bot");
        setTimeout(() => { window.location.reload(); }, 2000);
        return;
      }
      throw new Error('Chat request failed');
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let botMessage = '';
    let botDiv = null;
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split('\n\n');
      buffer = events.pop() || '';

      for (const event of events) {
        if (!event.trim()) continue;
        const lines = event.split('\n');
        let eventType = '', eventData = '';
        for (const line of lines) {
          if (line.startsWith('event: ')) eventType = line.substring(7).trim();
          else if (line.startsWith('data: ')) eventData = line.substring(6);
        }

        if (eventType === 'delta' && eventData) {
          try {
            const data = JSON.parse(eventData);
            botMessage += data.text;
            if (!botDiv) {
              stopTyping();
              botDiv = document.createElement("div");
              botDiv.className = "message bot";
              messages.appendChild(botDiv);
            }
            // Use innerHTML so formatting stays during streaming
            botDiv.innerHTML = botHTML(botMessage);
            lastBotMessage = botMessage;
            messages.scrollTop = messages.scrollHeight;
          } catch (e) { console.error('delta error:', e); }

        } else if (eventType === 'done' && eventData) {
          try {
            const data = JSON.parse(eventData);
            if (data.text && data.text.length > botMessage.length) {
              botMessage = data.text;
              if (botDiv) botDiv.innerHTML = botHTML(botMessage);
            }
            lastBotMessage = botMessage;
            // Word card → quick check → reply buttons (lesson-flow.js); Mila says the word
            window.MilaLesson.onReply(botMessage, botDiv, data.course);
            if (data.progress) updateProgress(data.progress);
            if (data.quiz_ready && data.quiz) {
              quizData = data.quiz; quizIndex = 0; showQuiz();
            }
          } catch (e) { console.error('done error:', e); }
        }
      }
    }
  } catch (error) {
    console.error('Chat error:', error);
    stopTyping();
    addMessage('Sorry, there was an error. Please try again.', 'bot');
  }
}

function updateProgress(p) {
  const totalXp = Number(p.xp || 0);
  const levelNumber = Math.floor(totalXp / 100) + 1;
  const xpInLevel = totalXp % 100;

  // Update all XP displays
  const levelEl = document.getElementById("userLevel");
  if (levelEl) levelEl.innerText = levelNumber;

  document.getElementById("currentXP").innerText = xpInLevel;
  document.getElementById("totalXP").innerText = totalXp;  // Show total XP
  document.getElementById("streakDays").innerText = p.streak;
  document.getElementById("proficiencyLevel").innerText = p.level;
  document.getElementById("progressFill").style.width = `${xpInLevel}%`;

  // Update word counter in sidebar
  if (p.words_completed !== undefined) {
    // Update sidebar word count (index.html uses 'completedCount')
    const sidebarWordsEl = document.getElementById("completedCount");
    if (sidebarWordsEl) {
      sidebarWordsEl.innerText = p.words_completed;
    }

    // Update progress page word count (progress.html uses 'statWords')
    const progressWordsEl = document.getElementById("statWords");
    if (progressWordsEl) {
      progressWordsEl.innerText = p.words_completed;
    }

    console.log('✅ Word counter updated:', p.words_completed);
  }
}

// Difficulty selector
function setDifficulty(level) {
  // Save to localStorage
  localStorage.setItem('difficulty', level);
  
  // Update active button
  document.querySelectorAll('.difficulty-btn').forEach(btn => {
    btn.classList.remove('active');
  });
  document.querySelector(`.difficulty-btn[data-level="${level}"]`).classList.add('active');
  
  console.log('Difficulty set to:', level);
  addMessage(`Difficulty set to ${level}! Lessons will now be adjusted.`, 'bot');
}

// Load saved difficulty, avatar, and word count on page load
window.addEventListener('DOMContentLoaded', async () => {
  const saved = localStorage.getItem('difficulty') || 'beginner';
  document.querySelectorAll('.difficulty-btn').forEach(btn => {
    if (btn.dataset.level === saved) btn.classList.add('active');
    else btn.classList.remove('active');
  });

  // Update sidebar avatar with saved emoji
  const savedAvatar = localStorage.getItem('userAvatar');
  const sidebarAvatar = document.getElementById('sidebarAvatar');
  if (savedAvatar && sidebarAvatar) {
    sidebarAvatar.textContent = savedAvatar;
  }

  // Load current word count from server
  try {
    const res = await fetch('/api/progress');
    if (res.ok) {
      const data = await res.json();
      if (data.words_completed !== undefined) {
        const wordsEl = document.getElementById('completedCount');
        if (wordsEl) {
          wordsEl.textContent = data.words_completed;
          console.log('✅ Loaded word count on page load:', data.words_completed);
        }
      }
    }
  } catch (e) {
    console.error('Failed to load word count:', e);
  }
});

function showQuiz() {
  quizBox.classList.remove("hidden");
  quizQuestion.innerText = quizData[quizIndex].prompt;
}

function submitQuiz() {
  quizIndex++;
  if (quizIndex >= quizData.length) {
    quizBox.classList.add("hidden");
  } else {
    quizQuestion.innerText = quizData[quizIndex].prompt;
  }
}

function skipQuiz() {
  quizBox.classList.add("hidden");
}

// Allow Enter key to send message
if (input) {
  input.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') {
      sendMessage();
    }
  });
}

// ========== DAILY GOAL (active learning time) ==========
// Counts only real learning time: logged in, tab visible, the learner used the page
// in the last 2 minutes, and no tour/onboarding/popup on screen. The total is kept
// per user per day (survives reloads), and the "time's up" popup shows once a day,
// at a calm moment (not over another popup, not while Mila is talking).

const GOAL_TICK_SECONDS = 15;
const GOAL_IDLE_LIMIT_MS = 2 * 60 * 1000;
let lastActivityAt = Date.now();

['click', 'keydown', 'mousemove', 'touchstart', 'scroll'].forEach(evt =>
  document.addEventListener(evt, () => { lastActivityAt = Date.now(); }, { passive: true, capture: true })
);

function goalKeys() {
  const user = (document.getElementById('usernameDisplay')?.textContent || '').trim() || 'anon';
  const day = new Date().toLocaleDateString('en-CA');   // YYYY-MM-DD in local time
  return { time: `learnSeconds:${user}:${day}`, shown: `goalShown:${user}:${day}` };
}

function readNumber(key) {
  try { return parseInt(localStorage.getItem(key) || '0', 10) || 0; } catch (e) { return 0; }
}

function isLoggedIn() {
  return document.getElementById('mainApp')?.classList.contains('active');
}

// Something else is on screen: onboarding, recap, welcome popup, the tour, the time-up popup
function otherPopupOpen() {
  return !!document.querySelector('.popup-overlay.active, #onboardingModal.active, #recapModal.active, .tour-card');
}

function milaIsTalking() {
  return !!(window.Mila && Mila.voice.audio && !Mila.voice.audio.paused);
}

function dailyGoalTick() {
  if (!isLoggedIn() || document.visibilityState !== 'visible' || otherPopupOpen()) return;
  const keys = goalKeys();
  const goalSeconds = parseInt(localStorage.getItem('dailyGoalMinutes') || '10', 10) * 60;

  // Count this tick if the learner is active (or listening to Mila)
  if (Date.now() - lastActivityAt < GOAL_IDLE_LIMIT_MS || milaIsTalking()) {
    try { localStorage.setItem(keys.time, String(readNumber(keys.time) + GOAL_TICK_SECONDS)); } catch (e) {}
  }

  if (readNumber(keys.time) >= goalSeconds && !localStorage.getItem(keys.shown) && !milaIsTalking()) {
    try { localStorage.setItem(keys.shown, '1'); } catch (e) {}
    showTimeUpPopup(goalSeconds / 60);
  }
}

function showTimeUpPopup(minutes) {
  document.getElementById('goalMinutesDisplay').textContent = minutes;
  document.getElementById('timeUpPopup').classList.add('active');
}

function closeTimeUpPopup() {
  document.getElementById('timeUpPopup').classList.remove('active');
}

// Wire time-up popup buttons (shown once a day, so "keep learning" just closes it)
document.addEventListener('DOMContentLoaded', function() {
  document.getElementById('btnTimeUpContinue').addEventListener('click', closeTimeUpPopup);
  document.getElementById('btnTimeUpDone').addEventListener('click', function() {
    closeTimeUpPopup();
    addMessage("Great work today! See you tomorrow! 👋", "bot");
  });
});

setInterval(dailyGoalTick, GOAL_TICK_SECONDS * 1000);

// ========== LANGUAGE MODE TOGGLE ==========

window.toggleLanguage = function() {
  if (currentMode === 'en-ru') {
    currentMode = 'ru-en';
    document.getElementById('langFrom').textContent = 'Русский';
    document.getElementById('langTo').textContent = 'Английский';
  } else {
    currentMode = 'en-ru';
    document.getElementById('langFrom').textContent = 'English';
    document.getElementById('langTo').textContent = 'Russian';
  }
  
  localStorage.setItem('languageMode', currentMode);
  window.MilaLesson?.renderRound();
  
  // Update entire UI language
  if (typeof updateUILanguage === 'function') {
    updateUILanguage();
  }
  
  // Show notification
  const modeText = currentMode === 'en-ru' 
    ? 'English → Russian' 
    : 'Русский → Английский';
  addMessage(`🔄 ${currentMode === 'en-ru' ? 'Mode switched to' : 'Режим переключен на'}: ${modeText}`, 'bot');
  
  console.log('Language mode:', currentMode);
}

// Initialize language display on page load
window.addEventListener('DOMContentLoaded', function() {
  const mode = localStorage.getItem('languageMode') || 'en-ru';
  currentMode = mode;
  
  if (mode === 'ru-en') {
    document.getElementById('langFrom').textContent = 'Русский';
    document.getElementById('langTo').textContent = 'Английский';
  } else {
    document.getElementById('langFrom').textContent = 'English';
    document.getElementById('langTo').textContent = 'Russian';
  }
  
  // Update UI language
  if (typeof updateUILanguage === 'function') {
    updateUILanguage();
  }


  
  // Post-login onboarding/recap flow is triggered from index.html after showMainApp()
});


// ===================== ONBOARDING + RECAP (Duolingo-style) =====================




window.checkOnboarding = async function checkOnboarding() {
  try {
    const res = await fetch("/onboarding/status");
    if (!res.ok) return window.checkRecap();

    const data = await res.json();
    if (data.show) {
      const modal = document.getElementById("onboardingModal");
      if (modal) {
        // Initialize avatar preview with saved avatar or default
        const savedAvatar = localStorage.getItem('userAvatar') || '👤';
        const preview = document.getElementById('onboardingAvatarPreview');
        if (preview) {
          preview.innerHTML = `<span>${savedAvatar}</span>`;
        }
        selectedOnboardingAvatar = savedAvatar;

        // Reset to step 1
        document.querySelectorAll('.onboarding-step').forEach(step => {
          step.classList.remove('active');
        });
        document.getElementById('step1').classList.add('active');

        // Reset progress bar
        for (let i = 1; i <= 5; i++) {
          const progressBar = document.getElementById('progress' + i);
          if (i === 1) {
            progressBar.classList.add('active');
          } else {
            progressBar.classList.remove('active');
          }
        }

        modal.classList.add("active");
      }
      return;
    }
    return window.checkRecap();
  } catch (e) {
    console.error("checkOnboarding error:", e);
    return window.checkRecap();
  }
};

// Emoji avatar picker for onboarding
const AVATARS = ['🐱','🐶','🐼','🐨','🦊','🦁','🐯','🐮','🐷','🐸','🦉','🐵','🐔','🐧','🐦','🦆','🦅','🦋','🐝','🐞','🎮','🎨','🎭','🎪','🎯','🎲','⚽','🏀','🎸','🎺','🎻','🎹','🌸','🌺','🌻','🌹','🌷','🌱','🌲','🌳','🍀','🌾','🌟','⭐','🌙','☀️','🪐','🚀','🛸','⚡','💫','✨','🍕','🍔','🍟','🌮','🍜','🍱','🍣','🍰','🍩','🍪'];

let selectedOnboardingAvatar = localStorage.getItem('userAvatar') || '👤';

window.openOnboardingAvatarPicker = function() {
  const grid = document.getElementById('onboardingAvatarGrid');
  grid.innerHTML = '';

  AVATARS.forEach(emoji => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = emoji;

    if (emoji === selectedOnboardingAvatar) {
      btn.style.borderColor = '#ffd700';
      btn.style.background = 'rgba(255,255,255,0.3)';
    }

    btn.onclick = () => {
      grid.querySelectorAll('button').forEach(b => {
        b.style.borderColor = 'transparent';
        b.style.background = 'rgba(255,255,255,0.15)';
      });
      btn.style.borderColor = '#ffd700';
      btn.style.background = 'rgba(255,255,255,0.3)';
      selectedOnboardingAvatar = emoji;
    };

    grid.appendChild(btn);
  });

  document.getElementById('onboardingAvatarModal').classList.add('open');
  document.body.style.overflow = 'hidden';
};

window.closeOnboardingAvatarPicker = function() {
  document.getElementById('onboardingAvatarModal').classList.remove('open');
  document.body.style.overflow = '';
};

window.saveOnboardingAvatar = function() {
  if (selectedOnboardingAvatar) {
    localStorage.setItem('userAvatar', selectedOnboardingAvatar);
    const preview = document.getElementById('onboardingAvatarPreview');
    preview.innerHTML = `<span>${selectedOnboardingAvatar}</span>`;
    closeOnboardingAvatarPicker();
    console.log('✅ Avatar selected:', selectedOnboardingAvatar);
  }
};

// Close avatar modal by clicking outside
document.addEventListener('click', (e) => {
  if (e.target.id === 'onboardingAvatarModal') {
    closeOnboardingAvatarPicker();
  }
});

// ESC key closes avatar modal
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    closeOnboardingAvatarPicker();
  }
});

// Multi-step onboarding navigation
window.nextStep = function(stepNumber) {
  // Validate step 2: study reason is required
  if (stepNumber === 3) {
    const reason = document.getElementById('studyReason')?.value.trim();
    if (!reason) {
      const ta = document.getElementById('studyReason');
      ta.style.borderColor = '#ff6b6b';
      ta.placeholder = 'Please tell us what motivates you...';
      ta.focus();
      if (!document.getElementById('studyReasonError')) {
        const err = document.createElement('p');
        err.id = 'studyReasonError';
        err.style.cssText = 'color:#ff6b6b;font-size:13px;margin:-20px 0 16px;text-align:center;';
        err.textContent = 'This field is required — tell us your motivation!';
        ta.insertAdjacentElement('afterend', err);
      }
      return;
    }
    // Clear error state if valid
    const ta = document.getElementById('studyReason');
    ta.style.borderColor = 'rgba(255,255,255,0.3)';
    const err = document.getElementById('studyReasonError');
    if (err) err.remove();
  }

  // Hide all steps
  document.querySelectorAll('.onboarding-step').forEach(step => {
    step.classList.remove('active');
  });

  // Show target step
  document.getElementById('step' + stepNumber).classList.add('active');

  // Update progress bar
  for (let i = 1; i <= 5; i++) {
    const progressBar = document.getElementById('progress' + i);
    if (i <= stepNumber) {
      progressBar.classList.add('active');
    } else {
      progressBar.classList.remove('active');
    }
  }
};

window.prevStep = function(stepNumber) {
  window.nextStep(stepNumber);
};

// Goal selection
window.selectGoalOption = function(element) {
  document.querySelectorAll('.goal-option').forEach(opt => {
    opt.classList.remove('selected');
  });
  element.classList.add('selected');
  document.getElementById('studyGoal').value = element.dataset.goal;
};

// Level selection
window.selectLevelOption = function(element) {
  document.querySelectorAll('.level-option').forEach(opt => {
    opt.classList.remove('selected');
  });
  element.classList.add('selected');
  document.getElementById('studyLevel').value = element.dataset.level;
};

// Daily goal selection
window.selectDailyGoal = function(element) {
  document.querySelectorAll('.daily-option').forEach(opt => {
    opt.classList.remove('active');
  });
  element.classList.add('active');
  document.getElementById('dailyGoal').value = element.dataset.minutes;
};

window.submitOnboarding = async function submitOnboarding() {
  const reason = (document.getElementById("studyReason")?.value || "").trim();
  // Remove emojis from goal and level before submitting
  const goal = (document.getElementById("studyGoal")?.value || "Fun").replace(/[\u{1F300}-\u{1F9FF}]/gu, '').trim();
  const level = (document.getElementById("studyLevel")?.value || "Beginner").replace(/[\u{1F300}-\u{1F9FF}]/gu, '').trim();
  const dailyGoalMinutes = parseInt(document.getElementById("dailyGoal")?.value || "10");

  // Save daily goal to localStorage
  localStorage.setItem('dailyGoalMinutes', dailyGoalMinutes.toString());

  console.log(`✅ Onboarding complete: Daily goal set to ${dailyGoalMinutes} minutes`);

  await fetch("/onboarding/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason, goal, level, avatar: selectedOnboardingAvatar, daily_goal: dailyGoalMinutes })
  }).catch(() => {});

  const modal = document.getElementById("onboardingModal");
  if (modal) {
    modal.classList.remove("active");
  }

  // Update sidebar avatar immediately
  const sidebarAvatar = document.getElementById('sidebarAvatar');
  if (sidebarAvatar && selectedOnboardingAvatar) {
    sidebarAvatar.textContent = selectedOnboardingAvatar;
    console.log('✅ Sidebar avatar updated:', selectedOnboardingAvatar);
  }

  await window.checkRecap();
  // Brand-new user: Mila shows them around the site
  window.MilaTour?.startIfNew();
};

window.checkRecap = async function checkRecap() {
  try {
    console.log('Checking recap status...');
    const res = await fetch("/recap/status");
    if (!res.ok) {
      console.log('Recap status not ok:', res.status);
      return;
    }
    const data = await res.json();
    console.log('Recap status:', data);

    if (data.show) {
      console.log('Showing recap!');
      return window.showRecap();
    } else {
      console.log('Recap not needed (show=false)');
    }
  } catch (e) {
    console.error("checkRecap error:", e);
  }
};

let _recapQuestions = [];
let _recapIndex = 0;
let _recapAnswers = [];

window.showRecap = async function showRecap() {
  console.log('showRecap called - fetching questions...');
  const res = await fetch("/recap/questions");
  if (!res.ok) {
    console.log('Recap questions fetch failed:', res.status);
    return;
  }

  const data = await res.json();
  console.log('Recap questions:', data);
  _recapQuestions = data.questions || [];

  // show even if small (don't block user)
  if (_recapQuestions.length === 0) {
    console.log('No recap questions available');
    return;
  }

  _recapIndex = 0;
  _recapAnswers = [];

  const modal = document.getElementById("recapModal");
  console.log('Recap modal element:', modal);
  if (modal) {
    console.log('Activating recap modal...');
    modal.classList.add("active");

    // Click outside to close
    modal.onclick = function(e) {
      if (e.target === modal) {
        window.skipRecap();
      }
    };
  }
  renderRecapQuestion();
  console.log('Recap shown successfully!');
};

window.skipRecap = async function skipRecap() {
  // Mark recap as done so it won't keep popping
  await fetch("/recap/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answers: [], ratings: "skipped", comment: "" })
  }).catch(() => {});

  // Close recap modal completely
  const modal = document.getElementById("recapModal");
  if (modal) {
    modal.classList.remove("active");
  }

  // Clear recap content to prevent stuck state
  const content = document.getElementById("recapContent");
  if (content) {
    content.innerHTML = '';
  }

  console.log('Recap skipped and closed');
};

function renderRecapQuestion() {
  const q = _recapQuestions[_recapIndex];
  if (!q) return renderRecapFeedback();

  const total = _recapQuestions.length;

  const html = `
    <div class="recap-mascot"><img class="mila-img" src="/static/mila.svg" alt="Mila"></div>

    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
      <h2 style="margin:0;color:white;">Quick Recap</h2>
      <div style="display:flex;gap:10px;align-items:center;">
        <div style="font-weight:600;color:rgba(255,255,255,0.9);">${_recapIndex + 1}/${total}</div>
        <button class="recap-skip" onclick="window.skipRecap()">×</button>
      </div>
    </div>

    <p style="font-size:16px;margin:12px 0 14px;color:rgba(255,255,255,0.95);">${escapeHtml(q.prompt || "Pick the correct answer")}</p>

    <div class="recap-options">
      ${(q.options || []).map(opt => `
        <button class="recap-option" onclick="answerRecap('${opt.replace(/'/g, "\\'")}')">
          ${escapeHtml(opt)}
        </button>
      `).join("")}
    </div>
  `;

  document.getElementById("recapContent").innerHTML = html;
}

window.answerRecap = function answerRecap(selected) {
  _recapAnswers.push(String(selected));
  _recapIndex += 1;
  renderRecapQuestion();
};

function renderRecapFeedback() {
  let correct = 0;
  for (let i = 0; i < _recapAnswers.length; i++) {
    if (_recapQuestions[i] && _recapAnswers[i] === _recapQuestions[i].answer) correct++;
  }

  const mascotEmoji = correct === _recapAnswers.length ? '🎉' : correct >= _recapAnswers.length / 2 ? '😊' : '<img class="mila-img" src="/static/mila.svg" alt="Mila">';

  const html = `
    <div class="recap-mascot">${mascotEmoji}</div>

    <div style="display:flex;justify-content:space-between;align-items:center;">
      <h2 style="margin:0;color:white;">Recap complete!</h2>
      <button class="recap-skip" onclick="window.skipRecap()">×</button>
    </div>

    <p style="margin:10px 0 14px;color:rgba(255,255,255,0.95);font-size:18px;">Score: <b>${correct}/${_recapAnswers.length}</b></p>

    <p style="margin:8px 0 10px;color:rgba(255,255,255,0.9);">How did that feel?</p>

    <div class="recap-feedback">
      <button class="recap-pill" onclick="submitRecap('too_easy')">😴 Too easy</button>
      <button class="recap-pill" onclick="submitRecap('just_right')">👍 Just right</button>
      <button class="recap-pill" onclick="submitRecap('too_hard')">😰 Too hard</button>
    </div>

    <textarea id="recapComment" placeholder="Optional feedback..."></textarea>

    <button class="recap-primary" style="margin-top:12px;" onclick="submitRecap(null)">✨ Continue</button>
  `;

  document.getElementById("recapContent").innerHTML = html;
}

window.submitRecap = async function submitRecap(rating) {
  const comment = (document.getElementById("recapComment")?.value || "").trim();

  // Show "Thanks" screen first
  const content = document.getElementById("recapContent");
  if (content) {
    content.innerHTML = `
      <div style="text-align:center;padding:40px 20px;">
        <div style="font-size:80px;margin-bottom:16px;">🎉</div>
        <h2 style="margin:0 0 8px;color:white;">Thanks for the feedback!</h2>
        <p style="color:rgba(255,255,255,0.9);margin:0;font-size:16px;">Keep up the great work!</p>
      </div>
    `;
  }

  // Submit in background
  await fetch("/recap/submit", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ answers: _recapAnswers, ratings: rating, comment })
  }).catch(() => {});

  // Auto-close after 1.5 seconds
  setTimeout(() => {
    const modal = document.getElementById("recapModal");
    if (modal) {
      modal.classList.remove("active");
    }

    // Clear content
    if (content) {
      content.innerHTML = '';
    }

    console.log('Recap submitted and closed');
  }, 1500);
};

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (m) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[m]));
}

// ========== UPDATE NOTICE ==========
// If the app is updated while this page is open, offer a refresh so the page
// never runs a mix of old and new files.
(function watchForUpdates() {
  let loadedVersion = null;
  async function check() {
    try {
      const res = await fetch('/api/version', { cache: 'no-store' });
      if (!res.ok) return;
      const { version } = await res.json();
      if (loadedVersion === null) loadedVersion = version;
      else if (version !== loadedVersion) showUpdateBar();
    } catch (e) {}
  }
  function showUpdateBar() {
    if (document.getElementById('updateBar')) return;
    const bar = document.createElement('div');
    bar.id = 'updateBar';
    bar.className = 'update-bar';
    bar.innerHTML = '<span>✨ Mila has been updated.</span>';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.textContent = 'Refresh';
    btn.onclick = () => location.reload();
    bar.appendChild(btn);
    document.body.appendChild(bar);
  }
  check();
  setInterval(check, 60000);
})();
