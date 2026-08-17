{
  description = "nadamas — control Nothing and CMF earbuds from Linux, without the phone app";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
  };

  outputs =
    {
      self,
      nixpkgs,
      flake-utils,
    }:
    flake-utils.lib.eachDefaultSystem (
      system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        python = pkgs.python3;
      in
      {
        packages.default = self.packages.${system}.nadamas;

        packages.nadamas = python.pkgs.buildPythonApplication {
          pname = "nadamas";
          version = "0.1.0";
          pyproject = true;
          src = ./.;

          # setuptools-scm derives the version from git tags; the source that
          # reaches the builder has no .git, so pin it explicitly instead.
          SETUPTOOLS_SCM_PRETEND_VERSION = "0.1.0";

          build-system = with python.pkgs; [
            setuptools
            setuptools-scm
          ];

          dependencies = with python.pkgs; [
            pygobject3
            dbus-python
          ];

          # ⚠️ wrapGAppsHook4 AND gobject-introspection ARE BOTH REQUIRED, and
          # for different reasons: the first sets GSETTINGS_SCHEMA_DIR and the
          # GDK backend, the second makes `gi.require_version("Gtk", "4.0")`
          # resolve at runtime. Dropping either produces a program that starts
          # and then fails on the first widget.
          nativeBuildInputs = [
            pkgs.wrapGAppsHook4
            pkgs.gobject-introspection
          ];

          buildInputs = [
            pkgs.gtk4
            pkgs.libadwaita
            pkgs.glib
          ];

          # ⚠️ RUNTIME TOOLS THE APP SHELLS OUT TO. `bluez` provides sdptool for
          # channel discovery and `libnotify` provides notify-send. Without them
          # the failure is silent: no notifications, and channel discovery falls
          # back to the probe list -- which happens to work, so the omission
          # would go unnoticed until a device needed the SDP path.
          makeWrapperArgs = [
            "--prefix PATH : ${
              pkgs.lib.makeBinPath [
                pkgs.bluez
                pkgs.libnotify
              ]
            }"
          ];

          # The test suite needs a session bus and a display; skip it here and
          # run it in CI where both can be provided.
          doCheck = false;

          meta = with pkgs.lib; {
            description = "Control Nothing and CMF earbuds from Linux";
            longDescription = ''
              Fork of SoaOaoS/something-x adding: a working system-tray menu,
              the three ANC strengths, a codec selector that turns LDAC on
              without an Android phone, and pluggable per-model JSON profiles.
            '';
            homepage = "https://github.com/ezvk/nadamas";
            license = licenses.mit;
            platforms = platforms.linux;
            mainProgram = "nadamas";
          };
        };

        devShells.default = pkgs.mkShell {
          packages = [
            python
            python.pkgs.pygobject3
            python.pkgs.dbus-python
            python.pkgs.pytest
            pkgs.gtk4
            pkgs.libadwaita
            pkgs.gobject-introspection
            pkgs.ruff
            pkgs.bluez
          ];
        };
      }
    );
}
