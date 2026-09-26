"""Portage du correctif amont fec9aa2 (#47) : CMF Buds Pro 2 (B172).

Canal : préférer celui qui parle 0x55. EQ : modes d'écoute déclarés par le profil
cpb2.json (0xF01D / 0xC050), courbe Custom (0xF041 / 0xC044), et restauration
différée tant que le code du modèle (0xC01C) n'est pas arrivé.
"""

from unittest.mock import MagicMock

from nadamas import models, protocol
from nadamas.protocol import (
    NothingDevice,
    _CMD_SET_EQ,
    _CMD_SET_LISTENING_MODE,
    _CMD_SET_CUSTOM_EQ,
    _CMD_LISTENING_MODE,
    _CMD_CUSTOM_EQ,
    _CMD_MODEL,
    _CUSTOM_EQ_TEMPLATE,
    _CUSTOM_EQ_GAIN_OFFSETS,
    _eq_float,
    _eq_float_decode,
)

CPB2 = bytes.fromhex("87b1")  # code modèle relu sur NOS Buds Pro 2 (cpb2.json)
NE3A = bytes.fromhex("90b1")  # Ear (3a)


def _dev(mock_profiles=None):
    d = NothingDevice.__new__(NothingDevice)
    NothingDevice.__init__(d, "AA:BB:CC:DD:EE:FF", "CMF Buds Pro 2")
    d._x55_send = MagicMock()
    d._activated = True
    d.emit = MagicMock()
    return d


def _sent(d):
    return [(c.args[0], c.args[1] if len(c.args) > 1 else b"") for c in d._x55_send.call_args_list]


# ── profil ────────────────────────────────────────────────────────────────────


def test_cpb2_profile_declares_listening_modes():
    prof = models.match(CPB2)
    assert prof is not None and prof.id == "cpb2"
    assert prof.uses_listening_mode
    assert prof.eq_presets({})["Custom"] == 6


def test_ear3a_profile_keeps_ear_presets():
    prof = models.match(NE3A)
    assert prof is not None and not prof.uses_listening_mode
    assert prof.eq_presets(protocol.EQ_PRESETS) == protocol.EQ_PRESETS


# ── envoi du préréglage ───────────────────────────────────────────────────────


def test_buds_pro_2_uses_listening_mode_command(mock_profiles):
    d = _dev()
    d._dispatch_x55(_CMD_MODEL, CPB2)
    d._x55_send.reset_mock()
    d.set_eq_preset("Rock")
    assert _sent(d) == [(_CMD_SET_LISTENING_MODE, bytes([1, 0x00]))]


def test_ear_still_uses_eq_command(mock_profiles):
    """Témoin : sans le profil CMF, rien ne change pour les Ear."""
    d = _dev()
    d._dispatch_x55(_CMD_MODEL, NE3A)
    d._x55_send.reset_mock()
    d.set_eq_preset("More Bass")
    assert _sent(d) == [(_CMD_SET_EQ, bytes([1]))]


def test_stale_ear_preset_is_not_sent_to_buds_pro_2(mock_profiles):
    d = _dev()
    d._dispatch_x55(_CMD_MODEL, CPB2)
    d._x55_send.reset_mock()
    d.set_eq_preset("More Bass")
    assert _sent(d) == []


def test_model_reply_queries_listening_mode_and_curve(mock_profiles):
    d = _dev()
    d._dispatch_x55(_CMD_MODEL, CPB2)
    cmds = [c for c, _ in _sent(d)]
    assert _CMD_LISTENING_MODE in cmds and _CMD_CUSTOM_EQ in cmds


# ── restauration différée ─────────────────────────────────────────────────────


