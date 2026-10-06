/*******************************************************
 * Website tour — Mila shows new users around the chat page.
 * Starts automatically for users who finished onboarding but haven't
 * completed/skipped the tour yet (saved on their account, so it works on
 * any device); "🧭 Take the tour" in the sidebar replays it.
 *******************************************************/
(function () {
  // target: CSS selector to spotlight (null = centred card)
  const STEPS = {
    "en-ru": [
      { target: null, title: "Hi, I'm Mila! 👋", text: "I'm your Russian tutor. Let me show you around. It only takes a minute." },
      { target: ".mila-header", title: "Chat with me", text: "This is where we talk. I teach you one word at a time, then we practise it together." },
      { target: "#messageInput", title: "Type here", text: "Write to me in English or Russian. Try \"teach me greetings\" to get started." },
      { target: "#voiceBtn", title: "Speak", text: "Tap the mic and say it out loud. Great for practising pronunciation." },
      { target: "#listenBtn", title: "Listen", text: "Tap the speaker to hear me say the word again." },
      { target: "#milaMuteBtn", title: "My voice", text: "I read new words out loud. Prefer quiet? Mute me here." },
      { target: "#tourLessons", title: "Your course", text: "Three levels: Beginner and Intermediate teach words and phrases (a quick quiz every 5), Advanced teaches grammar and how to build any sentence. Pick a topic to start." },
      { target: "#tourProgress", title: "Your progress", text: "Earn XP, keep your daily streak going and watch your word count grow." },
      { target: "#tourLanguage", title: "Switch language", text: "Learning English instead? Switch the direction here." },
      { target: "#tourExplore", title: "Explore", text: "See your progress, compete on the leaderboard, and take quizzes on the words you've learnt with me." },
      { target: "#usernameDisplay", title: "Your profile", text: "Change your avatar and see your stats here." },
      { target: null, title: "You're ready! 🎉", text: "Let's learn your first word together. Just say hi!", last: true }
    ],
    "ru-en": [
      { target: null, title: "Привет, я Мила! 👋", text: "Я твой репетитор английского. Давай я покажу, что здесь есть. Это займёт минуту." },
      { target: ".mila-header", title: "Чат со мной", text: "Здесь мы общаемся. Я учу тебя по одному слову, а потом мы вместе практикуемся." },
      { target: "#messageInput", title: "Пиши здесь", text: "Пиши мне по-русски или по-английски. Начни с «научи меня приветствиям»." },
      { target: "#voiceBtn", title: "Говори", text: "Нажми на микрофон и скажи вслух. Отлично для тренировки произношения." },
      { target: "#listenBtn", title: "Слушай", text: "Нажми на динамик, чтобы услышать слово ещё раз." },
      { target: "#milaMuteBtn", title: "Мой голос", text: "Я читаю новые слова вслух. Хочешь тишины? Выключи звук здесь." },
      { target: "#tourLessons", title: "Твой курс", text: "Три уровня: на начальном и среднем учим слова и фразы (короткий тест каждые 5), на продвинутом — грамматику и как строить любое предложение. Выбери тему, чтобы начать." },
      { target: "#tourProgress", title: "Твой прогресс", text: "Зарабатывай XP, держи серию дней и следи, как растёт число выученных слов." },
      { target: "#tourLanguage", title: "Смена языка", text: "Хочешь учить русский? Переключи направление здесь." },
      { target: "#tourExplore", title: "Разделы", text: "Смотри прогресс, соревнуйся в рейтинге и проходи тесты по словам, которые мы выучили." },
      { target: "#usernameDisplay", title: "Твой профиль", text: "Здесь можно сменить аватар и посмотреть статистику." },
      { target: null, title: "Всё готово! 🎉", text: "Давай выучим первое слово вместе. Просто поздоровайся!", last: true }
    ]
  };

  const LABELS = {
    "en-ru": { next: "Next", back: "Back", skip: "Skip tour", done: "Let's start!" },
    "ru-en": { next: "Далее", back: "Назад", skip: "Пропустить", done: "Начнём!" }
  };

  const mode = () => (localStorage.getItem("languageMode") === "ru-en" ? "ru-en" : "en-ru");

  let steps = [];
  let index = 0;
  let els = null;

  function build() {
    const blocker = document.createElement("div");
    blocker.className = "tour-blocker";
    const spot = document.createElement("div");
    spot.className = "tour-spot";
    const card = document.createElement("div");
    card.className = "tour-card";
    card.setAttribute("role", "dialog");
    card.innerHTML = `
      <div class="tour-head">
        <img class="tour-mila" src="/static/mila.svg" alt="Mila">
        <div class="tour-title"></div>
      </div>
      <div class="tour-text"></div>
      <div class="tour-foot">
        <button type="button" class="tour-skip"></button>
        <div class="tour-dots"></div>
        <div class="tour-nav">
          <button type="button" class="tour-back"></button>
          <button type="button" class="tour-next"></button>
        </div>
      </div>`;
    document.body.append(blocker, spot, card);
    card.querySelector(".tour-skip").onclick = () => end();
    card.querySelector(".tour-back").onclick = () => go(index - 1, -1);
    card.querySelector(".tour-next").onclick = () => (steps[index].last ? end() : go(index + 1, 1));
    blocker.onclick = () => card.querySelector(".tour-next").focus();
    return { blocker, spot, card };
  }

  function targetFor(step) {
    if (!step.target) return null;
    const el = document.querySelector(step.target);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    // Hidden or off screen (e.g. inside the closed mobile menu) — skip this step
    return r.width && r.height && r.right > 0 && r.left < window.innerWidth ? el : null;
  }

  function go(i, dir = 1) {
    // Skip steps whose element isn't on screen
    while (i >= 0 && i < steps.length && steps[i].target && !targetFor(steps[i])) i += dir;
    if (i < 0 || i >= steps.length) return end();
    index = i;
    const step = steps[i];
    const labels = LABELS[mode()];
    const { card } = els;

    card.querySelector(".tour-title").textContent = step.title;
    card.querySelector(".tour-text").textContent = step.text;
    card.querySelector(".tour-skip").textContent = labels.skip;
    card.querySelector(".tour-skip").hidden = !!step.last;
    card.querySelector(".tour-back").textContent = labels.back;
    card.querySelector(".tour-back").hidden = i === 0;
    card.querySelector(".tour-next").textContent = step.last ? labels.done : labels.next;
    card.querySelector(".tour-dots").textContent = `${i + 1} / ${steps.length}`;

    const target = targetFor(step);
    if (target) target.scrollIntoView({ block: "nearest" });
    position();
    card.querySelector(".tour-next").focus({ preventScroll: true });

    if (window.Mila) Mila.voice.speak(step.text);
  }

  function position() {
    if (!els) return;
    const { spot, card } = els;
    const target = targetFor(steps[index]);
    const vw = window.innerWidth, vh = window.innerHeight, gap = 14, pad = 6;

    if (!target) {
      spot.classList.add("center");
      card.classList.add("center");
      card.style.left = card.style.top = "";
      return;
    }
    spot.classList.remove("center");
    card.classList.remove("center");

    const r = target.getBoundingClientRect();
    Object.assign(spot.style, {
      left: `${r.left - pad}px`, top: `${r.top - pad}px`,
      width: `${r.width + pad * 2}px`, height: `${r.height + pad * 2}px`
    });

    // Place the card to the right, else below, else above the highlight
    const cw = card.offsetWidth, ch = card.offsetHeight;
    let left, top;
    if (r.right + gap + cw < vw - 8) {
      left = r.right + gap + pad;
      top = r.top + r.height / 2 - ch / 2;
    } else if (r.bottom + gap + ch < vh - 8) {
      left = r.left + r.width / 2 - cw / 2;
      top = r.bottom + gap + pad;
    } else {
      left = r.left + r.width / 2 - cw / 2;
      top = r.top - gap - pad - ch;
    }
    card.style.left = `${Math.max(8, Math.min(left, vw - cw - 8))}px`;
    card.style.top = `${Math.max(8, Math.min(top, vh - ch - 8))}px`;
  }

  function onKey(e) {
    if (!els) return;
    if (e.key === "Escape") end();
    else if (e.key === "ArrowRight") els.card.querySelector(".tour-next").click();
    else if (e.key === "ArrowLeft" && index > 0) go(index - 1, -1);
  }

  function start() {
    if (els) return;
    steps = STEPS[mode()];
    els = build();
    window.addEventListener("resize", position);
    window.addEventListener("keydown", onKey);
    go(0);
  }

  function end() {
    if (!els) return;
    fetch("/tour/done", { method: "POST" }).catch(() => {});
    if (window.Mila) Mila.voice.stop();
    window.removeEventListener("resize", position);
    window.removeEventListener("keydown", onKey);
    els.blocker.remove(); els.spot.remove(); els.card.remove();
    els = null;
    document.getElementById("messageInput")?.focus();
  }

  // Start once no other popup (onboarding, recap) is showing
  let autoStarted = false;  // the automatic start happens at most once per page visit
  function startWhenClear(tries = 0) {
    if (autoStarted) return;
    const busy = document.querySelector(".popup-overlay.active, #onboardingModal.active, #recapModal.active");
    if (busy && tries < 120) return setTimeout(() => startWhenClear(tries + 1), 1000);
    if (!busy && !autoStarted) {
      autoStarted = true;
      start();
    }
  }

  window.MilaTour = {
    start,
    // New users: run until they finish or skip it once
    async startIfNew() {
      try {
        const res = await fetch("/tour/status");
        if (res.ok && (await res.json()).show && !autoStarted) startWhenClear();
      } catch (e) {}
    }
  };

  // On page load (e.g. the tour was interrupted, or on another device)
  window.MilaTour.startIfNew();

  document.getElementById("tourReplayLink")?.addEventListener("click", e => {
    e.preventDefault();
    start();
  });
})();
