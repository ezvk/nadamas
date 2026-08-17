# nadamas

Control Nothing and CMF earbuds from Linux — including the settings the phone
app keeps to itself.

The headline: **it can turn LDAC on**. The Nothing X app does not expose the
hi-res codec switch on iOS at all, so an owner without an Android phone has no
way to enable it. This does, over the same RFCOMM protocol the phone uses.

---

## Credit where it is due

nadamas is a fork of **[SoaOaoS/something-x](https://github.com/SoaOaoS/something-x)**
(MIT). The GTK4 application, the 0x55 frame handling, the channel discovery and
most of the device logic are that project's work. If you only need ANC, battery
and EQ presets, use it directly — it is excellent and this fork exists for a
narrower reason.

The protocol command table comes from **[chukfinley/nada](https://github.com/chukfinley/nada)**
(MIT), whose `docs/PROTOCOL.md` documents the 0x55 commands verified against
real hardware. Several corrections below are refinements of that table, not
replacements for it — without it none of this would have been findable.

The name is a nod to both: *nada más*.

---

## What this fork adds

**A system-tray menu that exists.** Upstream shows "no menu items" on every
panel: the StatusNotifierItem `Menu` property pointed at the icon's own object,
which does not implement `com.canonical.dbusmenu`. There is now a real dbusmenu
server, rebuilt each time the menu opens so battery and current state are read
at that moment.

**The three ANC strengths.** Upstream reads the strength the device reports and
stores it, then sends `STRONG` unconditionally — so Mid and Low could be seen
and never set. They are selectable now.

**A codec selector.** `0xC029`/`0xF01C` is documented upstream as an LHDC on/off
toggle. It is a three-value selector:

| Value | Meaning |
|---|---|
| `0x00` | standard (SBC + AAC) |
| `0x01` | LHDC |
| `0x02` | **LDAC** |

Writing `0x01` on a device whose hi-res codec is LDAC is acknowledged, stored,
and does nothing — which is exactly what makes this worth documenting.

**Pluggable per-model profiles.** `nadamas/models/*.json`, one file per model,
plus `~/.config/nadamas/models/` for your own. Adding a device is a JSON file,
not a patch. A profile *narrows* what runtime probing found; it never invents a
control, so a wrong entry cannot produce a button that does nothing.

---

## What this fork deliberately does NOT add

**Gesture remapping.** The touch table (`0xC018`) is readable and `0xF003`
accepts writes — the table even reads back with the new value. The earbuds keep
doing what they did before. Measured three times on a Nothing Ear (3a):

```
double press, action 0x08 (stock)    → AVRCP FORWARD
double press, action 0x16 (written)  → AVRCP FORWARD   unchanged
double press, action 0x09 (written)  → AVRCP FORWARD   unchanged
```

A gesture editor would therefore lie in the most convincing way available: the
control moves, the table agrees, nothing happens. The table is exposed read-only
until someone finds what makes the firmware apply it.

> **The rule this fork follows:** on this protocol an ACK means *frame
> received*, never *setting applied*. Every setting shipped here was checked
> against something observable — audible, measurable, or a change in the A2DP
> endpoint list. Anything that only reads back correctly is not enough.

---

## Verified hardware

Nothing Ear (3a), firmware 1.0.1.65 — every entry checked against an effect:

| Setting | Evidence |
|---|---|
| Codec (LDAC) | a third A2DP endpoint appears/disappears, vendor `0x012d` |
| ANC on/off | audible |
| ANC strength | audible, High vs Low |
| EQ presets | audible, More Bass vs More Treble |
| Spatial audio | audible, stereo image widens |
| Bass boost | audible, markedly muffled at level 6 |
| Low latency | measured: sink latency 276.7 ms → 186.7 ms, codec unchanged |
| Gestures | **refuted**, see above |

Not present on this model, though the protocol carries them: the advanced
per-band equaliser (`0xC06C`/`0xC06D`) and the Mimi personalised-audio group
(`0xC022`–`0xC025`). They stay silent, and the UI hides them accordingly.

Nothing Headphone (1) and CMF Buds Pro 2 ship with partially verified profiles;
what is confirmed and what is not is stated in each JSON file rather than
implied.

---

## Install

```nix
# flake.nix
inputs.nadamas.url = "github:ezvk/nadamas";

# then
environment.systemPackages = [ inputs.nadamas.packages.${system}.default ];
```

Or run it directly:

```
nix run github:ezvk/nadamas
```

---

## Adding your device

Run it, connect your earbuds, and see what appears — unknown models are not
rejected, everything that answers is shown with generic labels. To make it
nicer, drop a file in `~/.config/nadamas/models/`:

```json
{
  "id": "myphones",
  "name": "CMF Buds Pro 2",
  "match": { "model_codes": ["b172"], "name_patterns": ["cmf buds pro 2"] },
  "features": {
    "codec": { "choices": { "0": "Standard", "2": "LDAC" } },
    "spatial_audio": {}
  },
  "anc_levels": [1, 2, 3]
}
```

The model code is what the device reports on `0xC01C`; the name pattern is only
a fallback, since Bluetooth names are user-editable.

**Please send it upstream** — a pull request adding one JSON file is the most
useful contribution this project can receive. State what you verified and what
you assumed; the existing files do the same.

## Licence

MIT, as upstream. See `LICENSE`.
