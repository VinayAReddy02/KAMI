"""Node labels for every place a node appears (Round 7, N1): dashboard API, alert message and citizen bot.

    node_label("node-4")  -> "Bagayam Booster (node-4 · Ward 4)"
    node_short("node-4")  -> "4 · Bagayam"
    ward_label(4)         -> "Ward 4 (Bagayam, sensor point node-4)"     (Hindi: "वार्ड 4 (बागायम, सेंसर पॉइंट node-4)")

The node name and id come from config/nodes.json, the ward number and ward names from
data/citizen/wards_demo_fictional.json (Ward N is linked to node-N; both are fictional demo data). This module is the
only place where these strings are built; the dashboard's frontend/src/labels.ts builds the same strings from the
fields that `node_fields` adds to the API objects.
"""
from __future__ import annotations

import re
from functools import lru_cache

SEP = " · "  # a middle dot between spaces


@lru_cache(maxsize=1)
def _table() -> dict[str, dict]:
    import json

    from .. import config
    from ..citizen.data import load_wards

    wards = {w.node_id: w for w in load_wards()}
    out = {}
    for n in json.loads((config.ROOT / "config" / "nodes.json").read_text(encoding="utf-8"))["nodes"]:
        m = re.fullmatch(r"node-(\d+)", n["id"])
        w = wards.get(n["id"])
        out[n["id"]] = {"id": n["id"], "name": n["name"], "number": int(m.group(1)) if m else None,
                        "ward": w.number if w else None, "ward_name": w.name_en if w else None, "ward_name_hi": w.name_hi if w else None}
    return out


def node_info(node_id: str) -> dict | None:
    return _table().get(node_id)


def node_label(node_id: str) -> str:
    """Full label: name, id and ward. An unknown id is returned as it is."""
    n = node_info(node_id)
    if n is None:
        return node_id
    return f"{n['name']} ({n['id']}{SEP}Ward {n['ward']})" if n["ward"] is not None else f"{n['name']} ({n['id']})"


def node_short(node_id: str) -> str:
    """Short label for tight places (map marker, phone width): number and locality."""
    n = node_info(node_id)
    if n is None:
        return node_id
    place = n["ward_name"] or n["name"]
    return f"{n['number']}{SEP}{place}" if n["number"] is not None else place


def node_fields(node_id: str | None) -> dict:
    """Additive API fields for an object that names a node (Round 7): number, ward, label, short."""
    n = node_info(node_id) if node_id else None
    if n is None:
        return {"number": None, "ward": None, "label": node_id, "short": node_id}
    return {"number": n["number"], "ward": n["ward"], "ward_name": n["ward_name"], "label": node_label(node_id), "short": node_short(node_id)}


def ward_label(ward, hi: bool = False) -> str:
    """How the citizen bot names a ward: with its locality and its sensor point. `ward` is a ward number or an object
    with number, node_id, name_en and name_hi (citizen.data.Ward)."""
    if not isinstance(ward, int):
        name = ward.name_hi if hi else ward.name_en
        return f"वार्ड {ward.number} ({name}, सेंसर पॉइंट {ward.node_id})" if hi else f"Ward {ward.number} ({name}, sensor point {ward.node_id})"
    for n in _table().values():
        if n["ward"] == ward:
            if hi:
                return f"वार्ड {ward} ({n['ward_name_hi']}, सेंसर पॉइंट {n['id']})"
            return f"Ward {ward} ({n['ward_name']}, sensor point {n['id']})"
    return f"वार्ड {ward}" if hi else f"Ward {ward}"
