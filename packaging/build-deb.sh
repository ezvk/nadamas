#!/usr/bin/env bash
# Build a .deb from a source checkout.
#
# Runs anywhere dpkg-deb exists -- it does not need a Debian machine, since a
# .deb is a file tree plus a control file. What DOES need Debian is checking
# that the declared dependencies resolve, so run `apt-get install --dry-run`
# against the result on the target release before publishing one.
#
# Deliberately not dh_make / debhelper: this package installs a pure-Python
# tree and one script. The full Debian toolchain would add a build-dependency
# on Debian itself for no gain.
set -euo pipefail

VERSION="${1:-0.1.0~alpha1}"
SRC="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${SRC}/dist"
ROOT="${OUT}/nadamas_${VERSION}_all"

rm -rf "$ROOT"
mkdir -p "$ROOT/DEBIAN" \
         "$ROOT/usr/lib/python3/dist-packages" \
         "$ROOT/usr/bin" \
         "$ROOT/usr/share/applications"

cp -r "$SRC/nadamas" "$ROOT/usr/lib/python3/dist-packages/"
find "$ROOT" -name __pycache__ -type d -exec rm -rf {} + 2>/dev/null || true

cp "$SRC/nadamas/data/io.github.ezvk.nadamas.desktop" \
   "$ROOT/usr/share/applications/"

cat > "$ROOT/usr/bin/nadamas" <<'BIN'
#!/usr/bin/python3
from nadamas.application import main

raise SystemExit(main())
BIN
chmod 755 "$ROOT/usr/bin/nadamas"

# ⚠️ DEPENDENCY NAMES ARE DEBIAN'S, NOT PyPI'S. python3-gi is PyGObject,
# python3-cairo is pycairo, and the GTK4/libadwaita typelibs come from the
# gir1.2-* packages rather than from the libraries themselves -- without them
# `gi.require_version("Gtk", "4.0")` fails at import with a message that says
# nothing about a missing package.
cat > "$ROOT/DEBIAN/control" <<CTRL
Package: nadamas
Version: ${VERSION}
Section: sound
Priority: optional
Architecture: all
Maintainer: ezvk <ezvk@users.noreply.github.com>
Depends: python3 (>= 3.11), python3-gi, python3-dbus, python3-cairo, gir1.2-gtk-4.0, gir1.2-adw-1, bluez
Recommends: playerctl, libnotify-bin
Homepage: https://github.com/ezvk/nadamas
Description: Control Nothing and CMF earbuds from Linux
 Fork of something-x adding a working system-tray menu, the four ANC
 strengths, and a codec selector that enables LDAC without an Android
 phone -- the Nothing X app does not expose that switch on iOS.
 .
 Per-model profiles are plain JSON, so adding a device needs no code.
CTRL

dpkg-deb --build --root-owner-group "$ROOT"
echo "built: ${ROOT}.deb"
