"""Declarative registry of device settings.

Why a registry rather than one method per setting: the 0x55 protocol is shared
across the whole Nothing/CMF range, but any given model implements only part of
it. Probing a Nothing Ear (3a) shows 26 of the query commands answering and the
rest staying silent -- including `advanced custom EQ` (0xC06C/0xC06D) and the
whole Mimi personalised-audio group (0xC022-0xC025), which exist on other
models. Hard-coding a UI for the union of all models produces controls that do
nothing on most of them; hard-coding it for one model loses the others.

So each setting is declared once, with its read command, its write command and
how to encode/decode the payload. `probe()` asks the device which of them answer
and the UI is built from that answer. A model that gains a feature in firmware
picks it up with no code change.

Command IDs come from the protocol table in `chukfinley/nada` (docs/PROTOCOL.md)
except where noted, and every value below was read back from real hardware.

⚠️ A SETTING IS ONLY "SUPPORTED" IF ITS EFFECT WAS OBSERVED. Reading a value
back proves the device stored it, nothing more -- the gesture table (see
gestures.py) accepts writes, reports them faithfully, and changes no behaviour
whatsoever. Everything exposed here was therefore checked against something
observable, and the evidence is named per feature below rather than assumed.

Verified on a Nothing Ear (3a), firmware 1.0.1.65:

    codec           A third A2DP endpoint appears/disappears (vendor 0x012d)
    ANC on/off      audible
    ANC strength    audible, High vs Low; FOUR levels exist (1-4), the
                    fourth being Adaptive -- upstream ships only three
    ANC mode field  swept 0x00-0x0f: exactly six values are accepted
                    (0x01-0x05 and 0x07), the rest leave the mode
                    unchanged. Six accepted values, six user-facing
                    states -- the mapping is forced by counting:
                    1/2/3/4 = ANC High/Mid/Low/Adaptive, 5 = Off,
                    7 = Transparency
    EQ presets      audible, More Bass vs More Treble
    spatial audio   audible, stereo image widens
    bass boost      audible, markedly muffled at level 6
    low latency     MEASURED: sink latency 276.7 ms → 186.7 ms, codec unchanged

    auto-pause      verified end to end on a CMF Buds Pro 2: the wear byte
                    goes 0x8c -> 0x8a on removal (bit 2) and back, and
                    playback now stops and resumes with it

    dual connection not yet verified -- needs a second host
    gestures        REFUTED, see gestures.py; deliberately not writable here
"""

from collections.abc import Callable
from dataclasses import dataclass, field

# ── payload codecs ────────────────────────────────────────────────────────────


def _u8(payload: bytes) -> int:
    return payload[0] if payload else 0


def _u8_out(value: int) -> bytes:
    return bytes([value & 0xFF])


def _pair(payload: bytes):
    """One byte in, one byte out; two in, two out.

    ⚠️ THE WIDTH MUST SURVIVE THE ROUND TRIP. The same setting is not the same
    width on every model: spatial audio reads back as `01 00` on a Nothing
    Ear (3a) and as a bare `00` on a CMF Buds Pro 2. Always returning a pair
    means always writing two bytes, and a device that expects one acknowledges
    the frame and ignores it -- the control flips in the menu and the setting
    does not stick, with nothing logged anywhere.

    So the decoder mirrors what it was given, and the encoder mirrors that.
    """
    if not payload:
        return 0
    if len(payload) == 1:
        return payload[0]
    return (payload[0], payload[1])


def _pair_out(value) -> bytes:
    if isinstance(value, (tuple, list)):
        return bytes([value[0] & 0xFF, value[1] & 0xFF])
    return bytes([value & 0xFF])


@dataclass(frozen=True)
class Feature:
    key: str
    label: str
    read_cmd: int
    write_cmd: int | None = None
    # "choice": pick one of `choices`; "toggle": on/off; "info": read-only.
    kind: str = "toggle"
    choices: dict[int, str] = field(default_factory=dict)
    decode: Callable[[bytes], object] = _u8
    encode: Callable[[object], bytes] = _u8_out
    # Free-text note surfaced in the UI when the setting has a non-obvious cost.
    note: str = ""


# ── the registry ──────────────────────────────────────────────────────────────

