"""Pluggable per-model device profiles, loaded from JSON.

Adding support for another Nothing or CMF model should not require writing
Python. The 0x55 protocol is shared across the range; what differs between
models is which commands answer, which values are real, and what the controls
should be called. All three are data, so they live in JSON files.

Two sources, user first:

    ~/.config/nadamas/models/*.json      user-contributed, wins on conflict
    <package>/models/*.json                  shipped with the app

A file describes one model:

    {
      "id": "ne3a",
      "name": "Nothing Ear (3a)",
      "match": {
        "model_codes": ["90b1"],                 hex of the 0xC01C reply
        "name_patterns": ["nothing ear (3a)"]    lowercase substring, fallback
      },
      "features": {
        "codec": {"choices": {"0": "Standard (AAC/SBC)", "2": "LDAC (hi-res)"}},
        "spatial_audio": {},
        "low_latency": {"label": "Gaming mode"}
      },
      "anc_levels": [1, 2, 3],
      "notes": "free text shown in the device page"
    }

⚠️ A PROFILE NARROWS, IT DOES NOT INVENT. Runtime probing (features.probe)
remains the authority on what the device implements: a setting listed here but
silent on the wire stays hidden, because a wrong entry in a contributed file
must not produce a control that does nothing. What the profile adds is the part
probing cannot know -- that codec value 2 means LDAC on this model and value 1
is a codec it does not have, that a control deserves a clearer name, that only
three of the four ANC strengths are real.

Unknown devices are not rejected: with no profile, everything that answers is
shown with its generic label. A profile makes the UI better, never mandatory.
"""

import json
import os
from dataclasses import dataclass, field

_USER_DIR = os.path.join(
    os.getenv("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
    "nadamas",
    "models",
)
_BUILTIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")


@dataclass
class DeviceProfile:
    id: str
    name: str
    model_codes: frozenset = field(default_factory=frozenset)
    name_patterns: tuple = ()
    features: dict = field(default_factory=dict)
    anc_levels: tuple | None = None
    notes: str = ""
    source: str = ""

    def feature_label(self, key: str, default: str) -> str:
        return (self.features.get(key) or {}).get("label") or default

    def feature_choices(self, key: str, default: dict) -> dict:
        """Model-specific value labels, keys coerced from JSON strings to int."""
        raw = (self.features.get(key) or {}).get("choices")
        if not raw:
            return default
        out = {}
        for k, v in raw.items():
            try:
                out[int(k, 0) if isinstance(k, str) else int(k)] = str(v)
            except (TypeError, ValueError):
                continue
        return out or default

    def declares(self, key: str) -> bool:
        return key in self.features


def _load_file(path: str) -> DeviceProfile | None:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        # A broken contributed file must not take the app down with it.
        print(f"[models] ignoring {path}: {exc}")
        return None
    match = data.get("match") or {}
    codes = frozenset(str(c).lower().replace(" ", "") for c in match.get("model_codes") or ())
    pats = tuple(str(p).lower() for p in match.get("name_patterns") or ())
    return DeviceProfile(
        id=str(data.get("id") or os.path.splitext(os.path.basename(path))[0]),
        name=str(data.get("name") or "Unknown"),
        model_codes=codes,
        name_patterns=pats,
        features=data.get("features") or {},
        anc_levels=tuple(data.get("anc_levels")) if data.get("anc_levels") else None,
        notes=str(data.get("notes") or ""),
        source=path,
    )


def load_all() -> list[DeviceProfile]:
    """User directory last so its entries override the bundled ones by id."""
    by_id: dict[str, DeviceProfile] = {}
    for directory in (_BUILTIN_DIR, _USER_DIR):
        if not os.path.isdir(directory):
            continue
        for name in sorted(os.listdir(directory)):
            if not name.endswith(".json"):
                continue
            prof = _load_file(os.path.join(directory, name))
            if prof:
                by_id[prof.id] = prof
    return list(by_id.values())


def match(model_code: bytes | None, device_name: str = "") -> DeviceProfile | None:
    """Model code first -- it is what the device says about itself.

    The advertised Bluetooth name is only a fallback: it is user-editable in
    BlueZ, and several models share a naming pattern.
    """
    profiles = load_all()
    if model_code:
        want = model_code.hex().lower()
        for prof in profiles:
            if want in prof.model_codes:
                return prof
    lowered = (device_name or "").lower()
    if lowered:
        for prof in profiles:
            for pat in prof.name_patterns:
                if pat in lowered:
                    return prof
    return None
