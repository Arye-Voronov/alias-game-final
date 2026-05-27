#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import json
import random
import argparse
import os
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import words


HOST = "0.0.0.0"
PORT = int(os.environ.get("PORT", "8000"))
APP_DIR = Path(__file__).resolve().parent
SERVER_RECORDS_FILE = APP_DIR / "server_records.json"
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "gemma3:4b")
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434/api/generate")
OLLAMA_TIMEOUT_SECONDS = int(os.environ.get("OLLAMA_TIMEOUT_SECONDS", "60"))
DIFFICULTY_SECONDS = {"קל": 90, "רגיל": 60, "קשה": 45}
MIN_PLAYERS_TO_START = 2
ROOMS = {}


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


def read_records():
    records = read_json_file(SERVER_RECORDS_FILE, {})
    records.setdefault("rooms", {})
    return records


def write_records(records):
    write_json_file(SERVER_RECORDS_FILE, records)


def html_response(handler, status, html):
    body = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def json_response(handler, status, payload):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_json(handler):
    length = int(handler.headers.get("Content-Length", "0"))
    if not length:
        return {}
    return json.loads(handler.rfile.read(length).decode("utf-8"))


def clean_ai_hint(hint):
    hint = hint.strip()
    for prefix in ("הרמז:", "רמז:", "Hint:"):
        if hint.startswith(prefix):
            hint = hint[len(prefix):].strip()
    return hint.strip("\"'“”")


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


