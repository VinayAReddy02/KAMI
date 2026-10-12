"""Pipe-damage tickets: a photo plus a location becomes a complaint linked to the nearest sensor node.

Nothing here looks at what the photo shows: there is no image recognition. The photo is checked only for its type and
size, stored for staff, and a small copy without metadata is made for the dashboard.

Location: a Telegram location message, or the GPS position in the EXIF data of a photo that was sent as a file
(Telegram removes EXIF from photos sent the normal way). A photo without a location is kept in memory for 10 minutes
while the citizen is asked for the location, and the other way round. A ticket stores no chat id and no name.
"""
from __future__ import annotations

import io
import math
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

MAX_PHOTO_BYTES = 10 * 1024 * 1024
FORMATS = {"JPEG": ".jpg", "PNG": ".png"}
DEMO_RADIUS_KM = 3.0
PENDING_SECONDS = 600.0
THUMB_PX = 360


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    return 2 * 6371.0088 * math.asin(math.sqrt(a))


def valid_position(lat, lon) -> bool:
    return (isinstance(lat, (int, float)) and isinstance(lon, (int, float)) and not isinstance(lat, bool) and not isinstance(lon, bool)
            and math.isfinite(lat) and math.isfinite(lon) and -90 <= lat <= 90 and -180 <= lon <= 180 and not (lat == 0 and lon == 0))


def inspect_photo(data: bytes) -> tuple[str, tuple[float, float] | None, bytes] | None:
    """(file extension, GPS position from EXIF or None, small JPEG copy without metadata), or None if this is not a
    JPEG or PNG image."""
    from PIL import Image, ImageOps

    try:
        with Image.open(io.BytesIO(data)) as im:
            fmt = im.format
            if fmt not in FORMATS:
                return None
            gps = _exif_gps(im)
            im = ImageOps.exif_transpose(im).convert("RGB")
            im.thumbnail((THUMB_PX, THUMB_PX))
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=80)  # a fresh image: no EXIF, no location, no camera data
            return FORMATS[fmt], gps, buf.getvalue()
    except Exception:
        return None


def _exif_gps(im) -> tuple[float, float] | None:
    try:
        gps = im.getexif().get_ifd(0x8825)
        lat, lon = _degrees(gps[2], gps.get(1, "N")), _degrees(gps[4], gps.get(3, "E"))
    except Exception:
        return None
    return (lat, lon) if valid_position(lat, lon) else None


def _degrees(dms, ref) -> float:
    d, m, s = (float(x) for x in dms)
    v = d + m / 60 + s / 3600
    return -v if str(ref).upper() in ("S", "W") else v


@dataclass
class Outcome:
    kind: str  # ticket | need_location | need_photo | rejected
    ticket: dict | None = None
    reason: str = ""  # rejected: too_big | not_an_image | bad_location


class TicketService:
    def __init__(self, store, nodes: list[dict], uploads: Path, node_state=lambda node_id: None, replay_ts=lambda: None, clock=time.time):
        self.store, self.nodes, self.uploads = store, nodes, Path(uploads)
        self.node_state, self.replay_ts, self.clock = node_state, replay_ts, clock
        self._pending: dict = {}  # chat key -> ("photo", time, data, ext, thumb) or ("location", time, lat, lon); memory only
        self._lock = threading.Lock()

    # ----------------------------------------------------------- inputs
    def add_photo(self, chat_key, data: bytes, source: str = "telegram") -> Outcome:
        if len(data) > MAX_PHOTO_BYTES:
            return Outcome("rejected", reason="too_big")
        info = inspect_photo(data)
        if info is None:
            return Outcome("rejected", reason="not_an_image")
        ext, gps, thumb = info
        with self._lock:
            self._purge()
            waiting = self._pending.get(chat_key)
            if gps is not None:
                self._pending.pop(chat_key, None)
                return Outcome("ticket", self._create(data, ext, thumb, gps[0], gps[1], "photo_exif", source))
            if waiting and waiting[0] == "location":
                self._pending.pop(chat_key)
                return Outcome("ticket", self._create(data, ext, thumb, waiting[2], waiting[3], "telegram_location", source))
            self._pending[chat_key] = ("photo", self.clock(), data, ext, thumb)
            return Outcome("need_location")

    def add_location(self, chat_key, lat, lon, source: str = "telegram") -> Outcome:
        if not valid_position(lat, lon):
            return Outcome("rejected", reason="bad_location")
        with self._lock:
            self._purge()
            waiting = self._pending.get(chat_key)
            if waiting and waiting[0] == "photo":
                self._pending.pop(chat_key)
                return Outcome("ticket", self._create(waiting[2], waiting[3], waiting[4], float(lat), float(lon), "telegram_location", source))
            self._pending[chat_key] = ("location", self.clock(), float(lat), float(lon))
            return Outcome("need_photo")

    def pending_count(self) -> int:
        with self._lock:
            self._purge()
            return len(self._pending)

    # ----------------------------------------------------------- internals
    def _purge(self) -> None:
        now = self.clock()
        for k in [k for k, v in self._pending.items() if now - v[1] > PENDING_SECONDS]:
            del self._pending[k]

    def nearest(self, lat: float, lon: float) -> tuple[dict, float]:
        return min(((n, haversine_km(lat, lon, n["lat"], n["lon"])) for n in self.nodes), key=lambda x: x[1])

    def _create(self, data: bytes, ext: str, thumb: bytes, lat: float, lon: float, location_source: str, source: str) -> dict:
        node, km = self.nearest(lat, lon)
        inside = km <= DEMO_RADIUS_KM
        try:
            s = self.node_state(node["id"]) if inside else None
        except Exception:
            s = None
        known = isinstance(s, dict) and s.get("category") and s.get("status") != "warming_up"
        name = uuid.uuid4().hex
        self.uploads.mkdir(parents=True, exist_ok=True)
        (self.uploads / f"{name}{ext}").write_bytes(data)
        (self.uploads / f"{name}_thumb.jpg").write_bytes(thumb)
        ticket = {"created_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "replay_ts": self.replay_ts(),
                  "lat": round(lat, 5), "lon": round(lon, 5), "location_source": location_source,
                  "node_id": node["id"] if inside else None, "node_name": node["name"] if inside else None,
                  "nearest_node_id": node["id"], "nearest_node_name": node["name"], "distance_km": round(km, 2), "in_demo_area": inside,
                  "node_category": s["category"] if known else None, "node_priority": s["priority"] if known else None,
                  "status": "open", "source": source, "photo_file": f"{name}{ext}", "thumb_file": f"{name}_thumb.jpg",
                  "photo_analysed": False}
        ticket["id"] = self.store.write_complaint(ticket)
        return ticket


def public_view(t: dict) -> dict:
    """A ticket as the API and the dashboard see it: no file names, a link to the small copy instead."""
    out = {k: v for k, v in t.items() if k not in ("photo_file", "thumb_file")}
    out["thumb_url"] = f"/complaints/{t['id']}/thumb"
    return out
