# -*- coding: utf-8 -*-
import difflib
import json
import random
import sys
import threading
import tkinter as tk
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk
import words


# שם המודל המקומי ש-Ollama יריץ בשביל רמזי AI.
OLLAMA_MODEL = "gemma3:4b"
OLLAMA_TIMEOUT_SECONDS = 60
SERVER_TIMEOUT_SECONDS = 130
APP_DIR = Path(__file__).resolve().parent
SETTINGS_FILE = APP_DIR / "settings.json"
SCORES_FILE = APP_DIR / "scores.json"
STATS_FILE = APP_DIR / "stats.json"
EXPORTS_DIR = APP_DIR / "game_exports"
DIFFICULTY_SETTINGS = {
    "קל": {"seconds": 90, "start_hints": 2, "max_attempts": 5, "score_bonus": 0},
    "רגיל": {"seconds": 60, "start_hints": 1, "max_attempts": 5, "score_bonus": 0},
    "קשה": {"seconds": 45, "start_hints": 1, "max_attempts": 4, "score_bonus": 2},
}
GAME_LENGTH_OPTIONS = ["כל הקטגוריה", "5", "10", "15", "20"]
RTL_START = "\u202B"
RTL_END = "\u202C"


def rtl_text(text):
    text = str(text)
    if not any("\u0590" <= char <= "\u05FF" for char in text):
        return text
    return "\n".join(f"{RTL_START}{line}{RTL_END}" if line else line for line in text.splitlines())


# מנקה תשובת AI מכותרות וממרכאות כדי להציג רק את הרמז עצמו.
def clean_ai_hint(hint):
    hint = hint.strip()
    for prefix in ("הרמז:", "רמז:", "Hint:"):
        if hint.startswith(prefix):
            hint = hint[len(prefix):].strip()
    return hint.strip("\"'“”")


# בודק שהרמז שה-AI החזיר באמת מתאים למשחק ולא חושף את המילה.
def is_usable_ai_hint(hint, word):
    normalized_hint = words.normalize_guess(hint)
    if not normalized_hint:
        return False
    if words.normalize_guess(word) in normalized_hint:
        return False
    if len(normalized_hint) < 6:
        return False
    if normalized_hint.count(" ") == 0 and any(mark in normalized_hint for mark in "?!"):
        return False
    return True


# הופך תשובת AI ארוכה לרשימה של 5 רמזים תקינים.
def parse_ai_hints(text, word):
    hints = []
    for line in text.splitlines():
        hint = clean_ai_hint(line)
        hint = hint.lstrip("-•0123456789. )(").strip()
        if is_usable_ai_hint(hint, word):
            hints.append(hint)
        if len(hints) == words.MAX_HINTS:
            break
    return hints if len(hints) == words.MAX_HINTS else None


def parse_single_ai_hint(text, word):
    for line in text.splitlines():
        hint = clean_ai_hint(line)
        hint = hint.lstrip("-•0123456789. )(").strip()
        if is_usable_ai_hint(hint, word):
            return hint

    hint = clean_ai_hint(text)
    return hint if is_usable_ai_hint(hint, word) else None


# שולח ל-Ollama את המילה והרמזים המוכנים, ומבקש ממנו לשפר אותם.
def generate_ollama_hints(word, prepared_hints, category):
    prompt = (
        "כתוב 5 רמזים בעברית למשחק Alias.\n"
        f"המילה הסודית היא: {word}\n"
        f"הקטגוריה היא: {category}\n"
        f"הרמזים המוכנים שכבר קיימים, מהקשה לקל, הם: {prepared_hints}\n"
        "המטרה: ליצור רמזים איכותיים יותר מהרמזים המוכנים, אבל בלי להפוך את המשחק לקל מדי.\n"
        "כל רמז צריך לתת כיוון משמעותי חדש, לא לחזור על אותו רעיון במילים אחרות.\n"
        "שמור על סדר קושי ברור: רמז 1 עקיף וחכם, רמז 3 כבר מכוון, רמז 5 כמעט פותר אבל עדיין לא חושף.\n"
        "עדיף רמזים שמבוססים על שימוש, מאפיינים, הקשר, פעולה או קטגוריה - לא על אותיות או צליל.\n"
        "כתוב בעברית טבעית, קצרה וברורה, בלי בדיחות ובלי ניסוח מוזר.\n"
        "רמז 1 צריך להיות הכי קשה, ורמז 5 הכי קל.\n"
        "אסור להשתמש במילה הסודית עצמה או בהטיות ישירות שלה.\n"
        "אסור להשתמש במילים מאותה משפחת שורש אם הן מסגירות את התשובה.\n"
        "אל תיתן משחק אותיות, אל תכתוב את האותיות של המילה, ואל תשתמש בצליל של המילה.\n"
        "ענה ב-5 שורות בלבד. בכל שורה רמז אחד קצר. בלי הסברים ובלי כותרות."
    )
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }

    try:
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
        return parse_ai_hints(data.get("response", ""), word)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


# שכבת עטיפה: כרגע ה-AI היחיד הוא Ollama, אבל כך קל להחליף ספק בעתיד.
def generate_ai_hints(word, prepared_hints, category):
    return generate_ollama_hints(word, prepared_hints, category)


def generate_ollama_adaptive_hint(word, base_hint, revealed_hints, wrong_guesses, category):
    recent_guesses = wrong_guesses[-3:]
    prompt = (
        "כתוב רמז אחד בעברית למשחק Alias.\n"
        f"המילה הסודית היא: {word}\n"
        f"הקטגוריה היא: {category}\n"
        f"הרמז הבא המקורי הוא: {base_hint}\n"
        f"רמזים שכבר נפתחו: {revealed_hints}\n"
        f"ניחושים שגויים אחרונים של השחקן: {recent_guesses}\n"
        "כתוב רמז טוב יותר מהרמז המקורי: ברור, קצר, ומועיל לשחקן.\n"
        "התאם את הרמז כך שיעזור לשחקן להתרחק מהכיוון השגוי ולהתקרב למילה הנכונה.\n"
        "אם הניחושים מראים בלבול בקטגוריה, תן רמז שמחדד את הקטגוריה או השימוש.\n"
        "אם הניחושים קרובים, תן רמז שמבדיל בינם לבין המילה הנכונה.\n"
        "אל תגיד במפורש שהניחוש שגוי ואל תזכיר את הניחוש עצמו אם זה מסגיר יותר מדי.\n"
        "אסור להשתמש במילה הסודית עצמה או בהטיות ישירות שלה.\n"
        "אסור להשתמש במילים מאותה משפחת שורש אם הן מסגירות את התשובה.\n"
        "אל תיתן משחק אותיות, אל תכתוב את האותיות של המילה, ואל תשתמש בצליל של המילה.\n"
        "ענה בשורה אחת בלבד. רמז קצר אחד, בלי הסברים ובלי כותרת."
    )
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }

    try:
        request = urllib.request.Request(
            "http://127.0.0.1:11434/api/generate",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
        return parse_single_ai_hint(data.get("response", ""), word)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def generate_adaptive_hint(word, base_hint, revealed_hints, wrong_guesses, category):
    return generate_ollama_adaptive_hint(word, base_hint, revealed_hints, wrong_guesses, category)


def read_json_file(path, fallback):
    try:
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return fallback


def write_json_file(path, data):
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=4)
        file.write("\n")


def get_hint_similarity(first_hint, second_hint):
    first = words.normalize_guess(first_hint)
    second = words.normalize_guess(second_hint)
    return difflib.SequenceMatcher(None, first, second).ratio()


def filter_duplicate_ai_hints(ai_hints, prepared_hints):
    if not ai_hints:
        return None
    filtered = []
    for hint in ai_hints:
        if any(get_hint_similarity(hint, existing) > 0.86 for existing in filtered):
            continue
        filtered.append(hint)
    if len(filtered) < words.MAX_HINTS:
        for hint in prepared_hints:
            if all(get_hint_similarity(hint, existing) <= 0.86 for existing in filtered):
                filtered.append(hint)
            if len(filtered) == words.MAX_HINTS:
                break
    return filtered[:words.MAX_HINTS] if len(filtered) == words.MAX_HINTS else None


class OnlineGameError(Exception):
    pass


class OnlineGameService:
    def __init__(self, server_url, room_id, player_name, hint_source="prepared"):
        self.server_url = server_url.rstrip("/")
        self.room_id = room_id.strip()
        self.player_name = player_name.strip() or "שחקן"
        self.hint_source = hint_source if hint_source in ("prepared", "ai") else "prepared"

    def _request(self, method, path, payload=None):
        url = self.server_url + path
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=SERVER_TIMEOUT_SECONDS) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            detail = error.read().decode("utf-8", errors="replace")
            raise OnlineGameError(f"השרת החזיר שגיאה {error.code}: {detail or error.reason}") from error
        except (OSError, urllib.error.URLError) as error:
            raise OnlineGameError(f"לא הצלחתי להתחבר לשרת: {error}") from error

        if not body.strip():
            return {}
        try:
            return json.loads(body)
        except json.JSONDecodeError as error:
            raise OnlineGameError("השרת ענה, אבל לא החזיר JSON תקין.") from error

    def health(self):
        return self._request("GET", "/health")

    def scores(self):
        return self._request("GET", "/scores").get("scores", [])

    def stats(self):
        return self._request("GET", "/stats").get("stats", {})

    def create_room(self, category, difficulty, max_rounds, timer_enabled=True, time_limit=0):
        payload = {
            "player": self.player_name,
            "category": category,
            "difficulty": difficulty,
            "max_rounds": max_rounds,
            "hint_source": self.hint_source,
            "timer_enabled": timer_enabled,
            "time_limit": time_limit,
        }
        data = self._request("POST", "/rooms", payload)
        self.room_id = str(data.get("room_id") or data.get("room") or self.room_id)
        return data.get("state", data)

    def join_room(self):
        if not self.room_id:
            raise OnlineGameError("חסר קוד חדר.")
        payload = {"player": self.player_name}
        data = self._request("POST", f"/rooms/{self.room_id}/join", payload)
        return data.get("state", data)

    def start_game(self, category, difficulty, max_rounds, timer_enabled=True, time_limit=0):
        if not self.room_id:
            return self.create_room(category, difficulty, max_rounds, timer_enabled, time_limit)
        return self.join_room()

    def state(self):
        if not self.room_id:
            raise OnlineGameError("חסר קוד חדר.")
        return self._request("GET", f"/rooms/{self.room_id}/state")

    def next_round(self):
        data = self._request("POST", f"/rooms/{self.room_id}/next-round", {"player": self.player_name})
        return data.get("state", data)

    def submit_guess(self, guess):
        payload = {"player": self.player_name, "guess": guess}
        data = self._request("POST", f"/rooms/{self.room_id}/guess", payload)
        return data.get("state", data)

    def request_hint(self):
        data = self._request("POST", f"/rooms/{self.room_id}/hint", {"player": self.player_name})
        return data.get("state", data)

    def skip_round(self):
        data = self._request("POST", f"/rooms/{self.room_id}/skip", {"player": self.player_name})
        return data.get("state", data)


