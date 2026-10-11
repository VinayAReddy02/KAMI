"""No test in this folder can send a real message: any HTTP request that would leave the process is refused, recorded,
and makes the test fail at teardown even if the code under test swallowed the error."""
import httpx
import pytest

LOCAL = {"127.0.0.1", "localhost", "::1", "testserver"}


class RealHTTPAttempted(AssertionError):
    pass


@pytest.fixture(autouse=True)
def no_real_http(monkeypatch):
    attempts: list[str] = []

    def refuse(self, request):
        if request.url.host in LOCAL:
            raise RuntimeError("local servers are not used by these tests")
        attempts.append(f"{request.method} {request.url.host}")
        raise RealHTTPAttempted(f"a test tried a real HTTP request to {request.url.host}")

    async def refuse_async(self, request):
        refuse(self, request)

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", refuse)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse_async)
    yield attempts
    assert not attempts, f"real HTTP request attempted: {attempts}"
