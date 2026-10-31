import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ACTION_ROOT = Path(__file__).resolve().parents[1]
ORIGINAL_MTIME = 1_700_000_000_123_456_789
CHECKOUT_MTIME = 1_800_000_000_987_654_321


class SourceMtimeTests(unittest.TestCase):
    def setUp(self):
        temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        self.workspace = Path(temporary_directory.name)
        self.derived_data = self.workspace / "DerivedData"
        self.derived_data.mkdir()
        self.environment = {
            **os.environ,
            "GITHUB_WORKSPACE": str(self.workspace),
            "DERIVED_DATA_PATH": str(self.derived_data),
            "SOURCE_PACKAGES_PATH": str(self.workspace / "SourcePackages"),
            "MTIME_TARGETS": "",
        }

    def make_source(self):
        path = self.workspace / "Source with spaces.swift"
        path.write_text("let value = 1\n")
        self.set_mtime(path, ORIGINAL_MTIME)
        return path

    def make_assets(self):
        path = self.workspace / "Assets.xcassets"
        path.mkdir()
        (path / "Contents.json").write_text("{}")
        self.set_mtime(path, ORIGINAL_MTIME)
        return path

    def set_mtime(self, path, timestamp):
        os.utime(path, ns=(timestamp, timestamp))
        self.assertEqual(path.stat().st_mtime_ns, timestamp)

    def run_script(self, command):
        result = subprocess.run(
            command,
            cwd=self.workspace,
            env=self.environment,
            capture_output=True,
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result.stdout

    def store(self):
        return self.run_script([sys.executable, str(ACTION_ROOT / "mtimes.py"), "store"])

    def restore(self):
        return self.run_script([sys.executable, str(ACTION_ROOT / "mtimes.py"), "restore"])

    def read_metadata(self):
        return json.loads((self.derived_data / "xcode-cache-mtime.json").read_text())

    def make_file(self, name):
        path = self.workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("example")
        return path

    def test_unchanged_file_restores_exact_nanoseconds(self):
        path = self.make_source()
        self.store()
        metadata = json.loads(
            (self.derived_data / "xcode-cache-mtime.json").read_text()
        )
        self.assertEqual(metadata[0]["path"], path.name)
        self.assertEqual(metadata[0]["time"], "1700000000.123456789")
        self.set_mtime(path, CHECKOUT_MTIME)

        self.assertIn("Restored 1 source mtimes.", self.restore())

        self.assertEqual(path.stat().st_mtime_ns, ORIGINAL_MTIME)

    def test_unchanged_directory_restores_exact_nanoseconds(self):
        path = self.make_assets()
        self.store()
        self.set_mtime(path, CHECKOUT_MTIME)

        self.restore()

        self.assertEqual(path.stat().st_mtime_ns, ORIGINAL_MTIME)

    def test_changed_file_keeps_current_timestamp(self):
        path = self.make_source()
        self.store()
        path.write_text("let value = 2\n")
        self.set_mtime(path, CHECKOUT_MTIME)

        self.assertIn("Restored 0 source mtimes.", self.restore())

        self.assertEqual(path.stat().st_mtime_ns, CHECKOUT_MTIME)

    def test_changed_directory_keeps_current_timestamp(self):
        path = self.make_assets()
        self.store()
        (path / "New.imageset").mkdir()
        self.set_mtime(path, CHECKOUT_MTIME)

        self.restore()

        self.assertEqual(path.stat().st_mtime_ns, CHECKOUT_MTIME)

    def test_deleted_path_is_skipped(self):
        path = self.make_source()
        self.store()
        path.unlink()

        self.assertIn("Restored 0 source mtimes.", self.restore())

        self.assertFalse(path.exists())

    def test_missing_metadata_is_a_no_op(self):
        path = self.make_source()

        self.assertIn("No source mtime metadata found", self.restore())

        self.assertEqual(path.stat().st_mtime_ns, ORIGINAL_MTIME)

    def test_storage_matches_ruby_metadata(self):
        self.make_source()
        assets = self.make_assets()
        self.set_mtime(assets / "Contents.json", ORIGINAL_MTIME)
        self.set_mtime(assets, ORIGINAL_MTIME)

        self.store()

        legacy_metadata = json.loads(
            (ACTION_ROOT / "tests/fixtures/ruby-mtimes.json").read_text()
        )
        self.assertEqual(self.read_metadata(), legacy_metadata)

    def test_restores_existing_ruby_metadata(self):
        source = self.make_source()
        assets = self.make_assets()
        legacy_metadata = (ACTION_ROOT / "tests/fixtures/ruby-mtimes.json").read_text()
        (self.derived_data / "xcode-cache-mtime.json").write_text(legacy_metadata)
        paths = (source, assets / "Contents.json", assets)
        for path in paths:
            self.set_mtime(path, CHECKOUT_MTIME)

        self.assertIn("Restored 3 source mtimes.", self.restore())

        for path in paths:
            self.assertEqual(path.stat().st_mtime_ns, ORIGINAL_MTIME)

    def test_default_globs_include_nested_sources_and_bundle_contents(self):
        expected = {
            "Root.swift", "Sources/Nested/Feature.swift", "Model.xcdatamodel",
            "Model.xcdatamodel/contents", "Assets.xcassets", "Assets.xcassets/image.png",
        }
        for name in expected - {"Model.xcdatamodel", "Assets.xcassets"}:
            self.make_file(name)
        self.make_file("README.md")
        self.make_file(".hidden.swift")
        self.make_file(".hidden/Ignored.swift")

        self.store()

        self.assertEqual({entry["path"] for entry in self.read_metadata()}, expected)

    def test_custom_globs_expand_braces_and_deduplicate(self):
        expected = {
            "App/project.pbxproj", "App/Debug.xcconfig", ".config/settings.txt",
            "ConfigFiles/settings.txt",
        }
        for name in expected:
            self.make_file(name)
        self.environment["MTIME_TARGETS"] = (
            "  App/**/*.{pbxproj,{xcconfig,entitlements}}\n"
            "App/**/*.pbxproj\n\n.config/*.txt\nConfig**/*.txt\n"
        )

        self.store()

        paths = [entry["path"] for entry in self.read_metadata()]
        self.assertEqual(paths, sorted(expected))

    def test_cache_directories_are_excluded_without_excluding_siblings(self):
        source_packages = self.workspace / "SourcePackages"
        for name in (
            "DerivedData/Build/Generated.swift", "SourcePackages/Checkout/Dependency.swift",
            "DerivedDataOther/Source.swift", "SourcePackagesOther/Source.swift",
        ):
            self.make_file(name)
        self.environment["MTIME_TARGETS"] = f"{self.derived_data}/**/*\n{source_packages}/**/*"

        self.store()

        self.assertEqual(
            {entry["path"] for entry in self.read_metadata()},
            {"DerivedDataOther/Source.swift", "SourcePackagesOther/Source.swift"},
        )

    def test_recursive_globs_do_not_follow_directory_symlinks(self):
        self.make_file("Sources/Feature.swift")
        (self.workspace / "Link").symlink_to(self.workspace / "Sources", target_is_directory=True)
        (self.workspace / "Sources/Loop").symlink_to(self.workspace, target_is_directory=True)
        (self.workspace / "Missing.swift").symlink_to(self.workspace / "deleted.swift")

        self.store()

        self.assertEqual([entry["path"] for entry in self.read_metadata()], ["Sources/Feature.swift"])

    def test_workspace_path_can_differ_from_working_directory(self):
        self.make_file("Project [1]/Sources/Feature.swift")
        self.environment["GITHUB_WORKSPACE"] = str(self.workspace / "Project [1]")

        self.store()

        self.assertEqual([entry["path"] for entry in self.read_metadata()], ["Sources/Feature.swift"])

    def test_missing_derived_data_is_a_no_op(self):
        self.derived_data.rmdir()

        self.store()

        self.assertFalse(self.derived_data.exists())


if __name__ == "__main__":
    unittest.main()