# AliasGameApp implements the full Alias guessing game UI and logic.
class AliasGameApp:
    window_count = 0

    # Initialize app state, UI styles, and starting state when constructed.
    def __init__(self, root):
        AliasGameApp.window_count += 1
        self.colors = {
            "hero":         "#B80F2A",
            "hero_accent":  "#7A0A1B",
            "card":         "#FFFFFF",
            "card_alt":     "#FFF5F6",
            "card_inner":   "#FFF3F5",
            "entry":        "#FFFFFF",
            "list":         "#FFFFFF",
            "primary":      "#B80F2A",
            "text":         "#1A1A1A",
            "muted":        "#747474",
            "info":         "#8F1230",
            "success":      "#1A7A4A",
            "warning":      "#B45309",
            "error":        "#8F1230",
            "bg":           "#FBF7F8",
        }
        self.root = root
        self.root.title(f"Alias AI - חלון {AliasGameApp.window_count}")
        self.root.geometry("1060x760")
        self.root.minsize(900, 660)
        self.root.configure(bg=self.colors["bg"])

        # מצב המשחק: ניקוד, מילה נוכחית, רמזים, ניסיונות וקטגוריה.
        self.score = 0
        self.secret_word = None
        self.all_hints = []
        self.revealed_hints = []
        self.wrong_guesses = []
        self.used_extra_hint = False
        self.pending_adaptive_status = ""
        self.attempts_used = 0
        self.round_number = 0
        self.round_finished = False
        self.current_category = None
        self.current_difficulty = "רגיל"
        self.randomizer = random.SystemRandom()
        self.category_options = []
        self.category_lookup = {}
        self.used_words = set()
        self.hint_source_var = tk.StringVar(value="prepared")
        self.difficulty_var = tk.StringVar(value="רגיל")
        self.game_length_var = tk.StringVar(value=GAME_LENGTH_OPTIONS[0])
        self.player_name_var = tk.StringVar(value="שחקן")
        self.use_server_var = tk.BooleanVar(value=False)
        self.server_url_var = tk.StringVar(value="")
        self.room_id_var = tk.StringVar(value="")
        self.practice_mode_var = tk.BooleanVar(value=False)
        self.timer_enabled_var = tk.BooleanVar(value=True)
        self.online_service = None
        self.multiplayer_active = False
        self.online_scoreboard = {}
        self.ai_request_id = 0
        self.adaptive_hint_request_id = 0
        self.timer_after_id = None
        self.animation_after_id = None
        self.status_animation_after_id = None
        self.loading_after_id = None
        self.hint_animation_after_ids = []
        self.progress_after_id = None
        self.last_hint_count = 0
        self.displayed_attempts = 0
        self.time_left = 0
        self.max_rounds = None
        self.correct_words = 0
        self.failed_words = 0
        self.skipped_words = 0
        self.total_hints_used = 0
        self.success_streak = 0
        self.struggle_streak = 0
        self.dynamic_difficulty_message = ""
        self.last_summary = ""
        self.round_results = []
        self.achievements = set()
        self.best_correct_streak = 0
        self.current_correct_streak = 0
        self.one_hint_wins = 0
        self.settings = read_json_file(SETTINGS_FILE, {})

        # בניית המסך והכנת הנתונים הראשוניים.
        self.configure_styles()
        self.build_layout()
        self.populate_categories()
        self.load_saved_settings()
        self.refresh_multiplayer_status()
        self.refresh_online_banner()
        self.render_intro_state()

    # Configure all ttk style themes and self.colors["bg" visual styles used by the app.
    def configure_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
    
        # צבעי בסיס לסגנונות Tkinter/ttk.
        red       = self.colors["primary"]
        red_dark  = self.colors["hero_accent"]
        red_soft  = "#FFF3F5"
        red_muted = "#F2B7C2"
        white     = "#FFFFFF"
        bg_main   = "#FAFAFA"
        text_dark = "#1A1A1A"
        muted     = "#888888"
    
        style.configure("App.TFrame", background=bg_main)
    
        style.configure("Title.TLabel",
            background=red, foreground=white,
            font=("Segoe UI", 34, "bold"), anchor="center")
    
        style.configure("Subtitle.TLabel",
            background=red, foreground="#FFCCCC",
            font=("Segoe UI", 11), anchor="center")
    
        style.configure("CardTitle.TLabel",
            background=white, foreground=red,
            font=("Segoe UI", 12, "bold"))
    
        style.configure("Body.TLabel",
            background=white, foreground=muted,
            font=("Segoe UI", 10))
    
        style.configure("MetricValue.TLabel",
            background=white, foreground=red,
            font=("Segoe UI", 24, "bold"))
    
        style.configure("MetricLabel.TLabel",
            background=white, foreground=muted,
            font=("Segoe UI", 10, "bold"))
    
        style.configure("Start.TButton",
            font=("Segoe UI", 13, "bold"),
            background=red, foreground=white, borderwidth=0)
        style.map("Start.TButton",
            background=[("active", red_dark), ("disabled", red_muted)])
    
        style.configure("Next.TButton",
            font=("Segoe UI", 12, "bold"),
            background=white, foreground=red, borderwidth=1, relief="solid")
        style.map("Next.TButton",
            background=[("active", red_soft), ("disabled", white)],
            foreground=[("disabled", muted)])
    
        style.configure("Guess.TButton",
            font=("Segoe UI", 13, "bold"),
            background=red_dark, foreground=white, borderwidth=0)
        style.map("Guess.TButton",
            background=[("active", "#7A0A1B"), ("disabled", red_muted)])
    
        style.configure("Game.Horizontal.TProgressbar",
            troughcolor=red_muted, background=red, thickness=8, borderwidth=0)
    
        style.configure("TCombobox",
            fieldbackground=white, background=white, foreground=text_dark,
            selectbackground=red_soft, selectforeground=text_dark)
        style.map("TCombobox",
        fieldbackground=[("readonly", white)],
        foreground=[("readonly", text_dark)])
    # Build the GUI layout with frames, buttons, labels and interactive widgets.
    def build_layout(self):
        self.root.grid_columnconfigure(0, weight=1)
        self.root.grid_rowconfigure(0, weight=1)

        self.home_screen = ttk.Frame(self.root, style="App.TFrame", padding=22)
        self.game_screen = ttk.Frame(self.root, style="App.TFrame", padding=20)
        for screen in (self.home_screen, self.game_screen):
            screen.grid(row=0, column=0, sticky="nsew")
            screen.grid_columnconfigure(0, weight=1)

        self.home_screen.grid_rowconfigure(1, weight=1)

        home_header = tk.Frame(
            self.home_screen,
            bg=self.colors["hero"],
            highlightthickness=2,
            highlightbackground="#F2B7C2",
            bd=0,
            padx=30,
            pady=30,
        )
        home_header.grid(row=0, column=0, sticky="ew", pady=(0, 16))
        home_header.grid_columnconfigure(0, weight=1)
        ttk.Label(home_header, text="Alias AI", style="Title.TLabel").grid(row=0, column=0, sticky="e")
        ttk.Label(
            home_header,
            text="בחר הגדרות, בדוק את המאגר, ואז עבור למשחק",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="e", pady=(6, 0))

        # מעטפת מסך המשחק.
        outer = self.game_screen
        outer.grid_columnconfigure(0, weight=1)
        outer.grid_rowconfigure(3, weight=1)

        # כותרת עליונה של המשחק.
        header = tk.Frame(
            outer,
            bg=self.colors["hero"],
            highlightthickness=2,
            highlightbackground="#F2B7C2",
            bd=0,
            padx=26,
            pady=26,
        )
        header.grid(row=0, column=0, sticky="ew", pady=(0, 14))
        header.grid_columnconfigure(0, weight=1)

        ttk.Label(header, text="Alias AI", style="Title.TLabel").grid(row=0, column=0, sticky="e")
        ttk.Label(
            header,
            text="משחק ניחוש מילים עם רמזים שמתחילים קשים והופכים קלים יותר בכל ניסיון",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="e", pady=(6, 0))
        self.hero_badge = tk.Label(
            header,
            text="Game Center Style",
            bg=self.colors["hero_accent"],
            fg="#ffffff",
            font=("Helvetica", 10, "bold"),
            padx=18,
            pady=9,
        )
        self.hero_badge.grid(row=0, column=1, rowspan=2, sticky="w", padx=(0, 12))
        self.online_banner = tk.Label(
            header,
            text="Solo",
            bg="#ffffff",
            fg=self.colors["hero_accent"],
            font=("Helvetica", 10, "bold"),
            padx=18,
            pady=9,
        )
        self.online_banner.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(14, 0))

        # אזור בחירת קטגוריה, התחלת משחק ובחירת מקור הרמזים.
        controls_card = tk.Frame(self.home_screen, bg=self.colors["card"], bd=0, highlightthickness=2, highlightbackground="#FFE2E7", padx=26, pady=26)
        controls_card.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        controls_card.grid_columnconfigure(0, weight=1)
        controls_card.grid_columnconfigure(1, weight=1)
        controls_card.grid_columnconfigure(2, weight=0)
        controls_card.grid_columnconfigure(3, weight=0)

        ttk.Label(controls_card, text="קטגוריה", style="CardTitle.TLabel").grid(
            row=0, column=3, sticky="ne", padx=(0, 10)
        )

        self.category_var = tk.StringVar()
        self.category_combo = ttk.Combobox(
            controls_card,
            textvariable=self.category_var,
            state="readonly",
            justify="right",
            font=("Arial", 12),
        )
        self.category_combo.grid(row=0, column=2, sticky="ew", padx=(12, 0))

        self.start_button = ttk.Button(
            controls_card,
            text="התחל משחק",
            style="Start.TButton",
            command=self.start_game,
        )
        self.start_button.grid(row=0, column=0, columnspan=2, sticky="ew", padx=(12, 0))

        ttk.Label(controls_card, text="רמת קושי", style="CardTitle.TLabel").grid(
            row=1, column=3, sticky="ne", padx=(0, 10), pady=(14, 0)
        )

        self.difficulty_combo = ttk.Combobox(
            controls_card,
            textvariable=self.difficulty_var,
            values=list(DIFFICULTY_SETTINGS),
            state="readonly",
            justify="right",
            font=("Arial", 12),
            width=10,
        )
        self.difficulty_combo.grid(row=1, column=2, sticky="ew", padx=(12, 0), pady=(14, 0))

        ttk.Label(controls_card, text="שם שחקן", style="CardTitle.TLabel").grid(
            row=2, column=3, sticky="ne", padx=(0, 10), pady=(14, 0)
        )
        self.player_entry = tk.Entry(
            controls_card,
            textvariable=self.player_name_var,
            justify="right",
            font=("Arial", 12),
            relief="solid",
            bd=1,
            bg=self.colors["entry"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            highlightthickness=2,
            highlightbackground="#FFE2E7",
            highlightcolor=self.colors["primary"],
        )
        self.player_entry.grid(row=2, column=2, sticky="ew", padx=(12, 0), pady=(14, 0))
        self.enable_entry_edit_shortcuts(self.player_entry)

        self.game_length_combo = ttk.Combobox(
            controls_card,
            textvariable=self.game_length_var,
            values=GAME_LENGTH_OPTIONS,
            state="readonly",
            justify="right",
            font=("Arial", 12),
            width=12,
        )
        self.game_length_combo.grid(row=2, column=1, sticky="ew", padx=(12, 0), pady=(14, 0))

        self.practice_check = tk.Checkbutton(
            controls_card,
            text="אימון ללא ניקוד (0 נקודות)",
            variable=self.practice_mode_var,
            bg=self.colors["card"],
            fg=self.colors["text"],
            activebackground=self.colors["card"],
            activeforeground=self.colors["primary"],
            selectcolor=self.colors["card_inner"],
            font=("Helvetica", 11, "bold"),
            anchor="e",
            justify="right",
        )
        self.practice_check.grid(row=2, column=0, sticky="e", pady=(14, 0))

        self.timer_check = tk.Checkbutton(
            controls_card,
            text="משחק עם טיימר",
            variable=self.timer_enabled_var,
            bg=self.colors["card"],
            fg=self.colors["text"],
            activebackground=self.colors["card"],
            activeforeground=self.colors["primary"],
            selectcolor=self.colors["card_inner"],
            font=("Helvetica", 11, "bold"),
            anchor="e",
            justify="right",
        )
        self.timer_check.grid(row=3, column=0, sticky="e", pady=(14, 0))

        # בחירה בין רמזים מוכנים לבין רמזים שה-AI משפר בתחילת כל סבב.
        hint_source_frame = tk.Frame(controls_card, bg=self.colors["card"])
        hint_source_frame.grid(row=3, column=2, columnspan=2, sticky="e", pady=(14, 0), padx=(0, 10))

        self.prepared_hints_radio = tk.Radiobutton(
            hint_source_frame,
            text="רמזים מוכנים מראש",
            variable=self.hint_source_var,
            value="prepared",
            bg=self.colors["card"],
            fg=self.colors["text"],
            activebackground=self.colors["card"],
            activeforeground=self.colors["primary"],
            selectcolor=self.colors["card_inner"],
            font=("Helvetica", 11, "bold"),
            anchor="e",
            justify="right",
        )
        self.prepared_hints_radio.grid(row=0, column=1, sticky="e", padx=(14, 0))

        self.ai_hints_radio = tk.Radiobutton(
            hint_source_frame,
            text="AI משפר רמזים מוכנים",
            variable=self.hint_source_var,
            value="ai",
            bg=self.colors["card"],
            fg=self.colors["text"],
            activebackground=self.colors["card"],
            activeforeground=self.colors["primary"],
            selectcolor=self.colors["card_inner"],
            font=("Helvetica", 11, "bold"),
            anchor="e",
            justify="right",
        )
        self.ai_hints_radio.grid(row=0, column=0, sticky="e")

        self.multiplayer_check = tk.Checkbutton(
            controls_card,
            text="Multiplayer דרך שרת",
            variable=self.use_server_var,
            command=self.on_multiplayer_toggle,
            bg=self.colors["card"],
            fg=self.colors["text"],
            activebackground=self.colors["card"],
            activeforeground=self.colors["primary"],
            selectcolor=self.colors["card_inner"],
            font=("Helvetica", 11, "bold"),
            anchor="e",
            justify="right",
        )
        self.multiplayer_check.grid(row=4, column=3, sticky="e", padx=(0, 10), pady=(14, 0))

        ttk.Label(controls_card, text="כתובת שרת", style="CardTitle.TLabel").grid(
            row=4, column=0, sticky="ne", padx=(12, 0), pady=(14, 0)
        )

        self.server_entry = tk.Entry(
            controls_card,
            textvariable=self.server_url_var,
            justify="right",
            font=("Arial", 12),
            relief="solid",
            bd=1,
            bg=self.colors["entry"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            highlightthickness=2,
            highlightbackground="#FFE2E7",
            highlightcolor=self.colors["primary"],
        )
        self.server_entry.grid(row=4, column=1, columnspan=2, sticky="ew", padx=(12, 0), pady=(14, 0))
        self.enable_entry_edit_shortcuts(self.server_entry)

        ttk.Label(controls_card, text="קוד חדר", style="CardTitle.TLabel").grid(
            row=5, column=3, sticky="ne", padx=(0, 10), pady=(14, 0)
        )
        self.room_entry = tk.Entry(
            controls_card,
            textvariable=self.room_id_var,
            justify="right",
            font=("Arial", 12),
            relief="solid",
            bd=1,
            bg=self.colors["entry"],
            fg=self.colors["text"],
            insertbackground=self.colors["text"],
            highlightthickness=2,
            highlightbackground="#FFE2E7",
            highlightcolor=self.colors["primary"],
        )
        self.room_entry.grid(row=5, column=2, sticky="ew", padx=(12, 0), pady=(14, 0))
        self.enable_entry_edit_shortcuts(self.room_entry)

        self.new_room_button = ttk.Button(
            controls_card,
            text="חדר חדש",
            style="Next.TButton",
            command=self.clear_room_code,
        )
        self.new_room_button.grid(row=5, column=1, sticky="ew", padx=(12, 0), pady=(14, 0))

        server_buttons_frame = tk.Frame(controls_card, bg=self.colors["card"])
        server_buttons_frame.grid(row=5, column=0, sticky="ew", padx=(12, 0), pady=(14, 0))
        server_buttons_frame.grid_columnconfigure(0, weight=1)
        server_buttons_frame.grid_columnconfigure(1, weight=1)

        self.server_paste_button = ttk.Button(
            server_buttons_frame,
            text="הדבק כתובת",
            style="Next.TButton",
            command=self.paste_server_url,
        )
        self.server_paste_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        self.server_test_button = ttk.Button(
            server_buttons_frame,
            text="בדוק שרת",
            style="Next.TButton",
            command=self.test_server_connection,
        )
        self.server_test_button.grid(row=0, column=0, sticky="ew")

        self.multiplayer_status_label = tk.Label(
            controls_card,
            text="Multiplayer כבוי",
            bg="#FFF8E8",
            fg=self.colors["warning"],
            font=("Helvetica", 11, "bold"),
            anchor="e",
            justify="right",
            padx=12,
            pady=10,
        )
        self.multiplayer_status_label.grid(row=6, column=0, columnspan=4, sticky="ew", pady=(14, 0))

        self.categories_summary = tk.Label(
            controls_card,
            text="",
            bg=self.colors["card"],
            fg=self.colors["muted"],
            font=("Helvetica", 11),
            anchor="e",
            justify="right",
        )
        self.categories_summary.grid(row=7, column=0, columnspan=4, sticky="ew", pady=(14, 0))

        tools_frame = tk.Frame(controls_card, bg=self.colors["card"])
        tools_frame.grid(row=8, column=0, columnspan=4, sticky="ew", pady=(14, 0))
        for index in range(4):
            tools_frame.grid_columnconfigure(index, weight=1)

        ttk.Button(tools_frame, text="שיאים", style="Next.TButton", command=self.show_high_scores).grid(
            row=0, column=3, sticky="ew", padx=(0, 8)
        )
        ttk.Button(tools_frame, text="סטטיסטיקה", style="Next.TButton", command=self.show_category_stats).grid(
            row=0, column=2, sticky="ew", padx=8
        )
        ttk.Button(tools_frame, text="ייצוא סיכום", style="Next.TButton", command=self.export_last_summary).grid(
            row=0, column=1, sticky="ew", padx=8
        )
        ttk.Button(tools_frame, text="חלון נוסף", style="Next.TButton", command=self.open_additional_window).grid(
            row=0, column=0, sticky="ew", padx=(8, 0)
        )

        game_actions = tk.Frame(outer, bg=self.colors["card"], bd=0, highlightthickness=2, highlightbackground="#FFE2E7", padx=18, pady=14)
        game_actions.grid(row=1, column=0, sticky="ew", pady=(0, 12))
        for index in range(5):
            game_actions.grid_columnconfigure(index, weight=1)

        ttk.Button(game_actions, text="חזרה לבית", style="Next.TButton", command=self.return_home).grid(
            row=0, column=4, sticky="ew", padx=(0, 8)
        )
        self.next_button = ttk.Button(
            game_actions,
            text="למילה הבאה",
            style="Next.TButton",
            command=self.next_round,
            state="disabled",
        )
        self.next_button.grid(row=0, column=3, sticky="ew", padx=8)
        self.skip_button = ttk.Button(
            game_actions,
            text="דלג",
            style="Next.TButton",
            command=self.skip_round,
            state="disabled",
        )
        self.skip_button.grid(row=0, column=2, sticky="ew", padx=8)
        self.extra_hint_button = ttk.Button(
            game_actions,
            text="רמז AI נוסף",
            style="Next.TButton",
            command=self.request_extra_ai_hint,
            state="disabled",
        )
        self.extra_hint_button.grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(game_actions, text="ייצוא סיכום", style="Next.TButton", command=self.export_last_summary).grid(
            row=0, column=0, sticky="ew", padx=(8, 0)
        )

        # כרטיסי מדדים: ניקוד, כמות רמזים פתוחים וקטגוריה.
        metrics = ttk.Frame(outer, style="App.TFrame")
        metrics.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        for index in range(5):
            metrics.grid_columnconfigure(index, weight=1)

        self.score_value = self.build_metric(metrics, 0, "ניקוד", "0")
        self.hints_value = self.build_metric(metrics, 1, "רמזים פתוחים", f"0/{words.MAX_HINTS}")
        self.timer_value = self.build_metric(metrics, 2, "זמן", "--")
        self.difficulty_value = self.build_metric(metrics, 3, "קושי דינמי", "רגיל")
        self.category_value = self.build_metric(metrics, 4, "קטגוריה", "עדיין לא נבחרה")

        # אזור התוכן הראשי: רמזים בצד אחד וניחושים בצד השני.
        content = ttk.Frame(outer, style="App.TFrame")
        content.grid(row=3, column=0, sticky="nsew")
        content.grid_columnconfigure(0, weight=3)
        content.grid_columnconfigure(1, weight=2)
        content.grid_rowconfigure(0, weight=1)

        # לוח הסבב: סטטוס, התקדמות ורשימת הרמזים שנפתחו.
        game_card = tk.Frame(content, bg=self.colors["card"], bd=0, highlightthickness=2, highlightbackground="#FFE2E7", padx=24, pady=24)
        game_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        game_card.grid_columnconfigure(0, weight=1)
        game_card.grid_rowconfigure(4, weight=1)

        self.round_title = ttk.Label(game_card, text="מוכנים להתחיל?", style="CardTitle.TLabel")
        self.round_title.grid(row=0, column=0, sticky="e")
        self.status_box = tk.Label(
            game_card,
            text="בחר קטגוריה ולחץ על התחל משחק כדי לקבל את הרמז הראשון!",
            bg="#f3f7ff",
            fg=self.colors["info"],
            font=("Helvetica", 13, "bold"),
            anchor="e",
            justify="right",
            wraplength=520,
            padx=18,
            pady=16,
        )
        self.status_box.grid(row=1, column=0, sticky="ew", pady=(12, 10))

        # פונקציית למדא ישירה לפתיחת החלון ללא תלות במיקום פונקציות אחרות בקובץ
        self.rules_btn = tk.Button(
            game_card, text="❓ חוקי המשחק", font=("Arial", 11, "bold"),
            bg="white", fg="#b30021", cursor="hand2",
            command=lambda: [
                rules_win := tk.Toplevel(self.root),
                rules_win.title("📜 הוראות וחוקי המשחק: Alias AI"),
                rules_win.geometry("650x600"),
                rules_win.configure(bg="#f8f9fa"),
                rules_win.wm_attributes("-topmost", True),
                tk.Label(rules_win, text="📜 הוראות וחוקי המשחק: Alias AI", font=("Arial", 16, "bold"), bg="#f8f9fa", fg="#b30021").pack(pady=12),
                frame := tk.Frame(rules_win, bg="#f8f9fa"),
                frame.pack(expand=True, fill="both", padx=20, pady=5),
                scrollbar := tk.Scrollbar(frame),
                scrollbar.pack(side="left", fill="y"),
                text_widget := tk.Text(frame, wrap="word", font=("Arial", 11), bg="white", yscrollcommand=scrollbar.set, padx=15, pady=15, spacing1=6, cursor="arrow"),
                text_widget.pack(expand=True, fill="both"),
                scrollbar.configure(command=text_widget.yview),
                text_widget.insert("1.0", """ברוכים הבאים לגרסה הדיגיטלית והחכמה של משחק המילים המפורסם! במשחק זה תצטרכו לנחש מילים סודיות בעזרת רמזים שיופיעו על המסך בזמן אמת.

🛠️ שלב 1: הגדרת המשחק (בתפריט הראשי)
לפני שיוצאים לדרך, מגדירים את הנתונים במסך הבית:
1. שם שחקן: הקלידו את השם שלכם.
2. בחירת קטגוריה: בחרו את נושא המילים שתרצו (אוכל, חפצים, חיות ועוד).
3. רמת קושי: בחרו את רמת הקושי המתאימה לכם.
4. מצב אימון: ניתן לסמן "מצב אימון" כדי לשחק בכיף ללא חישוב ניקוד.

⚠️ חזרה לדף הבית: בכל שלב במשחק ניתן ללחוץ על כפתור "חזור לדף הבית" כדי לשנות שם, קטגוריה או קושי. שימו לב: חזרה לדף הבית מוחקת את היסטוריית המשחק, והניקוד יתאפס ויתחיל מהתחלה!

🎮 שלב 2: מהלך המשחק והרמזים
• לוחצים על "התחל משחק" – המילה הסודית נבחרת, הטיימר מתחיל לרוץ, והרמז הראשון מופיע.
• איך מקבלים עוד רמזים? אי אפשר לבקש רמז סתם כך. הרמז הבא ייחשף רק אם ניחשתם לא נכון. לכל מילה יש מקסימום 5 רמזים.
• כפתורי עזרה במהלך המשחק:
  - גלה תשובה: אם נתקעתם, לחיצה על כפתור זה תחשוף מיד את המילה הסודית, ותאפשר לכם ללחוץ על "למילה הבאה".
  - דלג: לחיצה על כפתור זה תחשוף את המילה הנוכחית ותעביר אתכם הלאה.

📈 שלב 3: שיטת הניקוד והזמן
הניקוד שלכם נקבע לפי כמות הרמזים שנאלצתם לראות כדי לנחש את המילה:
• 🎯 ניחוש נכון לפי רמז 1 👈 זוכה ב-10 נקודות
• 🎯 ניחוש נכון לפי 2 רמזים 👈 זוכה ב-7 נקודות
• 🎯 ניחוש נכון לפי 3 רמזים 👈 זוכה ב-4 נקודות
• 🎯 ניחוש נכון לפי 4 רמזים 👈 זוכה ב-2 נקודות
• 🎯 ניחוש נכון לפי 5 רמזים 👈 לא מזכה בנקודות (0 נק').

⏱️ הזמן עבר! הטיימר מוגדר לכל מילה בנפרד. אם הזמן של המילה הנוכחית נגמר לפני שהספקתם לנחש – המילה הסודית תתגלה אוטומטית, ותצטרכו ללחוץ על "למילה הבאה" כדי להמשיך."""),
                text_widget.tag_configure("right", justify="right"),
                text_widget.tag_add("right", "1.0", "end"),
                text_widget.configure(state="disabled"),
                tk.Button(rules_win, text="הבנתי, סגור חלון", font=("Arial", 10, "bold"), bg="#b30021", fg="white", command=rules_win.destroy, cursor="hand2").pack(pady=12)
            ]
        )
        self.rules_btn.grid(row=10, column=0, sticky="ew", pady=(15, 5))
        self.progress_label = ttk.Label(game_card, text="התקדמות בסבב", style="Body.TLabel")
        self.progress_label.grid(row=2, column=0, sticky="e", pady=(0, 6))

        self.progress = ttk.Progressbar(
            game_card,
            maximum=words.MAX_HINTS,
            value=0,
            style="Game.Horizontal.TProgressbar",
        )
        self.progress.grid(row=3, column=0, sticky="ew", pady=(0, 14))

        hints_card = tk.Frame(game_card, bg=self.colors["card_inner"], bd=0, highlightthickness=2, highlightbackground="#FFD7DF", padx=14, pady=14)
        hints_card.grid(row=4, column=0, sticky="nsew")
        hints_card.grid_columnconfigure(0, weight=1)
        hints_card.grid_rowconfigure(0, weight=1)

        self.hints_text = tk.Text(
            hints_card,
            height=12,
            wrap="word",
            font=("Helvetica", 13),
            bg=self.colors["card_inner"],
            fg=self.colors["text"],
            relief="flat",
            padx=14,
            pady=14,
            insertbackground=self.colors["text"],
        )
        self.hints_text.grid(row=0, column=0, sticky="nsew")
        self.hints_text.tag_configure("rtl", justify="right", rmargin=10, lmargin1=10, lmargin2=10)
        self.hints_text.tag_configure("hint_title", foreground=self.colors["primary"], font=("Helvetica", 14, "bold"))
        self.hints_text.tag_configure("hint_points", foreground=self.colors["muted"], font=("Helvetica", 11, "bold"))
        self.hints_text.tag_configure("new_hint", background="#FFE1E7")
        self.hints_text.configure(state="disabled")

        # לוח הניחוש: שדה כתיבה, כפתור בדיקה והיסטוריית ניחושים.
        input_card = tk.Frame(content, bg=self.colors["card"], bd=0, highlightthickness=2, highlightbackground="#FFE2E7", padx=24, pady=24)
        input_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        input_card.grid_columnconfigure(0, weight=1)
        input_card.grid_rowconfigure(5, weight=1)

        ttk.Label(input_card, text="הניחוש שלך", style="CardTitle.TLabel").grid(row=0, column=0, sticky="e")

        self.guess_var = tk.StringVar()
        self.guess_entry = tk.Entry(
            input_card,
            textvariable=self.guess_var,
            justify="right",
            font=("Helvetica", 15),
            relief="solid",
            bd=1,
            bg=self.colors["entry"],
            fg=self.colors["text"],
            highlightthickness=2,
            highlightbackground="#dbe6ff",
            highlightcolor=self.colors["primary"],
            insertbackground=self.colors["text"],
            disabledbackground="#f3f6fb",
            disabledforeground=self.colors["muted"],
        )
        self.guess_entry.grid(row=1, column=0, sticky="ew", pady=(10, 12))
        self.enable_entry_edit_shortcuts(self.guess_entry)
        self.guess_entry.bind("<Return>", self.submit_guess)

        self.submit_button = ttk.Button(
            input_card,
            text="בדיקת ניחוש",
            style="Guess.TButton",
            command=self.submit_guess,
            state="disabled",
        )
        self.submit_button.grid(row=2, column=0, sticky="ew")

        self.reveal_button = ttk.Button(
            input_card,
            text="גלה תשובה",
            style="Next.TButton",
            command=self.reveal_answer,
            state="disabled",
        )
        self.reveal_button.grid(row=3, column=0, sticky="ew", pady=(10, 0))

        ttk.Label(input_card, text="היסטוריית ניחושים", style="CardTitle.TLabel").grid(
            row=4, column=0, sticky="e", pady=(18, 8)
        )

        self.guesses_list = tk.Listbox(
            input_card,
            font=("Helvetica", 12),
            activestyle="none",
            relief="flat",
            bg=self.colors["list"],
            fg=self.colors["text"],
            highlightthickness=2,
            highlightbackground="#dbe6ff",
            selectbackground="#dfe8ff",
            selectforeground="#10264f",
            justify="right",
            bd=0,
        )
        self.guesses_list.grid(row=5, column=0, sticky="nsew")

        self.footer_label = ttk.Label(
            input_card,
            text="ניחוש נכון מוקדם יותר שווה יותר נקודות",
            style="Body.TLabel",
            wraplength=260,
        )
        self.footer_label.grid(row=6, column=0, sticky="sew", pady=(14, 0))

    # בונה כרטיס מדד קטן עבור הניקוד/רמזים/קטגוריה.
    def build_metric(self, parent, column, label, value):
        card = tk.Frame(parent, bg=self.colors["card_alt"], bd=0, highlightthickness=1, highlightbackground="#ffffff", padx=4, pady=4)
        card.grid(row=0, column=column, sticky="ew", padx=6)
        card.grid_columnconfigure(0, weight=1)

        ttk.Label(card, text=label, style="MetricLabel.TLabel").grid(row=0, column=0, sticky="ew", pady=(10, 2))
        value_label = ttk.Label(card, text=value, style="MetricValue.TLabel")
        value_label.grid(row=1, column=0, sticky="ew", pady=(0, 10), padx=12)
        return value_label

    def enable_entry_edit_shortcuts(self, entry):
        menu = tk.Menu(entry, tearoff=0)
        menu.add_command(label="גזור", command=lambda: entry.event_generate("<<Cut>>"))
        menu.add_command(label="העתק", command=lambda: entry.event_generate("<<Copy>>"))
        menu.add_command(label="הדבק", command=lambda: self.paste_into_entry(entry))
        menu.add_separator()
        menu.add_command(label="בחר הכל", command=lambda: self.select_entry_text(entry))

        def show_menu(event):
            entry.focus_set()
            menu.tk_popup(event.x_root, event.y_root)

        entry.bind("<Button-2>", show_menu, add="+")
        entry.bind("<Button-3>", show_menu, add="+")
        for sequence in ("<<Paste>>", "<Command-v>", "<Command-V>", "<Control-v>", "<Control-V>"):
            entry.bind(sequence, lambda event: self.paste_into_entry(event.widget))
        for sequence in ("<Command-a>", "<Command-A>", "<Control-a>", "<Control-A>"):
            entry.bind(sequence, lambda event: self.select_entry_text(event.widget))

    def paste_server_url(self):
        self.use_server_var.set(True)
        self.server_entry.configure(state="normal")
        self.server_entry.focus_set()
        result = self.paste_into_entry(self.server_entry)
        if self.server_url_var.get().strip():
            self.refresh_multiplayer_status()
            self.set_status("כתובת השרת הודבקה. אפשר ללחוץ בדוק שרת.")
        else:
            messagebox.showwarning("הדבקת כתובת", "לא נמצאה כתובת בלוח ההעתקה.")
        return result

    def paste_into_entry(self, entry):
        try:
            text = self.root.clipboard_get()
        except tk.TclError:
            return "break"
        if entry.cget("state") == "disabled":
            return "break"
        text = text.strip()
        if not text:
            return "break"
        try:
            selection_start = entry.index(tk.SEL_FIRST)
            selection_end = entry.index(tk.SEL_LAST)
            entry.delete(selection_start, selection_end)
        except tk.TclError:
            pass
        entry.insert(tk.INSERT, text)
        return "break"

    def select_entry_text(self, entry):
        entry.selection_range(0, tk.END)
        entry.icursor(tk.END)
        return "break"

    def open_additional_window(self):
        new_window = tk.Toplevel(self.root)
        AliasGameApp(new_window)

    # Load categories from words.py and refresh category combobox values and summary.
    def populate_categories(self):
        current_label = self.category_var.get().strip()
        self.category_options = words.get_category_options()
        self.category_lookup = {label: category for category, label in self.category_options}
        labels = [label for _, label in self.category_options]
        self.category_combo["values"] = labels
        self.categories_summary.configure(
            text="כל הקטגוריות מהקובץ: " + " | ".join(labels) if labels else "לא נמצאו קטגוריות ב-data.json"
        )
        if current_label in labels:
            self.category_var.set(current_label)
        elif labels:
            self.category_combo.current(0)

    # טוען את ההגדרות האחרונות שנשמרו, אם הן עדיין תקפות.
    def load_saved_settings(self):
        settings = self.settings
        if settings.get("category") in self.category_lookup:
            self.category_var.set(settings["category"])
        if settings.get("difficulty") in DIFFICULTY_SETTINGS:
            self.difficulty_var.set(settings["difficulty"])
        if settings.get("hint_source") in ("prepared", "ai"):
            self.hint_source_var.set(settings["hint_source"])
        if settings.get("game_length") in GAME_LENGTH_OPTIONS:
            self.game_length_var.set(settings["game_length"])
        if settings.get("player_name"):
            self.player_name_var.set(settings["player_name"])
        self.use_server_var.set(False)
        self.server_url_var.set("")
        self.room_id_var.set("")
        self.practice_mode_var.set(bool(settings.get("practice_mode", False)))
        self.timer_enabled_var.set(bool(settings.get("timer_enabled", True)))

    # שומר את ההגדרות שנבחרו כך שהאפליקציה תיפתח איתן בפעם הבאה.
    def save_current_settings(self):
        write_json_file(SETTINGS_FILE, {
            "category": self.category_var.get().strip(),
            "difficulty": self.difficulty_var.get(),
            "hint_source": self.hint_source_var.get(),
            "game_length": self.game_length_var.get(),
            "player_name": self.player_name_var.get().strip() or "שחקן",
            "practice_mode": self.practice_mode_var.get(),
            "timer_enabled": self.timer_enabled_var.get(),
        })

    # מתרגם את בחירת אורך המשחק למספר סבבים או None לכל הקטגוריה.
    def get_selected_game_length(self):
        value = self.game_length_var.get()
        return None if value == GAME_LENGTH_OPTIONS[0] else int(value)

    def build_online_service(self):
        server_url = self.server_url_var.get().strip()
        if not server_url:
            raise OnlineGameError("צריך למלא כתובת שרת בשביל Multiplayer.")
        if not server_url.startswith(("http://", "https://")):
            server_url = "http://" + server_url
            self.server_url_var.set(server_url)
        return OnlineGameService(
            server_url,
            self.room_id_var.get().strip(),
            self.player_name_var.get().strip() or "שחקן",
            self.hint_source_var.get(),
        )

    def on_multiplayer_toggle(self):
        if self.use_server_var.get():
            self.server_entry.focus_set()
        else:
            self.category_combo.focus_set()
        self.refresh_multiplayer_status()
        self.refresh_online_banner()

    def clear_room_code(self):
        self.room_id_var.set("")
        self.online_service = None
        self.multiplayer_active = False
        self.room_entry.focus_set()
        self.set_setup_controls_state("normal")
        self.refresh_multiplayer_status()
        self.set_status("קוד החדר נוקה. בהתחלת משחק Multiplayer השרת ייצור חדר חדש.")

    def test_server_connection(self):
        try:
            service = self.build_online_service()
            data = service.health()
        except OnlineGameError as error:
            messagebox.showerror("בדיקת שרת", str(error))
            return
        status = data.get("status") or data.get("message") or "ok"
        room_note = "אם קוד החדר ריק, התחלת משחק תיצור חדר חדש."
        self.refresh_multiplayer_status("מחובר לשרת. " + room_note)
        messagebox.showinfo("בדיקת שרת", f"השרת ענה בהצלחה: {status}\n{room_note}")

    def get_online_scoreboard_text(self):
        if not self.online_scoreboard:
            return ""
        ordered = sorted(self.online_scoreboard.items(), key=lambda item: item[1], reverse=True)
        return " | ".join(f"{name}: {score}" for name, score in ordered)

    def refresh_multiplayer_status(self, text=None):
        if not hasattr(self, "multiplayer_status_label"):
            return
        if not self.use_server_var.get():
            text = text or "Multiplayer כבוי"
            bg = "#FFF8E8"
            fg = self.colors["warning"]
        else:
            room_id = self.room_id_var.get().strip()
            server_url = self.server_url_var.get().strip() or "לא הוגדרה כתובת"
            room_text = f"חדר {room_id}" if room_id else "חדר חדש ייווצר בתחילת המשחק"
            text = text or f"Multiplayer פעיל | {room_text} | {server_url}"
            bg = "#E8F8EF"
            fg = self.colors["success"]
        self.multiplayer_status_label.configure(text=rtl_text(text), bg=bg, fg=fg)

    def refresh_online_banner(self):
        if not hasattr(self, "online_banner"):
            return
        if self.multiplayer_active or self.use_server_var.get():
            room_id = self.room_id_var.get().strip() or "חדש"
            scoreboard_text = self.get_online_scoreboard_text()
            parts = [f"Multiplayer", f"חדר {room_id}"]
            if scoreboard_text:
                parts.append(scoreboard_text)
            self.online_banner.configure(text=rtl_text(" | ".join(parts)), bg="#E8F8EF", fg=self.colors["success"])
        else:
            self.online_banner.configure(text="Solo", bg="#ffffff", fg=self.colors["hero_accent"])

    def apply_online_state(self, state, fallback_message="", quiet=False):
        self.multiplayer_active = True
        previous_round_number = self.round_number
        if state.get("room_id"):
            self.room_id_var.set(str(state["room_id"]))
            if self.online_service:
                self.online_service.room_id = str(state["room_id"])
        self.current_category = state.get("category") or self.current_category
        self.current_difficulty = state.get("difficulty") or self.current_difficulty
        if state.get("hint_source") in ("prepared", "ai"):
            self.hint_source_var.set(state["hint_source"])
        self.round_number = int(state.get("round_number", self.round_number or 1))
        self.online_scoreboard = state.get("scoreboard", {}) or {}
        self.online_players = state.get("players", [])
        player_name = self.player_name_var.get().strip() or "שחקן"
        self.score = int(self.online_scoreboard.get(player_name, self.score))
        self.revealed_hints = list(state.get("revealed_hints", []))
        self.all_hints = list(self.revealed_hints)
        self.attempts_used = int(state.get("attempts_used", len(state.get("guesses", []))))
        self.timer_enabled_var.set(bool(state.get("timer_enabled", self.timer_enabled_var.get())))
        self.time_left = int(state.get("time_left", 0) or 0)
        self.round_finished = not bool(state.get("round_active", False))
        self.secret_word = "__server_round__" if state.get("round_active", False) else None
        if not quiet or self.round_number != previous_round_number or not self.secret_word:
            self.guess_var.set("")
        self.guesses_list.delete(0, tk.END)
        for guess_line in state.get("guesses", [])[:20]:
            self.guesses_list.insert(tk.END, rtl_text(guess_line))
        scoreboard_text = self.get_online_scoreboard_text()
        if scoreboard_text:
            self.guesses_list.insert(0, rtl_text("ניקוד: " + scoreboard_text))

        self.update_round_title()
        self.refresh_hints()
        self.refresh_metrics()
        self.refresh_multiplayer_status()
        self.refresh_online_banner()
        if not quiet:
            message = state.get("message") or fallback_message or "מצב Multiplayer עודכן מהשרת."
            if state.get("waiting_for_players"):
                min_players = state.get("min_players_to_start", 2)
                message = (
                    f"מחכים לשחקן נוסף. קוד חדר: {state.get('room_id', '')}. "
                    f"שחקנים בחדר: {state.get('player_count', 1)}/{min_players}"
                )
            if state.get("hint_source_used") == "ai":
                message = f"{message} | רמזי AI מהשרת"
            elif state.get("hint_source_used") == "prepared_fallback":
                message = f"{message} | ה-AI לא זמין, משתמשים ברמזים מוכנים"
            if state.get("room_id"):
                message = f"חדר {state['room_id']} | {message}"
            if scoreboard_text:
                message = f"{message}\n{scoreboard_text}"
            self.set_status(message)

        if state.get("game_over"):
            self.finish_online_game(state)
            return

        waiting_for_players = bool(state.get("waiting_for_players", False))
        self.submit_button.configure(state="normal" if self.secret_word else "disabled")
        self.guess_entry.configure(state="normal" if self.secret_word else "disabled")
        self.next_button.configure(state="normal" if self.round_finished else "disabled")
        self.skip_button.configure(state="normal" if self.secret_word else "disabled")
        self.reveal_button.configure(state="disabled")
        self.extra_hint_button.configure(text="פתח רמז")
        self.extra_hint_button.configure(state="normal" if self.secret_word else "disabled")
        if self.secret_word:
            self.start_online_timer()
            if not quiet:
                self.guess_entry.focus_set()
        elif waiting_for_players:
            min_players = state.get("min_players_to_start", 2)
            if not quiet:
                self.set_status(
                    f"מחכים לשחקן נוסף. קוד חדר: {state.get('room_id', '')}. "
                    f"שחקנים בחדר: {state.get('player_count', 1)}/{min_players}"
                )
            self.start_online_lobby_poll()
        else:
            self.start_online_lobby_poll()

    def finish_online_game(self, state):
        self.stop_timer()
        self.multiplayer_active = False
        self.online_service = None
        self.secret_word = None
        self.round_finished = True
        self.submit_button.configure(state="disabled")
        self.next_button.configure(state="disabled")
        self.skip_button.configure(state="disabled")
        self.reveal_button.configure(state="disabled")
        self.extra_hint_button.configure(text="רמז AI נוסף")
        self.extra_hint_button.configure(state="disabled")
        self.guess_entry.configure(state="disabled")
        self.set_setup_controls_state("normal")
        self.set_status(state.get("message", "משחק ה-Multiplayer הסתיים."))

    # מציג את מסך הבית ומסתיר את מסך המשחק.
    def show_home_screen(self, force=False):
        if not force and self.multiplayer_active and self.secret_word:
            self.show_game_screen()
            return
        if not self.multiplayer_active and not self.secret_word:
            self.set_setup_controls_state("normal")
        self.home_screen.tkraise()
        self.root.title("Alias AI - בית")

    # מציג את מסך המשחק אחרי שההגדרות נבחרו.
    def show_game_screen(self):
        self.game_screen.tkraise()
        self.root.title("Alias AI - משחק")

    # חוזר למסך הבית, עם אישור אם סבב עדיין פעיל.
    def return_home(self):
        if self.secret_word and not self.round_finished:
            should_return = messagebox.askyesno("חזרה לבית", "המשחק הפעיל ייעצר. לחזור למסך הבית?")
            if not should_return:
                return
        self.stop_timer()
        self.stop_loading_status()
        self.ai_request_id += 1
        self.adaptive_hint_request_id += 1
        self.multiplayer_active = False
        self.online_service = None
        self.online_scoreboard = {}
        self.refresh_online_banner()
        self.secret_word = None
        self.all_hints = []
        self.revealed_hints = []
        self.wrong_guesses = []
        self.pending_adaptive_status = ""
        self.attempts_used = 0
        self.round_finished = True
        self.submit_button.configure(state="disabled")
        self.next_button.configure(state="disabled")
        self.skip_button.configure(state="disabled")
        self.reveal_button.configure(state="disabled")
        self.extra_hint_button.configure(text="רמז AI נוסף")
        self.extra_hint_button.configure(state="disabled")
        self.guess_entry.configure(state="disabled")
        self.set_setup_controls_state("normal")
        self.refresh_metrics()
        self.refresh_hints()
        self.show_home_screen(force=True)

    # מציג את השיאים האחרונים והשיאים הגבוהים ביותר.
    def show_high_scores(self):
        if self.use_server_var.get() and self.server_url_var.get().strip():
            try:
                scores = self.build_online_service().scores()
            except OnlineGameError as error:
                messagebox.showerror("שיאים", str(error))
                return
        else:
            scores = read_json_file(SCORES_FILE, [])
        if not scores:
            messagebox.showinfo("שיאים", "עדיין אין שיאים שמורים.")
            return
        best_scores = sorted(scores, key=lambda item: item.get("score", 0), reverse=True)[:10]
        lines = []
        for index, score in enumerate(best_scores, start=1):
            lines.append(
                f"{index}. {score.get('player', 'שחקן')} | {score.get('score', 0)} נקודות | "
                f"{score.get('category', '')} | {score.get('difficulty', '')}"
            )
        messagebox.showinfo("שיאים", "\n".join(lines))

    # מציג סטטיסטיקה מצטברת לפי קטגוריה.
    def show_category_stats(self):
        if self.use_server_var.get() and self.server_url_var.get().strip():
            try:
                stats = self.build_online_service().stats()
            except OnlineGameError as error:
                messagebox.showerror("סטטיסטיקה", str(error))
                return
        else:
            stats = read_json_file(STATS_FILE, {})
        if not stats:
            messagebox.showinfo("סטטיסטיקה", "עדיין אין סטטיסטיקה שמורה.")
            return
        lines = []
        for category, data in stats.items():
            played = data.get("played", 0)
            correct = data.get("correct", 0)
            success_rate = (correct / played * 100) if played else 0
            players = data.get("players", {})
            best_player = ""
            if players:
                best_name, best_data = max(players.items(), key=lambda item: item[1].get("best_score", 0))
                best_player = f", שחקן מוביל {best_name} ({best_data.get('best_score', 0)})"
            lines.append(
                f"{category}: {correct}/{played} נכונות ({success_rate:.0f}%), "
                f"שיא {data.get('best_score', 0)}{best_player}"
            )
        messagebox.showinfo("סטטיסטיקה לפי קטגוריה", "\n".join(lines))

    # מערבב את המילים בקטגוריה כדי שכל משחק יהיה בסדר שונה.
    def build_rounds(self, category):
        entries = list(words.get_words_by_category(category).items())
        self.randomizer.shuffle(entries)
        return entries

    # מחזיר את המילה הבאה שלא השתמשנו בה עדיין במשחק הנוכחי.
    def get_next_entry(self):
        if self.max_rounds is not None and self.round_number >= self.max_rounds:
            return None, None
        entries = self.build_rounds(self.current_category)
        available_entries = [(word, hints) for word, hints in entries if word not in self.used_words]
        if not available_entries:
            return None, None
        word, hints = available_entries[0]
        self.used_words.add(word)
        return word, hints

    # מכין את רשימת הרמזים לסבב: מוכנים מראש או משופרים על ידי AI.
    def build_hints_for_current_round(self):
        prepared_hints = words.order_hints_by_difficulty(self.all_hints)
        return prepared_hints

    # מחזיר את הגדרות הקושי הנוכחיות, עם ברירת מחדל יציבה.
    def get_difficulty_settings(self):
        return DIFFICULTY_SETTINGS.get(self.current_difficulty, DIFFICULTY_SETTINGS["רגיל"])

    # משנה את הקושי בתוך המשחק לפי ביצועי השחקן.
    def adjust_dynamic_difficulty(self, result):
        old_difficulty = self.current_difficulty
        levels = list(DIFFICULTY_SETTINGS)
        current_index = levels.index(self.current_difficulty)
        quick_success = result == "correct" and len(self.revealed_hints) <= 2 and self.attempts_used <= 1

        if quick_success:
            self.success_streak += 1
            self.struggle_streak = 0
        elif result in ("failed", "skipped", "revealed"):
            self.struggle_streak += 1
            self.success_streak = 0
        else:
            self.success_streak = 0
            self.struggle_streak = 0

        if self.success_streak >= 2 and current_index < len(levels) - 1:
            self.current_difficulty = levels[current_index + 1]
            self.success_streak = 0
        elif self.struggle_streak >= 2 and current_index > 0:
            self.current_difficulty = levels[current_index - 1]
            self.struggle_streak = 0

        if self.current_difficulty != old_difficulty:
            self.dynamic_difficulty_message = f"הקושי הותאם אוטומטית ל: {self.current_difficulty}"
        else:
            self.dynamic_difficulty_message = ""

    # מחשב ניקוד לסבב לפי מספר הרמזים שנפתחו ורמת הקושי.
    def get_points_for_current_difficulty(self, hint_number):
        return words.get_points_for_hint_number(hint_number) + self.get_difficulty_settings()["score_bonus"]

    # מפעיל קריאת Ollama ברקע כדי שהממשק הגרפי לא יקפא בזמן יצירת הרמזים.
    def start_ai_hint_generation(self, prepared_hints):
        self.ai_request_id += 1
        request_id = self.ai_request_id
        word = self.secret_word
        category_label = words.get_category_label(self.current_category)
        prepared_hints = list(prepared_hints)
        self.set_round_controls_state("disabled")
        self.skip_button.configure(state="normal")
        self.extra_hint_button.configure(state="disabled")
        self.start_loading_status("מכין רמזי AI לסבב הזה")

        def worker():
            ai_hints = generate_ai_hints(word, prepared_hints, category_label)
            filtered_hints = filter_duplicate_ai_hints(ai_hints, prepared_hints)
            self.root.after(0, lambda: self.finish_ai_hint_generation(request_id, filtered_hints))

        threading.Thread(target=worker, daemon=True).start()

    # מחיל את תוצאת ה-AI אם היא עדיין שייכת לסבב הנוכחי.
    def finish_ai_hint_generation(self, request_id, ai_hints):
        if request_id != self.ai_request_id or self.round_finished or not self.secret_word:
            return
        self.stop_loading_status()
        if ai_hints:
            self.all_hints = ai_hints
            self.reveal_starting_hints()
            self.set_status("רמזי AI מוכנים. תנסה לנחש!")
        else:
            self.set_status("ה-AI לא עובד כרגע, אז הסבב ממשיך עם הרמזים המוכנים.")
            messagebox.showwarning("AI לא זמין", "ה-AI לא עובד כרגע, אז הסבב ממשיך עם הרמזים המוכנים.")
        self.refresh_hints()
        self.refresh_metrics()
        self.set_round_controls_state("normal")
        self.extra_hint_button.configure(state="normal")
        self.start_timer()
        self.guess_entry.focus_set()

    def reveal_hint_after_wrong_guess(self, next_hint_index, status_text):
        if next_hint_index < len(self.all_hints):
            self.revealed_hints.append(self.all_hints[next_hint_index])
        self.set_status(status_text)
        self.refresh_hints()
        self.refresh_metrics()
        self.guess_entry.focus_set()

    # מבקש מה-AI להתאים את הרמז הבא לפי הניחושים השגויים האחרונים.
    def start_adaptive_hint_generation(self, next_hint_index):
        self.adaptive_hint_request_id += 1
        request_id = self.adaptive_hint_request_id
        word = self.secret_word
        base_hint = self.all_hints[next_hint_index]
        revealed_hints = list(self.revealed_hints)
        wrong_guesses = list(self.wrong_guesses)
        category_label = words.get_category_label(self.current_category)
        fallback_status = self.pending_adaptive_status or "לא נכון. נפתח רמז נוסף, קצת יותר קל."
        self.pending_adaptive_status = ""

        self.set_round_controls_state("disabled")
        self.skip_button.configure(state="normal")
        self.reveal_button.configure(state="normal")
        self.start_loading_status("מתאים את הרמז הבא לפי הניחוש שלך")

        def worker():
            hint = generate_adaptive_hint(
                word, base_hint, revealed_hints, wrong_guesses, category_label
            )
            self.root.after(0, lambda: self.finish_adaptive_hint_generation(request_id, next_hint_index, hint, fallback_status))

        threading.Thread(target=worker, daemon=True).start()

    def finish_adaptive_hint_generation(self, request_id, next_hint_index, hint, fallback_status):
        if request_id != self.adaptive_hint_request_id or self.round_finished or not self.secret_word:
            return
        self.stop_loading_status()

        status_text = fallback_status
        if hint:
            self.all_hints[next_hint_index] = hint
            status_text = "הרמז הבא הותאם לניחושים שלך." if self.used_extra_hint else "לא נכון. הרמז הבא הותאם לניחושים שלך."

        self.reveal_hint_after_wrong_guess(next_hint_index, status_text)
        self.set_round_controls_state("normal")
        self.extra_hint_button.configure(state="disabled" if self.used_extra_hint else "normal")

    def request_extra_ai_hint(self):
        if self.multiplayer_active and self.online_service:
            try:
                state = self.online_service.request_hint()
            except OnlineGameError as error:
                self.set_status(str(error))
                return
            self.apply_online_state(state, "השרת פתח רמז נוסף.")
            return

        if self.round_finished or not self.secret_word:
            return
        if self.hint_source_var.get() != "ai":
            self.set_status("רמז AI נוסף זמין כשמקור הרמזים הוא AI.")
            return
        if self.used_extra_hint:
            self.set_status("כבר השתמשת ברמז AI נוסף בסבב הזה.")
            return
        next_hint_index = len(self.revealed_hints)
        if next_hint_index >= len(self.all_hints):
            self.set_status("אין עוד רמזים לפתוח בסבב הזה.")
            return

        self.used_extra_hint = True
        self.wrong_guesses.append(self.guess_var.get().strip() or "בקשת רמז נוסף")
        self.guess_var.set("")
        self.pending_adaptive_status = "נפתח רמז AI נוסף."
        self.start_adaptive_hint_generation(next_hint_index)

    # מתחיל משחק חדש בקטגוריה שנבחרה ומאפס ניקוד ומילים שכבר שוחקו.
    def start_game(self):
        self.populate_categories()
        selected_label = self.category_var.get().strip()
        if not selected_label:
            messagebox.showwarning("קטגוריה חסרה", "בחר קטגוריה לפני תחילת המשחק.")
            return

        self.current_category = self.category_lookup[selected_label]
        self.current_difficulty = self.difficulty_var.get()
        self.save_current_settings()

        if self.use_server_var.get():
            self.start_online_game()
            return

        self.multiplayer_active = False
        self.online_service = None
        self.online_scoreboard = {}
        self.refresh_online_banner()
        self.set_setup_controls_state("disabled")
        self.show_game_screen()
        self.refresh_multiplayer_status()
        self.refresh_online_banner()
        self.score = 0
        self.round_number = 0
        self.max_rounds = self.get_selected_game_length()
        self.used_words = set()
        self.correct_words = 0
        self.failed_words = 0
        self.skipped_words = 0
        self.total_hints_used = 0
        self.success_streak = 0
        self.struggle_streak = 0
        self.current_correct_streak = 0
        self.best_correct_streak = 0
        self.one_hint_wins = 0
        self.achievements = set()
        self.dynamic_difficulty_message = ""
        self.round_results = []
        self.last_summary = ""
        self.next_round()

    def start_online_game(self):
        try:
            self.online_service = self.build_online_service()
            state = self.online_service.start_game(
                self.current_category,
                self.current_difficulty,
                self.get_selected_game_length(),
                self.timer_enabled_var.get(),
                self.get_difficulty_settings()["seconds"],
            )
        except OnlineGameError as error:
            self.multiplayer_active = False
            self.online_service = None
            self.set_setup_controls_state("normal")
            self.show_home_screen(force=True)
            messagebox.showerror("Multiplayer", str(error))
            return

        self.set_setup_controls_state("disabled")
        self.show_game_screen()
        self.score = 0
        self.round_number = 0
        self.max_rounds = self.get_selected_game_length()
        self.correct_words = 0
        self.failed_words = 0
        self.skipped_words = 0
        self.total_hints_used = 0
        self.round_results = []
        self.last_summary = ""
        self.apply_online_state(state, "התחברת לשרת והמשחק התחיל.")
        if not state.get("game_over"):
            self.show_game_screen()
            self.root.after(80, self.show_game_screen)
            self.root.after(250, self.show_game_screen)

    # Proceed to the next round, choose the next word, and show the first hint.
    def next_round(self):
        if self.multiplayer_active and self.online_service:
            try:
                state = self.online_service.next_round()
            except OnlineGameError as error:
                self.set_status(str(error))
                return
            self.apply_online_state(state, "השרת עבר למילה הבאה.")
            return

        self.stop_timer()
        self.ai_request_id += 1
        self.adaptive_hint_request_id += 1
        self.populate_categories()
        if not self.current_category:
            return

        self.secret_word, hints = self.get_next_entry()
        if not self.secret_word:
            self.finish_game()
            return

        self.round_number += 1
        self.all_hints = words.order_hints_by_difficulty(hints)
        self.all_hints = self.build_hints_for_current_round()
        self.revealed_hints = []
        self.wrong_guesses = []
        self.used_extra_hint = False
        self.pending_adaptive_status = ""
        self.attempts_used = 0
        self.round_finished = False
        self.time_left = self.get_difficulty_settings()["seconds"] if self.timer_enabled_var.get() else 0
        self.guess_var.set("")
        self.guesses_list.delete(0, tk.END)
        self.reveal_starting_hints()
        status_text = self.dynamic_difficulty_message or "הרמז הראשון מוכן. תנסה לנחש!"
        self.dynamic_difficulty_message = ""
        self.set_status(status_text)
        self.update_round_title()
        self.refresh_hints()
        self.refresh_metrics()
        self.next_button.configure(state="disabled")
        self.skip_button.configure(state="normal")
        self.reveal_button.configure(state="normal")
        self.extra_hint_button.configure(state="normal" if self.hint_source_var.get() == "ai" else "disabled")
        if self.hint_source_var.get() == "ai":
            self.start_ai_hint_generation(self.all_hints)
        else:
            self.set_round_controls_state("normal")
            self.start_timer()
            self.guess_entry.focus_set()

    # מסיים את המשחק כאשר נגמרו המילים בקטגוריה.
    def finish_game(self):
        self.stop_timer()
        self.stop_loading_status()
        self.secret_word = None
        self.all_hints = []
        self.revealed_hints = []
        self.attempts_used = 0
        self.round_finished = True
        self.submit_button.configure(state="disabled")
        self.next_button.configure(state="disabled")
        self.skip_button.configure(state="disabled")
        self.reveal_button.configure(state="disabled")
        self.extra_hint_button.configure(state="disabled")
        self.guess_entry.configure(state="disabled")
        self.set_setup_controls_state("normal")
        self.refresh_hints()
        self.refresh_metrics()
        self.round_title.configure(text=rtl_text("המשחק הסתיים"))
        summary = self.build_game_summary()
        self.last_summary = summary
        self.save_game_records()
        self.set_status(f"סיימת את הקטגוריה עם {self.score} נקודות.")
        self.show_game_over_window(summary)

    def start_online_timer(self):
        self.stop_timer()
        if not self.multiplayer_active or not self.online_service or not self.secret_word:
            return
        self.timer_after_id = self.root.after(1000, self.poll_online_state)

    def start_online_lobby_poll(self):
        self.stop_timer()
        if not self.multiplayer_active or not self.online_service:
            return
        self.timer_after_id = self.root.after(1000, self.poll_online_state)

    def poll_online_state(self):
        if not self.multiplayer_active or not self.online_service:
            self.timer_after_id = None
            return
        try:
            state = self.online_service.state()
        except OnlineGameError as error:
            self.timer_after_id = None
            self.set_status(str(error))
            return
        self.timer_after_id = None
        if state.get("round_active", False):
            self.apply_online_state(state, quiet=True)
        elif state.get("waiting_for_players", False):
            self.apply_online_state(state, quiet=True)
        else:
            self.apply_online_state(state, "הסבב הסתיים בשרת.")

    def get_practice_insight(self, played_rounds, average_hints):
        if not played_rounds:
            return "עוד לא שוחקו מספיק מילים כדי ללמוד דפוס."
        success_rate = self.correct_words / played_rounds
        if success_rate >= 0.8 and average_hints <= 2:
            return "היית חד מאוד: רוב המילים נפתרו מוקדם, כדאי לעלות קושי."
        if success_rate >= 0.6:
            return "הכיוון טוב: אתה פותר הרבה, אבל עוד רמזים לפני הניחוש יעזרו לדייק."
        if self.skipped_words > self.correct_words:
            return "נראה שהדילוגים עצרו מומנטום. כדאי לשחק בלי דילוגים לכמה סבבים."
        return "כדאי להתמקד בקשר בין הרמז הראשון לקטגוריה לפני שמנחשים מהר."

    def update_achievements(self, played_rounds, average_hints):
        if self.score > 0:
            self.achievements.add("צברת נקודות")
        if self.best_correct_streak >= 3:
            self.achievements.add("3 מילים נכונות ברצף")
        if self.one_hint_wins:
            self.achievements.add("ניחוש ברמז ראשון")
        if not self.timer_enabled_var.get() and self.correct_words >= max(1, played_rounds // 2):
            self.achievements.add("ניצחון בלי טיימר")
        if played_rounds and average_hints <= 2 and self.correct_words:
            self.achievements.add("חסכוני ברמזים")

    def show_game_over_window(self, summary):
        window = tk.Toplevel(self.root)
        window.title("סיום משחק")
        window.configure(bg=self.colors["bg"])
        window.geometry("620x580")
        window.minsize(520, 460)
        window.grid_columnconfigure(0, weight=1)
        window.grid_rowconfigure(2, weight=1)

        title_frame = tk.Frame(window, bg=self.colors["hero"], padx=20, pady=16)
        title_frame.grid(row=0, column=0, sticky="ew")
        title_frame.grid_columnconfigure(0, weight=1)
        title = tk.Label(
            title_frame,
            text="סיכום משחק",
            bg=self.colors["hero"],
            fg="#ffffff",
            font=("Helvetica", 25, "bold"),
        )
        title.grid(row=0, column=0, sticky="e")
        subtitle = tk.Label(
            title_frame,
            text=f"{self.score} נקודות | {self.correct_words} מילים נכונות",
            bg=self.colors["hero"],
            fg="#FFDDE4",
            font=("Helvetica", 13, "bold"),
        )
        subtitle.grid(row=1, column=0, sticky="e", pady=(4, 0))

        confetti = tk.Canvas(window, height=72, bg=self.colors["bg"], highlightthickness=0)
        confetti.grid(row=1, column=0, sticky="ew")
        self.animate_confetti(confetti)

        summary_frame = tk.Frame(window, bg=self.colors["card"], highlightthickness=2, highlightbackground="#FFE2E7")
        summary_frame.grid(row=2, column=0, sticky="nsew", padx=16, pady=(0, 16))
        summary_frame.grid_columnconfigure(0, weight=1)
        summary_frame.grid_rowconfigure(0, weight=1)
        text = tk.Text(
            summary_frame,
            wrap="word",
            font=("Helvetica", 12),
            bg=self.colors["card"],
            fg=self.colors["text"],
            relief="flat",
            padx=18,
            pady=18,
        )
        text.grid(row=0, column=0, sticky="nsew")
        text.insert("1.0", summary)
        text.tag_configure("rtl", justify="right")
        text.tag_configure("headline", foreground=self.colors["primary"], font=("Helvetica", 14, "bold"), justify="right")
        text.tag_add("rtl", "1.0", "end")
        text.tag_add("headline", "1.0", "1.end")
        text.configure(state="disabled")

        buttons = tk.Frame(window, bg=self.colors["bg"])
        buttons.grid(row=3, column=0, sticky="ew", padx=16, pady=(0, 16))
        buttons.grid_columnconfigure(0, weight=1)
        buttons.grid_columnconfigure(1, weight=1)
        ttk.Button(buttons, text="משחק חדש", style="Start.TButton", command=lambda: (window.destroy(), self.start_game())).grid(
            row=0, column=1, sticky="ew", padx=(0, 8)
        )
        ttk.Button(buttons, text="סגור", style="Next.TButton", command=window.destroy).grid(
            row=0, column=0, sticky="ew", padx=(8, 0)
        )

    def animate_confetti(self, canvas, step=0):
        colors = ["#B80F2A", "#FFD166", "#1A7A4A", "#8F1230", "#FF9FB0"]
        width = max(canvas.winfo_width(), 520)
        if step == 0:
            canvas.delete("all")
            for index in range(34):
                x = (index * 47) % width
                y = -10 - (index % 7) * 9
                size = 5 + index % 4
                canvas.create_rectangle(
                    x, y, x + size, y + size,
                    fill=colors[index % len(colors)],
                    outline="",
                    tags=("piece", f"speed{1 + index % 3}"),
                )
        if step > 34:
            return
        for speed in (1, 2, 3):
            canvas.move(f"speed{speed}", 0, speed + 1)
        canvas.after(45, lambda: self.animate_confetti(canvas, step + 1))

    # בונה הודעת סיכום עשירה יותר לסוף המשחק.
    def build_game_summary(self):
        played_rounds = self.correct_words + self.failed_words + self.skipped_words
        average_hints = self.total_hints_used / played_rounds if played_rounds else 0
        success_rate = (self.correct_words / played_rounds * 100) if played_rounds else 0
        self.update_achievements(played_rounds, average_hints)
        insight = self.get_practice_insight(played_rounds, average_hints)
        achievements_text = "\n".join(f"- {achievement}" for achievement in sorted(self.achievements))
        if not achievements_text:
            achievements_text = "- עוד לא נפתחו הישגים במשחק הזה"
        result_lines = []
        for result in self.round_results:
            result_label = {
                "correct": "נכון",
                "failed": "לא נוחש",
                "skipped": "דולג",
                "revealed": "נחשף",
            }.get(result["result"], result["result"])
            result_lines.append(f"- {result['word']}: {result_label}, {result['hints']} רמזים")
        details = "\n\nפירוט מילים:\n" + "\n".join(result_lines) if result_lines else ""
        return (
            f"המשחק הסתיים עם {self.score} נקודות.\n\n"
            f"שחקן: {self.player_name_var.get().strip() or 'שחקן'}\n"
            f"קטגוריה: {words.get_category_label(self.current_category) if self.current_category else ''}\n"
            f"רמת קושי התחלתית: {self.difficulty_var.get()}\n"
            f"רמת קושי בסיום: {self.current_difficulty}\n"
            f"טיימר: {'פעיל' if self.timer_enabled_var.get() else 'כבוי'}\n"
            f"מצב: {'אימון' if self.practice_mode_var.get() else 'ניקוד'}\n\n"
            f"מילים שנוחשו נכון: {self.correct_words}\n"
            f"מילים שלא נוחשו: {self.failed_words}\n"
            f"מילים שדולגו: {self.skipped_words}\n"
            f"אחוז הצלחה: {success_rate:.0f}%\n"
            f"רצף נכון הכי ארוך: {self.best_correct_streak}\n"
            f"ממוצע רמזים למילה: {average_hints:.1f}\n\n"
            f"הישגים:\n{achievements_text}\n\n"
            f"אימון חכם:\n{insight}"
            f"{details}"
        )

    # שומר שיאים וסטטיסטיקה לאחר משחק מלא.
    def save_game_records(self):
        category_label = words.get_category_label(self.current_category) if self.current_category else ""
        played_rounds = self.correct_words + self.failed_words + self.skipped_words
        if not played_rounds:
            return

        if not self.practice_mode_var.get():
            scores = read_json_file(SCORES_FILE, [])
            scores.append({
                "player": self.player_name_var.get().strip() or "שחקן",
                "score": self.score,
                "category": category_label,
                "difficulty": self.current_difficulty,
                "rounds": played_rounds,
                "success_rate": round(self.correct_words / played_rounds * 100) if played_rounds else 0,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            })
            write_json_file(SCORES_FILE, scores[-100:])

        stats = read_json_file(STATS_FILE, {})
        current = stats.setdefault(category_label, {
            "played": 0,
            "correct": 0,
            "failed": 0,
            "skipped": 0,
            "best_score": 0,
            "players": {},
        })
        current["played"] += played_rounds
        current["correct"] += self.correct_words
        current["failed"] += self.failed_words
        current["skipped"] += self.skipped_words
        current["best_score"] = max(current.get("best_score", 0), self.score)
        players = current.setdefault("players", {})
        player_name = self.player_name_var.get().strip() or "שחקן"
        player_stats = players.setdefault(player_name, {"played": 0, "correct": 0, "best_score": 0})
        player_stats["played"] += played_rounds
        player_stats["correct"] += self.correct_words
        player_stats["best_score"] = max(player_stats.get("best_score", 0), self.score)
        write_json_file(STATS_FILE, stats)

    # מייצא את הסיכום האחרון לקובץ טקסט.
    def export_last_summary(self):
        if not self.last_summary:
            messagebox.showinfo("ייצוא סיכום", "אין עדיין סיכום משחק לייצוא.")
            return
        EXPORTS_DIR.mkdir(exist_ok=True)
        path = EXPORTS_DIR / f"alias-summary-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"
        path.write_text(self.last_summary + "\n", encoding="utf-8")
        messagebox.showinfo("ייצוא סיכום", f"הסיכום נשמר בקובץ:\n{path}")

    # מזהה ניחוש קרוב מספיק כדי לתת פידבק בלי לפתוח רמז נוסף.
    def is_close_guess(self, guess):
        normalized_guess = words.normalize_guess(guess)
        normalized_word = words.normalize_guess(self.secret_word or "")
        if len(normalized_guess) < 3 or len(normalized_word) < 3:
            return False
        return difflib.SequenceMatcher(None, normalized_guess, normalized_word).ratio() >= 0.74

    # Handle guess submission: validate, score, reveal hints, end round if needed.
    def submit_guess(self, event=None):
        if self.multiplayer_active and self.online_service:
            self.submit_online_guess()
            return

        if self.round_finished or not self.secret_word:
            return

        guess = self.guess_var.get().strip()
        if not guess:
            self.set_status("צריך לכתוב ניחוש לפני שבודקים!")
            return

        normalized_guess = words.normalize_guess(guess)
        normalized_word = words.normalize_guess(self.secret_word)
        if normalized_guess != normalized_word and self.is_close_guess(guess):
            self.guesses_list.insert(0, rtl_text(f"{guess} - קרוב"))
            self.guess_var.set("")
            category_label = words.get_category_label(self.current_category)
            self.set_status(f"קרוב מאוד! אתה בכיוון של {category_label}, נסה לדייק בלי לפתוח רמז נוסף.")
            self.play_feedback("warning")
            self.guess_entry.focus_set()
            return

        self.attempts_used += 1
        self.guesses_list.insert(0, rtl_text(guess))

        if normalized_guess == normalized_word:
            points = self.get_points_for_current_difficulty(len(self.revealed_hints))
            if self.practice_mode_var.get():
                points = 0
            self.score += points
            self.round_finished = True
            self.correct_words += 1
            self.current_correct_streak += 1
            self.best_correct_streak = max(self.best_correct_streak, self.current_correct_streak)
            if len(self.revealed_hints) <= 1:
                self.one_hint_wins += 1
            self.total_hints_used += len(self.revealed_hints)
            self.round_results.append({"word": self.secret_word, "result": "correct", "hints": len(self.revealed_hints)})
            self.adjust_dynamic_difficulty("correct")
            self.stop_timer()
            if self.practice_mode_var.get():
                self.set_status(f"בול! מצב אימון לא נותן ניקוד. המילה הייתה: {self.secret_word}!")
            else:
                self.set_status(f"בול! קיבלת {points} נקודות. המילה הייתה: {self.secret_word}!")
            self.play_feedback("success")
            self.submit_button.configure(state="disabled")
            self.next_button.configure(state="normal")
            self.skip_button.configure(state="disabled")
            self.reveal_button.configure(state="disabled")
            self.extra_hint_button.configure(state="disabled")
            self.guess_entry.configure(state="disabled")
            self.refresh_metrics()
            return

        if self.attempts_used >= self.get_difficulty_settings()["max_attempts"]:
            self.end_round_without_success("לא הצלחת אחרי כל הניסיונות")
            return

        self.wrong_guesses.append(guess)
        self.guess_var.set("")
        next_hint_index = len(self.revealed_hints)
        if self.hint_source_var.get() == "ai" and next_hint_index < len(self.all_hints):
            self.start_adaptive_hint_generation(next_hint_index)
            return

        self.reveal_hint_after_wrong_guess(next_hint_index, "לא נכון. נפתח רמז נוסף, קצת יותר קל.")

    def submit_online_guess(self):
        if self.round_finished or not self.secret_word:
            return
        guess = self.guess_var.get().strip()
        if not guess:
            self.set_status("צריך לכתוב ניחוש לפני שבודקים!")
            return
        try:
            state = self.online_service.submit_guess(guess)
        except OnlineGameError as error:
            self.set_status(str(error))
            return
        self.apply_online_state(state, "הניחוש נשלח לשרת.")

    # מדלג על הסבב הנוכחי וממשיך למילה הבאה בלי לתת ניקוד.
    def skip_round(self):
        if self.multiplayer_active and self.online_service:
            try:
                state = self.online_service.skip_round()
            except OnlineGameError as error:
                self.set_status(str(error))
                return
            self.apply_online_state(state, "השרת דילג על הסבב.")
            return

        if self.round_finished or not self.secret_word:
            return
        word = self.secret_word
        self.round_finished = True
        self.skipped_words += 1
        self.current_correct_streak = 0
        self.total_hints_used += len(self.revealed_hints)
        self.round_results.append({"word": word, "result": "skipped", "hints": len(self.revealed_hints)})
        self.adjust_dynamic_difficulty("skipped")
        self.stop_timer()
        self.set_status(f"דילגת על המילה: {word}")
        self.play_feedback("warning")
        self.submit_button.configure(state="disabled")
        self.next_button.configure(state="normal")
        self.skip_button.configure(state="disabled")
        self.reveal_button.configure(state="disabled")
        self.extra_hint_button.configure(state="disabled")
        self.guess_entry.configure(state="disabled")
        self.refresh_metrics()

    # מגלה את התשובה ומסיים את הסבב בלי ניקוד.
    def reveal_answer(self):
        if self.multiplayer_active:
            self.set_status("ב-Multiplayer התשובה נשארת רק בשרת, כדי שלא יהיה אפשר לראות אותה מהמחשב של השחקן.")
            return

        if self.round_finished or not self.secret_word:
            return
        word = self.secret_word
        self.round_finished = True
        self.failed_words += 1
        self.current_correct_streak = 0
        self.total_hints_used += len(self.revealed_hints)
        self.round_results.append({"word": word, "result": "revealed", "hints": len(self.revealed_hints)})
        self.adjust_dynamic_difficulty("revealed")
        self.stop_timer()
        self.set_status(f"התשובה היא: {word}")
        self.play_feedback("warning")
        self.submit_button.configure(state="disabled")
        self.next_button.configure(state="normal")
        self.skip_button.configure(state="disabled")
        self.reveal_button.configure(state="disabled")
        self.extra_hint_button.configure(state="disabled")
        self.guess_entry.configure(state="disabled")
        self.refresh_metrics()

    # מסיים סבב אחרי כישלון, בלי לשכפל קוד בין זמן שנגמר וניסיונות שנגמרו.
    def end_round_without_success(self, reason):
        if self.round_finished:
            return
        word = self.secret_word
        self.round_finished = True
        self.failed_words += 1
        self.current_correct_streak = 0
        self.total_hints_used += len(self.revealed_hints)
        self.round_results.append({"word": word, "result": "failed", "hints": len(self.revealed_hints)})
        self.adjust_dynamic_difficulty("failed")
        self.stop_timer()
        self.set_status(f"{reason}. המילה הייתה: {word}")
        self.play_feedback("error")
        self.submit_button.configure(state="disabled")
        self.next_button.configure(state="normal")
        self.skip_button.configure(state="disabled")
        self.reveal_button.configure(state="disabled")
        self.extra_hint_button.configure(state="disabled")
        self.guess_entry.configure(state="disabled")
        self.refresh_metrics()

    # פותח רמזים התחלתיים לפי רמת הקושי.
    def reveal_starting_hints(self):
        self.revealed_hints = []
        hints_to_reveal = self.get_difficulty_settings()["start_hints"]
        for hint in self.all_hints[:hints_to_reveal]:
            self.revealed_hints.append(hint)

    # מפעיל/מכבה את אזור הניחוש בזמן טעינת AI או סיום סבב.
    def set_round_controls_state(self, state):
        self.submit_button.configure(state=state)
        self.guess_entry.configure(state=state)

    # נועל הגדרות משחק אחרי ההתחלה כדי שהן יהיו בחירה של תחילת משחק בלבד.
    def set_setup_controls_state(self, state):
        readonly_state = "readonly" if state == "normal" else "disabled"
        self.category_combo.configure(state=readonly_state)
        self.difficulty_combo.configure(state=readonly_state)
        self.game_length_combo.configure(state=readonly_state)
        self.player_entry.configure(state=state)
        self.prepared_hints_radio.configure(state=state)
        self.ai_hints_radio.configure(state=state)
        self.multiplayer_check.configure(state=state)
        self.server_entry.configure(state=state)
        self.room_entry.configure(state=state)
        self.new_room_button.configure(state=state)
        self.server_paste_button.configure(state=state)
        self.server_test_button.configure(state=state)
        self.practice_check.configure(state=state)
        self.timer_check.configure(state=state)
        self.start_button.configure(state=state)

    # מתחיל טיימר חדש לסבב הנוכחי.
    def start_timer(self):
        self.stop_timer()
        self.refresh_metrics()
        if not self.timer_enabled_var.get():
            return
        self.timer_after_id = self.root.after(1000, self.tick_timer)

    # עוצר את הטיימר הפעיל, אם קיים.
    def stop_timer(self):
        if self.timer_after_id:
            self.root.after_cancel(self.timer_after_id)
            self.timer_after_id = None

    # מוריד שנייה מהטיימר ומסיים את הסבב אם הזמן נגמר.
    def tick_timer(self):
        if self.round_finished or not self.secret_word:
            self.timer_after_id = None
            return
        self.time_left -= 1
        self.refresh_metrics()
        if self.time_left <= 0:
            self.timer_after_id = None
            self.end_round_without_success("נגמר הזמן")
            return
        self.timer_after_id = self.root.after(1000, self.tick_timer)

    # מעדכן את כותרת הסבב לפי מספר הסבב והקטגוריה.
    def update_round_title(self):
        category_label = words.get_category_label(self.current_category) if self.current_category else "ללא קטגוריה"
        self.round_title.configure(text=rtl_text(f"סבב {self.round_number} | {category_label}"))

    def hex_to_rgb(self, color):
        color = color.lstrip("#")
        return tuple(int(color[index:index + 2], 16) for index in (0, 2, 4))

    def rgb_to_hex(self, rgb):
        return "#{:02x}{:02x}{:02x}".format(*rgb)

    def blend_colors(self, start, end, ratio):
        start_rgb = self.hex_to_rgb(start)
        end_rgb = self.hex_to_rgb(end)
        blended = tuple(round(start_rgb[index] + (end_rgb[index] - start_rgb[index]) * ratio) for index in range(3))
        return self.rgb_to_hex(blended)

    def animate_status_to(self, text, bg, fg, step=0, steps=8, start_bg=None):
        if step == 0:
            if self.status_animation_after_id:
                self.root.after_cancel(self.status_animation_after_id)
            start_bg = self.status_box.cget("bg")
            self.status_box.configure(text=rtl_text(text), fg=fg)
        if step >= steps:
            self.status_box.configure(text=rtl_text(text), bg=bg, fg=fg)
            self.status_animation_after_id = None
            return
        next_bg = self.blend_colors(start_bg, bg, (step + 1) / steps)
        self.status_box.configure(bg=next_bg)
        self.status_animation_after_id = self.root.after(
            24,
            lambda: self.animate_status_to(text, bg, fg, step + 1, steps, start_bg),
        )

    def start_loading_status(self, base_text):
        self.stop_loading_status()

        def tick(frame=0):
            dots = "." * (frame % 4)
            self.set_status(f"{base_text}{dots}")
            self.loading_after_id = self.root.after(360, lambda: tick(frame + 1))

        tick()

    def stop_loading_status(self):
        if self.loading_after_id:
            self.root.after_cancel(self.loading_after_id)
            self.loading_after_id = None

    # מציג הודעת מצב בצבע מתאים לפי סוג האירוע.
    def set_status(self, text):
        bg = "#eef6ff"
        fg = self.colors["info"]
        if "בול" in text or "נקודות" in text:
            bg = "#e8f8ef"
            fg = self.colors["success"]
        elif "לא הצלחת" in text or "צריך לכתוב" in text or "נגמר הזמן" in text:
            bg = "#fff0ee"
            fg = self.colors["error"]
        elif "לא נכון" in text or "דילגת" in text:
            bg = "#fff6e7"
            fg = self.colors["warning"]
        elif "קרוב" in text or "התשובה היא" in text:
            bg = "#fff6e7"
            fg = self.colors["warning"]

        self.animate_status_to(text, bg, fg)

    # נותן פידבק קטן של צליל וצבע אחרי אירוע חשוב.
    def play_feedback(self, kind):
        try:
            self.root.bell()
        except tk.TclError:
            pass
        flash_color = {
            "success": "#d9fbe8",
            "warning": "#fff1c2",
            "error": "#ffd9d4",
        }.get(kind, "#eef6ff")
        if self.animation_after_id:
            self.root.after_cancel(self.animation_after_id)
        original = self.status_box.cget("bg")
        pulse_steps = [flash_color, original, flash_color, original] if kind == "success" else [flash_color, original]

        def pulse(index=0):
            if index >= len(pulse_steps):
                self.animation_after_id = None
                return
            self.status_box.configure(bg=pulse_steps[index])
            self.animation_after_id = self.root.after(130, lambda: pulse(index + 1))

        pulse()

    def animate_progress_to(self, target):
        if self.progress_after_id:
            self.root.after_cancel(self.progress_after_id)
            self.progress_after_id = None
        target = int(target)
        current = int(self.displayed_attempts)
        if current == target:
            self.progress.configure(value=target)
            return
        direction = 1 if target > current else -1

        def step(value=current):
            next_value = value + direction
            self.displayed_attempts = next_value
            self.progress.configure(value=next_value)
            if next_value != target:
                self.progress_after_id = self.root.after(45, lambda: step(next_value))
            else:
                self.progress_after_id = None

        step()

    def animate_new_hint(self):
        for after_id in self.hint_animation_after_ids:
            try:
                self.root.after_cancel(after_id)
            except tk.TclError:
                pass
        self.hint_animation_after_ids = []
        colors = ["#FFE1E7", "#FFD1DB", "#FFE8ED", self.colors["card_inner"]]

        def step(index=0):
            if index >= len(colors):
                self.hints_text.tag_configure("new_hint", background=self.colors["card_inner"])
                self.hint_animation_after_ids = []
                return
            self.hints_text.tag_configure("new_hint", background=colors[index])
            self.hint_animation_after_ids.append(self.root.after(110, lambda: step(index + 1)))

        step()

    # מרענן את המדדים שמוצגים מעל אזור המשחק.
    def refresh_metrics(self):
        category_text = words.get_category_label(self.current_category) if self.current_category else "עדיין לא נבחרה"
        self.score_value.configure(text=str(self.score))
        self.hints_value.configure(text=f"{len(self.revealed_hints)}/{words.MAX_HINTS}")
        if not self.secret_word:
            timer_text = "--"
        elif not self.timer_enabled_var.get():
            timer_text = "ללא"
        else:
            timer_text = f"{self.time_left}s"
        self.timer_value.configure(text=timer_text)
        self.difficulty_value.configure(text=self.current_difficulty)
        self.category_value.configure(text=category_text)
        self.progress.configure(maximum=self.get_difficulty_settings()["max_attempts"])
        self.animate_progress_to(self.attempts_used)

    # מציג את כל הרמזים שנפתחו עד עכשיו בתוך תיבת הטקסט.
    def refresh_hints(self):
        previous_hint_count = self.last_hint_count
        current_hint_count = len(self.revealed_hints)
        self.hints_text.configure(state="normal")
        self.hints_text.delete("1.0", tk.END)

        if not self.revealed_hints:
            self.hints_text.insert("1.0", "כאן יופיעו הרמזים של הסבב")
            self.hints_text.tag_add("rtl", "1.0", "end")
            self.last_hint_count = 0
            self.hints_text.configure(state="disabled")
            return

        for index, hint in enumerate(self.revealed_hints, start=1):
            points = self.get_points_for_current_difficulty(index)
            start = self.hints_text.index("end-1c")
            self.hints_text.insert("end", f"רמז {index}\n")
            self.hints_text.insert("end", f"{hint}\n")
            self.hints_text.insert("end", f"נקודות בשלב הזה: {points}\n\n")
            end = self.hints_text.index("end-1c")
            self.hints_text.tag_add("rtl", start, end)
            if index == current_hint_count and current_hint_count > previous_hint_count:
                self.hints_text.tag_add("new_hint", start, end)

        content = self.hints_text.get("1.0", "end-1c")
        lines = content.splitlines()
        current_index = "1.0"
        for line in lines:
            line_end = f"{current_index} lineend"
            if line.startswith("רמז "):
                self.hints_text.tag_add("hint_title", current_index, line_end)
            elif line.startswith("נקודות בשלב הזה:"):
                self.hints_text.tag_add("hint_points", current_index, line_end)
            current_index = self.hints_text.index(f"{current_index} +1 line")

        self.hints_text.tag_add("rtl", "1.0", "end")
        self.hints_text.configure(state="disabled")
        self.last_hint_count = current_hint_count
        if current_hint_count > previous_hint_count:
            self.animate_new_hint()

        # מצב פתיחה לפני שהמשתמש התחיל סבב.
    def render_intro_state(self):
        self.refresh_metrics()
        self.refresh_hints()
        self.guess_entry.configure(state="disabled")
        self.skip_button.configure(state="disabled")
        self.reveal_button.configure(state="disabled")
        self.extra_hint_button.configure(state="disabled")
        self.show_home_screen()

# Entry point: initialize TK root and launch the AliasGameApp.
def main():
    try:
        root = tk.Tk()
    except tk.TclError as error:
        print(f"לא ניתן לפתוח חלון גרפי: {error}")
        print("נסה להריץ את הקובץ מסביבה גרפית רגילה על המחשב.")
        sys.exit(1)

    print("Alias AI נפתח בחלון חדש. כדי לסיים, סוגרים את החלון.")
    AliasGameApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()