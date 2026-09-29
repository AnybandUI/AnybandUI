# Frontend implementation

See the [project README](../README.md) for building and running this standalone
frontend and the [engine contract](../protocol/README.md) for integration.

`build.py` builds only the frontend and its tests. `package_windows.py` produces
an engine-free Windows ZIP. `AnybandUI-AngbandAdapter` owns the reference engine's
protocol implementation, tests and packaging. The sibling `angband` checkout
contains the game and the generic interfaces required by that external adapter.
See the adapter README for building and installing an engine package.

`--engines-dir PATH` selects the installation folder. `--backend PATH` is a test
convenience requiring a matching adjacent manifest; `--data-dir PATH` can override
that package's data for isolated tests. `--user-dir PATH` selects the frontend
profile root, with engine saves isolated underneath it. `--check-assets` validates
frontend assets without requiring an engine. Runtime assets have no engine-source
fallback.
