# Engine packages

Complete AnybandUI releases include Angband in `engines/angband/` beside the UI.
Each engine package supplies `engine.anyband.json`, a compatible executable and
its own game data. Keep each engine together in its own directory. Avoid installing
two copies of the same engine identity.

For a frontend-only development build, install a supported engine in
`build/dev/game/engines/` and click **Rescan**. The engine contract is documented
under `protocol/` in the UI source (also included in the release's UI source ZIP).
