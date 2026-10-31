# Xcode cache

A composite GitHub Action that restores or saves Xcode DerivedData, SwiftPM checkouts,
and the source modification times needed to reuse cached build products.

The action uses `actions/cache` for cache transport and a Python 3 script for timestamp
metadata. It requires `python3` on the runner and has no third-party Python dependencies.
Xcode's command-line tools provide Python on macOS.

Source timestamps are stored and restored as integer nanoseconds. Restoration only
updates existing paths whose content hashes still match the cached metadata. The
metadata remains compatible with caches written by the previous Ruby implementation.

`mtime-targets` accepts additional newline-separated glob patterns, including `**/`
and brace alternatives such as `App/**/*.{pbxproj,xcconfig}`. Recursive matching skips
hidden directories and directory symlinks unless explicitly targeted. DerivedData and
SwiftPM checkout directories are excluded from source metadata.
