"""Front-end behaviour in a real browser."""
import json


def test_ai_replies_cannot_inject_html(page_factory):
    page = page_factory("/")
    html = page.evaluate("""botHTML('<img src=x onerror="window.hacked=1"> **Привет** <script>window.hacked=2</script>')""")
    assert "<img" not in html and "<script" not in html
    assert "&lt;img" in html
    assert "<strong>Привет</strong>" in html          # our own formatting still works
    page.evaluate("""addMessage('<img src=x onerror="window.hacked=1">', 'bot')""")
    page.wait_for_timeout(300)
    assert page.evaluate("window.hacked || false") is False
    assert page.errors == []


def test_typed_answers_are_marked_fairly(page_factory):
    page = page_factory("/quiz")
    q = {"options": ["Спасибо", "Пока", "Привет", "Да"], "correct": 0, "accepted": []}
    grade = lambda text: page.evaluate("([t, q]) => gradeTyped(t, q)", [text, q])
    assert grade("спасибо!!") == "exact"       # case and punctuation don't matter
    assert grade("Спосибо") == "typo"          # one wrong letter: right, with a spelling note
    assert grade("Пока") == "wrong"            # a different option is wrong even if close
    assert grade("Хорошо") == "wrong"


def test_mila_reads_text_without_cards_emojis_or_romanisation(page_factory):
    page = page_factory("/")
    parts = page.evaluate("""Mila.speechParts('Great job! 🎉 **Привет** (pree-VYET) means hello.\\n[[WORD {"word": "Привет"}]]')""")
    spoken = " ".join(parts)
    assert "Привет" in spoken and "hello" in spoken
    assert "[[WORD" not in spoken and "🎉" not in spoken and "pree-VYET" not in spoken and "**" not in spoken


def test_phone_layout_fits_and_menu_opens(page_factory):
    page = page_factory("/", logged_in=True, mobile=True)
    assert page.evaluate("document.documentElement.scrollWidth") <= 390
    assert page.locator("#menuBtn").is_visible()
    page.click("#menuBtn")
    assert page.evaluate("document.getElementById('sidebar').classList.contains('open')")
    assert page.get_attribute("#menuBtn", "aria-expanded") == "true"
    page.keyboard.press("Escape")
    assert not page.evaluate("document.getElementById('sidebar').classList.contains('open')")


def test_desktop_has_no_menu_button(page_factory):
    page = page_factory("/", logged_in=True)
    assert not page.locator("#menuBtn").is_visible()


def test_sentence_builder_works_with_the_keyboard(page_factory):
    page = page_factory("/", logged_in=True)
    build = {"translation": "My brother reads books.",
             "parts": [{"t": "My brother", "role": "subject"}, {"t": "reads", "role": "verb"}, {"t": "books", "role": "object"}]}
    page.evaluate("text => MilaLesson.onReply(text, null, undefined)", "Build this!\n[[BUILD " + json.dumps(build) + "]]")
    page.wait_for_selector(".builder .tile")
    assert page.locator(".builder .b-bank button.tile").count() == 3      # real buttons, reachable with Tab

    for i in range(3):                                                    # tap blocks in order using only Enter
        page.locator(f".builder .b-bank .tile[data-i='{i}']").focus()
        page.keyboard.press("Enter")
    page.locator(".builder .b-check").focus()
    page.keyboard.press("Enter")
    page.wait_for_selector(".builder .b-answer.right")
    assert page.errors == []


def test_language_switch_works_with_the_keyboard(page_factory):
    page = page_factory("/", logged_in=True)
    before = page.evaluate("localStorage.getItem('languageMode') || 'en-ru'")
    page.focus("#tourLanguage")
    page.keyboard.press("Enter")
    assert page.evaluate("localStorage.getItem('languageMode')") != before


def test_bracketed_meanings_are_still_read(page_factory):
    page = page_factory("/")
    spoken = " ".join(page.evaluate("Mila.speechParts('Привет (Hello) and Пока (doh svee-DAN-ya) means bye.')"))
    assert "(Hello)" in spoken and "svee-DAN-ya" not in spoken