def test_restore_waits_for_model_then_uses_listening_mode(mock_profiles):
    protocol_profiles = __import__("nadamas.profiles", fromlist=["load"])
    protocol_profiles.load.return_value = {"eq": "Classical"}
    d = _dev()
    d._restore_profile()
    assert _sent(d) == [], "rien ne doit partir avant le code du modèle"
    d._dispatch_x55(_CMD_MODEL, CPB2)
    assert (_CMD_SET_LISTENING_MODE, bytes([5, 0x00])) in _sent(d)
    assert all(c != _CMD_SET_EQ for c, _ in _sent(d))


def test_restore_after_model_is_immediate(mock_profiles):
    protocol_profiles = __import__("nadamas.profiles", fromlist=["load"])
    protocol_profiles.load.return_value = {"eq": "Voice"}
    d = _dev()
    d._dispatch_x55(_CMD_MODEL, NE3A)
    d._x55_send.reset_mock()
    d._restore_profile()
    assert _sent(d) == [(_CMD_SET_EQ, bytes([3]))]


# ── lecture du mode et de la courbe ───────────────────────────────────────────


def test_listening_mode_reply_updates_state(mock_profiles):
    d = _dev()
    d._dispatch_x55(_CMD_MODEL, CPB2)
    d._dispatch_x55(_CMD_LISTENING_MODE, bytes([2]))
    assert d.state.eq_preset == "Electronic"


def test_empty_listening_mode_reply_is_not_a_value(mock_profiles):
    """Les Buds Pro 2 répondent VIDE à ce qu'ils ne gèrent pas (cpb2.json)."""
    d = _dev()
    d._dispatch_x55(_CMD_MODEL, CPB2)
    d.state.eq_preset = "Pop"
    d._dispatch_x55(_CMD_LISTENING_MODE, b"")
    assert d.state.eq_preset == "Pop"


def test_custom_curve_roundtrip(mock_profiles):
    d = _dev()
    d._dispatch_x55(_CMD_MODEL, CPB2)
    d._x55_send.reset_mock()
    d.set_custom_eq(4, -3, 2)
    ((cmd, payload),) = _sent(d)
    assert cmd == _CMD_SET_CUSTOM_EQ and len(payload) == len(_CUSTOM_EQ_TEMPLATE)
    mid, treble, bass = (_eq_float_decode(payload[o : o + 4]) for o in _CUSTOM_EQ_GAIN_OFFSETS)
    assert (bass, mid, treble) == (4.0, -3.0, 2.0)
    d2 = _dev()
    d2._dispatch_x55(_CMD_MODEL, CPB2)
    d2._dispatch_x55(_CMD_CUSTOM_EQ, payload)
    assert d2.state.custom_eq == (4, -3, 2)


def test_custom_curve_clamped_to_range(mock_profiles):
    d = _dev()
    d.set_custom_eq(20, -20, 0)
    assert d.state.custom_eq == (6, -6, 0)


def test_preamp_is_negative_zero_for_non_positive_headroom():
    assert _eq_float(0.0, preamp=True) == bytes([0, 0, 0, 0x80])


# ── choix du canal ────────────────────────────────────────────────────────────


def _sock():
    s = MagicMock()
    return s


def test_prefers_0x55_channel_over_earlier_legacy_one():
    d = _dev()
    legacy, good = _sock(), _sock()
    replies = {3: (legacy, bytes([0x03, 0x01])), 15: (good, bytes([0x55, 0x00]))}
    d._try_channel = lambda ch: replies.get(ch)
    sock, initial, ch = d._select_channel([3, 15])
    assert ch == 15 and sock is good
    legacy.close.assert_called_once()


def test_legacy_channel_kept_as_fallback():
    d = _dev()
    legacy = _sock()
    d._try_channel = lambda ch: (legacy, bytes([0x03])) if ch == 17 else None
    assert d._select_channel([15, 17, 16])[2] == 17


def test_witness_old_behaviour_would_take_legacy_first():
    """Témoin : avec l'ancien parcours (premier qui répond), ch3 aurait gagné."""
    replies = {3: bytes([0x03]), 15: bytes([0x55])}
    first = next(ch for ch in [3, 15] if ch in replies)
    assert first == 3
