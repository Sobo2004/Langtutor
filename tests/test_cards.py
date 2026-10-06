"""Parsing the structured cards Mila's replies carry ([[WORD ...]], [[GRAMMAR ...]])."""


def test_word_card_is_parsed(app_module):
    text = 'Here we go!\n[[WORD {"word": "Привет", "meaning": "Hi", "check": {"question": "?", "options": ["a", "b"], "answer": 0}}]]'
    card = app_module._parse_word_card(text)
    assert card["word"] == "Привет"
    assert card["meaning"] == "Hi"


def test_broken_or_empty_cards_are_ignored(app_module):
    assert app_module._parse_word_card("no card here") is None
    assert app_module._parse_word_card('[[WORD {"word": "Привет", }]]') is None     # invalid JSON
    assert app_module._parse_word_card('[[WORD {"word": "  "}]]') is None           # no word
    assert app_module._parse_grammar_card('[[GRAMMAR {"explain": "x"}]]') is None    # no title


def test_grammar_card_is_parsed(app_module):
    card = app_module._parse_grammar_card('Ok!\n[[GRAMMAR {"title": "Word order", "rule": [{"t": "Subject", "role": "subject"}]}]]')
    assert card["title"] == "Word order"
    assert card["rule"][0]["role"] == "subject"


def test_taught_word_is_taken_from_the_card(app_module):
    text = '[[WORD {"word": "Спасибо", "pron": "spa-SEE-ba", "meaning": "Thank you"}]]'
    assert app_module._extract_taught_word(text) == {"word": "Спасибо", "pronunciation": "spa-SEE-ba", "meaning": "Thank you"}


def test_grammar_prompt_examples_are_valid_json(app_module):
    import json
    for mode, prompt in app_module.GRAMMAR_CARD_FORMAT.items():
        example = prompt[prompt.index("[[GRAMMAR") + len("[[GRAMMAR "):prompt.index("]]\nRules")]
        card = json.loads(example)
        assert card["title"] and card["build"]["parts"], mode
