"""File hashing shared by the freeze and the feature-cache check.

Text files are hashed with line endings normalised to LF, so a checkout with a different autocrlf setting does not
change the hash. Binary files are hashed as they are. Digests are memoised per (path, size, mtime) within a process.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

TEXT = {".py", ".json", ".csv", ".md", ".txt", ".yaml", ".yml", ".toml"}
_memo: dict = {}


def sha256_file(path: Path) -> str:
    path = Path(path)
    st = path.stat()
    key = (str(path.resolve()), st.st_size, st.st_mtime_ns)
    if key in _memo:
        return _memo[key]
    h = hashlib.sha256()
    if path.suffix.lower() in TEXT:
        h.update(path.read_bytes().replace(b"\r\n", b"\n"))
    else:
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
    _memo[key] = h.hexdigest()
    return _memo[key]
