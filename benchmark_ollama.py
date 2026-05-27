#!/usr/bin/env python3
import argparse
import ast
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


GAME_FILE = Path(__file__).with_name("normal code.py")
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
PROMPTS = [
    "תן רמז קצר למילה שמש בלי להגיד את המילה.",
    "תן רמז קצר למילה בית בלי להגיד את המילה.",
    "תן רמז קצר למילה תפוח בלי להגיד את המילה.",
]


def get_game_model():
    tree = ast.parse(GAME_FILE.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "OLLAMA_MODEL":
                    return ast.literal_eval(node.value)
    raise RuntimeError("לא נמצא OLLAMA_MODEL בקובץ המשחק.")


def ask_ollama(model, prompt):
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"num_predict": 60},
    }
    request = urllib.request.Request(
        OLLAMA_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    start = time.perf_counter()
    with urllib.request.urlopen(request, timeout=120) as response:
        data = json.loads(response.read().decode("utf-8"))
    return time.perf_counter() - start, data.get("response", "").strip()


def main():
    parser = argparse.ArgumentParser(description="Measure Ollama response speed.")
    parser.add_argument(
        "--model",
        help="Model name to test. If omitted, uses OLLAMA_MODEL from normal code.py.",
    )
    args = parser.parse_args()

    model = args.model or get_game_model()
    print(f"Testing model: {model}")

    times = []
    for index, prompt in enumerate(PROMPTS, start=1):
        print(f"\nRequest {index}:")
        try:
            seconds, answer = ask_ollama(model, prompt)
        except urllib.error.HTTPError as error:
            print(f"Ollama returned HTTP {error.code}: {error.reason}")
            print("בדוק שהמודל הזה מופיע בפקודה: ollama list")
            return
        except urllib.error.URLError as error:
            print(f"Could not connect to Ollama: {error}")
            print("בדוק ש-Ollama פתוח ורץ במחשב.")
            return
        except TimeoutError:
            print("הבקשה לקחה יותר מדי זמן ונעצרה.")
            return

        times.append(seconds)
        print(f"Time: {seconds:.2f} seconds")
        print(f"Answer: {answer}")

    print(f"\nAverage time: {sum(times) / len(times):.2f} seconds")


if __name__ == "__main__":
    main()
