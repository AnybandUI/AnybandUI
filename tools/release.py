"""Build a local Windows release candidate. Never publishes or installs it."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import uuid
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PENDING = [
    "Manual gameplay, save/quit/relaunch/reload using the extracted candidate.",
    "Clean-machine installation checks.",
    "Live transport/gameplay integration coverage: earlier helpers remain quarantined; not run.",
]


def sha(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def tree_hashes(root):
    result = {}
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise RuntimeError(f"Unexpected source symlink: {path}")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = sha(path)
    return result


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args])


def snapshot(repo, destination, allow_dirty):
    """Freeze source before compilation; no build reads the working checkout."""
    revision = git(repo, "rev-parse", "HEAD").decode().strip()
    status = git(repo, "status", "--porcelain", "--untracked-files=all").decode()
    if status and not allow_dirty:
        raise RuntimeError(f"{repo.name} has uncommitted files. Commit them, or use --allow-dirty for a development candidate.")
    destination.mkdir(parents=True)
    if allow_dirty:
        paths = git(repo, "ls-files", "--cached", "--others", "--exclude-standard", "-z").decode().split("\0")
        for name in sorted(set(paths) - {""}):
            source = repo / name
            if not source.resolve().is_relative_to(repo.resolve()) or source.is_symlink():
                raise RuntimeError(f"Source escapes checkout: {source}")
            if source.is_file():
                target = destination / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(source.read_bytes())
    else:
        with tarfile.open(fileobj=io.BytesIO(git(repo, "archive", revision))) as archive:
            archive.extractall(destination, filter="data")
    return {"commit": revision, "dirty": bool(status), "status": status,
            "files": tree_hashes(destination)}


def toolchain():
    if os.name != "nt":
        raise RuntimeError("This release workflow currently targets Windows x64.")
    finder = Path(os.environ.get("ProgramFiles(x86)", "C:/Program Files (x86)")) / "Microsoft Visual Studio/Installer/vswhere.exe"
    installations = json.loads(subprocess.check_output([
        str(finder), "-products", "*", "-requires", "Microsoft.VisualStudio.Component.VC.Tools.x86.x64", "-format", "json"]))
    for item in installations:
        install = Path(item["installationPath"])
        cmake = install / "Common7/IDE/CommonExtensions/Microsoft/CMake/CMake/bin/cmake.exe"
        ninja = install / "Common7/IDE/CommonExtensions/Microsoft/CMake/Ninja/ninja.exe"
        if cmake.is_file() and ninja.is_file():
            break
    else:
        raise RuntimeError("Install Visual Studio C++ tools, including CMake and Ninja.")
    vcvars = install / "VC/Auxiliary/Build/vcvars64.bat"
    # A single, quoted tool path; no user-supplied command text is interpolated.
    output = subprocess.check_output(
        f'cmd.exe /d /s /c ""{vcvars}" >nul && set"', text=True)
    env = {key.upper(): value for line in output.splitlines() if "=" in line
           for key, value in [line.split("=", 1)] if key and not key.startswith("=")}
    redist = Path(env["VCTOOLSREDISTDIR"]) / "x64"
    runtimes = sorted(redist.glob("Microsoft.VC*.CRT"))
    if len(runtimes) != 1 or not list(runtimes[0].glob("*.dll")):
        raise RuntimeError(f"Cannot identify one x64 runtime in {redist}")
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env, {"installation": str(install), "cmake": str(cmake), "ninja": str(ninja),
                 "runtime": str(runtimes[0]), "compiler_version": env.get("VCTOOLSVERSION")}


def dependencies(source, cache):
    """Cache pinned upstream archives, checking cached contents before reuse."""
    declarations = (source / "anybandui/CMakeLists.txt").read_text()
    pins = re.findall(r"FetchContent_Declare\((\w+)\s+GIT_REPOSITORY https://github.com/([^\s]+)\.git\s+GIT_TAG ([0-9a-f]{40})\)", declarations)
    if {name.lower() for name, _, _ in pins} != {"sdl3", "imgui", "json"}:
        raise RuntimeError("Review release dependency discovery: expected three commit-pinned dependencies.")
    cache.mkdir(parents=True, exist_ok=True)
    result = {}
    for name, repository, commit in pins:
        key = f"{name.lower()}-{commit}"
        directory, receipt = cache / key, cache / (key + ".json")
        if directory.exists():
            if not receipt.is_file():
                raise RuntimeError(f"Incomplete dependency cache: {directory}. Select another --cache directory.")
            info = json.loads(receipt.read_text())
            if info.get("repository") != repository or info.get("commit") != commit or info["files"] != tree_hashes(directory):
                raise RuntimeError(f"Dependency cache changed: {directory}. Select another --cache directory.")
        else:
            print(f"Downloading pinned {name} source...", flush=True)
            url = f"https://codeload.github.com/{repository}/tar.gz/{commit}"
            with urllib.request.urlopen(url, timeout=120) as response:
                data = response.read()
            directory.mkdir()
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
                # Drop GitHub's single top-level directory, retaining data filtering.
                members = archive.getmembers()
                prefixes = {m.name.split("/", 1)[0] for m in members}
                if len(prefixes) != 1:
                    raise RuntimeError("Unexpected dependency archive layout")
                for member in members:
                    parts = member.name.split("/", 1)
                    if len(parts) == 2 and parts[1]:
                        member.name = parts[1]
                        archive.extract(member, directory, filter="data")
            required_file = "imgui.cpp" if name.lower() == "imgui" else "CMakeLists.txt"
            if not (directory / required_file).is_file():
                raise RuntimeError(f"Incomplete dependency: {name}")
            info = {"repository": repository, "commit": commit,
                    "archive_sha256": hashlib.sha256(data).hexdigest(), "files": tree_hashes(directory)}
            write_json(receipt, info)
        result[name.lower()] = {**info, "directory": str(directory)}
    return result


def require_native_passes(output, expected):
    totals = re.findall(r"finished: (\d+)/(\d+) passed", output)
    if len(totals) != 1 or tuple(map(int, totals[0])) != (expected, expected):
        raise RuntimeError(f"Expected {expected}/{expected} native tests to pass; inspect the log.")


def verify_archive(archive_path, destination, manifest_name, *, root_name=None):
    """Validate the exact ZIP, including unexpected files, before extraction."""
    with zipfile.ZipFile(archive_path) as archive:
        files = [i.filename for i in archive.infolist() if not i.is_dir()]
        if len(files) != len({name.casefold() for name in files}):
            raise RuntimeError("Duplicate ZIP entries")
        roots = {name.split("/")[0] for name in files}
        if len(roots) != 1:
            raise RuntimeError("Package must have one root directory")
        root = next(iter(roots))
        if root_name is not None and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", root_name):
            raise ValueError("Invalid extraction directory name")
        for name in files:
            path = destination / name
            if "\\" in name or not path.resolve().is_relative_to(destination.resolve()):
                raise RuntimeError(f"Unsafe ZIP entry: {name}")
        manifest = json.loads(archive.read(f"{root}/{manifest_name}"))
        hashes = manifest["sha256"] if manifest_name == "manifest.json" else manifest
        expected = {f"{root}/{name}" for name in hashes} | {f"{root}/{manifest_name}"}
        if set(files) != expected:
            raise RuntimeError("Package file list does not match its manifest")
        for name, digest in hashes.items():
            if hashlib.sha256(archive.read(f"{root}/{name}")).hexdigest() != digest:
                raise RuntimeError(f"Package checksum mismatch: {name}")
        target_root = destination / (root_name or root)
        if target_root.exists():
            raise FileExistsError(target_root)
        for name in files:
            target = target_root / name.split("/", 1)[1]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
    return target_root


def bundle(ui_zip, engine_zip, staging, archive_path, build_info):
    """Combine verified components into the single extract-and-play deliverable."""
    app = verify_archive(ui_zip, staging, "manifest.json", root_name="AnybandUI")
    engine = verify_archive(engine_zip, app / "engines", "SHA256.json", root_name="angband")
    manifests = list((app / "engines").rglob("engine.anyband.json"))
    if manifests != [engine / "engine.anyband.json"]:
        raise RuntimeError("The combined release must contain exactly one engine")
    identity = json.loads(manifests[0].read_text())
    for key in ("executable", "data_directory"):
        target = (engine / identity[key]).resolve()
        if not target.is_relative_to(engine.resolve()) or not target.exists():
            raise RuntimeError(f"Invalid packaged engine {key}")
    if not (app / "AnybandUI.exe").is_file():
        raise RuntimeError("Combined package has no UI executable")
    write_json(app / "build-info.json", build_info)
    hashes = tree_hashes(app)
    hashes.pop("manifest.json")
    write_json(app / "manifest.json", {"sha256": hashes})
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path, "x", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(app.rglob("*")):
            if path.is_file():
                archive.write(path, "AnybandUI/" + path.relative_to(app).as_posix())
    return app


def verify_source_archive(path, expected):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise RuntimeError(f"Packaged source file list differs from the build snapshot: {path}")
        for name, digest in expected.items():
            if hashlib.sha256(archive.read(name)).hexdigest() != digest:
                raise RuntimeError(f"Packaged source differs from the build snapshot: {name}")


class Run:
    def __init__(self, directory, env, info):
        self.directory, self.env, self.info = directory, env, info
        (directory / "logs").mkdir()
        self.info.update(status="running", steps=[], pending=PENDING)
        self.save()

    def save(self):
        write_json(self.directory / "build-info.json", self.info)
        lines = ["# Local release candidate", "", f"Status: **{self.info['status']}**", "",
                 "This workflow does not publish or certify a public release.", "", "## Automated steps", ""]
        lines += [f"- {step['name']}: {step['status']} (logs/{step['log']})" for step in self.info["steps"]]
        lines += ["", "## Still required", ""] + [f"- {item}" for item in PENDING]
        if "error" in self.info:
            lines += ["", "## Failure", "", self.info["error"]]
        (self.directory / "validation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    def command(self, name, command, cwd, native_total=None):
        print(f"[{len(self.info['steps']) + 1}] {name}", flush=True)
        step = {"name": name, "status": "running", "log": name + ".log", "command": [str(v) for v in command]}
        self.info["steps"].append(step)
        self.save()
        log = self.directory / "logs" / step["log"]
        try:
            with log.open("w", encoding="utf-8") as stream:
                subprocess.run(step["command"], cwd=cwd, env=self.env, stdout=stream,
                               stderr=subprocess.STDOUT, check=True, timeout=1800)
            if native_total is not None:
                require_native_passes(log.read_text(encoding="utf-8", errors="replace"), native_total)
            step["status"] = "passed"
        except Exception:
            step["status"] = "failed"
            raise
        finally:
            self.save()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adapter", type=Path, default=ROOT.parent / "AnybandUI-AngbandAdapter")
    parser.add_argument("--angband", type=Path, default=ROOT.parent / "angband")
    parser.add_argument("--output", type=Path, default=ROOT / "dist", help="Finished candidates (default: dist)")
    parser.add_argument("--work-root", type=Path, default=ROOT / "build/releases", help="Isolated build workspaces")
    parser.add_argument("--cache", type=Path, default=ROOT / "build/dependencies", help="Shared pinned dependency cache")
    parser.add_argument("--version", default="candidate")
    parser.add_argument("--allow-dirty", action="store_true", help="Snapshot local edits and label the result a development build")
    parser.add_argument("--preflight", action="store_true", help="Check repositories and toolchain without building or downloading")
    args = parser.parse_args()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", args.version):
        parser.error("Version may contain letters, numbers, dots, underscores and hyphens")
    env, tools = toolchain()
    adapter, angband = args.adapter.resolve(), args.angband.resolve()
    # Keep generated files out of source snapshots even with a custom output path.
    for path in (args.output.resolve(), args.work_root.resolve(), args.cache.resolve()):
        for repo in (ROOT, adapter, angband):
            if path.is_relative_to(repo):
                result = subprocess.run(["git", "-C", str(repo), "check-ignore", "-q", str(path / "release-output-probe")])
                if result.returncode != 0:
                    raise RuntimeError(f"Output/cache inside a repository must be Git-ignored: {path}")
    for repo in (ROOT, adapter):
        if git(repo, "status", "--porcelain", "--untracked-files=all").strip() and not args.allow_dirty:
            raise RuntimeError(f"{repo.name} has uncommitted files; commit or pass --allow-dirty.")
    if json.loads((ROOT / "protocol/anyband-protocol.json").read_text()) != json.loads((adapter / "anyband-protocol.json").read_text()):
        raise RuntimeError("UI and adapter protocol contracts differ")
    pinned = json.loads((adapter / "upstream.json").read_text())["commit"]
    git(angband, "cat-file", "-e", pinned + "^{commit}")
    if args.preflight:
        print(json.dumps({"toolchain": tools, "angband_commit": pinned, "result": "preflight passed"}, indent=2))
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    name = f"{args.version}-{'dev-' if args.allow_dirty else ''}{stamp}-{uuid.uuid4().hex[:6]}"
    directory = args.work_root.resolve() / name
    output = args.output.resolve() / name
    if directory == output or output.is_relative_to(directory) or directory.is_relative_to(output):
        raise RuntimeError("Build workspace and finished output must be separate directories")
    directory.mkdir(parents=True, exist_ok=False)
    run = Run(directory, env, {"candidate": name, "development": args.allow_dirty, "toolchain": tools,
                               "python": sys.version, "angband_commit": pinned})
    print(f"Build workspace: {directory}\nFinished candidate: {output}", flush=True)
    try:
        ui, adapter_source = directory / "source/ui", directory / "source/adapter"
        run.info["sources"] = {"ui": snapshot(ROOT, ui, args.allow_dirty),
                               "adapter": snapshot(adapter, adapter_source, args.allow_dirty)}
        if json.loads((ui / "protocol/anyband-protocol.json").read_text()) != json.loads((adapter_source / "anyband-protocol.json").read_text()):
            raise RuntimeError("Snapshot protocol contracts differ")
        source_list = directory / "ui-source-files.json"
        write_json(source_list, sorted(run.info["sources"]["ui"]["files"]))
        deps = dependencies(ui, args.cache.resolve())
        run.info["dependencies"] = deps
        cmake, ninja, runtime = tools["cmake"], tools["ninja"], tools["runtime"]
        run.command("cmake-version", [cmake, "--version"], directory)
        engine, engine_build, ui_build = directory / "source/engine", directory / "engine-build", directory / "ui-build"
        py = [sys.executable, "-B"]
        run.command("prepare-engine", [*py, adapter_source / "tools/prepare.py", "--repository", angband, "--source", engine], directory)
        run.info["engine_source"] = json.loads((engine / ".adapter-source.json").read_text())
        run.command("configure-ui", [cmake, "-S", ui, "-B", ui_build, "-G", "Ninja", "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
                                    f"-DCMAKE_MAKE_PROGRAM={ninja}", *[f"-DFETCHCONTENT_SOURCE_DIR_{key.upper()}={value['directory']}" for key, value in deps.items()]], directory)
        run.command("build-ui", [cmake, "--build", ui_build, "--parallel", "4", "--target", "AnybandUI", "anybandui-client-tests", "anybandui-gpu-tests"], directory)
        run.command("configure-engine", [cmake, "-S", engine, "-B", engine_build, "-G", "NMake Makefiles", "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
                                        f"-DANGBAND_EXTERNAL_FRONTEND={adapter_source}", "-DSUPPORT_BORG=OFF", "-DSUPPORT_SPOIL_FRONTEND=OFF"], directory)
        run.command("build-engine", [cmake, "--build", engine_build, "--target", "OurExecutable", "anybandui-map-tests"], directory)
        game = ui_build / "game"
        run.command("client-tests", [game / "anybandui-client-tests.exe", directory / "test-settings.json"], directory)
        run.command("gpu-tests", [game / "anybandui-gpu-tests.exe"], directory)
        run.command("map-tests", [engine_build / "game/anybandui-map-tests.exe", "-v"], engine_build / "game", native_total=5)
        run.command("packaging-tests", [*py, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"], adapter_source)
        # Source must still be identical before creating source archives.
        for key, source in (("ui", ui), ("adapter", adapter_source)):
            if tree_hashes(source) != run.info["sources"][key]["files"]:
                raise RuntimeError(f"{key} source snapshot changed during the build")
        run.command("verify-engine-source", [*py, adapter_source / "tools/prepare.py", "--repository", angband, "--source", engine], directory)
        for key, dep in deps.items():
            if tree_hashes(Path(dep["directory"])) != dep["files"]:
                raise RuntimeError(f"{key} dependency changed during the build")
        packages = directory / "components"
        ui_name, engine_name = "AnybandUI", "Angband"
        run.command("package-ui", [*py, ui / "tools/package_windows.py", "--build", ui_build, "--output", packages,
                                  "--name", ui_name, "--runtime", runtime, "--source-files", source_list], directory)
        run.command("package-engine", [*py, adapter_source / "tools/package.py", "--build", engine_build, "--source", engine,
                                      "--output", packages / engine_name, "--runtime", runtime], directory)
        ui_zip, engine_zip = packages / (ui_name + ".zip"), packages / (engine_name + ".zip")
        output.mkdir(parents=True, exist_ok=False)
        final_zip = output / "packages" / f"AnybandUI-{name}-windows-x64.zip"
        public_info = {"candidate": name, "development": args.allow_dirty,
                       "source_commits": {key: info["commit"] for key, info in run.info["sources"].items()},
                       "source_dirty": {key: info["dirty"] for key, info in run.info["sources"].items()},
                       "angband": run.info["engine_source"], "compiler_version": tools["compiler_version"],
                       "dependencies": {key: {field: value[field] for field in ("repository", "commit", "archive_sha256")} for key, value in deps.items()}}
        bundle(ui_zip, engine_zip, directory / "bundle", final_zip, public_info)
        installed_ui = verify_archive(final_zip, output / "playtest", "manifest.json")
        installed_engine = installed_ui / "engines/angband"
        verify_source_archive(installed_ui / "source.zip", {
            "AnybandUI-source/" + path: digest for path, digest in run.info["sources"]["ui"]["files"].items()})
        engine_files = tree_hashes(engine)
        adapter_files = run.info["sources"]["adapter"]["files"]
        source_roots = {"src", "tests", "tools", "vendor", "docs"}
        source_files = {".clang-format", ".gitignore", "LICENSE", "README.md", "frontend.cmake",
                        "engine.anyband.json.in", "anyband-protocol.json", "upstream.json"}
        expected = {"adapter/" + path: digest for path, digest in adapter_files.items()
                    if path in source_files or Path(path).parts[0] in source_roots}
        expected.update({"angband/" + path: digest for path, digest in engine_files.items()
                         if Path(path).parts[:2] not in (("lib", "user"), ("lib", "save"))})
        verify_source_archive(installed_engine / "source.zip", expected)
        identity = json.loads((installed_engine / "engine.anyband.json").read_text())
        if not (installed_engine / identity["executable"]).is_file() or not (installed_engine / identity["data_directory"]).is_dir():
            raise RuntimeError("Packaged engine manifest references missing files")
        if sha(installed_ui / "AnybandUI.exe") != sha(game / "AnybandUI.exe") or sha(installed_engine / identity["executable"]) != sha(engine_build / "game" / identity["executable"]):
            raise RuntimeError("Packaged executable differs from the new build")
        run.command("packaged-assets", [installed_ui / "AnybandUI.exe", "--check-assets"], installed_ui)
        run.info["artifacts"] = {final_zip.relative_to(output).as_posix(): sha(final_zip)}
        run.info["package_verification"] = "Combined ZIP manifest, both source snapshots, executable hashes and engine paths passed"
        reports = output / "reports"
        reports.mkdir()
        (reports / "checksums.txt").write_text("".join(f"{digest}  {path}\n" for path, digest in run.info["artifacts"].items()))
        run.info["status"] = "automated checks passed; manual validation pending"
        run.info["playtest_executable"] = str(installed_ui / "AnybandUI.exe")
        (reports / "PLAYTEST.txt").write_text(
            'Launch from PowerShell with an isolated profile:\n\n& "' + str(installed_ui / "AnybandUI.exe") +
            '" --user-dir "' + str(ROOT / "build/profiles" / name) + '"\n\n' + "\n".join(PENDING) + "\n", encoding="utf-8")
        run.save()
        for report in ("build-info.json", "validation.md"):
            shutil.copy2(directory / report, reports / report)
        shutil.copytree(directory / "logs", reports / "logs")
        print(f"Candidate ready for manual testing: {output}\nDistribute: {final_zip}\nSee reports/validation.md and reports/PLAYTEST.txt.", flush=True)
    except BaseException as error:
        run.info.update(status="failed", error=str(error))
        run.save()
        print(f"Build stopped. Details: {directory / 'validation.md'}", file=sys.stderr)
        raise


if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print(f"Release failed: {error}", file=sys.stderr)
        sys.exit(1)