FEATURES: tuple[Feature, ...] = (
    # ⚠️ THE CODEC SELECTOR IS NOT A BOOLEAN, and that matters more than it
    # looks. nada documents 0xC029/0xF01C as "LHDC codec | [on]", which reads as
    # on/off -- writing 1 is then the obvious thing to do, and it is wrong on a
    # device whose hi-res codec is LDAC. Measured on a Nothing Ear (3a):
    #
    #     0x00  standard (SBC + AAC only)
    #     0x01  LHDC   -- accepted and stored, no endpoint appears on this model
    #     0x02  LDAC   -- a third A2DP endpoint appears, vendor 0x012d (Sony)
    #     0x03  accepted and stored, no endpoint on this model
    #
    # The device ACKs every value, including ones its hardware cannot honour,
    # then drops the RFCOMM link to renegotiate. So "the write succeeded" says
    # nothing; the only proof is a new endpoint in the A2DP discovery, visible
    # as an extra `sepN` object under the BlueZ device path.
    #
    # This is the single most valuable setting here: on iOS the Nothing X app
    # does not expose it at all, so an owner without an Android device has no
    # way to turn hi-res on. Now they do.
    Feature(
        key="codec",
        label="Audio codec",
        read_cmd=0xC029,
        write_cmd=0xF01C,
        kind="choice",
        choices={0x00: "Standard (AAC/SBC)", 0x01: "LHDC", 0x02: "LDAC (hi-res)", 0x03: "Alt"},
        note="Reconnect after changing: the codec set is fixed at A2DP negotiation.",
    ),
    Feature(
        key="low_latency",
        label="Low latency mode",
        read_cmd=0xC041,
        write_cmd=0xF040,
        kind="choice",
        choices={0x01: "On", 0x02: "Off"},
        # ⚠️ NOT exclusive with LDAC on the Ear (3a), contrary to the usual
        # claim: enabling it left the codec on ldac and cut the sink latency
        # from 276.7 ms to 186.7 ms. Verify per model rather than assuming.
        note="Cuts output latency; on the Ear (3a) it keeps the hi-res codec.",
    ),
    Feature(
        key="dual_connection",
        label="Dual connection",
        read_cmd=0xC027,
        write_cmd=0xF01A,
        kind="toggle",
        note="Usually mutually exclusive with the hi-res codec.",
    ),
    Feature(
        key="spatial_audio",
        label="Spatial audio",
        read_cmd=0xC04F,
        write_cmd=0xF052,
        kind="toggle",
        decode=_pair,
        encode=_pair_out,
    ),
    Feature(
        key="bass_boost",
        label="Bass boost",
        read_cmd=0xC04E,
        write_cmd=0xF051,
        kind="toggle",
        decode=_pair,
        encode=_pair_out,
    ),
    # Present on models that carry them; silent on the Ear (3a). Declared so the
    # UI picks them up automatically wherever they do answer.
    Feature(key="detail_enhancement", label="Detail enhancement", read_cmd=0xC069, write_cmd=0xF069),
    Feature(key="smart_anc", label="Adaptive ANC", read_cmd=0xC055, write_cmd=0xF059),
    Feature(key="smart_free", label="Smart Free", read_cmd=0xC054, write_cmd=0xF058),
    Feature(key="mimi", label="Personalised audio", read_cmd=0xC022, write_cmd=0xF015),
    Feature(
        key="mimi_intensity",
        label="Personalisation intensity",
        read_cmd=0xC023,
        write_cmd=0xF016,
        kind="choice",
        choices={0: "Low", 1: "Mid", 2: "High"},
    ),
    # Read-only signals worth surfacing rather than hiding.
    Feature(key="exclusive_set", label="Mutually exclusive set", read_cmd=0xC062, kind="info"),
)

BY_KEY = {f.key: f for f in FEATURES}


def probe(send, recv) -> dict[str, object]:
    """Ask the device which settings it implements.

    `send(cmd)` writes a query frame, `recv()` returns [(cmd, payload), ...].
    Returns {key: decoded value} holding only the features that answered --
    silence is the device saying "not supported", which is how it reports the
    difference between models.
    """
    found: dict[str, object] = {}
    for feat in FEATURES:
        send(feat.read_cmd)
        for cmd, payload in recv():
            if cmd & 0x7FFF == feat.read_cmd & 0x7FFF and payload:
                found[feat.key] = feat.decode(payload)
                break
    return found
