#!/usr/bin/env python3
"""Validate two portable desktop ZIPs and stage one copy of each for GitHub Releases.

This tool neither executes uploaded binaries nor uploads anything. Python 3.11+.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import plistlib
import re
import shutil
import struct
import sys
from zipfile import ZipFile

RELEASE_VERSION = re.compile(r"^v(?P<app_version>\d+\.\d+\.\d+)-beta\.(?P<number>[1-9]\d*)$")
REPO = "Hazernit/operator-complex-python"
CHUNK_SIZE = 1024 * 1024


class ArchiveError(ValueError):
    """Unsafe, incomplete, wrong-version or duplicate build."""


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for piece in iter(lambda: stream.read(CHUNK_SIZE), b""):
            digest.update(piece)
    return digest.hexdigest()


def verify_zip(z: ZipFile) -> None:
    names = [record.filename for record in z.infolist()]
    if len(names) != len(set(names)):
        raise ArchiveError("Duplicate ZIP entry names detected")
    for name in names:
        p = PurePosixPath(name)
        if p.is_absolute() or ".." in p.parts or "\\" in name or not name.strip():
            raise ArchiveError(f"Unsafe archive entry: {name!r}")
    failed = z.testzip()
    if failed:
        raise ArchiveError(f"Broken ZIP CRC: {failed}")


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def verify_windows(path: Path, expected_version: str, source_tree: dict | None) -> dict:
    with ZipFile(path) as z:
        verify_zip(z)
        real_names = [record.filename for record in z.infolist() if not record.is_dir()]
        app_roots = {
            name.split("/", 1)[0]
            for name in real_names if name.endswith("/build-manifest.json") and "/" in name
        }
        if len(app_roots) != 1:
            raise ArchiveError("Windows ZIP must contain exactly one application build-manifest.json")
        app_root = next(iter(app_roots))
        if any(not name.startswith(app_root + "/") for name in real_names):
            raise ArchiveError("Unexpected files outside Windows application directory")
        manifest = json.loads(z.read(f"{app_root}/build-manifest.json"))
        if manifest.get("application_version") != expected_version:
            raise ArchiveError(f"Wrong Windows version: {manifest.get('application_version')!r} vs {expected_version}")
        if manifest.get("target") != "Windows 10 1809+/Windows 11 x86_64":
            raise ArchiveError(f"Unexpected Windows target: {manifest.get('target')!r}")
        names = set(real_names)
        exe = f"{app_root}/{app_root}.exe"
        bat = f"{app_root}/Start-{app_root}.bat"
        if not {exe, bat, f"{app_root}/runtime/python.exe"}.issubset(names):
            raise ArchiveError("Missing Windows .exe/.bat/bundled runtime")
        binary = z.read(exe)
        if binary[:2] != b"MZ" or len(binary) < 0x50:
            raise ArchiveError("Windows launcher is not a PE executable")
        pe_start = struct.unpack_from("<I", binary, 0x3C)[0]
        if binary[pe_start:pe_start + 4] != b"PE\0\0":
            raise ArchiveError("Invalid Windows PE signature")
        machine = struct.unpack_from("<H", binary, pe_start + 4)[0]
        if machine != 0x8664:
            raise ArchiveError(f"Expected Windows x64 PE, machine=0x{machine:x}")
        if b"runtime" not in z.read(bat).lower():
            raise ArchiveError("Diagnostic BAT doesn't reference bundled runtime")
        entries = manifest.get("files")
        if not isinstance(entries, dict) or len(entries) < 10:
            raise ArchiveError("Missing or empty Windows file verification manifest")
        if len(real_names) != len(entries) + 1:
            raise ArchiveError("Windows build file count differs from its manifest")
        for relpath, spec in entries.items():
            key = f"{app_root}/{relpath}"
            if key not in names:
                raise ArchiveError(f"Missing Windows package file: {key}")
            data = z.read(key)
            if len(data) != spec["bytes"] or hashlib.sha256(data).hexdigest() != spec["sha256"]:
                raise ArchiveError(f"Windows package SHA-256 mismatch: {key}")
        verified_git = None
        if source_tree is not None:
            expected = {
                item["path"].removeprefix("operator_stub/"): item["sha"]
                for item in source_tree.get("tree", [])
                if item.get("type") == "blob" and item.get("path", "").startswith("operator_stub/")
                and item.get("path", "").endswith(".py")
            }
            if not expected:
                raise ArchiveError("GitHub tree lacks Python source files")
            for relpath, refsha in expected.items():
                filename = f"{app_root}/app/operator_stub/{relpath}"
                if filename not in names:
                    raise ArchiveError(f"Windows ZIP is missing repository source: {filename}")
                packaged_sha = git_blob_sha(z.read(filename))
                if packaged_sha != refsha:
                    raise ArchiveError(
                        f"Windows ZIP is stale vs selected GitHub commit: operator_stub/{relpath}"
                    )
            verified_git = len(expected)
        return {
            "version": manifest["application_version"],
            "files_verified": len(entries),
            "source_files_matched": verified_git,
            "runtime_verified_on_real_windows": bool(manifest.get("verification", {}).get("windows_execution_tested", False)),
            "exe": exe,
            "bat": bat,
        }


def verify_macos(path: Path, expected_version: str) -> dict:
    with ZipFile(path) as z:
        verify_zip(z)
        all_names = z.namelist()
        app_plists = [n for n in all_names if n.endswith(".app/Contents/Info.plist") and n.count("/") == 2]
        if len(app_plists) != 1:
            raise ArchiveError("macOS ZIP must contain exactly one .app bundle")
        plist_path = app_plists[0]
        app_root = plist_path.split("/", 1)[0]
        info = plistlib.loads(z.read(plist_path))
        if info.get("CFBundleShortVersionString") != expected_version:
            raise ArchiveError(f"Wrong Mac app version: {info.get('CFBundleShortVersionString')!r} vs {expected_version}")
        executable = info.get("CFBundleExecutable")
        if not executable:
            raise ArchiveError("macOS CFBundleExecutable missing")
        binary_path = f"{app_root}/Contents/MacOS/{executable}"
        if binary_path not in all_names:
            raise ArchiveError(f"Mac executable missing: {binary_path}")
        binary = z.read(binary_path)
        if len(binary) < 12 or binary[:4] != b"\xcf\xfa\xed\xfe":
            raise ArchiveError("Expected arm64 Mach-O 64-bit executable")
        cputype = struct.unpack_from("<I", binary, 4)[0]
        if cputype != 0x0100000C:
            raise ArchiveError(f"Expected Apple Silicon arm64 Mach-O, found CPU type {cputype}")
        if not z.getinfo(binary_path).external_attr >> 16 & 0o111:
            raise ArchiveError("macOS binary missing executable permissions in ZIP")
        required = [f"{app_root}/Contents/Resources/config/demo_platforms.json"]
        required += [f"{app_root}/Contents/Resources/examples/{name}.txt" for name in
                     ("lidar-room", "sonar-route", "mixed-route")]
        if any(p not in all_names for p in required):
            raise ArchiveError("Mac app missing one or more bundled sample data files")
        return {
            "version": info["CFBundleShortVersionString"],
            "bundle": app_root,
            "executable": executable,
            "minimum_macos": info.get("LSMinimumSystemVersion", "not stated"),
            "developer_id_notarization_verified": False,
        }


def prepare(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tag", help="e.g. v0.4.0-beta.1")
    parser.add_argument("windows", type=Path, help="portable Windows ZIP (.exe + .bat inside)")
    parser.add_argument("macos", type=Path, help="macOS Apple Silicon ZIP (.app inside)")
    parser.add_argument("--github-tree", type=Path, help="optional GitHub tree JSON to compare all Windows Python sources")
    parser.add_argument("--output", type=Path, help="staging directory; does not upload anything")
    args = parser.parse_args(argv)
    match = RELEASE_VERSION.fullmatch(args.tag)
    if not match:
        raise ArchiveError("Use vMAJOR.MINOR.PATCH-beta.N with N>=1, e.g. v0.4.0-beta.1")
    if not args.windows.is_file() or not args.macos.is_file():
        raise ArchiveError("Both Windows and macOS ZIPs are required")
    if args.windows.resolve() == args.macos.resolve():
        raise ArchiveError("Windows and macOS ZIPs cannot be the same file")
    version = match["app_version"]
    tree = json.loads(args.github_tree.read_text(encoding="utf-8")) if args.github_tree else None
    win = verify_windows(args.windows, version, tree)
    mac = verify_macos(args.macos, version)
    sha_win, sha_mac = sha256_path(args.windows), sha256_path(args.macos)
    if sha_win == sha_mac:
        raise ArchiveError("Duplicate ZIP content: Windows and macOS builds are identical")
    asset_names = [f"OperatorComplex-{args.tag}-Windows-x64.zip", f"OperatorComplex-{args.tag}-macOS-arm64.zip"]
    print(f"Validated {args.tag} for Windows x64 and macOS arm64")
    print(f"Windows: {win['files_verified']} manifest SHA-256 entries OK; "
          f"GitHub-matched app modules: {win['source_files_matched']}; "
          f"native execution verified: {win['runtime_verified_on_real_windows']}")
    print(f"Mac: {mac['bundle']} (macOS {mac['minimum_macos']}+); "
          "Developer ID/notarization not verified")
    print(f"SHA-256 Windows: {sha_win}\nSHA-256 macOS:   {sha_mac}")
    if args.output:
        dest = args.output
        dest.mkdir(parents=True, exist_ok=True)
        for src, name, checksum in ((args.windows, asset_names[0], sha_win),
                                    (args.macos, asset_names[1], sha_mac)):
            target = dest / name
            if target.exists():
                if sha256_path(target) != checksum:
                    raise ArchiveError(f"Refusing to overwrite nonmatching staged file: {target}")
            else:
                shutil.copy2(src, target)
        (dest / "SHA256SUMS.txt").write_text(
            f"{sha_win}  {asset_names[0]}\n{sha_mac}  {asset_names[1]}\n", encoding="utf-8"
        )
        notes = f"""# Operator Complex {args.tag} — публичная бета

