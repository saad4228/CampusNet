"""Smoke tests for the bundled CampusNet brand assets."""
from pathlib import Path
import struct
import unittest

ASSETS = Path(__file__).resolve().parents[1] / "src" / "campusnet" / "assets"


class BrandAssetTests(unittest.TestCase):
    def test_brand_images_are_bundled(self):
        for name in (
            "campusnet-mark.png",
            "campusnet-mark-white-bg.png",
            "campusnet-wordmark-white-bg.png",
            "campusnet-app-icon.png",
        ):
            with self.subTest(name=name):
                path = ASSETS / name
                self.assertTrue(path.is_file(), f"Missing asset: {name}")
                self.assertGreater(path.stat().st_size, 1000)
                self.assertEqual(path.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")

    def test_windows_icon_has_ico_header(self):
        icon = (ASSETS / "campusnet.ico").read_bytes()
        self.assertEqual(icon[:4], b"\x00\x00\x01\x00")

    def test_macos_icon_has_valid_container_length(self):
        icon = (ASSETS / "campusnet.icns").read_bytes()
        self.assertEqual(icon[:4], b"icns")
        declared_length = struct.unpack(">I", icon[4:8])[0]
        self.assertEqual(declared_length, len(icon))


if __name__ == "__main__":
    unittest.main()
