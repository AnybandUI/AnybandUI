"""Create a relocatable Windows playtest ZIP; never includes personal saves."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]

def package(build, output, *, name=None, runtime=None, source_files=None):
    build, output = build.resolve(), output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    name = name or "AnybandUI-Windows-" + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    if not name or name in (".", "..") or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-" for c in name):
        raise ValueError("Package name must be a simple directory name")
    stage = output / name
    stage.mkdir()  # Never overwrite a previous package or someone else's files.
    game = build / "game"
    for file in ("AnybandUI.exe",):
        shutil.copy2(game/file, stage/file)
    for folder in ("audio", "fonts"):
        shutil.copytree(game/folder, stage/folder)
    (stage/"engines").mkdir()
    shutil.copy2(ROOT/"docs/engines.md",stage/"engines/README.md")
    # App-local release runtimes: a clean PC does not need Visual Studio.
    candidates = sorted(Path("C:/Program Files/Microsoft Visual Studio").glob(
        "*/*/VC/Redist/MSVC/[0-9]*/x64/Microsoft.VC*.CRT"))
    if runtime is not None:
        candidates = [Path(runtime)]
    if not candidates or not list(candidates[-1].glob("*.dll")):
        raise RuntimeError("Install the Visual C++ x64 redistributable build tools before packaging")
    for file in candidates[-1].glob("*.dll"):
        shutil.copy2(file, stage/file.name)
    licenses = stage/"licenses"
    shutil.copytree(ROOT/"anybandui"/"licenses", licenses)
    cache = {}
    for line in (build/"CMakeCache.txt").read_text().splitlines():
        if line and not line.startswith(("#", "//")) and "=" in line:
            key, value = line.split("=", 1)
            cache[key.split(":", 1)[0]] = value
    def dependency(name):
        override = cache.get("FETCHCONTENT_SOURCE_DIR_"+name.upper(), "")
        return Path(override) if override else build/"_deps"/(name+"-src")
    for source, license_name in (("sdl3-src/LICENSE.txt", "SDL3.txt"),
                         ("imgui-src/LICENSE.txt", "Dear-ImGui.txt"),
                         ("json-src/LICENSE.MIT", "nlohmann-json.txt")):
        folder, relative = source.split("/", 1)
        shutil.copy2(dependency(folder.removesuffix("-src"))/relative, licenses/license_name)
    shutil.copy2(ROOT/"LICENSE", licenses/"AnybandUI-GPL-2.0.txt")
    shutil.copy2(dependency("sdl3")/"src"/"video"/"stb_image.h", licenses/"stb_image.h")
    (licenses/"Cousine-copyright.txt").write_text(
        "Cousine-Regular.ttf by Steve Matteson. Digitized data copyright (c) 2010 Google Corporation.\n"
        "Licensed under the SIL Open Font License 1.1; see Cousine-OFL.txt.\n")
    shutil.copy2(ROOT/"anybandui"/"PLAYTEST.md", stage/"START-HERE.md")
    # Bundle exact working-tree source alongside binaries, including local fixes.
    tracked = source_files if source_files is not None else subprocess.check_output(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"], cwd=ROOT).decode().split("\0")
    with zipfile.ZipFile(stage/"source.zip", "w", zipfile.ZIP_DEFLATED) as source:
        for file in sorted(set(tracked)):
            path = ROOT/file
            if not path.resolve().is_relative_to(ROOT.resolve()):
                raise ValueError(f"Source path escapes the repository: {file}")
            if file and path.is_file() and not path.is_relative_to(stage) and not file.endswith(".pyc") and not file.startswith("screenshots/"):
                source.write(path, "AnybandUI-source/"+file)
    manifest = {}
    for path in sorted(stage.rglob("*")):
        if path.is_file():
            manifest[path.relative_to(stage).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    (stage/"manifest.json").write_text(json.dumps({"sha256":manifest}, indent=2))
    archive = Path(shutil.make_archive(str(output/name), "zip", output, name))
    print(archive)
    return archive, stage

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, default=ROOT/"build/dev")
    parser.add_argument("--output", type=Path, default=ROOT/"build/components")
    parser.add_argument("--name")
    parser.add_argument("--runtime", type=Path)
    parser.add_argument("--source-files", type=Path, help="JSON file list for an isolated source snapshot")
    args = parser.parse_args()
    package(args.build, args.output, name=args.name, runtime=args.runtime,
            source_files=json.loads(args.source_files.read_text()) if args.source_files else None)
