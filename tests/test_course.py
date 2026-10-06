"""course.json content and course progress (rounds, topics, levels)."""


def test_course_file_is_well_formed(app_module):
    course = app_module.load_course()
    assert course["levels"], "course has no levels"
    for level in course["levels"]:
        topic_ids = [t["id"] for t in level["topics"]]
        assert len(topic_ids) == len(set(topic_ids)), f"duplicate topic id in {level['id']}"
        for topic in level["topics"]:
            assert topic["items"], f"{topic['id']} has no items"
            assert {"en", "ru"} <= set(topic["name"])
            for item in topic["items"]:
                if level.get("kind") == "grammar":
                    assert {"en", "ru"} <= set(item["title"]) and {"en-ru", "ru-en"} <= set(item["focus"])
                else:
                    assert item["ru"].strip() and item["en"].strip()


def test_each_learner_gets_the_other_language(app_module):
    item = {"ru": "Спасибо", "en": "Thank you"}
    assert app_module._target_and_meaning(item, "en-ru") == ("Спасибо", "Thank you")   # English speaker learns Russian
    assert app_module._target_and_meaning(item, "ru-en") == ("Thank you", "Спасибо")   # Russian speaker learns English


def test_rounds_and_topic_completion(user, app_module):
    _, _, uid = user
    choice = ("a1", "greetings")
    for i in range(5):
        app_module._mark_learnt(uid, "en-ru", *choice, i)
    snap = app_module._course_snapshot(uid, "en-ru", "beginner", choice)
    assert (snap["learnt"], snap["round"], snap["in_round"]) == (5, 1, 5)
    assert snap["round_words"][0] == "Привет"
    assert not snap["topic_done"]

    app_module._mark_learnt(uid, "en-ru", *choice, 5)
    snap = app_module._course_snapshot(uid, "en-ru", "beginner", choice)
    assert (snap["round"], snap["in_round"]) == (2, 1)

    for i in range(6, 15):
        app_module._mark_learnt(uid, "en-ru", *choice, i)
    snap = app_module._course_snapshot(uid, "en-ru", "beginner", choice)
    assert snap["topic_done"] and snap["next_topic"]["id"] == "numbers"


def test_next_word_skips_what_was_learnt(user, app_module):
    _, _, uid = user
    app_module._mark_learnt(uid, "en-ru", "a1", "greetings", 0)
    idx, item, _, _ = app_module._next_course_item(uid, "en-ru", "a1", "greetings")
    assert idx == 1 and item["ru"] == "Здравствуйте"


def test_levels_unlock_in_order_or_by_chosen_level(user, app_module):
    _, _, uid = user
    beginner = app_module._course_overview(uid, "en-ru", "beginner")["levels"]
    assert [l["unlocked"] for l in beginner] == [True, False, False]
    advanced = app_module._course_overview(uid, "en-ru", "advanced")["levels"]
    assert all(l["unlocked"] for l in advanced)


def test_course_api(user):
    client, _, _ = user
    data = client.get("/api/course?language_mode=en-ru&difficulty=beginner").json()
    assert data["levels"][0]["topics"][0]["id"] == "greetings"
    assert data["active"]["topic"]["id"] == "greetings"
