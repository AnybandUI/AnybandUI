"""Incremental Windows UI build, sharing the release dependency cache."""
import argparse
from pathlib import Path
import subprocess

from release import ROOT, dependencies, toolchain


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="RelWithDebInfo")
    parser.add_argument("--target", nargs="+", default=["AnybandUI"])
    parser.add_argument("--build-dir", type=Path, default=ROOT / "build/dev")
    parser.add_argument("--cache", type=Path, default=ROOT / "build/dependencies")
    parser.add_argument("--ninja", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--configure", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    env, tools = toolchain()
    deps = dependencies(ROOT, args.cache.resolve())
    build = args.build_dir.resolve()
    subprocess.run([tools["cmake"], "-S", str(ROOT), "-B", str(build), "-G", "Ninja",
                    f"-DCMAKE_BUILD_TYPE={args.config}", f"-DCMAKE_MAKE_PROGRAM={tools['ninja']}",
                    *[f"-DFETCHCONTENT_SOURCE_DIR_{name.upper()}={info['directory']}" for name, info in deps.items()]],
                   env=env, check=True)
    subprocess.run([tools["cmake"], "--build", str(build), "--parallel", "4", "--target", *args.target], env=env, check=True)
    print(f"Application: {build / 'game/AnybandUI.exe'}")


if __name__ == "__main__":
    main()
