#!/bin/sh
set -eu
cd -P "$(dirname "$0")"
archive='2byteasr-0.8.1-docker.1.tar'
sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | cut -d ' ' -f 1
    else
        shasum -a 256 "$1" | cut -d ' ' -f 1
    fi
}
verify() {
    test -f "$1" || { printf 'Missing file: %s\n' "$1" >&2; exit 1; }
    test "$(sha256 "$1")" = "$2" || { printf 'Checksum mismatch: %s\n' "$1" >&2; exit 1; }
    printf 'Verified %s\n' "$1"
}
verify "$archive.part01" 'f98df15a4aa4e3dd4b460e345bd7f753a296558b7e3a9974827e90d0c02bd71f'
verify "$archive.part02" '5a7db7b538d52770f63c22a642f129c0ea88a8b69eb5b6b2cadd208807a015dd'
if ! test -e "$archive"; then
    (set -C; cat "$archive.part01" "$archive.part02" > "$archive")
fi
verify "$archive" '1c2dcb24f5d74f6dd7cd6d469c78209165b10bb754f13895c58abd81256561c5'
if test "${1:-}" != '--verify-only'; then
    docker load -i "$archive"
    printf '%s\n' 'Next: docker compose up -d --no-build'
fi
