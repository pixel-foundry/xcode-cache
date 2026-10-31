#!/usr/bin/env python3
"""Store and restore source mtimes with integer nanosecond precision."""

import argparse
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import sys


METADATA_FILENAME = "xcode-cache-mtime.json"
DEFAULT_PATTERNS = """
    **/*.swift **/*.xib **/*.storyboard **/*.strings **/*.xcstrings **/*.plist
    **/*.intentdefinition **/*.json **/*.xcassets **/*.xcassets/**/* **/*.bundle
    **/*.bundle/**/* **/*.xcdatamodel **/*.xcdatamodel/**/* **/*.framework
    **/*.framework/**/* **/*.xcframework **/*.xcframework/**/* **/*.m **/*.mm
    **/*.h **/*.c **/*.cc **/*.cpp **/*.hpp **/*.hxx
""".split()


def digest_for(path):
    digest = hashlib.sha256()
    if path.is_dir():
        digest.update("".join(sorted(child.name for child in path.iterdir())).encode())
    else:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    return digest.hexdigest()


def expand_braces(pattern):
    """Preserve Ruby glob alternatives, including nested braces."""
    match = re.search(r"\{([^{}]*)\}", pattern)
    if match is None:
        yield pattern
        return
    for alternative in match.group(1).split(","):
        expanded = pattern[:match.start()] + alternative + pattern[match.end():]
        yield from expand_braces(expanded)


def is_excluded(path, excluded):
    absolute_path = Path(os.path.abspath(path))
    return any(root == absolute_path or root in absolute_path.parents for root in excluded)


def glob_paths(pattern, excluded):
    # Ruby's **/ skips hidden directories and does not follow directory symlinks.
    # os.walk preserves that behavior; ordinary glob handles each remaining segment.
    recursive = re.search(r"(?:^|/)\*\*/", pattern)
    if recursive is None:
        yield from glob.iglob(pattern)
        return
    prefix = pattern[:recursive.end() - 3]
    suffix = pattern[recursive.end():]
    for root in glob.iglob(prefix or "."):
        if is_excluded(root, excluded):
            continue
        for current, directories, _ in os.walk(root, followlinks=False):
            directories[:] = [
                name for name in directories
                if not name.startswith(".")
                and not is_excluded(Path(current) / name, excluded)
            ]
            yield from glob_paths(os.path.join(glob.escape(current), suffix), excluded)


def store():
    derived_data = Path(os.path.abspath(os.environ["DERIVED_DATA_PATH"]))
    source_packages = Path(os.path.abspath(os.environ["SOURCE_PACKAGES_PATH"]))
    workspace = Path(os.path.abspath(os.environ.get("GITHUB_WORKSPACE", os.getcwd())))
    if not derived_data.is_dir():
        print(
            f"DerivedData does not exist at {derived_data}; skipping mtime metadata.",
            file=sys.stderr,
        )
        return

    custom_patterns = [
        line.strip() for line in os.environ.get("MTIME_TARGETS", "").splitlines()
        if line.strip()
    ]
    excluded = (derived_data, source_packages)
    paths = set()
    for pattern in DEFAULT_PATTERNS + custom_patterns:
        for expanded in expand_braces(pattern):
            absolute_pattern = os.path.join(glob.escape(str(workspace)), expanded)
            for match in glob_paths(absolute_pattern, excluded):
                path = Path(match)
                if path.exists() and not is_excluded(path, excluded):
                    paths.add(os.path.relpath(path, workspace))

    metadata = []
    for relative_path in sorted(paths):
        path = workspace / relative_path
        seconds, nanoseconds = divmod(path.stat().st_mtime_ns, 1_000_000_000)
        metadata.append({
            "path": relative_path,
            "time": f"{seconds}.{nanoseconds:09d}",
            "sha256": digest_for(path),
        })

    (derived_data / METADATA_FILENAME).write_text(
        json.dumps(metadata, ensure_ascii=False), encoding="utf-8"
    )
    print(f"Stored {len(metadata)} source mtimes.")


def restore():
    metadata_path = Path(os.environ["DERIVED_DATA_PATH"]) / METADATA_FILENAME
    if not metadata_path.is_file():
        print(f"No source mtime metadata found at {metadata_path}.")
        return

    restored = 0
    for entry in json.loads(metadata_path.read_text(encoding="utf-8")):
        path = Path(entry["path"])
        if not path.exists() or digest_for(path) != entry["sha256"]:
            continue

        seconds, nanoseconds = entry["time"].split(".", 1)
        timestamp = int(seconds) * 1_000_000_000 + int(nanoseconds)
        # Integer nanoseconds avoid both float rounding and Ruby's microsecond truncation.
        os.utime(path, ns=(timestamp, timestamp))
        restored += 1

    print(f"Restored {restored} source mtimes.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("store", "restore"))
    arguments = parser.parse_args()
    {"store": store, "restore": restore}[arguments.operation]()
