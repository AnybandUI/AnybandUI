# Local Windows releases

From the AnybandUI checkout, in an ordinary PowerShell terminal:

```powershell
python -B tools/release.py
```

This creates **one distribution ZIP containing AnybandUI and Angband**, ready
to extract and play. No engine installation step is needed for that ZIP.
Nothing is published or installed automatically.

Requires Python 3.12+, Git, and Visual Studio C++ x64 tools with CMake, Ninja
and the release runtime. Visual Studio is discovered automatically. Keep
`AnybandUI-AngbandAdapter` and `angband` beside this checkout, or supply
`--adapter PATH` and `--angband PATH`.

UI and adapter working trees must be committed and clean by default. To test
local changes, pass `--allow-dirty`; the output is labelled as a development
candidate. This includes non-ignored untracked files, so review them before sharing.

```powershell
python -B tools/release.py --version 0.1.0-rc1
python -B tools/release.py --allow-dirty
python -B tools/release.py --preflight
```

Preflight checks tools, repository cleanliness, matching protocol contracts and
the pinned Angband commit. It does not compile or download dependencies.

## Where files go

```text
build/
  dev/                  Incremental UI development build
  dependencies/         Shared, verified dependency source cache
  releases/<run>/       Source snapshots, compiler output, component packages,
                        combined-package staging and diagnostic logs
  profiles/<run>/       Isolated profiles when using the playtest command
dist/<run>/
  packages/             ONE combined distribution ZIP
  playtest/AnybandUI/    Extracted from that exact ZIP, ready to run
  reports/              Validation, source/build details, checksums, logs,
                        and PLAYTEST.txt with an isolated-profile launch command
```

The final ZIP has a short `AnybandUI/` root and includes its executable, fonts,
audio, runtime DLLs, licences, UI source archive and build identity. Its
`engines/angband/` folder includes the engine executable, game data, manifest,
licences and corresponding engine/adapter source archive. The root checksum
manifest covers the complete combined package, including the engine.

Separate UI and engine component ZIPs remain internal files under `build/`.
Only the combined ZIP is placed in `dist/<run>/packages/`.

## What is checked

The workflow freezes the selected UI and adapter sources, prepares pinned
Angband with its patches, and builds everything in fresh directories. SDL3,
ImGui and JSON sources download on first use; cache contents are hashed before
reuse. Runtime DLLs come from the chosen Visual Studio toolchain.

It runs client, offscreen GPU, dummy-device audio, adapter map and packaging
checks. Map test pass totals are checked as well as exit status. Source snapshots
and dependency hashes are checked again before packaging. Component ZIPs are
verified before assembly; the final ZIP is verified and extracted, both bundled
source archives and executable hashes are checked, and the extracted UI runs
its asset check. Any failure stops the run and retains logs in the build workspace.

GPU checks require working graphics support; inability to run is a failure.
Quarantined transport helpers and the object/pile test target are not built or
run. Live gameplay integration coverage remains incomplete.

Use `reports/PLAYTEST.txt` to test character creation, gameplay and
save/quit/relaunch/reload. Normal profiles and installed engines are untouched.
Distribute the same combined ZIP after testing; do not rebuild it for publishing.
Manual gameplay, real-device checks and clean-machine installation remain
separate release checks. A successful automated run does not certify them.

The version argument labels the candidate; it does not change engine save or
protocol compatibility. Build records support rebuilding, but byte-identical
executables across toolchain versions are not promised. UI dependency source is
fetched separately rather than bundled into the UI source archive.

## Development and storage

For a quick incremental UI build:

```powershell
python -B tools/build.py
```

Run `build/dev/game/AnybandUI.exe`. Installed engines belong under its `engines/`
folder. Development and release builds share `build/dependencies/`.

`--output` relocates finished candidates, `--work-root` relocates release workspaces,
and `--cache` relocates dependencies. Generated paths inside a repository must be
Git-ignored. Release build and distribution directories must be separate.

Once a candidate is accepted, its workspace in `build/releases/` can be removed;
the ZIP, extracted copy and reports in `dist/` stand on their own. Keep any profiles
you care about. Deleting the dependency cache is safe but causes another download.
Migrated historical fixtures and logs, if present, are retained in `build/history/`.

Run workflow regression checks with:

```powershell
python -B -m unittest discover -s tests -p "test_release.py" -v
```