def generate_ollama_hints(word, prepared_hints, category):
    prompt = (
        "כתוב 5 רמזים בעברית למשחק Alias.\n"
        f"המילה הסודית היא: {word}\n"
        f"הקטגוריה היא: {category}\n"
        f"הרמזים המוכנים שכבר קיימים, מהקשה לקל, הם: {prepared_hints}\n"
        "כל רמז צריך לתת כיוון משמעותי חדש, לא לחזור על אותו רעיון במילים אחרות.\n"
        "שמור על סדר קושי ברור: רמז 1 עקיף וחכם, רמז 3 כבר מכוון, רמז 5 כמעט פותר אבל עדיין לא חושף.\n"
        "כתוב בעברית טבעית, קצרה וברורה.\n"
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
            OLLAMA_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=OLLAMA_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
        return parse_ai_hints(data.get("response", ""), word)
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return None


def build_round_hints(room, word, prepared_hints):
    ordered_hints = words.order_hints_by_difficulty(prepared_hints)
    if room.get("hint_source") != "ai":
        room["hint_source_used"] = "prepared"
        return ordered_hints

    category_label = words.get_category_label(room["category"])
    ai_hints = generate_ollama_hints(word, ordered_hints, category_label)
    if ai_hints:
        room["hint_source_used"] = "ai"
        return ai_hints

    room["hint_source_used"] = "prepared_fallback"
    return ordered_hints


def new_room_id():
    while True:
        room_id = str(random.randint(1000, 9999))
        if room_id not in ROOMS:
            return room_id


def public_state(room, message=""):
    expire_round_if_needed(room)
    hints = room.get("hints", [])
    revealed_count = room.get("revealed_count", 0)
    player_count = len(room.get("players", []))
    waiting_for_players = (
        not room["round_active"]
        and not room["game_over"]
        and player_count < MIN_PLAYERS_TO_START
    )
    return {
        "room_id": room["room_id"],
        "players": sorted(room.get("players", [])),
        "player_count": player_count,
        "min_players_to_start": MIN_PLAYERS_TO_START,
        "waiting_for_players": waiting_for_players,
        "category": room["category"],
        "difficulty": room["difficulty"],
        "hint_source": room.get("hint_source", "prepared"),
        "hint_source_used": room.get("hint_source_used", "prepared"),
        "timer_enabled": room.get("timer_enabled", True),
        "time_limit": room.get("time_limit", 0),
        "round_number": room["round_number"],
        "revealed_hints": hints[:revealed_count],
        "scoreboard": room["scoreboard"],
        "guesses": room["guesses"][-20:],
        "attempts_used": len(room["guesses"]),
        "timer_enabled": room.get("timer_enabled", True),
        "time_limit": room.get("time_limit", 0),
        "time_left": get_time_left(room),
        "round_active": room["round_active"],
        "game_over": room["game_over"],
        "round_results": room.get("round_results", []),
        "message": message,
    }


def get_time_left(room):
    if not room.get("timer_enabled", True) or not room.get("round_active", False):
        return 0
    started_at = room.get("round_started_at")
    time_limit = int(room.get("time_limit") or 0)
    if not started_at or not time_limit:
        return 0
    return max(0, int(time_limit - (time.time() - started_at)))


def expire_round_if_needed(room):
    if not room.get("round_active", False):
        return
    if not room.get("timer_enabled", True):
        return
    if get_time_left(room) > 0:
        return
    record_round_result(room, "failed", "השרת")
    room["round_active"] = False
    save_room_record(room)


def record_round_result(room, result, player="", points=0):
    word = room.get("secret_word", "")
    if not word:
        return
    if room.get("round_results") and room["round_results"][-1].get("word") == word:
        return
    room.setdefault("round_results", []).append({
        "word": word,
        "result": result,
        "player": player,
        "points": points,
        "hints": room.get("revealed_count", 0),
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    })


def get_room_record(room):
    round_results = room.get("round_results", [])
    correct_words = sum(1 for result in round_results if result.get("result") == "correct")
    skipped_words = sum(1 for result in round_results if result.get("result") == "skipped")
    failed_words = sum(1 for result in round_results if result.get("result") == "failed")
    played_rounds = len(round_results)
    return {
        "room_id": room["room_id"],
        "category": room["category"],
        "category_label": words.get_category_label(room["category"]),
        "difficulty": room["difficulty"],
        "hint_source": room.get("hint_source", "prepared"),
        "hint_source_used": room.get("hint_source_used", "prepared"),
        "max_rounds": room.get("max_rounds"),
        "scoreboard": room.get("scoreboard", {}),
        "round_results": round_results,
        "played_rounds": played_rounds,
        "correct_words": correct_words,
        "failed_words": failed_words,
        "skipped_words": skipped_words,
        "success_rate": round(correct_words / played_rounds * 100) if played_rounds else 0,
        "game_over": room.get("game_over", False),
        "created_at": room.get("created_at", ""),
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
    }


def save_room_record(room):
    records = read_records()
    records["rooms"][room["room_id"]] = get_room_record(room)
    write_records(records)


def build_scores(records):
    scores = []
    for room in records.get("rooms", {}).values():
        played_rounds = room.get("played_rounds", 0)
        if not played_rounds:
            continue
        for player, score in room.get("scoreboard", {}).items():
            scores.append({
                "player": player,
                "score": score,
                "category": room.get("category_label", ""),
                "difficulty": room.get("difficulty", ""),
                "rounds": played_rounds,
                "success_rate": room.get("success_rate", 0),
                "room_id": room.get("room_id", ""),
                "created_at": room.get("updated_at", ""),
            })
    return sorted(scores, key=lambda score: score.get("score", 0), reverse=True)[:100]


def build_stats(records):
    stats = {}
    for room in records.get("rooms", {}).values():
        category = room.get("category_label", "")
        if not category or not room.get("played_rounds", 0):
            continue
        current = stats.setdefault(category, {
            "played": 0,
            "correct": 0,
            "failed": 0,
            "skipped": 0,
            "best_score": 0,
            "players": {},
        })
        current["played"] += room.get("played_rounds", 0)
        current["correct"] += room.get("correct_words", 0)
        current["failed"] += room.get("failed_words", 0)
        current["skipped"] += room.get("skipped_words", 0)
        current["best_score"] = max(current["best_score"], max(room.get("scoreboard", {}).values(), default=0))

        for player, score in room.get("scoreboard", {}).items():
            player_stats = current["players"].setdefault(player, {"played": 0, "correct": 0, "best_score": 0})
            player_stats["played"] += room.get("played_rounds", 0)
            player_stats["correct"] += sum(
                1 for result in room.get("round_results", [])
                if result.get("result") == "correct" and result.get("player") == player
            )
            player_stats["best_score"] = max(player_stats["best_score"], score)
    return stats


def choose_round(room):
    entries = list(words.get_words_by_category(room["category"]).items())
    random.shuffle(entries)
    available = [(word, hints) for word, hints in entries if word not in room["used_words"]]
    if room["max_rounds"] is not None and room["round_number"] >= room["max_rounds"]:
        room["game_over"] = True
        room["round_active"] = False
        save_room_record(room)
        return "המשחק הסתיים."
    if not available:
        room["game_over"] = True
        room["round_active"] = False
        save_room_record(room)
        return "נגמרו המילים בקטגוריה."

    word, hints = available[0]
    room["used_words"].add(word)
    room["secret_word"] = word
    room["hints"] = build_round_hints(room, word, hints)
    room["revealed_count"] = 1
    room["guesses"] = []
    room["round_number"] += 1
    room["round_active"] = True
    room["round_started_at"] = time.time()
    return "מילה חדשה התחילה."


def maybe_start_room(room):
    if room["round_active"] or room["game_over"] or room["round_number"] > 0:
        return "מחכים לסבב הבא."
    if len(room.get("players", [])) < MIN_PLAYERS_TO_START:
        return f"מחכים לשחקן נוסף. צריך לפחות {MIN_PLAYERS_TO_START} שחקנים."
    return choose_round(room)


def choose_round_if_ready(room):
    if len(room.get("players", [])) < MIN_PLAYERS_TO_START:
        room["round_active"] = False
        return f"מחכים לשחקן נוסף. צריך לפחות {MIN_PLAYERS_TO_START} שחקנים."
    return choose_round(room)


def create_room(payload):
    room_id = new_room_id()
    player = payload.get("player") or "שחקן"
    room = {
        "room_id": room_id,
        "players": {player},
        "scoreboard": {player: 0},
        "category": payload.get("category") or words.get_categories()[0],
        "difficulty": payload.get("difficulty") or "רגיל",
        "hint_source": payload.get("hint_source") if payload.get("hint_source") in ("prepared", "ai") else "prepared",
        "hint_source_used": "prepared",
        "max_rounds": payload.get("max_rounds"),
        "timer_enabled": bool(payload.get("timer_enabled", True)),
        "time_limit": int(payload.get("time_limit") or DIFFICULTY_SECONDS.get(payload.get("difficulty") or "רגיל", 60)),
        "round_started_at": None,
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "used_words": set(),
        "secret_word": "",
        "hints": [],
        "revealed_count": 0,
        "guesses": [],
        "round_results": [],
        "round_number": 0,
        "round_active": False,
        "game_over": False,
    }
    ROOMS[room_id] = room
    message = maybe_start_room(room)
    save_room_record(room)
    return room, message


def server_home_page():
    return """<!doctype html>
<html lang="he" dir="rtl">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Alias AI Multiplayer Server</title>
  <style>
    body {
      margin: 0;
      font-family: Arial, sans-serif;
      background: #fbf7f8;
      color: #1a1a1a;
    }
    main {
      max-width: 760px;
      margin: 48px auto;
      padding: 28px;
      background: #ffffff;
      border: 2px solid #ffe2e7;
    }
    h1 {
      margin: 0 0 12px;
      color: #b80f2a;
      font-size: 30px;
    }
    .status {
      display: inline-block;
      margin: 10px 0 20px;
      padding: 8px 12px;
      background: #e8f8ef;
      color: #1a7a4a;
      font-weight: bold;
    }
    code {
      direction: ltr;
      display: inline-block;
      background: #fff3f5;
      padding: 3px 6px;
    }
    a {
      color: #8f1230;
      font-weight: bold;
    }
  </style>
</head>
<body>
  <main>
    <h1>Alias AI Multiplayer Server</h1>
    <div class="status">השרת עובד</div>
    <p>זה עמוד בדיקה של שרת ה-Multiplayer. אם אתה רואה את העמוד הזה בכרום, אפשר לגשת לשרת.</p>
    <p>במשחק הכנס את כתובת השרת, למשל: <code>http://127.0.0.1:8000</code></p>
    <p>בדיקת API: <a href="/health">/health</a></p>
  </main>
</body>
</html>
"""


class MultiplayerHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def do_GET(self):
        path = urlparse(self.path).path
        parts = [part for part in path.split("/") if part]
        if path == "/":
            html_response(self, 200, server_home_page())
            return
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if path == "/health":
            json_response(self, 200, {"status": "ok", "rooms": len(ROOMS)})
            return
        if path == "/records":
            records = read_records()
            json_response(self, 200, {
                "rooms": records.get("rooms", {}),
                "scores": build_scores(records),
                "stats": build_stats(records),
            })
            return
        if path == "/scores":
            json_response(self, 200, {"scores": build_scores(read_records())})
            return
        if path == "/stats":
            json_response(self, 200, {"stats": build_stats(read_records())})
            return
        if len(parts) == 3 and parts[0] == "rooms" and parts[2] == "state":
            room = ROOMS.get(parts[1])
            if not room:
                json_response(self, 404, {"error": "room not found"})
                return
            json_response(self, 200, public_state(room))
            return
        json_response(self, 404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        parts = [part for part in path.split("/") if part]
        try:
            payload = read_json(self)
        except json.JSONDecodeError:
            json_response(self, 400, {"error": "invalid json"})
            return

        if path == "/rooms":
            room, message = create_room(payload)
            json_response(self, 200, {"room_id": room["room_id"], "state": public_state(room, message)})
            return

        if len(parts) != 3 or parts[0] != "rooms":
            json_response(self, 404, {"error": "not found"})
            return

        room = ROOMS.get(parts[1])
        action = parts[2]
        if not room:
            json_response(self, 404, {"error": "room not found"})
            return

        player = payload.get("player") or "שחקן"
        room["players"].add(player)
        room["scoreboard"].setdefault(player, 0)

        if action == "join":
            message = maybe_start_room(room)
            save_room_record(room)
            if room["round_active"]:
                message = f"{player} הצטרף. המשחק התחיל."
            json_response(self, 200, {"state": public_state(room, message)})
            return

        if action == "start":
            room["category"] = payload.get("category") or room["category"]
            room["difficulty"] = payload.get("difficulty") or room["difficulty"]
            if payload.get("hint_source") in ("prepared", "ai"):
                room["hint_source"] = payload["hint_source"]
            room["timer_enabled"] = bool(payload.get("timer_enabled", room.get("timer_enabled", True)))
            room["time_limit"] = int(payload.get("time_limit") or DIFFICULTY_SECONDS.get(room["difficulty"], 60))
            room["max_rounds"] = payload.get("max_rounds")
            room["used_words"] = set()
            room["round_results"] = []
            room["round_number"] = 0
            room["game_over"] = False
            message = choose_round_if_ready(room)
            save_room_record(room)
            json_response(self, 200, {"state": public_state(room, message)})
            return

        if action == "next-round":
            message = choose_round_if_ready(room)
            save_room_record(room)
            json_response(self, 200, {"state": public_state(room, message)})
            return

        if action == "hint":
            if room["round_active"] and room["revealed_count"] < len(room["hints"]):
                room["revealed_count"] += 1
                message = "נפתח רמז נוסף."
            else:
                message = "אין עוד רמזים לפתוח."
            save_room_record(room)
            json_response(self, 200, {"state": public_state(room, message)})
            return

        if action == "skip":
            record_round_result(room, "skipped", player)
            room["round_active"] = False
            save_room_record(room)
            json_response(self, 200, {"state": public_state(room, f"{player} דילג על המילה.")})
            return

        if action == "guess":
            guess = payload.get("guess", "")
            room["guesses"].append(f"{player}: {guess}")
            correct = words.normalize_guess(guess) == words.normalize_guess(room.get("secret_word", ""))
            if correct and room["round_active"]:
                points = words.get_points_for_hint_number(room["revealed_count"])
                room["scoreboard"][player] += points
                record_round_result(room, "correct", player, points)
                room["round_active"] = False
                message = f"{player} צדק וקיבל {points} נקודות."
            else:
                if room["round_active"] and room["revealed_count"] < len(room["hints"]):
                    room["revealed_count"] += 1
                message = f"{player} ניחש לא נכון."
            save_room_record(room)
            json_response(self, 200, {"state": public_state(room, message)})
            return

        json_response(self, 404, {"error": "not found"})


def main():
    parser = argparse.ArgumentParser(description="Run a local Alias multiplayer test server.")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    server = ThreadingHTTPServer((args.host, args.port), MultiplayerHandler)
    display_host = "127.0.0.1" if args.host == "0.0.0.0" else args.host
    print(f"Multiplayer server: http://{display_host}:{args.port}")
    print("במחשב מקומי הכניסו את הכתובת הזאת. באינטרנט הכניסו את כתובת ה-HTTPS שהשירות נותן.")
    server.serve_forever()


if __name__ == "__main__":
    main()
