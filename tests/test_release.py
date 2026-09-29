"""Release integrity checks. No compiler, game process or network is used."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import zipfile

spec = importlib.util.spec_from_file_location("release", Path(__file__).resolve().parents[1] / "tools/release.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def archive(self, *, modified=False, extra=False, escape=False):
        path = self.root / "package.zip"
        name = "../../outside.txt" if escape else "app.exe"
        manifest = {"sha256": {name: hashlib.sha256(b"built binary").hexdigest()}}
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("package/" + name, b"changed binary" if modified else b"built binary")
            archive.writestr("package/manifest.json", json.dumps(manifest))
            if extra:
                archive.writestr("package/personal-save", b"unwanted")
        return path

    def test_valid_package_extracts(self):
        result = release.verify_archive(self.archive(), self.root / "installed", "manifest.json")
        self.assertEqual((result / "app.exe").read_bytes(), b"built binary")

    def component(self, name, files, manifest_name):
        path = self.root / (name + ".zip")
        hashes = {key: hashlib.sha256(value).hexdigest() for key, value in files.items()}
        manifest = {"sha256": hashes} if manifest_name == "manifest.json" else hashes
        with zipfile.ZipFile(path, "w") as archive:
            for key, value in files.items():
                archive.writestr(name + "/" + key, value)
            archive.writestr(name + "/" + manifest_name, json.dumps(manifest))
        return path

    def bundled_fixture(self, extra_ui=None):
        ui = self.component("UI-component", {"AnybandUI.exe": b"ui binary", "source.zip": b"ui source",
                            "fonts/font.ttf": b"font", "licenses/UI.txt": b"UI licence", **(extra_ui or {})}, "manifest.json")
        engine = self.component("Engine-component", {"engine.exe": b"engine binary", "lib/data.txt": b"game data",
                                "source.zip": b"engine source", "licenses/engine.txt": b"engine licence",
                                "engine.anyband.json": json.dumps({"executable": "engine.exe", "data_directory": "lib"}).encode()}, "SHA256.json")
        return ui, engine

    def test_single_distribution_contains_ui_engine_sources_and_complete_manifest(self):
        ui, engine = self.bundled_fixture()
        final = self.root / "dist/packages/AnybandUI.zip"
        release.bundle(ui, engine, self.root / "work/staging", final, {"candidate": "test"})
        app = release.verify_archive(final, self.root / "dist/playtest", "manifest.json")
        self.assertEqual(app.name, "AnybandUI")
        self.assertEqual((app / "AnybandUI.exe").read_bytes(), b"ui binary")
        self.assertEqual((app / "engines/angband/engine.exe").read_bytes(), b"engine binary")
        for name in ("source.zip", "licenses/UI.txt", "engines/angband/source.zip", "engines/angband/licenses/engine.txt"):
            self.assertTrue((app / name).is_file(), name)
        manifest = json.loads((app / "manifest.json").read_text())["sha256"]
        self.assertIn("engines/angband/engine.exe", manifest)
        self.assertIn("build-info.json", manifest)
        self.assertEqual(len(list((self.root / "dist/packages").glob("*.zip"))), 1)
        self.assertEqual(len(list((app / "engines").rglob("engine.anyband.json"))), 1)

    def test_combined_package_rejects_extra_engine(self):
        ui, engine = self.bundled_fixture({"engines/extra/engine.anyband.json": b"{}"})
        final = self.root / "dist/packages/AnybandUI.zip"
        with self.assertRaisesRegex(RuntimeError, "exactly one engine"):
            release.bundle(ui, engine, self.root / "work/staging", final, {})
        self.assertFalse(final.exists())

    def test_combined_package_cannot_overwrite_existing_archive(self):
        ui, engine = self.bundled_fixture()
        final = self.root / "keep.zip"
        final.write_bytes(b"previous release")
        with self.assertRaises(FileExistsError):
            release.bundle(ui, engine, self.root / "work/staging", final, {})
        self.assertEqual(final.read_bytes(), b"previous release")

    def test_tampered_or_extra_files_never_extract(self):
        for options in ({"modified": True}, {"extra": True}, {"escape": True}):
            with self.subTest(options=options), self.assertRaises(RuntimeError):
                release.verify_archive(self.archive(**options), self.root / "installed", "manifest.json")
            self.assertFalse((self.root / "installed").exists())
        self.assertFalse((self.root / "outside.txt").exists())

    def test_native_exit_success_does_not_hide_assertion_failure(self):
        release.require_native_passes("adapter/map finished: 5/5 passed", 5)
        for output in ("adapter/map finished: 4/5 passed", "", "adapter/map finished: 0/0 passed"):
            with self.subTest(output=output), self.assertRaises(RuntimeError):
                release.require_native_passes(output, 5)

    def test_source_archive_requires_exact_bytes_and_file_set(self):
        archive = self.root / "source.zip"
        with zipfile.ZipFile(archive, "w") as output:
            output.writestr("source/main.c", b"original")
        expected = {"source/main.c": hashlib.sha256(b"original").hexdigest()}
        release.verify_source_archive(archive, expected)
        for bad in ({}, {"source/main.c": hashlib.sha256(b"edited").hexdigest()}):
            with self.assertRaises(RuntimeError):
                release.verify_source_archive(archive, bad)

    def test_failed_step_stops_and_records_failure(self):
        run = release.Run(self.root, None, {})
        with self.assertRaises(subprocess.CalledProcessError):
            run.command("failure", [sys.executable, "-c", "raise SystemExit(7)"], self.root)
        self.assertEqual(run.info["steps"][0]["status"], "failed")
        self.assertEqual(len(run.info["steps"]), 1)

    def test_dirty_snapshot_is_explicit_and_frozen(self):
        repo = self.root / "repo"
        repo.mkdir()
        def git(*args):
            return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
        git("init")
        (repo / "main.c").write_text("committed")
        (repo / ".gitignore").write_text("build/\n")
        git("add", ".")
        git("-c", "user.name=Release Test", "-c", "user.email=release-test@example.invalid", "-c", "commit.gpgsign=false", "commit", "-m", "fixture")
        clean = release.snapshot(repo, self.root / "clean", False)
        self.assertFalse(clean["dirty"])
        (repo / "main.c").write_text("local edit")
        (repo / "new.c").write_text("new source")
        (repo / "build").mkdir()
        (repo / "build/private-save").write_text("private")
        with self.assertRaises(RuntimeError):
            release.snapshot(repo, self.root / "rejected", False)
        snapshot = self.root / "dirty"
        receipt = release.snapshot(repo, snapshot, True)
        (repo / "main.c").write_text("later edit")
        self.assertEqual((snapshot / "main.c").read_text(), "local edit")
        self.assertTrue((snapshot / "new.c").is_file())
        self.assertFalse((snapshot / "build").exists())
        self.assertEqual(release.tree_hashes(snapshot), receipt["files"])

    def test_pinned_dependency_cache_reuses_and_rejects_modified_source(self):
        source = self.root / "source"
        (source / "anybandui").mkdir(parents=True)
        declarations = []
        downloads = []
        for name, required in (("SDL3", "CMakeLists.txt"), ("imgui", "imgui.cpp"), ("json", "CMakeLists.txt")):
            declarations.append(f'FetchContent_Declare({name} GIT_REPOSITORY https://github.com/test/{name}.git GIT_TAG {"a" * 40})')
            payload = io.BytesIO()
            with tarfile.open(fileobj=payload, mode="w:gz") as archive:
                member = tarfile.TarInfo("upstream/" + required)
                member.size = len(b"pinned source")
                archive.addfile(member, io.BytesIO(b"pinned source"))
            downloads.append(io.BytesIO(payload.getvalue()))
        (source / "anybandui/CMakeLists.txt").write_text("\n".join(declarations))
        cache = self.root / "cache"
        with patch.object(release.urllib.request, "urlopen", side_effect=downloads) as fetch:
            first = release.dependencies(source, cache)
            second = release.dependencies(source, cache)
            self.assertEqual(first, second)
            self.assertEqual(fetch.call_count, 3)
            (Path(first["imgui"]["directory"]) / "imgui.cpp").write_text("modified")
            with self.assertRaisesRegex(RuntimeError, "cache changed"):
                release.dependencies(source, cache)


if __name__ == "__main__":
    unittest.main()
