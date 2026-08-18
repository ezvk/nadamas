import os
import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib, GObject

from .bluetooth import BluetoothManager, device_icon_name
from . import features
from .protocol import ANCLevel, ANCMode, EQ_PRESETS
from .traymenu import DBusMenu, MENU_PATH
from . import trayicon

_ITEM_IFACE = "org.kde.StatusNotifierItem"
_WATCHER_IFACE = "org.kde.StatusNotifierWatcher"
_WATCHER_SERVICE = "org.kde.StatusNotifierWatcher"
_ITEM_PATH = "/StatusNotifierItem"

_EMPTY_PIXMAPS = dbus.Array([], signature="(iiay)")


class _SNIItem(dbus.service.Object):
    def __init__(self, bus, service_name, on_activate):
        bus_name = dbus.service.BusName(service_name, bus)
        super().__init__(bus_name, _ITEM_PATH)
        self._on_activate = on_activate
        self._icon_name = "audio-headphones"
        self._tooltip_title = "Nadamas"
        self._tooltip_body = ""

    # ── SNI methods ────────────────────────────────────────────────────────────

    @dbus.service.method(_ITEM_IFACE, in_signature="ii")
    def Activate(self, x, y):
        GLib.idle_add(self._on_activate)

    @dbus.service.method(_ITEM_IFACE, in_signature="ii")
    def SecondaryActivate(self, x, y):
        pass

    @dbus.service.method(_ITEM_IFACE, in_signature="ii")
    def ContextMenu(self, x, y):
        pass

    @dbus.service.method(_ITEM_IFACE, in_signature="is")
    def Scroll(self, delta, orientation):
        pass

    # ── SNI signals ───────────────────────────────────────────────────────────

    @dbus.service.signal(_ITEM_IFACE)
    def NewIcon(self):
        pass

    @dbus.service.signal(_ITEM_IFACE)
    def NewToolTip(self):
        pass

    @dbus.service.signal(_ITEM_IFACE, signature="s")
    def NewStatus(self, status):
        pass

    # ── D-Bus Properties ──────────────────────────────────────────────────────

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ss", out_signature="v")
    def Get(self, interface, prop):
        return self._props()[prop]

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return self._props()

    def _props(self):
        tooltip = dbus.Struct(
            (
                dbus.String(""),
                _EMPTY_PIXMAPS,
                dbus.String(self._tooltip_title),
                dbus.String(self._tooltip_body),
            ),
            signature="sa(iiay)ss",
        )
        return {
            "Id": dbus.String("something-x"),
            "Category": dbus.String("Hardware"),
            "Title": dbus.String("Nadamas"),
            "Status": dbus.String("Active"),
            "WindowId": dbus.UInt32(0),
            "IconName": dbus.String(self._icon_name),
            # ⚠️ VOLONTAIREMENT VIDE : le bitmap dessine faisait DISPARAITRE
            # l'icone -- un hote qui voit IconPixmap le prefere a IconName et
            # n'affiche rien s'il ne sait pas le lire. Code de rendu conserve
            # dans trayicon.py.
            "IconPixmap": _EMPTY_PIXMAPS,
            "OverlayIconName": dbus.String(""),
            "OverlayIconPixmap": _EMPTY_PIXMAPS,
            "AttentionIconName": dbus.String(""),
            "AttentionIconPixmap": _EMPTY_PIXMAPS,
            "AttentionMovieName": dbus.String(""),
            "ToolTip": tooltip,
            "ItemIsMenu": dbus.Boolean(False),
            # ⚠️ A SEPARATE OBJECT, NOT _ITEM_PATH. Hosts fetch this path and
            # call com.canonical.dbusmenu on it; pointing it back at the item
            # yields an empty popup ("no menu items") because the item does not
            # implement that interface.
            "Menu": dbus.ObjectPath(MENU_PATH),
        }

    # ── update helpers ────────────────────────────────────────────────────────

    def set_icon(self, icon_name: str):
        if icon_name != self._icon_name:
            self._icon_name = icon_name
            self.NewIcon()

    def set_connected(self, connected: bool):
        """Recolour the icon. Redrawn only on a real change -- NewIcon makes
        every host refetch the bitmaps, and some redraw the whole tray."""
        if connected == self._connected:
            return
        self._connected = connected
        self._pixmaps = trayicon.pixmaps(connected)
        self.NewIcon()

    def set_tooltip(self, title: str, body: str):
        self._tooltip_title = title
        self._tooltip_body = body
        self.NewToolTip()


