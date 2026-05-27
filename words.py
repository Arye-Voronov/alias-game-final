import json
import random
import unicodedata
from pathlib import Path


DATA_FILE = Path(__file__).with_name("data.json")
POINTS_BY_HINT = [10, 7, 4, 2, 0]
MAX_HINTS = 5
CATEGORY_LABELS = {
    "food_and_drinks": "אוכל ושתייה",
    "animals": "חיות",
    "countries": "מדינות",
    "house": "הבית",
    "nature_and_landscape": "טבע ונוף",
    "human_body": "גוף האדם",
}


def load_data():
    with DATA_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def get_categories():
    return list(load_data().keys())


def get_category_label(category):
    if category in CATEGORY_LABELS:
        return CATEGORY_LABELS[category]

    normalized = category.replace("_", " ").replace("-", " ").strip()
    return normalized[:1].upper() + normalized[1:]


def get_category_options():
    return [(category, get_category_label(category)) for category in get_categories()]


def get_words_by_category(category):
    data = load_data()
    if category not in data:
        raise KeyError(f"Unknown category: {category}")
    return data[category]


def get_random_entry(category):
    words_by_category = get_words_by_category(category)
    word, hints = random.choice(list(words_by_category.items()))
    return word, order_hints_by_difficulty(hints)


def get_random_word(category):
    word, _ = get_random_entry(category)
    return word


def get_hints(word, category):
    words_by_category = get_words_by_category(category)
    if word not in words_by_category:
        raise KeyError(f"Unknown word '{word}' in category '{category}'")
    return order_hints_by_difficulty(words_by_category[word])


def normalize_guess(text):
    text = "".join(char for char in text if unicodedata.category(char) != "Mn")
    for mark in "\"'׳״`.,!?;:()[]{}-_":
        text = text.replace(mark, " ")
    return " ".join(text.strip().lower().split())


def order_hints_by_difficulty(hints):
    # הנתונים נשמרים מהקשה אל הקל, ואנחנו גם חותכים ל-5 רמזים לכל היותר.
    return list(hints[:MAX_HINTS])


def get_points_for_hint_number(hint_number):
    if hint_number < 1:
        return 0
    return POINTS_BY_HINT[min(hint_number - 1, len(POINTS_BY_HINT) - 1)]
