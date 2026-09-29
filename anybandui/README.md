# Frontend implementation

See the [project README](../README.md) for building and running this standalone
frontend and the [engine contract](../protocol/README.md) for integration.

`tools/build.py` builds only the frontend and its tests into `build/dev`.
`tools/release.py` produces one Windows ZIP with the UI and Angband installed.
`tools/package_windows.py` produces the internal frontend-only component.
`AnybandUI-AngbandAdapter` owns the reference engine's
protocol implementation, tests and packaging. The sibling `angband` checkout
contains the game and the generic interfaces required by that external adapter.
See the adapter README for building and installing an engine package.

`--engines-dir PATH` selects the installation folder. `--backend PATH` is a test
convenience requiring a matching adjacent manifest; `--data-dir PATH` can override
that package's data for isolated tests. `--user-dir PATH` selects the frontend
profile root, with engine saves isolated underneath it. `--check-assets` validates
frontend assets without requiring an engine. Runtime assets have no engine-source
fallback.
