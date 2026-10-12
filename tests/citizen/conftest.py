"""No test in this folder can reach Telegram, Ollama or a model hub: any HTTP request that would leave the process is
refused, recorded, and makes the test fail at teardown even if the code under test swallowed the error. Uploads go to
a temporary folder."""
import httpx
import pytest


class RealHTTPAttempted(AssertionError):
    pass


@pytest.fixture(autouse=True)
def no_real_http(monkeypatch, tmp_path):
    attempts: list[str] = []

    def refuse(self, request):
        attempts.append(f"{request.method} {request.url.host}")
        raise RealHTTPAttempted(f"a test tried a real HTTP request to {request.url.host}")

    async def refuse_async(self, request):
        refuse(self, request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse_async)
    monkeypatch.setenv("KAMI_CITIZEN_DIR", str(tmp_path / "citizen"))
    for k in ("KAMI_CITIZEN_ENABLE", "CITIZEN_ALLOWED_CHAT_IDS", "CITIZEN_ASR", "CITIZEN_TTS", "CITIZEN_DEVICE", "OLLAMA_MODEL", "OLLAMA_URL"):
        monkeypatch.delenv(k, raising=False)
    yield attempts
    assert not attempts, f"real HTTP request attempted: {attempts}"
