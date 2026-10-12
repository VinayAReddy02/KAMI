"""Make real alert sending impossible for the current process (used by test servers, checks and measurements).

After `lock_to_dry_run()` the settings loader reads a file that does not exist (a filled-in .env is ignored), the
alert-push settings are gone from the environment, the dry-run log and state go to a temporary folder, and every HTTP
request from this process to another machine is refused. Requests to 127.0.0.1 (the local API) still work.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .settings import CHAT, ENABLE, TOKEN

LOCAL_HOSTS = ("127.0.0.1", "localhost")
refused: list[str] = []  # hosts of refused requests, for callers that want to assert that nothing tried to get out
_locked = False


def lock_to_dry_run() -> Path:
    """Returns the temporary notification folder."""
    global _locked
    tmp = Path(tempfile.mkdtemp(prefix="kami_dryrun_"))
    for k in (TOKEN, CHAT, ENABLE):
        os.environ.pop(k, None)
    os.environ["KAMI_NOTIFY_ENV_FILE"] = str(tmp / "no_such.env")
    os.environ["KAMI_NOTIFY_DIR"] = str(tmp / "notifications")
    if not _locked:
        import httpx

        real = httpx.HTTPTransport.handle_request

        def local_only(self, request):
            if request.url.host not in LOCAL_HOSTS:
                refused.append(request.url.host)
                raise RuntimeError("this process refuses HTTP requests that leave the machine")
            return real(self, request)

        httpx.HTTPTransport.handle_request = local_only
        _locked = True
    return tmp / "notifications"
