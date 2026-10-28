import json
import readline  # noqa: F401  # importing it enables arrow-key/history editing in input()
import sys
from pathlib import Path

from openai import OpenAI

import profile_store
from models import Settings

# Same provider and key as the web app: its active profile, keychain key first.
settings = Settings()
store = profile_store.load_store(settings)
profile = next((p for p in store.profiles if p.id == store.active), None)
if profile is None:
    sys.exit("No provider configured: add one in the web app's Providers dialog (or set DOLPHINLLM_API_KEY, see .env.example)")
api_key = profile_store.resolve_key(settings, profile)[0] or (None if profile.needs_key else "not-needed")
if not api_key:
    sys.exit(f"No API key for {profile.name}: add one in the web app's Providers dialog")

client = OpenAI(base_url=profile.base_url, api_key=api_key)

# The API is stateless: continuity only exists because we resend the full history each time.
HISTORY_FILE = Path(__file__).with_name(".history.json")

args = sys.argv[1:]
if "--new" in args:
    args.remove("--new")
    HISTORY_FILE.unlink(missing_ok=True)

messages = json.loads(HISTORY_FILE.read_text()) if HISTORY_FILE.exists() else []


def ask(prompt):
    messages.append({"role": "user", "content": prompt})
    try:
        r = client.chat.completions.create(model=profile.model, messages=messages)
    except Exception:
        messages.pop()
        raise
    reply = r.choices[0].message.content
    messages.append({"role": "assistant", "content": reply})
    HISTORY_FILE.write_text(json.dumps(messages, ensure_ascii=False, indent=2))
    return reply


if args:
    print(ask(" ".join(args)))
else:
    print("Chat started. Empty line or Ctrl-D to quit.")
    while True:
        try:
            prompt = input("> ").strip()
        except EOFError:
            break
        if not prompt:
            break
        print(ask(prompt))
