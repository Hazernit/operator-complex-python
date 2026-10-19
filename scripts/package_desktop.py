"""Build a native portable ZIP from either operator-complex source track.

Install PyInstaller and PySide6 into a clean environment on the target OS.
This script never publishes or modifies a Git tag or release.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import plistlib
import platform
import shutil
import subprocess
import sys
import zipfile

TOOLS = Path(__file__).resolve().parent
TRACKS = {
    "technical": ("OperatorComplex", "ru.operatorcomplex.desktop"),
    "new-interface": ("OperatorComplexNewInterface", "ru.operatorcomplex.newinterface"),
}


def run(command: list[str], *, cwd: Path | None = None) -> None:
    print("+", " ".join(map(str, command)), flush=True)
    subprocess.run(command, check=True, cwd=cwd)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--edition", required=True, choices=TRACKS)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()

    if not args.tag.startswith("v0.") or "-beta." not in args.tag:
        parser.error("tag must have a v0.x.y-beta.n format")
    if not (len(args.source_sha) == 40 and all(c in "0123456789abcdef" for c in args.source_sha)):
        parser.error("source-sha must be a full lowercase Git commit SHA")

    source = args.source.resolve(strict=True)
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    for required in ("operator_stub/__main__.py", "config/demo_platforms.json", "examples/lidar-room.txt"):
        if not (source / required).is_file():
            parser.error(f"Missing required source file: {source / required}")

    os_name = platform.system()
    arch = platform.machine().lower()
    if os_name not in ("Windows", "Darwin"):
        parser.error(f"This packager must run on Windows or macOS, not {os_name}")
    if os_name == "Windows" and arch not in ("amd64", "x86_64"):
        parser.error(f"Windows x64 required, got {arch}")
    if os_name == "Darwin" and arch not in ("arm64", "aarch64"):
        parser.error(f"macOS Apple Silicon required, got {arch}")

    exe_name, bundle_id = TRACKS[args.edition]
    staging = out / "_staging"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir()
    command = [
        sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
        "--windowed", "--onedir", "--name", exe_name,
        "--distpath", str(staging / "dist"),
        "--workpath", str(staging / "build"),
        "--specpath", str(staging / "spec"),
        "--paths", str(source),
        "--add-data", f"{source / 'config'}{os.pathsep}config",
        "--add-data", f"{source / 'examples'}{os.pathsep}examples",
        "--hidden-import", "PySide6.QtTest",
        "--osx-bundle-identifier", bundle_id,
        str(TOOLS / "desktop_release_entry.py"),
    ]
    run(command)

    release_info = {"edition": args.edition, "release_tag": args.tag, "source_commit": args.source_sha,
                    "built_on": os_name, "architecture": arch, "unsigned_beta": True}
    release_name = f"OperatorComplex-{args.tag}-{args.edition}-{'Windows-x64' if os_name == 'Windows' else 'macOS-arm64'}.zip"
    result_zip = out / release_name

    if os_name == "Windows":
        folder = staging / "dist" / exe_name
        exe = folder / f"{exe_name}.exe"
        if not exe.is_file():
            raise RuntimeError(f"PyInstaller executable missing: {exe}")
        start = folder / f"Start-{exe_name}.bat"
        start.write_bytes((f'@echo off\r\nsetlocal DisableDelayedExpansion\r\n'
            f'"%~dp0{exe_name}.exe" %*\r\nset "CODE=%ERRORLEVEL%"\r\n'
            f'if not "%CODE%"=="0" pause\r\nexit /b %CODE%\r\n').encode("ascii"))
        (folder / "RELEASE_INFO.json").write_text(json.dumps(release_info, indent=2) + "\n", encoding="utf-8")
        # The application is a folder, not a standalone EXE: its _internal/ Qt DLLs are required.
        with zipfile.ZipFile(result_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            for file in sorted(folder.rglob("*")):
                if file.is_file():
                    z.write(file, arcname=f"{exe_name}/{file.relative_to(folder).as_posix()}")
    else:
        bundle = staging / "dist" / f"{exe_name}.app"
        macos_exe = bundle / "Contents" / "MacOS" / exe_name
        if not macos_exe.is_file():
            raise RuntimeError(f"PyInstaller .app executable missing: {macos_exe}")
        resources = bundle / "Contents" / "Resources"
        (resources / "RELEASE_INFO.json").write_text(json.dumps(release_info, indent=2) + "\n", encoding="utf-8")
        info_path = bundle / "Contents" / "Info.plist"
        with info_path.open("rb") as stream:
            info = plistlib.load(stream)
        base_version = args.tag[1:].split("-beta.")[0]
        info.update(CFBundleShortVersionString=base_version, CFBundleVersion=base_version,
                    CFBundleIdentifier=bundle_id, CFBundleName=exe_name)
        with info_path.open("wb") as stream:
            plistlib.dump(info, stream)
        # Ad-hoc signature: not a Developer ID signature and not notarization.
        run(["codesign", "--force", "--deep", "--sign", "-", str(bundle)])
        run(["codesign", "--verify", "--deep", str(bundle)])
        run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", str(bundle), str(result_zip)])

    if not result_zip.is_file() or not result_zip.stat().st_size:
        raise RuntimeError("Release artifact is missing or empty")
    with zipfile.ZipFile(result_zip) as z:
        if z.testzip():
            raise RuntimeError("ZIP CRC verification failed")
    digest = hashlib.file_digest(result_zip.open("rb"), "sha256").hexdigest()
    print(json.dumps({"artifact": str(result_zip), "bytes": result_zip.stat().st_size,
                      "sha256": digest, "edition": args.edition, "tag": args.tag}, indent=2), flush=True)


if __name__ == "__main__":
    main()