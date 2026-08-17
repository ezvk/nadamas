"""Touch-control table (0xC018), READ ONLY -- and that is a measurement, not a
design choice.

⚠️ DO NOT BUILD A GESTURE EDITOR ON 0xF003. The write is accepted, the table
reads back with the new value, and the earbuds keep doing what they did before.
Measured on a Nothing Ear (3a):

    double press, action 0x08 (stock)      → AVRCP FORWARD
    double press, action 0x16 (written)    → AVRCP FORWARD   unchanged
    double press, action 0x09 (written)    → AVRCP FORWARD   unchanged

Three writes, each confirmed by reading the table back, each with no effect on
behaviour. A UI offering to remap gestures would therefore lie to the user in
the most convincing way possible: the control moves, the table agrees, and
nothing happens. Exposing the table read-only is honest; exposing the write is
not, until someone finds what makes the firmware apply it (a power cycle in the
case, a companion-app handshake, or a commit command nobody has found yet).

The same lesson in one line: on this protocol an ACK means "frame received",
never "setting applied". Verify against behaviour, not against the read-back.

WHAT THE TABLE CONTAINS. One row per (earbud, button, gesture), each carrying
the action that gesture triggers. Measured on a Nothing Ear (3a): twelve rows,
six gestures mirrored on both buds. It cannot grow either -- writing a row for
a gesture id that is not already present is acknowledged and dropped (tried
with 0x01), so the six ids are the six physical gestures the hardware has.

LABEL PROVENANCE, since the two maps below mix measured and inferred:

    gesture 0x02 → action 0x09   single press, play/pause   MEASURED (AVRCP)
    gesture 0x03 → action 0x08   double press, next track   MEASURED (AVRCP)
    gesture 0x07 → action 0x16   triple press, previous     owner-reported
    action 0x25                  noise control              owner-reported
    gesture 0x09 / 0x0b / 0x0c   inferred by elimination

⚠️ NOT EVERY ACTION SHOWS UP ON THE WIRE. Noise control is handled inside the
earbuds and emits nothing, so btmon captures stay empty for it -- an absence of
traffic is not an absence of function. Only the media actions are observable
this way (AV/C passthrough operands: 0x44 PLAY, 0x46 PAUSE, 0x4b FORWARD,
0x4c BACKWARD, 0x41/0x42 volume).
"""

# "Side", same encoding as the wear/battery entries elsewhere -- plus one the
# earbuds alone never reveal.
#
# ⚠️ 0x04 IS THE CHARGING CASE, not a third earbud. Measured on a CMF Buds
# Pro 2, whose case carries a volume dial: its table has fifteen rows against
# the Ear (3a)'s twelve, and the extra ones all sit on side 0x04. That model is
# also the only place where the `button` field stops being constant -- the case
# uses 0x01 AND 0x09, one per control, which is finally an explanation for a
# field that looks pointless on devices without a case control.
#
# Every case row carries action 0x01, so those functions look fixed rather than
# remappable. Which is moot here anyway: writes to this table do not change
# behaviour (see above).
SIDE_LEFT = 0x02
SIDE_RIGHT = 0x03
SIDE_CASE = 0x04
# 0x06 = the whole device on single-unit hardware. The Nothing Headphone (1)
# uses it in the gesture table, and also for its battery and wear entries --
# the same "type 6" that means "one unit, no left/right, no case" everywhere
# else in this protocol. Its table has three rows across two button ids.
SIDE_SINGLE = 0x06
SIDES = {
    SIDE_LEFT: "Left",
    SIDE_RIGHT: "Right",
    SIDE_CASE: "Case",
    SIDE_SINGLE: "Device",
}

# Gesture ids, in the order the device lists them.
#   0x02 / 0x03: measured on hardware (AVRCP PLAY / FORWARD respectively)
#   the rest: inferred from position and from the actions they carry
GESTURES = {
    0x02: "Single press",  # measured
    0x03: "Double press",  # measured
    0x07: "Triple press",  # inferred
    0x09: "Press and hold",  # inferred
    0x0B: "Press and hold (2)",  # inferred
    0x0C: "Other",  # inferred
}

# Action ids. Only the first two are anchored to observed AVRCP traffic.
ACTIONS = {
    0x01: "None",  # inferred
    0x08: "Next track",  # measured: emits AVRCP FORWARD
    0x09: "Play / pause",  # measured: emits AVRCP PLAY-PAUSE toggle
    0x16: "Previous track",  # owner-reported
    0x25: "Noise control",  # owner-reported; emits no AVRCP
}


def parse_table(payload: bytes) -> list[tuple[int, int, int, int]]:
    """[count][side, button, gesture, action] * count → list of tuples."""
    if len(payload) < 5:
        return []
    count = payload[0]
    rows = []
    for i in range(count):
        off = 1 + 4 * i
        if off + 4 > len(payload):
            break
        rows.append(tuple(payload[off : off + 4]))
    return rows


# Deliberately no encode_set(): see the module docstring. The frame layout is
# [0x01, side, button, gesture, action] on 0xF003 if anyone revisits this, but
# it does not change behaviour on the hardware tested.


def describe(row: tuple[int, int, int, int]) -> str:
    side, _button, gesture, action = row
    return (
        f"{SIDES.get(side, f'0x{side:02x}')}: "
        f"{GESTURES.get(gesture, f'gesture 0x{gesture:02x}')} → "
        f"{ACTIONS.get(action, f'action 0x{action:02x}')}"
    )
