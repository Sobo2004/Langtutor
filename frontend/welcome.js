// welcome.js — Duolingo-style welcome popup
// Single IIFE — no scattered DOMContentLoaded listeners.
// initWelcomePopup() is called by index.html after auth succeeds.

(function() {

// ---- state ----
var welcomeData  = null;
var quizItems    = [];
var quizIdx      = 0;
var correctCount = 0;
var listenWord   = null;

// ---- word pool for listen quiz ----
var LISTEN_POOL = [
  { russian: 'Привет',     pron: 'pree-VYET',     meaning: 'Hello' },
  { russian: 'Спасибо',    pron: 'spa-SEE-ba',    meaning: 'Thank you' },
  { russian: 'Пожалуйста', pron: 'pa-ZHA-lu-sta', meaning: 'Please' },
  { russian: 'Да',         pron: 'DA',            meaning: 'Yes' },
  { russian: 'Нет',        pron: 'NYET',          meaning: 'No' },
  { russian: 'Добрый',     pron: 'do-BRYAI',      meaning: 'Good' },
  { russian: 'Вода',       pron: 'va-DA',         meaning: 'Water' }
];

// ============================================================
// ENTRY — called externally after auth succeeds
// ============================================================
window.initWelcomePopup = async function() {
  // Disabled - using app.js recap system instead
  console.log('Welcome popup disabled - using recap modal system');
  return;
};

// Also expose as startPostLoginFlow for compatibility
window.startPostLoginFlow = function() {
  console.log('startPostLoginFlow called');
  // Check onboarding first, then recap
  if (window.checkOnboarding) {
    window.checkOnboarding();
  } else if (window.checkRecap) {
    window.checkRecap();
  }
};

// ============================================================
// RETURNING USER — welcome greeting + recap quiz
// ============================================================
function renderWelcomeScreen() {
  document.getElementById('popupGreeting').textContent =
    'Welcome back, ' + welcomeData.username + '!';

  document.getElementById('popupStreak').textContent = welcomeData.streak > 0
    ? '🔥 ' + welcomeData.streak + '-day streak! Keep it going!'
    : '⭐ ' + welcomeData.xp + ' XP earned so far';

  var row = document.getElementById('popupReviewRow');
  row.innerHTML = '';
  (welcomeData.taught_words || []).slice(0, 3).forEach(function(w) {
    var pill      = document.createElement('span');
    pill.className  = 'word-pill';
    pill.textContent = w.word;
    row.appendChild(pill);
  });
}

function renderQuizQuestion() {
  var item = quizItems[quizIdx];
  document.getElementById('quizPrompt').textContent =
    'How do you pronounce "' + item.word + '"?';
  document.getElementById('quizHint').textContent =
    'Word ' + (quizIdx + 1) + ' of ' + quizItems.length;

  var options   = shuffleArray([item.pronunciation].concat(generateDistractors(item.pronunciation)));
  var container = document.getElementById('quizOptions');
  container.innerHTML = '';
  options.forEach(function(opt) {
    var btn       = document.createElement('button');
    btn.className = 'quiz-option';
    btn.textContent = opt;
    btn.addEventListener('click', function() { handleRecapAnswer(btn, opt, item.pronunciation); });
    container.appendChild(btn);
  });
  document.getElementById('quizFeedback').style.display = 'none';
}

function generateDistractors(correct) {
  var parts = correct.split('-');
  var d = [];

  // reversed syllables
  d.push(parts.slice().reverse().join('-'));

  // swap a vowel
  var vowels = 'aeiouAEIOU';
  var d2 = correct;
  for (var i = 0; i < d2.length; i++) {
    if (vowels.indexOf(d2[i]) !== -1) {
      d2 = d2.substring(0, i) + vowels[Math.floor(Math.random() * vowels.length)] + d2.substring(i + 1);
      break;
    }
  }
  d.push(d2);

  // swap two chars
  var d3 = correct.split('');
  var a  = Math.floor(Math.random() * d3.length);
  var b  = Math.floor(Math.random() * d3.length);
  while (b === a) b = Math.floor(Math.random() * d3.length);
  var tmp = d3[a]; d3[a] = d3[b]; d3[b] = tmp;
  d.push(d3.join(''));

  return d.filter(function(v, i, arr) { return v !== correct && arr.indexOf(v) === i; }).slice(0, 3);
}

function handleRecapAnswer(btn, selected, correct) {
  document.querySelectorAll('.quiz-option').forEach(function(b) { b.disabled = true; });
  var fb = document.getElementById('quizFeedback');
  fb.style.display = 'block';

  if (selected === correct) {
    btn.classList.add('correct');
    fb.className   = 'popup-feedback correct';
    fb.textContent = '✅ Correct!';
    correctCount++;
  } else {
    btn.classList.add('wrong');
    document.querySelectorAll('.quiz-option').forEach(function(b) {
      if (b.textContent === correct) b.classList.add('correct');
    });
    fb.className   = 'popup-feedback wrong';
    fb.textContent = '❌ Correct: ' + correct;
  }

  setTimeout(function() {
    quizIdx++;
    if (quizIdx < quizItems.length) renderQuizQuestion();
    else showScreen('screenDone');
  }, 1200);
}

// ============================================================
// NEW USER ONBOARDING — 4 steps
// ============================================================
function buildListenQuiz() {
  listenWord = LISTEN_POOL[Math.floor(Math.random() * LISTEN_POOL.length)];

  var others = LISTEN_POOL.filter(function(w) { return w.russian !== listenWord.russian; });
  var wrongs = shuffleArray(others).slice(0, 3);
  var all    = shuffleArray([listenWord].concat(wrongs));

  var grid = document.getElementById('listenOptions');
  grid.innerHTML = '';
  all.forEach(function(w, i) {
    var btn       = document.createElement('button');
    btn.className = 'listen-opt';
    btn.innerHTML = '<span class="listen-num">' + (i + 1) + '</span><span class="listen-word">' + w.russian + '</span>';
    btn.addEventListener('click', function() { handleListenAnswer(btn, w); });
    grid.appendChild(btn);
  });

  document.getElementById('listenFeedback').style.display = 'none';
  setTimeout(playListenWord, 700);
}

function playListenWord() {
  if (!window.speechSynthesis || !listenWord) return;
  speechSynthesis.cancel();
  var utt  = new SpeechSynthesisUtterance(listenWord.russian);
  utt.lang = 'ru-RU';
  utt.rate = 0.7;
  speechSynthesis.speak(utt);
}

function handleListenAnswer(btn, chosen) {
  document.querySelectorAll('.listen-opt').forEach(function(b) { b.disabled = true; });
  var fb = document.getElementById('listenFeedback');
  fb.style.display = 'block';

  if (chosen.russian === listenWord.russian) {
    btn.classList.add('correct');
    fb.className   = 'popup-feedback correct';
    fb.textContent = '✅ Correct! ' + listenWord.russian + ' means "' + listenWord.meaning + '"';
  } else {
    btn.classList.add('wrong');
    document.querySelectorAll('.listen-opt').forEach(function(b) {
      if (b.textContent.indexOf(listenWord.russian) !== -1) b.classList.add('correct');
    });
    fb.className   = 'popup-feedback wrong';
    fb.textContent = '❌ It was ' + listenWord.russian + ' (' + listenWord.pron + ') — "' + listenWord.meaning + '"';
  }

  setTimeout(function() { showScreen('screenOnboard4'); }, 1400);
}

// ============================================================
// WIRE ALL BUTTONS — runs once when DOM is ready
// ============================================================
function wireButtons() {
  // --- Onboard step 1: why options + continue ---
  var why1Container = document.getElementById('onboardWhyOptions');
  var why1Btn       = document.getElementById('btnOnboard1Next');
  if (why1Container && why1Btn) {
    why1Container.addEventListener('click', function(e) {
      var opt = e.target.closest('.onboard-opt');
      if (!opt) return;
      why1Container.querySelectorAll('.onboard-opt').forEach(function(b) { b.classList.remove('selected'); });
      opt.classList.add('selected');
      why1Btn.disabled = false;
    });
    why1Btn.addEventListener('click', function() {
      if (!why1Btn.disabled) showScreen('screenOnboard2');
    });
  }

  // --- Onboard step 2: goal options + continue ---
  var goal2Container = document.getElementById('onboardGoalOptions');
  var goal2Btn       = document.getElementById('btnOnboard2Next');
  var selectedGoalMinutes = 10; // default
  
  if (goal2Container && goal2Btn) {
    goal2Container.addEventListener('click', function(e) {
      var opt = e.target.closest('.onboard-opt');
      if (!opt) return;
      goal2Container.querySelectorAll('.onboard-opt').forEach(function(b) { b.classList.remove('selected'); });
      opt.classList.add('selected');
      goal2Btn.disabled = false;
      
      // Save the selected goal
      selectedGoalMinutes = parseInt(opt.dataset.val, 10);
      localStorage.setItem('dailyGoalMinutes', selectedGoalMinutes);
      console.log('Daily goal set to:', selectedGoalMinutes, 'minutes');
    });
    goal2Btn.addEventListener('click', function() {
      if (!goal2Btn.disabled) {
        // Save again to ensure it's persisted
        localStorage.setItem('dailyGoalMinutes', selectedGoalMinutes);
        buildListenQuiz();
        showScreen('screenOnboard3');
      }
    });
  }

  // --- Onboard step 3: play button ---
  var playBtn = document.getElementById('btnPlay');
  if (playBtn) {
    playBtn.addEventListener('click', playListenWord);
  }

  // --- Onboard step 4: finish ---
  var finishOnboard = document.getElementById('btnOnboardFinish');
  if (finishOnboard) {
    finishOnboard.addEventListener('click', closePopup);
  }

  // --- Returning user: start quiz ---
  var startQuiz = document.getElementById('btnStartQuiz');
  if (startQuiz) {
    startQuiz.addEventListener('click', function() {
      renderQuizQuestion();
      showScreen('screenQuiz');
    });
  }

  // --- Quiz done: continue → feedback ---
  var continueBtn = document.getElementById('btnContinue');
  if (continueBtn) {
    continueBtn.addEventListener('click', function() {
      showScreen('screenFeedback');
    });
  }

  // --- Feedback buttons (How are you enjoying?) ---
  var feedbacks = [
    { id: 'btnLove', value: 'loving', icon: '😍', msg: "That's awesome! We love hearing that." },
    { id: 'btnGood', value: 'good', icon: '👍', msg: "Great! We'll keep making it better." },
    { id: 'btnMeh',  value: 'okay', icon: '📊', msg: "Thanks for being honest! We're working on it." }
  ];
  feedbacks.forEach(function(f) {
    var el = document.getElementById(f.id);
    if (el) {
      el.addEventListener('click', function() {
        // Save enjoyment response
        localStorage.setItem('userEnjoyment', f.value);
        document.getElementById('thankIcon').textContent = f.icon;
        document.getElementById('thankMsg').textContent  = f.msg;
        showScreen('screenPurpose'); // Go to purpose screen
      });
    }
  });

  // --- Purpose buttons (What's your goal?) ---
  var purposes = [
    { id: 'btnPurposeTravel', value: 'travel' },
    { id: 'btnPurposeWork', value: 'work' },
    { id: 'btnPurposeCulture', value: 'culture' },
    { id: 'btnPurposeFun', value: 'fun' },
    { id: 'btnPurposeFamily', value: 'family' }
  ];
  purposes.forEach(function(p) {
    var el = document.getElementById(p.id);
    if (el) {
      el.addEventListener('click', function() {
        // Save purpose response
        localStorage.setItem('userPurpose', p.value);
        showScreen('screenThanks');
      });
    }
  });

  // --- Thanks: finish ---
  var finishThanks = document.getElementById('btnFinish');
  if (finishThanks) {
    finishThanks.addEventListener('click', closePopup);
  }
}

// ============================================================
// SHARED HELPERS
// ============================================================
function showScreen(id) {
  document.querySelectorAll('.popup-screen').forEach(function(s) { s.classList.remove('active'); });
  var el = document.getElementById(id);
  if (el) el.classList.add('active');
}

function showPopup() {
  document.getElementById('welcomePopup').classList.add('active');
}

function closePopup() {
  var popup = document.getElementById('welcomePopup');
  if (popup) popup.classList.remove('active');

  // ✅ prevent re-opening in this tab/session
  try {
    sessionStorage.removeItem('showWelcomeOnLogin');
    sessionStorage.setItem('welcomePopupDismissed', '1');
  } catch (e) {}

  // seed the chat with a welcome message if it's empty
  var messagesDiv = document.getElementById('messages');
  if (messagesDiv && messagesDiv.children.length === 0 && typeof addMessage === 'function') {
    addMessage(
      'Привет! (pree-VYET — Hello!) I\'m Mila, your Russian tutor.\n\n' +
      'I teach one word at a time, with a quick check after each one. Every 5 words we do a mini quiz!\n\n' +
      '🎤 Mic to speak  |  🔊 Speaker to listen\n\n' +
      'Click a lesson or type "teach me greetings"! 🇷🇺',
      'bot'
    );
  }
}

// ✅ Needed because popup HTML uses onclick="closePopup()"
window.closePopup = closePopup;

function shuffleArray(arr) {
  var a = arr.slice();
  for (var i = a.length - 1; i > 0; i--) {
    var j   = Math.floor(Math.random() * (i + 1));
    var tmp = a[i]; a[i] = a[j]; a[j] = tmp;
  }
  return a;
}

// ---- wire buttons as soon as DOM is ready ----
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', wireButtons);
} else {
  wireButtons(); // DOM already ready
}

})(); // end IIFE