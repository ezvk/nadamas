"""com.canonical.dbusmenu implementation for the tray icon.

The StatusNotifierItem spec has no menu of its own: the `Menu` property points
at a SEPARATE object that must speak com.canonical.dbusmenu. Pointing it at the
item's own path (as the tray did before) makes hosts render an empty popup --
"no menu items" in most panels.

Only the subset hosts actually call is implemented: GetLayout, GetGroupProperties,
GetProperty, Event, EventGroup, AboutToShow, AboutToShowGroup, plus the
LayoutUpdated signal used to invalidate a cached layout.
"""

import dbus
import dbus.service
from gi.repository import GLib

MENU_IFACE = "com.canonical.dbusmenu"
MENU_PATH = "/MenuBar"

# Root is always id 0 per the spec; children start above it.
_ROOT_ID = 0


def _struct(id_, props, children):
    """One dbusmenu node: (id, properties, children-as-variants)."""
    kids = dbus.Array(
        [dbus.Struct(c, signature="ia{sv}av", variant_level=1) for c in children],
        signature="v",
    )
    return (dbus.Int32(id_), dbus.Dictionary(props, signature="sv"), kids)


class DBusMenu(dbus.service.Object):
    """Serves a menu whose contents are supplied by a callback.

    `build_items()` returns a flat list of dicts, each either
      {"label": str, "enabled": bool, "action": callable|None,
       "toggle": "radio"|"checkmark"|None, "checked": bool}
    or {"separator": True}.
    Rebuilding on demand keeps the menu honest: hosts call AboutToShow right
    before drawing, so battery levels and the active ANC mode are read then
    rather than cached from whenever the tray last happened to update.
    """

    def __init__(self, bus, build_items):
        super().__init__(bus, MENU_PATH)
        self._build_items = build_items
        self._revision = 1
        self._actions: dict[int, callable] = {}
        # id -> properties, and id -> ordered child ids. Two maps rather than a
        # nested structure so GetGroupProperties stays a flat lookup.
        self._nodes: dict[int, dict] = {}
        self._children: dict[int, list] = {}
        self._next_id = 1
        self._rebuild()

    # ── construction ──────────────────────────────────────────────────────────

    def _rebuild(self):
        """Recompute the tree and the id -> action map.

        ⚠️ NESTED, NOT INDENTED. An earlier version returned one flat list and
        faked hierarchy with leading spaces; that degrades badly as soon as two
        devices are connected, and it is not what hosts expect. dbusmenu carries
        real submenus: a node advertises `children-display = "submenu"` and its
        children ride in the variant array of GetLayout.
        """
        self._actions.clear()
        self._nodes.clear()
        self._children.clear()
        self._next_id = 1
        self._children[_ROOT_ID] = self._add_items(self._build_items())

    def _add_items(self, specs) -> list:
        """Register one level, returning the ids of its entries."""
        ids = []
        for spec in specs:
            nid = self._next_id
            self._next_id += 1
            ids.append(nid)
            if spec.get("separator"):
                self._nodes[nid] = {"type": dbus.String("separator")}
                continue
            props = {
                "label": dbus.String(spec.get("label", "")),
                "enabled": dbus.Boolean(spec.get("enabled", True)),
                "visible": dbus.Boolean(True),
            }
            toggle = spec.get("toggle")
            if toggle:
                props["toggle-type"] = dbus.String(toggle)
                props["toggle-state"] = dbus.Int32(1 if spec.get("checked") else 0)
            kids = spec.get("children")
            if kids:
                props["children-display"] = dbus.String("submenu")
                self._nodes[nid] = props
                self._children[nid] = self._add_items(kids)
                continue
            self._nodes[nid] = props
            if spec.get("action"):
                self._actions[nid] = spec["action"]
        return ids

    def refresh(self):
        """Rebuild and tell hosts to discard their cached layout."""
        self._rebuild()
        self._revision += 1
        self.LayoutUpdated(dbus.UInt32(self._revision), dbus.Int32(_ROOT_ID))

    def _node(self, nid: int, depth: int):
        """One node and, within the requested depth, its children."""
        props = dict(self._nodes.get(nid, {}))
        kids = []
        if depth != 0:
            for cid in self._children.get(nid, []):
                kids.append(self._node(cid, depth - 1))
        return _struct(nid, props, kids)

    # ── dbusmenu methods ──────────────────────────────────────────────────────

    @dbus.service.method(MENU_IFACE, in_signature="iias", out_signature="u(ia{sv}av)")
    def GetLayout(self, parentId, recursionDepth, propertyNames):
        # recursionDepth -1 means "everything"; hosts commonly ask for that.
        pid = int(parentId)
        if pid == _ROOT_ID:
            kids = [self._node(c, recursionDepth - 1) for c in self._children.get(_ROOT_ID, [])]
            root = _struct(_ROOT_ID, {"children-display": dbus.String("submenu")}, kids)
            return dbus.UInt32(self._revision), root
        return dbus.UInt32(self._revision), self._node(pid, recursionDepth)

    @dbus.service.method(MENU_IFACE, in_signature="aias", out_signature="a(ia{sv})")
    def GetGroupProperties(self, ids, propertyNames):
        wanted = set(int(i) for i in ids)
        return dbus.Array(
            [
                dbus.Struct((dbus.Int32(i), dbus.Dictionary(p, signature="sv")), signature="ia{sv}")
                for i, p in self._nodes.items()
                if not wanted or i in wanted
            ],
            signature="(ia{sv})",
        )

    @dbus.service.method(MENU_IFACE, in_signature="is", out_signature="v")
    def GetProperty(self, id, name):
        return self._nodes.get(int(id), {}).get(name, dbus.String(""))

    @dbus.service.method(MENU_IFACE, in_signature="isvu")
    def Event(self, id, eventId, data, timestamp):
        if eventId != "clicked":
            return
        action = self._actions.get(int(id))
        if action:
            # Return to the host promptly; the action may talk to the device.
            GLib.idle_add(action)

    @dbus.service.method(MENU_IFACE, in_signature="a(isvu)", out_signature="ai")
    def EventGroup(self, events):
        for id_, eventId, data, timestamp in events:
            self.Event(id_, eventId, data, timestamp)
        return dbus.Array([], signature="i")

    @dbus.service.method(MENU_IFACE, in_signature="i", out_signature="b")
    def AboutToShow(self, id):
        # ⚠️ ONLY THE ROOT REBUILDS. Rebuilding when a submenu is about to open
        # renumbers every id, including the one the host is in the middle of
        # opening -- the submenu then draws empty.
        if int(id) == _ROOT_ID:
            self.refresh()
        return dbus.Boolean(True)

    @dbus.service.method(MENU_IFACE, in_signature="ai", out_signature="aiai")
    def AboutToShowGroup(self, ids):
        self.refresh()
        return dbus.Array([], signature="i"), dbus.Array([], signature="i")

    # ── signals ───────────────────────────────────────────────────────────────

    @dbus.service.signal(MENU_IFACE, signature="ui")
    def LayoutUpdated(self, revision, parent):
        pass

    @dbus.service.signal(MENU_IFACE, signature="a(ia{sv})a(ias)")
    def ItemsPropertiesUpdated(self, updatedProps, removedProps):
        pass

    # ── properties ────────────────────────────────────────────────────────────

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="ss", out_signature="v")
    def Get(self, interface, prop):
        return self._props().get(prop, dbus.String(""))

    @dbus.service.method(dbus.PROPERTIES_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        return self._props()

    def _props(self):
        return dbus.Dictionary(
            {
                "Version": dbus.UInt32(3),
                "Status": dbus.String("normal"),
                "TextDirection": dbus.String("ltr"),
                "IconThemePath": dbus.Array([], signature="s"),
            },
            signature="sv",
        )
