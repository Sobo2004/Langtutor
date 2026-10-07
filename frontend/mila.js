/*******************************************************
 * Mila — LangTutor's tutor character.
 * Shared by every page: her face, expressions and voice.
 *
 *   <div class="mila-face"></div>      → animated Mila (filled in automatically)
 *   <img src="/static/mila.svg">       → static Mila
 *   Mila.setMood("happy"|"sad"|"thinking"|"idle")
 *   Mila.voice.speak(text)             → natural voice via /api/tts, browser voice as fallback
 *   Mila.onTalking(on => ...)          → react when she starts/stops talking
 *******************************************************/
(function () {
  // Inserted inline (not via <img>/<use>) so CSS can switch her expressions.
  const SVG = `
<svg viewBox="0 0 120 120" aria-hidden="true">
  <circle cx="60" cy="58" r="44" fill="#5b3a29"/>
  <rect x="18" y="58" width="84" height="44" rx="20" fill="#5b3a29"/>
  <ellipse cx="60" cy="106" rx="30" ry="12" fill="#764ba2"/>
  <rect x="53" y="92" width="14" height="10" rx="4" fill="#f5c9a4"/>
  <circle cx="60" cy="64" r="34" fill="#ffdcbf"/>
  <path d="M26 58 C28 30 54 22 70 28 C84 33 94 44 94 60 C84 50 70 44 56 46 C44 47 34 52 26 58 Z" fill="#6b4431"/>
  <circle cx="88" cy="36" r="7" fill="#a88bff"/><circle cx="96" cy="42" r="5" fill="#a88bff"/>
  <g class="brows" stroke="#5b3a29" stroke-width="3" stroke-linecap="round" fill="none">
    <path d="M40 55 q7 -4 13 0"/><path d="M67 55 q7 -4 13 0"/>
  </g>
  <g class="eyes-open" fill="#2b2b33">
    <ellipse cx="47" cy="65" rx="4.2" ry="5.2"/><ellipse cx="73" cy="65" rx="4.2" ry="5.2"/>
    <circle cx="48.5" cy="63" r="1.4" fill="#fff"/><circle cx="74.5" cy="63" r="1.4" fill="#fff"/>
  </g>
  <g class="eyes-happy" stroke="#2b2b33" stroke-width="3" stroke-linecap="round" fill="none">
    <path d="M42 66 q5 -6 10 0"/><path d="M68 66 q5 -6 10 0"/>
  </g>
  <circle cx="39" cy="76" r="5" fill="#ff9eb1" opacity="0.6"/><circle cx="81" cy="76" r="5" fill="#ff9eb1" opacity="0.6"/>
  <path class="mouth-smile" d="M51 79 q9 8 18 0" stroke="#b5485d" stroke-width="3" stroke-linecap="round" fill="none"/>
  <path class="mouth-sad" d="M52 84 q8 -6 16 0" stroke="#b5485d" stroke-width="3" stroke-linecap="round" fill="none"/>
  <ellipse class="mouth-open" cx="60" cy="81" rx="6" ry="5" fill="#b5485d"/>
</svg>`;

  const faces = () => document.querySelectorAll(".mila-face");

  // Line icons for buttons that need one (speaker, mic, mute, menu, hearts…). They take
  // the button's text colour. Use Mila.icon("speaker") in code, or data-icon="speaker" in HTML.
  const ICON_PATHS = {
    speaker: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/>',
    volume: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>',
    mute: '<polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><line x1="23" y1="9" x2="17" y2="15"/><line x1="17" y1="9" x2="23" y2="15"/>',
    mic: '<path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/><path d="M19 10v2a7 7 0 0 1-14 0v-2"/><line x1="12" y1="19" x2="12" y2="23"/><line x1="8" y1="23" x2="16" y2="23"/>',
    stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
    menu: '<line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/>',
    heart: '<path fill="currentColor" stroke="none" d="M20.84 4.61a5.5 5.5 0 0 0-7.78 0L12 5.67l-1.06-1.06a5.5 5.5 0 0 0-7.78 7.78l1.06 1.06L12 21.23l7.78-7.78 1.06-1.06a5.5 5.5 0 0 0 0-7.78z"/>',
    swap: '<polyline points="17 1 21 5 17 9"/><path d="M3 11V9a4 4 0 0 1 4-4h14"/><polyline points="7 23 3 19 7 15"/><path d="M21 13v2a4 4 0 0 1-4 4H3"/>',
  };

  function icon(name) {
    return `<svg class="icon icon-${name}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ` +
           `stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">${ICON_PATHS[name] || ""}</svg>`;
  }

  // Put an icon (and optional label text) inside an element. The label is added as text, never HTML.
  function setIcon(el, name, label) {
    el.innerHTML = icon(name);
    if (label) el.append(" ", Object.assign(document.createElement("span"), { textContent: label }));
  }

  function mount(root = document) {
    root.querySelectorAll(".mila-face").forEach(el => {
      if (!el.querySelector("svg")) el.innerHTML = SVG;
    });
    root.querySelectorAll("[data-icon]").forEach(el => {
      if (!el.querySelector("svg.icon")) el.insertAdjacentHTML("afterbegin", icon(el.dataset.icon));
    });
  }

  function setMood(mood) {
    faces().forEach(el => {
      el.classList.remove("happy", "sad", "thinking");
      if (mood && mood !== "idle") {
        void el.offsetWidth; // restart the bounce/droop animation
        el.classList.add(mood);
      }
    });
  }

  const talkingListeners = [];
  function setTalking(on) {
    faces().forEach(el => el.classList.toggle("talking", on));
    talkingListeners.forEach(cb => cb(on));
  }

  const voice = {
    muted: (() => { try { return localStorage.getItem("tutorMuted") === "1"; } catch (e) { return false; } })(),
    audio: null,
    cache: new Map(),      // text -> Promise<objectURL | null>
    serverOk: true,        // flips to false if /api/tts is unavailable, then we use the browser voice
    token: 0,
    _resolve: null,

    setMuted(m) {
      this.muted = m;
      try { localStorage.setItem("tutorMuted", m ? "1" : "0"); } catch (e) {}
      if (m) this.stop();
    },

    fetchAudio(text) {
      if (!this.serverOk) return Promise.resolve(null);
      if (!this.cache.has(text)) {
        const p = fetch("/api/tts", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text })
        })
          .then(res => {
            if (res.status === 503 || res.status === 401) this.serverOk = false;
            if (!res.ok) throw new Error("tts " + res.status);
            return res.blob();
          })
          .then(blob => URL.createObjectURL(blob))
          .catch(err => {
            console.warn("Mila's voice unavailable, using browser voice:", err);
            this.cache.delete(text);
            return null;
          });
        this.cache.set(text, p);
      }
      return this.cache.get(text);
    },

    // Warm the cache without playing
    preload(texts) {
      if (this.muted) return;
      texts.filter(Boolean).forEach(t => this.fetchAudio(t));
    },

    _finish() {
      setTalking(false);
      const r = this._resolve;
      this._resolve = null;
      if (r) r();
    },

    // Stop the current clip only (a multi-part speakParts sequence carries on)
    _halt() {
      this.token++;
      if (this.audio) { this.audio.onended = this.audio.onerror = null; this.audio.pause(); this.audio = null; }
      if ("speechSynthesis" in window) speechSynthesis.cancel();
      this._finish();
    },

    // Stop talking completely
    stop() {
      this.seq = (this.seq || 0) + 1;
      this._halt();
    },

    // Resolves when Mila has finished speaking. force=true plays even when muted
    // (the user pressed a speaker button).
    speak(text, opts) {
      this.seq = (this.seq || 0) + 1; // interrupts any multi-part speech
      return this._speakOne(text, opts);
    },

    // Speak several pieces one after another (long messages are split into sentences
    // so Mila starts talking straight away). Stops early if anything else speaks or stop() is called.
    async speakParts(parts, { force = false } = {}) {
      parts = (parts || []).map(p => String(p || "").trim()).filter(Boolean);
      if (!parts.length || (this.muted && !force)) return;
      const seq = this.seq = (this.seq || 0) + 1;
      parts.forEach(p => this.fetchAudio(p.slice(0, 400)));
      for (const part of parts) {
        if (seq !== this.seq) return;
        await this._speakOne(part, { force });
      }
    },

    _speakOne(text, { force = false } = {}) {
      text = String(text || "").trim().slice(0, 400);
      if (!text || (this.muted && !force)) return Promise.resolve();
      this._halt();
      const token = this.token;

      return new Promise(resolve => {
        this._resolve = resolve;
        const done = () => { if (token === this.token && this._resolve === resolve) this._finish(); };
        setTimeout(done, 15000); // safety net if the audio never reports "ended"

        this.fetchAudio(text).then(url => {
          if (token !== this.token) return;
          if (!url) return this.speakWithBrowser(text, done);

          const audio = new Audio(url);
          this.audio = audio;
          audio.onplaying = () => setTalking(true);
          audio.onended = audio.onerror = done;
          audio.play().catch(done);
        });
      });
    },

    speakWithBrowser(text, done) {
      if (!("speechSynthesis" in window)) return done();
      const u = new SpeechSynthesisUtterance(text);
      u.lang = /[а-яё]/i.test(text) ? "ru-RU" : "en-US";
      u.rate = 0.9;
      const voices = speechSynthesis.getVoices().filter(v => v.lang.startsWith(u.lang.slice(0, 2)));
      // Prefer the high quality "Natural"/"Online" voices that Edge and some systems ship with
      u.voice = voices.find(v => /natural|online|premium|enhanced/i.test(v.name)) || voices[0] || null;
      u.onstart = () => setTalking(true);
      u.onend = u.onerror = done;
      speechSynthesis.speak(u);
    }
  };

  // Turn a chat message into speakable pieces: drop markdown, emojis, cards and
  // romanised pronunciations, then split into sentences of up to ~250 characters.
  function speechParts(text) {
    let t = String(text || "")
      .replace(/\[\[(WORD|EXAMPLE|GRAMMAR|BUILD)[\s\S]*$/, "")
      .replace(/\[SPEAK:[^\]]*\]/g, "")
      .replace(/https?:\/\/\S+/g, "")
      .replace(/\s*\([A-Za-z]+(?:[- ][A-Za-z]+)*-[A-Za-z]+[?!]?\)/g, "")   // (pree-VYET), (ZDRA-stvooy-tye), (doh svee-DAN-ya)
      .replace(/[*_#`>|]/g, "")
      .replace(/\p{Extended_Pictographic}|️/gu, "")
      .replace(/[ \t]+/g, " ");
    const sentences = t.split(/(?<=[.!?…])\s+|\n+/).map(s => s.trim()).filter(s => /[\p{L}\p{N}]/u.test(s));
    const parts = [];
    for (const s of sentences) {
      const last = parts[parts.length - 1];
      if (last && last.length + s.length < 120) parts[parts.length - 1] = last + " " + s;
      else parts.push(s.length > 250 ? s.slice(0, 250) : s);
    }
    return parts;
  }

  window.Mila = {
    SVG,
    mount,
    setMood,
    voice,
    speechParts,
    icon,
    setIcon,
    onTalking: cb => talkingListeners.push(cb)
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => mount());
  else mount();
})();