class NadamasTray(GObject.Object):
    """StatusNotifierItem tray icon. Shows battery on hover; icon adapts to device type."""

    def __init__(
        self,
        bt_manager: BluetoothManager,
        on_show_window,
        nothing_devices=None,
        on_quit=None,
    ):
        super().__init__()
        self._bt = bt_manager
        self._on_show = on_show_window
        # Callable returning {device-path: NothingDevice}. The tray does not own
        # these -- the window does, and it holds the single RFCOMM connection the
        # earbuds allow. Sharing the live objects is what lets the menu act on
        # the device without opening a second channel (which would fail with
        # "Device or resource busy").
        self._nothing_devices = nothing_devices or (lambda: {})
        self._on_quit = on_quit
        self._item: _SNIItem | None = None
        self._menu: DBusMenu | None = None
        self._setup()
        bt_manager.connect("devices-changed", self._on_devices_changed)

    # ── menu contents ─────────────────────────────────────────────────────────

    def _menu_items(self):
        """Rebuilt each time the host is about to draw the menu."""
        items = []
        by_path = self._nothing_devices()
        for bt_dev in self._bt.get_nothing_devices():
            if not bt_dev.connected:
                continue
            nd = by_path.get(bt_dev.path)
            if nd is None:
                continue
            title = bt_dev.name
            if bt_dev.battery is not None:
                title = f"{title} — {bt_dev.battery}%"
            items.append({"label": title, "enabled": False})

            supported = getattr(nd.state, "supported_anc_modes", None)
            for mode in (ANCMode.OFF, ANCMode.NOISE_CANCELLATION, ANCMode.TRANSPARENCY):
                if supported is not None and mode not in supported:
                    continue
                items.append(
                    {
                        "label": f"   {ANCMode.LABELS[mode]}",
                        "toggle": "radio",
                        "checked": nd.state.anc_mode == mode,
                        # Late binding is a real hazard in a loop; bind by default arg.
                        "action": (lambda d=nd, m=mode: d.set_anc_mode(m)),
                    }
                )
                # Strength, nested under ANC only -- Off and Transparency have
                # no level, and showing one there would suggest otherwise.
                if mode == ANCMode.NOISE_CANCELLATION:
                    prof0 = getattr(nd, "model_profile", None)
                    levels = (prof0.anc_levels if prof0 and prof0.anc_levels else ANCLevel.ALL)
                    for lvl in levels:
                        if lvl not in ANCLevel.LABELS:
                            continue
                        items.append(
                            {
                                "label": f"      {ANCLevel.LABELS[lvl]}",
                                "toggle": "radio",
                                "checked": nd.state.anc_level == lvl,
                                "action": (lambda d=nd, v=lvl: d.set_anc_level(v)),
                            }
                        )

            # Equaliser presets. These are the ONLY four the protocol exposes
            # (single-byte payload on 0xF010); the Nothing X per-band equaliser
            # uses a different, undocumented command and is not available here.
            items.append({"label": "   Equaliser", "enabled": False})
            for preset in EQ_PRESETS:
                items.append(
                    {
                        "label": f"      {preset}",
                        "toggle": "radio",
                        "checked": nd.state.eq_preset == preset,
                        "action": (lambda d=nd, p=preset: d.set_eq_preset(p)),
                    }
                )
            # Declared settings, only those this model actually answered to.
            # A device that implements none of them adds nothing here.
            prof = getattr(nd, "model_profile", None)
            for feat in features.FEATURES:
                if feat.key not in nd.features or feat.write_cmd is None:
                    continue
                cur = nd.features[feat.key]
                label = prof.feature_label(feat.key, feat.label) if prof else feat.label
                if feat.kind == "choice":
                    # A profile narrows the value list to the ones that are real
                    # on this model -- the firmware ACKs the others and does
                    # nothing, which would look like a broken control.
                    choices = prof.feature_choices(feat.key, feat.choices) if prof else feat.choices
                    items.append({"label": f"   {label}", "enabled": False})
                    for val, name in choices.items():
                        items.append(
                            {
                                "label": f"      {name}",
                                "toggle": "radio",
                                "checked": cur == val,
                                "action": (lambda d=nd, k=feat.key, v=val: d.set_feature(k, v)),
                            }
                        )
                elif feat.kind == "toggle":
                    # ⚠️ PRESERVE THE SECOND BYTE ON PAIR-ENCODED SETTINGS. Bass
                    # boost reads back as [enabled, level] -- [0x00, 0x06] on a
                    # stock Ear (3a). Sending a bare 1 encodes to [0x01, 0x00],
                    # which switches it on AND resets the level to zero: the
                    # control lights up and nothing is audible, which reads as a
                    # dead command rather than as the bug it is.
                    is_pair = isinstance(cur, tuple)
                    on = cur[0] if is_pair else cur
                    nxt = (0 if on else 1, cur[1]) if is_pair else (0 if on else 1)
                    items.append(
                        {
                            "label": f"   {label}",
                            "toggle": "checkmark",
                            "checked": bool(on),
                            "action": (lambda d=nd, k=feat.key, v=nxt: d.set_feature(k, v)),
                        }
                    )

            items.append({"separator": True})

        if not items:
            items.append({"label": "No device connected", "enabled": False})
            items.append({"separator": True})

        items.append({"label": "Open Nadamas", "action": self._on_show})
        if self._on_quit:
            items.append({"label": "Quit", "action": self._on_quit})
        return items

    def _setup(self):
        try:
            dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
            bus = dbus.SessionBus()
            service_name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
            self._item = _SNIItem(bus, service_name, self._on_show)
            self._menu = DBusMenu(bus, self._menu_items)
            try:
                watcher = bus.get_object(_WATCHER_SERVICE, "/StatusNotifierWatcher")
                dbus.Interface(watcher, _WATCHER_IFACE).RegisterStatusNotifierItem(service_name)
            except dbus.exceptions.DBusException:
                pass  # watcher not running; item is still exported on the bus
        except Exception as exc:
            print(f"[tray] SNI setup failed: {exc}")

    def _on_devices_changed(self, _manager):
        # Invalidate any layout a host cached; contents are recomputed lazily.
        if self._menu:
            self._menu.refresh()
        if not self._item:
            return
        nothing_devs = self._bt.get_nothing_devices()
        connected = [d for d in nothing_devs if d.connected]
        if connected:
            dev = connected[0]
            parts = []
            if dev.battery is not None:
                parts.append(f"{dev.name}: {dev.battery}%")
            self._item.set_tooltip("Nadamas", "\n".join(parts) if parts else "Connected")
            self._item.set_icon(device_icon_name(dev))
            self._item.set_connected(True)
        else:
            # fall back to first paired Nothing device, or generic icon
            paired = nothing_devs[0] if nothing_devs else None
            icon = device_icon_name(paired) if paired else "audio-headphones"
            self._item.set_tooltip("Nadamas", "No devices connected")
            self._item.set_icon(icon)
            self._item.set_connected(False)
