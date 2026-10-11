"""Find your chat with the bot and save its id in .env (one-time setup for the alert push).

    1. Put the bot token in .env:  TELEGRAM_BOT_TOKEN=...
    2. Open the bot in Telegram, press Start and send any message.
    3. python scripts/telegram_find_chat.py

It asks the Bot API once for the latest messages sent to the bot (getUpdates), takes the newest private chat and writes
or replaces only the TELEGRAM_CHAT_ID= line in .env. It prints the first name of that chat's owner and nothing else:
never the token, never the id.
"""
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
BOT_LINK = "t.me/KAMI67_BOT"
HOW = f"Open {BOT_LINK}, press Start, send any message, then run this again."


def newest_private_chat(updates: list) -> dict | None:
    """The private chat of the update with the highest update_id (None if there is none)."""
    best = None
    for u in updates if isinstance(updates, list) else []:
        msg = u.get("message") if isinstance(u, dict) else None
        chat = msg.get("chat") if isinstance(msg, dict) else None
        if not isinstance(chat, dict) or chat.get("type") != "private" or not isinstance(chat.get("id"), int) or isinstance(chat.get("id"), bool):
            continue
        if best is None or u.get("update_id", 0) >= best[0]:
            best = (u.get("update_id", 0), chat)
    return best[1] if best else None


def save_chat_id(env_path: Path, chat_id: int) -> None:
    """Write or replace only the TELEGRAM_CHAT_ID line; every other line of .env stays as it is."""
    from kami.notify.settings import CHAT

    text = env_path.read_bytes().decode("utf-8") if env_path.is_file() else ""
    nl = "\r\n" if "\r\n" in text else "\n"
    out, done = [], False
    for line in text.splitlines(keepends=True):
        s = line.strip()
        if "=" in s and not s.startswith("#") and s.split("=", 1)[0].strip() == CHAT:
            if not done:
                out.append(f"{CHAT}={chat_id}{nl}")
                done = True
            continue  # a second line with the same key is dropped
        out.append(line)
    if not done:
        if out and not out[-1].endswith(("\n", "\r")):
            out[-1] += nl
        out.append(f"{CHAT}={chat_id}{nl}")
    tmp = env_path.with_name(env_path.name + ".tmp")
    tmp.write_bytes("".join(out).encode("utf-8"))
    os.replace(tmp, env_path)


def main(env=None, transport=None, out=print) -> int:
    import httpx

    from kami.notify.settings import TOKEN, env_file, load_settings
    from kami.notify.telegram import API_ROOT, body_of  # importing it also keeps httpx request logging off (the URL has the token)

    env = os.environ if env is None else env
    settings = load_settings(env)
    if TOKEN in settings.missing:
        out(f"{TOKEN} is missing or malformed in .env. Add the token that @BotFather gave you, then run this again.")
        return 1
    try:
        with httpx.Client(timeout=15.0, transport=transport) as client:
            r = client.get(f"{API_ROOT}/bot{settings.value(TOKEN)}/getUpdates", params={"timeout": 0, "allowed_updates": '["message"]'})
    except httpx.HTTPError as e:
        out(f"Could not reach Telegram (network error, {type(e).__name__}). Check the connection and run this again.")
        return 1
    body = body_of(r)
    if r.status_code in (401, 404):
        out(f"Telegram rejected the bot token. Check {TOKEN} in .env.")
        return 1
    if r.status_code == 409:
        out("This bot has a webhook or another program is reading its messages, so they cannot be read here. Stop that first.")
        return 1
    if r.status_code != 200 or body.get("ok") is not True:
        out(f"Telegram did not answer as expected (HTTP {r.status_code}). Try again later.")
        return 1
    chat = newest_private_chat(body.get("result"))
    if chat is None:
        out("No message to the bot was found. " + HOW)
        return 1
    save_chat_id(env_file(env), chat["id"])
    name = "".join(ch for ch in str(chat.get("first_name") or "this chat") if ch.isprintable())[:40].strip() or "this chat"
    out(f"Chat id saved for {name}")
    return 0


if __name__ == "__main__":
    # Use the project's virtual environment if this was started with another Python.
    _venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    if _venv_py.is_file() and Path(sys.executable).resolve() != _venv_py.resolve():
        import subprocess

        raise SystemExit(subprocess.call([str(_venv_py), str(Path(__file__).resolve()), *sys.argv[1:]]))
    raise SystemExit(main())
