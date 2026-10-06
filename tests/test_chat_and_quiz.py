"""A chat lesson end to end (with the AI replaced by a fake) and quiz helpers."""
import json


def _read_done_event(stream_text):
    for block in stream_text.split("\n\n"):
        if block.startswith("event: done"):
            return json.loads(block.split("data: ", 1)[1])
    raise AssertionError("no done event")


def test_next_word_teaches_the_course_word_and_records_progress(user, app_module, monkeypatch):
    client, _, uid = user
    seen = {}

    def fake_llm_stream(system_prompt, messages):
        seen["note"] = messages[-1]["content"]
        card = {"word": "Привет", "meaning": "Hi", "check": {"question": "?", "options": ["Привет", "Пока"], "answer": 0}}
        yield app_module.sse("delta", {"text": "Let's start!\n[[WORD " + json.dumps(card, ensure_ascii=False) + "]]"})

    monkeypatch.setattr(app_module, "llm_stream", fake_llm_stream)
    res = client.post("/chat/stream", json={"message": "Let's learn Greetings!", "language_mode": "en-ru",
                                             "intent": "next", "topic": "greetings"})
    assert res.status_code == 200
    assert "«Привет»" in seen["note"]                          # Mila was told which word to teach
    done = _read_done_event(res.text)
    assert done["course"]["just_learnt"] is True
    assert done["course"]["learnt"] == 1
    assert app_module._next_course_item(uid, "en-ru", "a1", "greetings")[0] == 1


def test_chat_is_rate_limited(user, app_module, monkeypatch):
    client, _, _ = user
    monkeypatch.setitem(app_module.RATE_LIMITS, "chat", (2, 60))
    monkeypatch.setattr(app_module, "llm_stream", lambda s, m: iter([app_module.sse("delta", {"text": "Hi!"})]))
    codes = [client.post("/chat/stream", json={"message": "hi"}).status_code for _ in range(3)]
    assert codes == [200, 200, 429]


def test_invalid_quiz_questions_are_dropped(app_module):
    payload = {"questions": [
        {"q": "Hello", "options": ["Привет", "Пока", "Да", "Нет"], "correct": 0},
        {"q": "Bad: 3 options", "options": ["a", "b", "c"], "correct": 0},
        {"q": "Bad: duplicate options", "options": ["a", "a", "b", "c"], "correct": 1},
        {"q": "Bad: answer out of range", "options": ["a", "b", "c", "d"], "correct": 7},
    ]}
    result = app_module._validate_mcq_payload(payload, 10)
    assert [q["q"] for q in result["questions"]] == ["Hello"]


def test_lesson_quiz_prefers_questions_about_learnt_words(app_module):
    words = [{"word": "Спасибо"}, {"word": "Пожалуйста"}]
    questions = [
        {"q": "Hello", "options": ["Привет", "Пока", "Да", "Нет"], "correct": 0},
        {"q": "Thank you", "options": ["Спасибо", "Пока", "Да", "Нет"], "correct": 0},
    ]
    ordered = app_module._prefer_lesson_questions(questions, words)
    assert ordered[0]["q"] == "Thank you"
