"""Offline tests for release packaging: never run unpacked applications."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import plistlib
import struct
import tempfile
import unittest
import warnings
from zipfile import ZipFile, ZipInfo

SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "prepare_beta_release.py"
spec = importlib.util.spec_from_file_location("prepare_beta_release", SOURCE)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def win_binary() -> bytes:
    binary = bytearray(256)
    binary[:2] = b"MZ"
    struct.pack_into("<I", binary, 0x3C, 0x80)
    binary[0x80:0x84] = b"PE\0\0"
    struct.pack_into("<H", binary, 0x84, 0x8664)
    return bytes(binary)


def create_windows(path: Path, version: str = "0.4.0", source: bytes = b"pass\n"):
    root = "OperatorComplexNewInterface"
    data = {
        f"{root}.exe": win_binary(),
        f"Start-{root}.bat": b"echo runtime\n",
        "runtime/python.exe": b"runtime-embedded",
        "app/operator_stub/demo.py": source,
    }
    for index in range(8):
        data[f"LICENSES/{index}.txt"] = str(index).encode()
    manifest = {
        "application_version": version,
        "target": "Windows 10 1809+/Windows 11 x86_64",
        "verification": {"windows_execution_tested": False},
        "files": {key: {"sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)} for key,value in data.items()},
    }
    with ZipFile(path, "w") as zipf:
        for name, value in data.items():
            zipf.writestr(f"{root}/{name}", value)
        zipf.writestr(f"{root}/build-manifest.json", json.dumps(manifest))


def create_macos(path: Path, version: str = "0.4.0", cpu: int = 0x0100000C):
    root = "OperatorComplexNewInterface.app"
    info = {
        "CFBundleShortVersionString": version,
        "CFBundleExecutable": "OperatorComplexNewInterface",
        "LSMinimumSystemVersion": "14.4",
    }
    exe = ZipInfo(f"{root}/Contents/MacOS/OperatorComplexNewInterface")
    exe.external_attr = (0o100755 << 16)
    with ZipFile(path, "w") as zipf:
        zipf.writestr(f"{root}/Contents/Info.plist", plistlib.dumps(info))
        zipf.writestr(exe, b"\xcf\xfa\xed\xfe" + struct.pack("<I", cpu) + b"12345")
        zipf.writestr(f"{root}/Contents/Resources/config/demo_platforms.json", b"{}")
        for name in ("lidar-room", "sonar-route", "mixed-route"):
            zipf.writestr(f"{root}/Contents/Resources/examples/{name}.txt", b"test")


class ReleaseValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)
        self.win = self.path / "Windows.zip"
        self.mac = self.path / "Mac.zip"
        create_windows(self.win)
        create_macos(self.mac)

    def test_valid_pair_and_source_blob_hash(self):
        source_tree = {"tree": [{"path": "operator_stub/demo.py", "type": "blob", "sha": release.git_blob_sha(b"pass\n")} ]}
        checked = release.verify_windows(self.win, "0.4.0", source_tree)
        self.assertEqual(checked["source_files_matched"], 1)
        self.assertEqual(checked["files_verified"], 12)
        self.assertFalse(checked["runtime_verified_on_real_windows"])
        self.assertEqual(release.verify_macos(self.mac, "0.4.0")["minimum_macos"], "14.4")

    def test_version_mismatch_does_not_allow_stale_release(self):
        for archive, verifier in ((self.win, release.verify_windows), (self.mac, release.verify_macos)):
            with self.subTest(archive=archive.name), self.assertRaisesRegex(release.ArchiveError, "Wrong"):
                verifier(archive, "0.5.0", None) if verifier is release.verify_windows else verifier(archive, "0.5.0")

    def test_changed_source_is_rejected(self):
        tree = {"tree": [{"path": "operator_stub/demo.py", "type": "blob", "sha": release.git_blob_sha(b"not the packaged source")}]}
        with self.assertRaisesRegex(release.ArchiveError, "stale"):
            release.verify_windows(self.win, "0.4.0", tree)

    def test_windows_wrong_cpu_architecture(self):
        wrong = self.path / "wrong-arch.zip"
        root = "OperatorComplexNewInterface"
        with ZipFile(self.win) as source, ZipFile(wrong, "w") as output:
            for item in source.infolist():
                content = source.read(item)
                if item.filename.endswith(".exe") and item.filename == f"{root}/{root}.exe":
                    content = bytearray(content)
                    struct.pack_into("<H", content, 0x84, 0x14c)
                    content = bytes(content)
                output.writestr(item, content)
        with self.assertRaisesRegex(release.ArchiveError, "Expected Windows x64 PE"):
            release.verify_windows(wrong, "0.4.0", None)

    def test_macos_wrong_architecture(self):
        wrong = self.path / "IntelMac.zip"
        create_macos(wrong, cpu=0x01000007)
        with self.assertRaisesRegex(release.ArchiveError, "Expected Apple Silicon"):
            release.verify_macos(wrong, "0.4.0")

    def test_zip_slip_is_blocked(self):
        bad = self.path / "path-traversal.zip"
        with ZipFile(bad, "w") as z:
            z.writestr("../secret.txt", "nope")
        with ZipFile(bad) as z, self.assertRaisesRegex(release.ArchiveError, "Unsafe archive entry"):
            release.verify_zip(z)

    def test_duplicate_entry_name_is_blocked(self):
        bad = self.path / "dup.zip"
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            with ZipFile(bad, "w") as z:
                z.writestr("same.txt", "first")
                z.writestr("same.txt", "second")
        with ZipFile(bad) as z, self.assertRaisesRegex(release.ArchiveError, "Duplicate ZIP entry"):
            release.verify_zip(z)

    def test_staging_writes_exactly_two_archives_and_checksum_file(self):
        output = self.path / "stage"
        release.prepare(["v0.4.0-beta.1", str(self.win), str(self.mac), "--output", str(output)])
        names = {p.name for p in output.iterdir()}
        self.assertEqual(names, {
            "OperatorComplex-v0.4.0-beta.1-Windows-x64.zip",
            "OperatorComplex-v0.4.0-beta.1-macOS-arm64.zip",
            "SHA256SUMS.txt", "RELEASE_NOTES.md",
        })
        checksum = (output / "SHA256SUMS.txt").read_text()
        self.assertIn(release.sha256_path(self.win), checksum)
        self.assertIn(release.sha256_path(self.mac), checksum)
        # Idempotent only for byte-identical archives: never silently overwrite.
        release.prepare(["v0.4.0-beta.1", str(self.win), str(self.mac), "--output", str(output)])
        (output / "OperatorComplex-v0.4.0-beta.1-Windows-x64.zip").write_bytes(b"tampered")
        with self.assertRaisesRegex(release.ArchiveError, "Refusing to overwrite"):
            release.prepare(["v0.4.0-beta.1", str(self.win), str(self.mac), "--output", str(output)])

    def test_invalid_beta_tags(self):
        for tag in ("v0.4.0", "v0.4.0-beta.0", "snapshot/v0.4", "v0.4.0-beta.1/evil"):
            with self.subTest(tag=tag), self.assertRaisesRegex(release.ArchiveError, "Use vMAJOR"):
                release.prepare([tag, str(self.win), str(self.mac)])


if __name__ == "__main__":
    unittest.main()