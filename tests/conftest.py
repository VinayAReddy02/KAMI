"""Whole test suite: alert push can never use real credentials or write into the repository.

The settings loader is pointed at a file that does not exist (a filled-in .env is not read), every credential is
removed from the environment of the test process, and dry-run logs go to a temporary folder.
"""
import os
import tempfile

for _k in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_WHATSAPP_FROM", "WHATSAPP_TO", "KAMI_WHATSAPP_ENABLE", "WHATSAPP_MAX_TOTAL"):
    os.environ.pop(_k, None)
_tmp = tempfile.mkdtemp(prefix="kami_tests_notify_")
os.environ["KAMI_NOTIFY_ENV_FILE"] = os.path.join(_tmp, "no_such.env")
os.environ["KAMI_NOTIFY_DIR"] = os.path.join(_tmp, "notifications")
