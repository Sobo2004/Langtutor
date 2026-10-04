/*******************************************************
 * Interactive lessons in the chat with Mila — she talks you through each word.
 *
 * When Mila teaches a new word, her reply carries a word card:
 *   [[WORD {"word","pron","meaning","say","example","example_meaning","check":{question,options,answer}}]]
 * which plays out like a spoken lesson:
 *   word card (Mila explains it out loud) → quick tap check (she asks) →
 *   "Now you try!" 🎤 pronunciation → reply buttons.
 * "Another example" replies carry [[EXAMPLE {"sentence","translation"}]].
 * Grammar lessons (Advanced level) carry [[GRAMMAR {...}]]: Mila's Colour Blocks
 * method — the rule as coloured blocks, a comparison with the learner's language,
 * colour-coded examples, a check, then a sentence builder ([[BUILD {...}]] for more).
 * Every other message is read aloud in full.
 *
 * The course (course.json on the server) gives each topic 15 words = 3 rounds
 * of 5: a quick quiz after each round, a final quiz when the topic is done,
 * and a celebration when a whole level is finished.
 *******************************************************/
(function () {
  const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;

  // en-ru: English speakers learning Russian; ru-en: Russian speakers learning English
  const TEXT = {
    "en-ru": {
      round: (r, rs, k) => `Round ${r} of ${rs} · word ${k} of 5`,
      courseTitle: "Your course",
      locked: name => `🔒 ${name}: finish the level above to unlock`,
      startTopicMsg: name => `Let's learn ${name}!`,
      topicDone: name => `🎉 You've finished ${name}!`,
      topicDoneSub: n => `You know all ${n} words. Take the final quiz to lock them in.`,
      topicDoneSpoken: name => `Congratulations, you've finished ${name}! Take the final quiz to lock in every word.`,
      finalQuiz: "▶ Final quiz", nextTopic: t => `Next: ${t.emoji} ${t.name} →`,
      levelDone: name => `🎓 You've completed ${name}!`,
      levelDoneSub: next => next ? `${next} is now unlocked. Ready for the next step?` : "You've finished the whole course. Amazing work!",
      levelDoneSpoken: name => `Wow! You've completed ${name}. I'm so proud of you!`,
      startLevel: name => `Start ${name} →`,
      exampleLabel: "Example",
      lesson: (k, n) => `Lesson ${k} of ${n}`,
      formula: "Sentence pattern", examplesLabel: "Examples", compareLabel: "Compare", pointsLabel: "Key rules",
      patternSpoken: "The pattern is", forExample: "For example", tipLabel: "Memory tip",
      targetName: "Russian", nativeName: "English",
      roles: { subject: "Subject", verb: "Verb", object: "Object", adjective: "Adjective", adverb: "Adverb",
               article: "Article", pronoun: "Pronoun", preposition: "Preposition", place: "Place", time: "Time",
               question: "Question word", negation: "Negation", connector: "Connector", other: "Other" },
      nextLesson: "➡️ Next lesson", buildAnother: "🧱 Build another",
      grammarExampleMsg: g => `Give me another example of «${g}», please.`,
      grammarConfusedMsg: g => `I don't understand «${g}». Can you explain it more simply?`,
      buildMsg: g => `Give me another sentence to build for «${g}».`,
      buildTitle: "🧱 Build the sentence", buildHint: "Tap the blocks in the right order.",
      buildSpoken: tr => `Now build this sentence: ${tr}`,
      buildCheck: "Check", buildReset: "Start again", correctOrder: "Correct order:",
      buildWrong: ["Almost! Here's the right order.", "Listen and look at the colours."],
      listenAgain: "Listen again",
      hear: "🔊 Hear it", say: "🎤 Say it", example: "💡 Another example",
      confused: "🤔 I don't get it", next: "➡️ Next word",
      nextMsg: "Next word, please!",
      exampleMsg: w => `Give me another example with «${w}», please.`,
      confusedMsg: w => `I don't understand «${w}». Can you explain it more simply?`,
      correct: [["Отлично!", "Great job!"], ["Да, правильно!", "Yes, that's right!"], ["Молодец!", "Well done!"]],
      wrong: c => [`Not quite, it's «${c}».`, "You'll remember it next time!"],
      tryIt: w => [`Now you try! Say «${w}».`, "Tap the microphone and say it out loud."],
      tryItSpoken: w => `Now you try! Say: ${w}`,
      micBtn: "🎤 Tap and say it", skip: "Skip",
      listening: w => `🎤 Listening… say «${w}»`,
      heard: x => `I heard: «${x}»`,
      sayGood: ["Отличное произношение!", "Great pronunciation!"],
      sayAgain: ["Почти!", "Almost! Listen to me and try again."],
      micError: "I couldn't hear you. Check your microphone and try again.",
      checkpoint: n => `🎉 You learnt ${n} new words!`,
      checkpointSub: "Let's lock them in with a quick quiz.",
      checkpointSpoken: n => `Amazing, you learnt ${n} new words! Let's lock them in with a quick quiz.`,
      quiz: "▶ Quick quiz", keep: "Keep learning"
    },
    "ru-en": {
      round: (r, rs, k) => `Раунд ${r} из ${rs} · слово ${k} из 5`,
      courseTitle: "Твой курс",
      locked: name => `🔒 ${name}: пройди уровень выше, чтобы открыть`,
      startTopicMsg: name => `Давай учить тему «${name}»!`,
      topicDone: name => `🎉 Тема «${name}» пройдена!`,
      topicDoneSub: n => `Ты знаешь все ${n} слов. Пройди итоговый тест, чтобы закрепить их.`,
      topicDoneSpoken: name => `Поздравляю, тема ${name} пройдена! Пройди итоговый тест, чтобы закрепить все слова.`,
      finalQuiz: "▶ Итоговый тест", nextTopic: t => `Дальше: ${t.emoji} ${t.name} →`,
      levelDone: name => `🎓 Уровень «${name}» пройден!`,
      levelDoneSub: next => next ? `Теперь открыт уровень «${next}». Готов к следующему шагу?` : "Ты прошёл весь курс. Потрясающе!",
      levelDoneSpoken: name => `Ура! Уровень ${name} пройден. Я тобой горжусь!`,
      startLevel: name => `Начать: ${name} →`,
      exampleLabel: "Пример",
      lesson: (k, n) => `Урок ${k} из ${n}`,
      formula: "Шаблон предложения", examplesLabel: "Примеры", compareLabel: "Сравни", pointsLabel: "Главные правила",
      patternSpoken: "Шаблон такой", forExample: "Например", tipLabel: "Подсказка",
      targetName: "Английский", nativeName: "Русский",
      roles: { subject: "Подлежащее", verb: "Глагол", object: "Дополнение", adjective: "Прилагательное", adverb: "Наречие",
               article: "Артикль", pronoun: "Местоимение", preposition: "Предлог", place: "Место", time: "Время",
               question: "Вопросительное слово", negation: "Отрицание", connector: "Союз", other: "Другое" },
      nextLesson: "➡️ Следующий урок", buildAnother: "🧱 Собрать ещё",
      grammarExampleMsg: g => `Дай, пожалуйста, ещё пример на тему «${g}».`,
      grammarConfusedMsg: g => `Я не понимаю тему «${g}». Объясни попроще?`,
      buildMsg: g => `Дай ещё одно предложение для сборки на тему «${g}».`,
      buildTitle: "🧱 Собери предложение", buildHint: "Нажимай на блоки в правильном порядке.",
      buildSpoken: tr => `Теперь собери предложение: ${tr}`,
      buildCheck: "Проверить", buildReset: "Сначала", correctOrder: "Правильный порядок:",
      buildWrong: ["Почти! Вот правильный порядок.", "Послушай и посмотри на цвета."],
      listenAgain: "Послушать ещё раз",
      hear: "🔊 Послушать", say: "🎤 Сказать", example: "💡 Ещё пример",
      confused: "🤔 Не понимаю", next: "➡️ Следующее слово",
      nextMsg: "Следующее слово, пожалуйста!",
      exampleMsg: w => `Дай, пожалуйста, ещё пример с «${w}».`,
      confusedMsg: w => `Я не понимаю «${w}». Объясни попроще?`,
      correct: [["Great job!", "Отлично!"], ["Yes, that's right!", "Да, правильно!"], ["Well done!", "Молодец!"]],
      wrong: c => [`Не совсем, правильно: «${c}».`, "В следующий раз получится!"],
      tryIt: w => [`Теперь ты! Скажи «${w}».`, "Нажми на микрофон и скажи вслух."],
      tryItSpoken: w => `Теперь ты! Скажи: ${w}`,
      micBtn: "🎤 Нажми и скажи", skip: "Пропустить",
      listening: w => `🎤 Слушаю… скажи «${w}»`,
      heard: x => `Я услышала: «${x}»`,
      sayGood: ["Great pronunciation!", "Отличное произношение!"],
      sayAgain: ["Almost!", "Почти! Послушай меня и попробуй ещё раз."],
      micError: "Не получилось тебя услышать. Проверь микрофон и попробуй ещё раз.",
      checkpoint: n => `🎉 Ты выучил(а) ${n} новых слов!`,
      checkpointSub: "Давай закрепим их коротким тестом.",
      checkpointSpoken: n => `Потрясающе, ты выучил ${n} новых слов! Давай закрепим их коротким тестом.`,
      quiz: "▶ Быстрый тест", keep: "Учиться дальше"
    }
  };

  const mode = () => (typeof currentMode !== "undefined" && currentMode === "ru-en" ? "ru-en" : "en-ru");
  const t = () => TEXT[mode()];
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const pick = list => list[Math.floor(Math.random() * list.length)];

  function el(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function scrollDown() {
    const box = document.getElementById("messages");
    if (box) box.scrollTop = box.scrollHeight;
  }

  function addBot(className) {
    const div = el("div", "message bot " + (className || ""));
    document.getElementById("messages").appendChild(div);
    scrollDown();
    return div;
  }

  function speakerButton(text) {
    const b = el("button", "spk-btn", "🔊");
    b.type = "button";
    b.title = "Listen";
    b.onclick = () => Mila.voice.speak(text, { force: true });
    return b;
  }

  /* ---------- Mila reading a bubble aloud ---------- */

  // Reads the parts aloud while the bubble glows; resolves when she's done (or interrupted)
  async function readAloud(bubble, parts, opts) {
    parts = (parts || []).filter(Boolean);
    if (!parts.length) return;
    bubble?.classList.add("speaking");
    try {
      await Mila.voice.speakParts(parts, opts);
    } finally {
      bubble?.classList.remove("speaking");
    }
  }

  // Small "🔊 Listen again" button that replays what Mila said in this bubble
  function addReplay(bubble, parts) {
    if (!bubble || !parts.length || bubble.querySelector(".replay-btn")) return;
    const b = el("button", "replay-btn", "🔊 " + t().listenAgain);
    b.type = "button";
    b.onclick = () => readAloud(bubble, parts, { force: true });
    bubble.appendChild(b);
  }

  /* ---------- Card markers ---------- */

  function parseMarker(text, kind, field) {
    const m = String(text || "").match(new RegExp("\\[\\[" + kind + "\\s*(\\{[\\s\\S]*\\})\\s*\\]\\]"));
    if (!m) return null;
    try {
      const card = JSON.parse(m[1]);
      return card && String(card[field] || "").trim() ? card : null;
    } catch (e) {
      return null;
    }
  }

  const parseCard = text => parseMarker(text, "WORD", "word");
  const parseExample = text => parseMarker(text, "EXAMPLE", "sentence");
  const parseGrammar = text => parseMarker(text, "GRAMMAR", "title");
  const parseBuild = text => {
    const b = parseMarker(text, "BUILD", "translation");
    return b && Array.isArray(b.parts) ? b : null;
  };

  /* ---------- Course: sidebar map + chat header ---------- */

  let course = null;      // the active topic's progress, from the server

  function difficulty() {
    try { return localStorage.getItem("difficulty") || "beginner"; } catch (e) { return "beginner"; }
  }

  // mapOnly: just refresh the sidebar counts (keeps the progress that came with Mila's reply)
  async function loadCourse(mapOnly = false) {
    try {
      const res = await fetch(`/api/course?language_mode=${mode()}&difficulty=${difficulty()}`);
      if (!res.ok) return;
      const data = await res.json();
      if (!mapOnly) course = data.active;
      renderCourseMap(data.levels);
      renderHeader();
    } catch (e) {
      console.warn("Couldn't load the course:", e);
    }
  }

  function renderCourseMap(levels) {
    const box = document.getElementById("courseMap");
    if (!box) return;
    const tx = t();
    box.innerHTML = "";
    box.appendChild(el("h3", "course-title", tx.courseTitle));
    levels.forEach(level => {
      if (!level.unlocked) {
        box.appendChild(el("div", "course-locked", tx.locked(level.name)));
        return;
      }
      const learnt = level.topics.reduce((a, tp) => a + tp.learnt, 0);
      const total = level.topics.reduce((a, tp) => a + tp.total, 0);
      const head = el("div", "course-level");
      head.append(el("span", "", (level.done ? "🎓 " : "") + level.name), el("span", "course-level-count", `${learnt}/${total}`));
      box.appendChild(head);

      level.topics.forEach(tp => {
        const b = el("button", "course-topic");
        b.type = "button";
        if (tp.done) b.classList.add("done");
        if (course && course.topic.id === tp.id) b.classList.add("active");
        const row = el("div", "ct-row");
        row.append(el("span", "ct-emoji", tp.emoji), el("span", "ct-name", tp.name),
                   el("span", "ct-count", tp.done ? "✓" : `${tp.learnt}/${tp.total}`));
        const bar = el("div", "ct-bar");
        const fill = el("div", "ct-fill");
        fill.style.width = `${(tp.learnt / tp.total) * 100}%`;
        bar.appendChild(fill);
        b.append(row, bar);
        b.onclick = () => startTopic(tp);
        box.appendChild(b);
      });
    });
  }

  function renderHeader() {
    const box = document.getElementById("roundProgress");
    if (!box) return;
    box.hidden = !course || !course.learnt || course.topic_done;
    if (box.hidden) return;
    document.getElementById("roundLabel").textContent = `${course.topic.emoji} ${course.topic.name} · ` +
      (course.grammar ? t().lesson(course.learnt, course.total) : t().round(course.round, course.rounds, course.in_round));
    document.getElementById("roundFill").style.width = `${(course.in_round / 5) * 100}%`;
  }

  function startTopic(tp) {
    sendMessage(t().startTopicMsg(tp.name), "next", tp.id);
  }

  /* ---------- Reply buttons ---------- */

  function clearReplies() {
    document.querySelectorAll("#messages .reply-chips").forEach(c => c.remove());
  }

  function showReplies(card) {
    clearReplies();
    const tx = t();
    const row = el("div", "reply-chips");
    const chip = (label, onClick) => {
      const b = el("button", "reply-chip", label);
      b.type = "button";
      b.onclick = onClick;
      row.appendChild(b);
    };
    if (card && card.kind === "grammar") {
      chip(tx.example, () => sendMessage(tx.grammarExampleMsg(card.title), "example"));
      chip(tx.buildAnother, () => sendMessage(tx.buildMsg(card.title), "build"));
      chip(tx.confused, () => sendMessage(tx.grammarConfusedMsg(card.title), "explain"));
      chip(tx.nextLesson, () => sendMessage(tx.nextMsg, "next"));
      row.lastChild.classList.add("primary");
      document.getElementById("messages").appendChild(row);
      return scrollDown();
    }
    if (card) {
      chip(tx.hear, () => Mila.voice.speak(card.word, { force: true }));
      if (SpeechRecognition) chip(tx.say, () => sayIt(card, showReplies));
      chip(tx.example, () => sendMessage(tx.exampleMsg(card.word), "example"));
      chip(tx.confused, () => sendMessage(tx.confusedMsg(card.word), "explain"));
    }
    chip(tx.next, () => sendMessage(tx.nextMsg, "next"));
    row.lastChild.classList.add("primary");
    document.getElementById("messages").appendChild(row);
    scrollDown();
  }

  /* ---------- Word card → check → try it ---------- */

  function renderCard(card) {
    const div = addBot("word-card");
    const top = el("div", "wc-top");
    top.append(el("span", "wc-word", card.word), speakerButton(card.word));
    div.appendChild(top);

    const meta = el("div", "wc-meta");
    if (card.pron) meta.appendChild(el("span", "wc-pron", card.pron));
    if (card.meaning) meta.appendChild(el("span", "wc-meaning", card.meaning));
    div.appendChild(meta);

    if (card.example) {
      const ex = el("div", "wc-example");
      ex.append(el("span", "", card.example), speakerButton(card.example));
      div.appendChild(ex);
      if (card.example_meaning) div.appendChild(el("div", "wc-example-tr", card.example_meaning));
    }
    scrollDown();
    return div;
  }

  // What Mila says while showing the card: her tutor explanation, or a simple fallback
  function cardSpeech(card) {
    if (card.say) return Mila.speechParts(card.say);
    return [card.word, card.meaning, card.example, card.example_meaning].filter(Boolean);
  }

  function milaLine([say, sub], mood) {
    const div = addBot("mila-line");
    div.appendChild(el("div", "", say));
    if (sub) div.appendChild(el("div", "sub", sub));
    Mila.setMood(mood);
    return readAloud(div, [say]);
  }

  async function askCheck(card) {
    const check = card.check || {};
    const options = Array.isArray(check.options) ? check.options.slice(0, 4) : [];
    const answer = Number(check.answer);
    if (!check.question || options.length < 2 || !(answer >= 0 && answer < options.length)) {
      return card.kind === "grammar" ? buildSentence(card.build, card, afterWord) : tryIt(card);
    }

    const div = addBot("check");
    div.appendChild(el("div", "check-q", check.question));
    const opts = el("div", "check-options");
    options.forEach((opt, i) => {
      const b = el("button", "check-opt", String(opt));
      b.type = "button";
      b.onclick = async () => {
        Mila.voice.stop();
        opts.querySelectorAll("button").forEach((x, j) => {
          x.disabled = true;
          if (j === answer) x.classList.add("right");
          else if (j === i) x.classList.add("wrong");
        });
        const right = i === answer;
        await sleep(300);
        await Promise.race([
          right ? milaLine(pick(t().correct), "happy") : milaLine(t().wrong(options[answer]), "sad"),
          sleep(6000)
        ]);
        if (card.kind === "grammar") buildSentence(card.build, card, afterWord);
        else tryIt(card);
      };
      opts.appendChild(b);
    });
    div.appendChild(opts);
    scrollDown();
    readAloud(div, [check.question]);
  }

  // "Now you try!" — speaking practice is part of every word (when the browser has a mic API)
  async function tryIt(card) {
    if (!SpeechRecognition) return afterWord(card);
    const tx = t();
    const [say, sub] = tx.tryIt(card.word);
    const div = addBot("mila-line try-it");
    div.appendChild(el("div", "", say));
    div.appendChild(el("div", "sub", sub));

    const actions = el("div", "try-actions");
    const mic = el("button", "try-mic", tx.micBtn);
    mic.type = "button";
    const skip = el("button", "try-skip", tx.skip);
    skip.type = "button";
    const finish = () => { actions.remove(); };
    mic.onclick = () => { finish(); sayIt(card, afterWord); };
    skip.onclick = () => { finish(); Mila.voice.stop(); afterWord(card); };
    actions.append(mic, skip);
    div.appendChild(actions);
    scrollDown();

    Mila.setMood("idle");
    await readAloud(div, [tx.tryItSpoken(card.word)]);
  }

  // After a word: topic/round checkpoints for course words, otherwise the reply buttons
  function afterWord(card) {
    if (course && course.just_learnt && course.topic_done) return showTopicDone(course);
    if (course && course.just_learnt && course.in_round === 5) return showCheckpoint(course.round_words);
    showReplies(card);
  }

  function quizUrl(words) {
    return "/quiz?words=" + encodeURIComponent(words.join("|"));
  }

  function showCheckpoint(words) {
    clearReplies();
    const tx = t();
    const div = addBot("checkpoint");
    div.appendChild(el("div", "cp-title", tx.checkpoint(words.length)));
    div.appendChild(el("div", "cp-sub", tx.checkpointSub));
    const chips = el("div", "cp-words");
    words.forEach(w => chips.appendChild(el("span", "", w)));
    div.appendChild(chips);

    const actions = el("div", "cp-actions");
    const quiz = el("button", "cp-quiz", tx.quiz);
    quiz.type = "button";
    quiz.onclick = () => { location.href = quizUrl(words); };
    const keep = el("button", "cp-keep", tx.keep);
    keep.type = "button";
    keep.onclick = () => sendMessage(tx.nextMsg, "next");
    actions.append(quiz, keep);
    div.appendChild(actions);
    Mila.setMood("happy");
    readAloud(div, [tx.checkpointSpoken(words.length)]);
    scrollDown();
  }

  // Whole topic learnt: final quiz on all its words, then the next topic (or the next level)
  async function showTopicDone(c) {
    clearReplies();
    const tx = t();
    const div = addBot("checkpoint topic-done");
    div.appendChild(el("div", "cp-badge", c.topic.emoji));
    div.appendChild(el("div", "cp-title", tx.topicDone(c.topic.name)));
    div.appendChild(el("div", "cp-sub", tx.topicDoneSub(c.total)));
    const chips = el("div", "cp-words");
    c.topic_words.forEach(w => chips.appendChild(el("span", "", w)));
    div.appendChild(chips);

    const actions = el("div", "cp-actions");
    const quiz = el("button", "cp-quiz", tx.finalQuiz);
    quiz.type = "button";
    quiz.onclick = () => {
      location.href = quizUrl(c.topic_words) + (c.grammar ? "&grammar=" + encodeURIComponent(c.level.id + "/" + c.topic.id) : "");
    };
    actions.appendChild(quiz);
    if (c.next_topic) {
      const next = el("button", "cp-keep", tx.nextTopic(c.next_topic));
      next.type = "button";
      next.onclick = () => startTopic(c.next_topic);
      actions.appendChild(next);
    }
    div.appendChild(actions);
    Mila.setMood("happy");
    scrollDown();
    await readAloud(div, [tx.topicDoneSpoken(c.topic.name)]);

    if (c.level.done) showLevelDone(c);
  }

  function showLevelDone(c) {
    const tx = t();
    const div = addBot("checkpoint level-done");
    div.appendChild(el("div", "cp-badge", "🎓"));
    div.appendChild(el("div", "cp-title", tx.levelDone(c.level.name)));
    div.appendChild(el("div", "cp-sub", tx.levelDoneSub(c.next_level && c.next_level.name)));
    if (c.next_level && c.next_level.first_topic) {
      const actions = el("div", "cp-actions");
      const go = el("button", "cp-quiz", tx.startLevel(c.next_level.name));
      go.type = "button";
      go.onclick = () => startTopic(c.next_level.first_topic);
      actions.appendChild(go);
      div.appendChild(actions);
    }
    Mila.setMood("happy");
    scrollDown();
    readAloud(div, [tx.levelDoneSpoken(c.level.name)]);
  }

  /* ---------- 🎤 Pronunciation practice ---------- */

  function normalize(s) {
    return String(s || "").toLowerCase().replace(/ё/g, "е").replace(/[.,!?;:"'«»()…\-–—]/g, " ").replace(/\s+/g, " ").trim();
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

  // then(card) is called when practice is over (reply buttons, or the checkpoint)
  function sayIt(card, then) {
    clearReplies();
    Mila.voice.stop();
    const tx = t();
    const prompt = addBot("mila-line listening");
    prompt.textContent = tx.listening(card.word);

    const rec = new SpeechRecognition();
    rec.lang = mode() === "en-ru" ? "ru-RU" : "en-US";
    rec.maxAlternatives = 3;
    let heard = null;

    rec.onresult = e => {
      const alts = Array.from(e.results[0]).map(a => a.transcript);
      const target = normalize(card.word);
      // Use the alternative closest to the target word
      heard = alts.sort((a, b) => editDistance(normalize(a), target) - editDistance(normalize(b), target))[0];
    };
    rec.onend = async () => {
      prompt.classList.remove("listening");
      if (!heard) {
        prompt.textContent = tx.micError;
        return then(card);
      }
      const u = el("div", "message user", heard);
      document.getElementById("messages").appendChild(u);
      scrollDown();

      const said = normalize(heard), target = normalize(card.word);
      const good = said.includes(target) || editDistance(said, target) <= Math.max(1, Math.floor(target.length / 4));
      await sleep(250);
      if (good) {
        await Promise.race([milaLine(tx.sayGood, "happy"), sleep(6000)]);
      } else {
        const div = addBot("mila-line");
        div.appendChild(el("div", "", tx.heard(heard)));
        div.appendChild(el("div", "sub", tx.sayAgain[1]));
        Mila.setMood("thinking");
        await readAloud(div, [tx.sayAgain[1], card.word]);
      }
      then(card);
    };
    rec.onerror = () => {};
    rec.start();
  }

  /* ---------- Grammar: Mila's Colour Blocks method ---------- */

  const ROLES = ["subject", "verb", "object", "adjective", "adverb", "article", "pronoun", "preposition",
                 "place", "time", "question", "negation", "connector", "other"];
  const roleOf = p => (ROLES.includes(p && p.role) ? p.role : "other");
  const sentenceOf = parts => parts.map(p => p.t).join(" ").replace(/\s+([.,!?])/g, "$1");

  function block(part) {
    const b = el("span", "block role-" + roleOf(part), part.t);
    b.title = t().roles[roleOf(part)];
    return b;
  }

  // A sentence drawn as coloured blocks, with 🔊 for the whole sentence
  function blocksLine(parts, translation) {
    const wrap = el("div", "g-example");
    const line = el("div", "blocks");
    parts.forEach(p => line.appendChild(block(p)));
    line.appendChild(speakerButton(sentenceOf(parts)));
    wrap.appendChild(line);
    if (translation) wrap.appendChild(el("div", "g-translation", translation));
    return wrap;
  }

  // Grammar lesson, taught step by step: each part appears while Mila explains it
  async function teachGrammar(card) {
    const tx = t();
    const run = lessonRun;
    const div = addBot("word-card grammar-card");
    div.appendChild(el("div", "g-title", card.title));
    const allSpeech = [];

    async function step(node, speech) {
      node.classList.add("reveal");
      div.appendChild(node);
      scrollDown();
      speech = speech.filter(Boolean);
      allSpeech.push(...speech);
      if (run !== lessonRun) return;                 // student moved on: just show the rest
      if (Mila.voice.muted) return sleep(350);
      await readAloud(node, speech.flatMap(x => Mila.speechParts(x)));
    }
    const section = (label, ...children) => {
      const box = el("div", "g-section");
      if (label) box.appendChild(el("div", "g-label", label));
      children.forEach(c => box.appendChild(c));
      return box;
    };

    Mila.setMood("happy");

    // 1. Overview
    const intro = card.explain || card.say;
    if (intro) await step(section(null, el("div", "g-explain", intro)), [intro]);

    // 2. Key rules, one at a time
    const points = Array.isArray(card.points) ? card.points.filter(pt => pt && (pt.head || pt.text)) : [];
    if (points.length) {
      div.appendChild(section(tx.pointsLabel));
      for (const pt of points) {
        const row = el("div", "g-point");
        row.appendChild(el("span", "g-point-head", pt.head || ""));
        row.appendChild(el("span", "g-point-text", pt.text || ""));
        if (pt.examples) {
          const ex = el("div", "g-point-ex");
          ex.append(el("span", "", pt.examples), speakerButton(pt.examples));
          row.appendChild(ex);
        }
        await step(row, [`${pt.head ? pt.head + ": " : ""}${pt.text || ""}.`, pt.examples ? `${tx.forExample}: ${pt.examples}` : ""]);
      }
    }

    // 3. Sentence pattern as coloured blocks
    const rule = Array.isArray(card.rule) ? card.rule.filter(p => p && p.t) : [];
    if (rule.length) {
      const line = el("div", "blocks formula");
      rule.forEach((p, i) => {
        if (i) line.appendChild(el("span", "plus", "+"));
        line.appendChild(block(p));
      });
      await step(section(tx.formula, line), [`${tx.patternSpoken}: ${rule.map(p => p.t).join(", ")}.`]);
    }

    // 4. Compare the two languages
    const cmp = card.compare;
    if (cmp && (cmp.target || cmp.native)) {
      const box = el("div", "g-compare");
      const row = (name, text, speak) => {
        const r = el("div", "g-cmp-row");
        r.append(el("span", "g-cmp-lang", name), el("span", "g-cmp-text", text || ""));
        if (speak && text) r.appendChild(speakerButton(text));
        box.appendChild(r);
      };
      row(tx.targetName, cmp.target, true);
      row(tx.nativeName, cmp.native, false);
      if (cmp.note) box.appendChild(el("div", "g-cmp-note", "💡 " + cmp.note));
      await step(section(tx.compareLabel, box), [cmp.target, cmp.native, cmp.note]);
    }

    // 5. Examples, each with why it's built that way
    const examples = Array.isArray(card.examples) ? card.examples.filter(e => Array.isArray(e.parts) && e.parts.length) : [];
    if (examples.length) {
      div.appendChild(section(tx.examplesLabel));
      for (const e of examples) {
        const parts = e.parts.filter(p => p && p.t);
        const ex = blocksLine(parts, e.translation);
        if (e.note) ex.appendChild(el("div", "g-note", "👉 " + e.note));
        await step(ex, [sentenceOf(parts), e.translation, e.note]);
      }
    }

    // 6. Memory tip
    if (card.tip) {
      const tip = el("div", "g-tip");
      tip.append(el("strong", "", "💡 " + tx.tipLabel + ": "), document.createTextNode(card.tip));
      await step(tip, [card.tip]);
    }

    // Colour key for the blocks used in this lesson
    const used = [...new Set([...rule, ...examples.flatMap(e => e.parts)].map(roleOf))];
    if (used.length) {
      const legend = el("div", "g-legend");
      used.forEach(r => legend.appendChild(el("span", "block role-" + r, tx.roles[r])));
      div.appendChild(legend);
    }
    addReplay(div, allSpeech.flatMap(x => Mila.speechParts(x)));
    scrollDown();
  }

  // Sentence builder: tap the shuffled blocks into the right order
  function buildSentence(build, card, then) {
    const parts = build && Array.isArray(build.parts) ? build.parts.filter(p => p && p.t) : [];
    if (parts.length < 2) return then(card);
    const tx = t();
    clearReplies();

    const div = addBot("builder");
    div.appendChild(el("div", "b-title", tx.buildTitle));
    if (build.translation) div.appendChild(el("div", "b-translation", build.translation));
    div.appendChild(el("div", "sub", tx.buildHint));
    const answer = el("div", "blocks b-answer");
    const bank = el("div", "blocks b-bank");
    div.append(answer, bank);

    // Shuffle (never leave it already in order)
    let order = parts.map((_, i) => i);
    for (let tries = 0; tries < 10 && order.every((v, i) => v === i); tries++) {
      order = order.map(v => [Math.random(), v]).sort((a, b) => a[0] - b[0]).map(x => x[1]);
    }
    const tiles = order.map(i => {
      const b = block(parts[i]);
      b.dataset.i = i;
      b.classList.add("tile");
      b.onclick = () => {
        if (div.classList.contains("done")) return;
        (b.parentElement === bank ? answer : bank).appendChild(b);
        checkBtn.disabled = bank.children.length > 0;
      };
      bank.appendChild(b);
      return b;
    });

    const actions = el("div", "b-actions");
    const checkBtn = el("button", "b-check", tx.buildCheck);
    checkBtn.type = "button";
    checkBtn.disabled = true;
    const reset = el("button", "b-reset", tx.buildReset);
    reset.type = "button";
    reset.onclick = () => { if (!div.classList.contains("done")) { tiles.forEach(x => bank.appendChild(x)); checkBtn.disabled = true; } };
    actions.append(checkBtn, reset);
    div.appendChild(actions);
    scrollDown();

    checkBtn.onclick = async () => {
      div.classList.add("done");
      actions.remove();
      Mila.voice.stop();
      const built = [...answer.children].map(x => parts[+x.dataset.i].t);
      const right = built.every((w, i) => w === parts[i].t);
      answer.classList.add(right ? "right" : "wrong");
      const sentence = sentenceOf(parts);
      if (!right) {
        div.appendChild(el("div", "sub", tx.correctOrder));
        div.appendChild(blocksLine(parts));
      }
      await sleep(300);
      await Promise.race([
        right ? milaLine(pick(tx.correct), "happy") : milaLine(tx.buildWrong, "sad"),
        sleep(6000)
      ]);
      await Promise.race([Mila.voice.speakParts([sentence]), sleep(8000)]);
      then(card);
    };

    readAloud(div, [tx.buildSpoken(build.translation || "")]);
  }

  /* ---------- "Another example" ---------- */

  function renderExample(ex) {
    const div = addBot("example-card");
    div.appendChild(el("div", "ex-label", t().exampleLabel));
    const line = el("div", "ex-sentence");
    line.append(el("span", "", ex.sentence), speakerButton(ex.sentence));
    div.appendChild(line);
    if (ex.translation) div.appendChild(el("div", "ex-translation", ex.translation));
    scrollDown();
    return div;
  }

  /* ---------- Entry point: called by app.js when Mila's reply is complete ---------- */

  let lastCard = null;
  let lessonRun = 0;   // bumped when the student sends a message, so a lesson in progress stops talking

  async function onReply(text, botDiv, courseUpdate) {
    if (courseUpdate !== undefined) {
      course = courseUpdate;
      renderHeader();
      if (course && course.just_learnt) loadCourse(true);   // refresh the sidebar counts
    }
    const intro = botDiv ? botDiv.textContent.trim() : "";
    if (botDiv && !intro) botDiv.remove();
    const grammar = parseGrammar(text);
    if (grammar) {
      // Grammar lesson: Mila explains with colour blocks, asks the check, then the builder
      grammar.kind = "grammar";
      lastCard = grammar;
      await teachGrammar(grammar);
      await sleep(300);
      return askCheck(grammar);
    }
    const build = parseBuild(text);
    if (build) {
      if (botDiv && intro) readAloud(botDiv, Mila.speechParts(intro));
      return buildSentence(build, lastCard, () => showReplies(lastCard));
    }

    const card = parseCard(text);
    const example = card ? null : parseExample(text);

    if (card) {
      // Word lesson: Mila explains the card out loud, then asks the quick check
      lastCard = card;
      const cardDiv = renderCard(card);
      Mila.setMood("happy");
      const speech = cardSpeech(card);
      addReplay(cardDiv, speech);
      await Promise.race([readAloud(cardDiv, speech), sleep(30000)]);
      await sleep(300);
      return askCheck(card);
    }

    if (example) {
      const exDiv = renderExample(example);
      const speech = [...Mila.speechParts(intro), example.sentence, example.translation];
      addReplay(exDiv, speech);
      Mila.setMood("happy");
      showReplies(lastCard);
      return readAloud(exDiv, speech);
    }

    // Anything else (feedback, explanations, answers): Mila reads the whole message
    const speech = Mila.speechParts(text);
    if (botDiv && intro) addReplay(botDiv, speech);
    Mila.setMood("happy");
    if (course && course.topic_done_reply) {
      // Asked for the next word but the topic is finished: celebrate and offer what's next
      await readAloud(botDiv, speech);
      return showTopicDone(course);
    }
    showReplies(lastCard);
    readAloud(botDiv, speech);
  }

  // renderRound: kept as the name app.js calls after switching language
  window.MilaLesson = { onReply, clearReplies, parseCard, renderRound: () => loadCourse(), startTopic,
                        interrupt: () => { lessonRun++; } };
  loadCourse();
})();
