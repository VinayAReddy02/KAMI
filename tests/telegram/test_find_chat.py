"""scripts/telegram_find_chat.py (PLAN_ROUND4.md T3) with mocked HTTP and a temporary .env. Never run against Telegram here."""
import importlib.util
from pathlib import Path

import httpx
import pytest

from .helpers import SECRETS, TOKEN, Bot

ROOT = Path(__file__).resolve().parents[2]
CHAT_ID = 5550001112
OTHER_ID = 5550009998


def script():
    spec = importlib.util.spec_from_file_location("telegram_find_chat", ROOT / "scripts" / "telegram_find_chat.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def update(update_id, chat_id, first_name="Asha", kind="private"):
    return {"update_id": update_id, "message": {"message_id": update_id, "text": "hi", "chat": {"id": chat_id, "type": kind, "first_name": first_name}}}


def updates(*items):
    return (200, {"ok": True, "result": list(items)})


def run(tmp_path, bot: Bot, env_text: str | None = f"TELEGRAM_BOT_TOKEN={TOKEN}\n"):
    f = tmp_path / ".env"
    if env_text is not None:
        f.write_bytes(env_text.encode("utf-8"))
    out: list[str] = []
    code = script().main(env={"KAMI_NOTIFY_ENV_FILE": str(f)}, transport=bot.transport, out=out.append)
    assert not any(s in " ".join(out) for s in (*SECRETS, str(CHAT_ID), str(OTHER_ID))), "the token or a chat id was printed"
    return code, out, (f.read_bytes().decode("utf-8") if f.exists() else None)


def test_saves_the_newest_private_chat_and_prints_only_the_first_name(tmp_path):
    bot = Bot(updates(update(11, OTHER_ID, "Old"), update(14, -100777, "Group", kind="group"), update(13, CHAT_ID, "Asha"),
                      {"update_id": 15, "edited_message": {"chat": {"id": 1, "type": "private"}}}))
    before = f"# my settings\nTELEGRAM_BOT_TOKEN={TOKEN}\nKAMI_TELEGRAM_ENABLE=0\n\nOTHER=keep me\n"
    code, out, after = run(tmp_path, bot, before)
    assert code == 0 and out == ["Chat id saved for Asha"]
    assert after == before + f"TELEGRAM_CHAT_ID={CHAT_ID}\n"  # only one line added, everything else untouched
    assert bot.n == 1
    req = bot.requests[0]
    assert req.method == "GET" and req.url.host == "api.telegram.org" and req.url.path == f"/bot{TOKEN}/getUpdates"


def test_replaces_only_the_existing_chat_id_line_and_keeps_line_endings(tmp_path):
    before = f"TELEGRAM_BOT_TOKEN={TOKEN}\r\nTELEGRAM_CHAT_ID={OTHER_ID}\r\n# note\r\nTELEGRAM_CHAT_ID=\r\nKAMI_TELEGRAM_ENABLE=1"
    code, out, after = run(tmp_path, Bot(updates(update(1, CHAT_ID, "Ravi"))), before)
    assert code == 0 and out == ["Chat id saved for Ravi"]
    assert after == f"TELEGRAM_BOT_TOKEN={TOKEN}\r\nTELEGRAM_CHAT_ID={CHAT_ID}\r\n# note\r\nKAMI_TELEGRAM_ENABLE=1"


def test_appends_after_a_last_line_without_a_newline(tmp_path):
    code, _, after = run(tmp_path, Bot(updates(update(1, CHAT_ID))), f"TELEGRAM_BOT_TOKEN={TOKEN}")
    assert code == 0 and after == f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_CHAT_ID={CHAT_ID}\n"


def test_the_saved_id_is_what_the_notifier_then_uses(tmp_path):
    from kami.notify import load_settings

    run(tmp_path, Bot(updates(update(1, CHAT_ID))), f"TELEGRAM_BOT_TOKEN={TOKEN}\nKAMI_TELEGRAM_ENABLE=1\n")
    s = load_settings({"KAMI_NOTIFY_ENV_FILE": str(tmp_path / ".env")})
    assert s.ready and s.value("TELEGRAM_CHAT_ID") == str(CHAT_ID)


@pytest.mark.parametrize("answer", [updates(), updates(update(3, -100777, "Group", kind="supergroup")), (200, {"ok": True, "result": "odd"})])
def test_no_private_message_gives_a_clear_instruction_and_changes_nothing(tmp_path, answer):
    before = f"TELEGRAM_BOT_TOKEN={TOKEN}\n"
    code, out, after = run(tmp_path, Bot(answer), before)
    assert code == 1 and after == before
    assert out == ["No message to the bot was found. Open t.me/KAMI67_BOT, press Start, send any message, then run this again."]


@pytest.mark.parametrize("env_text", [None, "", "TELEGRAM_BOT_TOKEN=\n", "TELEGRAM_BOT_TOKEN=not a token\n"])
def test_without_a_usable_token_nothing_is_requested(tmp_path, env_text):
    bot = Bot()
    code, out, after = run(tmp_path, bot, env_text)
    assert code == 1 and bot.requests == [] and after == env_text
    assert "TELEGRAM_BOT_TOKEN is missing or malformed in .env" in out[0]


@pytest.mark.parametrize("answer, words", [
    ((401, {"ok": False, "error_code": 401, "description": f"Unauthorized {TOKEN}"}), "Telegram rejected the bot token. Check TELEGRAM_BOT_TOKEN in .env."),
    ((404, {"ok": False, "error_code": 404, "description": "Not Found"}), "Telegram rejected the bot token"),
    ((409, {"ok": False, "error_code": 409, "description": "Conflict: can't use getUpdates method while webhook is active"}), "webhook or another program"),
    ((500, None), "Telegram did not answer as expected (HTTP 500)"),
    ((200, {"ok": False, "description": TOKEN}), "Telegram did not answer as expected (HTTP 200)"),
    (httpx.ConnectError(f"cannot reach https://api.telegram.org/bot{TOKEN}/getUpdates"), "Could not reach Telegram (network error, ConnectError)"),
])
def test_errors_are_fixed_sentences_and_change_nothing(tmp_path, answer, words):
    before = f"TELEGRAM_BOT_TOKEN={TOKEN}\nTELEGRAM_CHAT_ID={OTHER_ID}\n"
    bot = Bot(answer)
    code, out, after = run(tmp_path, bot, before)
    assert code == 1 and bot.n == 1 and after == before and len(out) == 1 and words in out[0]


def test_first_name_is_cleaned_before_printing(tmp_path):
    code, out, _ = run(tmp_path, Bot(updates(update(1, CHAT_ID, "Me\x1b[31m\nera" + "x" * 100))))
    assert code == 0 and out[0].startswith("Chat id saved for Me[31mera") and len(out[0]) <= len("Chat id saved for ") + 40 and "\n" not in out[0]
    code, out, _ = run(tmp_path, Bot(updates({"update_id": 2, "message": {"chat": {"id": CHAT_ID, "type": "private"}}})))
    assert code == 0 and out == ["Chat id saved for this chat"]
