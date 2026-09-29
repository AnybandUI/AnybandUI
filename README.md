# AnybandUI

A standalone native frontend for engines implementing the
[Anyband Protocol](protocol/README.md). Angband is built by the
separate `AnybandUI-AngbandAdapter` project.

## Build a complete release

From this directory, with the adapter and `angband` checkouts alongside it:

```powershell
python -B tools/release.py
```

Produces **one ready-to-play ZIP containing the UI and Angband** under
`dist/<run>/packages/`, plus an extracted copy in `dist/<run>/playtest/AnybandUI/`
and reports in `dist/<run>/reports/`. Nothing is published automatically.
Use `--allow-dirty` to make a development candidate from uncommitted changes.
See [the local release guide](docs/releasing.md) for prerequisites and validation.

## Develop the frontend

```powershell
python -B tools/build.py
```

Run `build/dev/game/AnybandUI.exe`. This incremental build stages fonts;
install an engine under `build/dev/game/engines/` to play. Without an engine it
shows **No supported Anyband binaries found**. Click **Rescan** after installation.

The UI and engine remain independently buildable. The component-only frontend
packager is `tools/package_windows.py`; its output stays under `build/components/`.
The release command combines both components into the single distributable ZIP.

## Folders

- `anybandui/`: application source and assets.
- `protocol/`: shared engine contract.
- `tools/`: build, package and release commands.
- `tests/`: build/release regression checks; C++ UI tests live with the application.
- `docs/`: developer documentation.
- `build/`: generated development builds, release workspaces and dependency cache.
- `dist/`: finished candidates, extracted playtest copies and reports.

UI settings and saves live outside the installation directory. See the
[Windows playtest guide](anybandui/PLAYTEST.md) and [protocol](protocol/README.md)
for controls, package layout and save isolation. GPL-2.0; see LICENSE.