**Версия приложения:** {version}. Локальный учебный прототип для БПЛА, НРТК и БЭК, без реального управления оборудованием. Это **Pre-release**, а не стабильный релиз.

## Скачать и запустить

- **Windows 10/11 x64:** `{asset_names[0]}` ({args.windows.stat().st_size / 1024**2:.1f} МиБ). Распакуйте **весь** архив, затем запустите `{win['exe'].split('/')[-1]}`. Для диагностики — `{win['bat'].split('/')[-1]}`; он оставляет сообщения в консоли. Python не требуется: runtime включён в ZIP. Не извлекайте EXE отдельно от папок `runtime` и `app`.
- **macOS Apple Silicon:** `{asset_names[1]}` ({args.macos.stat().st_size / 1024**2:.1f} МиБ). Распакуйте ZIP, откройте `{mac['bundle']}` двойным щелчком или перенесите в «Программы». Поддерживается macOS {mac['minimum_macos']} и новее на Apple Silicon; для Intel Mac нет готового пакета.

**Важные ограничения:** Windows-сборка не проходила подтверждённого нативного запуска на Windows (отмечено в `build-manifest.json`); проверьте её на целевой машине. Подпись Apple Developer ID и нотариальное заверение macOS не подтверждены: Gatekeeper может запросить разрешение для загруженного приложения. [Штатная справка Apple](https://support.apple.com/en-us/102445). Не отключайте системную защиту глобально.

## Обновление

Для перехода к более новой бете скачайте ZIP с **более новым номером** (`beta.2`, `beta.3` и т.д.), полностью распакуйте его в новую папку и запустите новую копию приложения. На Mac замените `.app` в «Программах» после закрытия предыдущей версии. На Windows не заменяйте отдельный EXE в старой папке. Автоматического обновления внутри приложения пока нет.

## Проверки и контрольные суммы

- Windows: {win['files_verified']} файла проверено по `build-manifest.json` и совпали с SHA-256 из ZIP.
- Контрольные суммы публикуемых архивов: `SHA256SUMS.txt` в этом релизе.
- Проверки приложения в GitHub Actions и тестовый запуск Windows-упаковки — **разные виды проверок**. Не следует считать кроссплатформенный CI подтверждением запуска именно приложенного Windows EXE.

Источник: [{REPO}](https://github.com/{REPO}). Код распространяется с лицензиями сторонних компонентов внутри архивов.
"""
        (dest / "RELEASE_NOTES.md").write_text(notes, encoding="utf-8")
        print(f"Staged 2 ZIP files, SHA256SUMS.txt, RELEASE_NOTES.md into {dest}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(prepare())
    except (ArchiveError, OSError, ValueError, KeyError, json.JSONDecodeError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(2)