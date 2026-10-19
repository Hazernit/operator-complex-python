#!/usr/bin/env bash
# Publish exactly one verified Windows and one macOS portable application ZIP.
# Requires owner-authenticated GitHub CLI (`gh`) and Python 3.11+ on macOS/Linux.
set -euo pipefail
if [[ "$#" -ne 3 ]]; then
  echo "Usage: $0 v0.4.0-beta.1 /path/to/Windows-x64.zip /path/to/macOS-AppleSilicon.zip" >&2
  exit 2
fi
TAG="$1"
if [[ ! "$TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+-beta\.[1-9][0-9]*$ ]]; then
  echo "Invalid beta tag: $TAG (expected v0.4.0-beta.1)" >&2
  exit 2
fi
WIN_ZIP="$2"
MAC_ZIP="$3"
REPO="Hazernit/operator-complex-python"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
for cmd in gh python3; do
  if ! command -v "$cmd" >/dev/null 2>&1; then echo "Missing tool: $cmd" >&2; exit 1; fi
done
gh auth status >/dev/null
# Avoid publishing with the wrong account or duplicating an existing release/tag.
ACCOUNT="$(gh api user --jq '.login')"
if [[ "$(printf '%s' "$ACCOUNT" | tr '[:upper:]' '[:lower:]')" != "hazernit" ]]; then
  echo "Expected GitHub login Hazernit; current login: ${ACCOUNT}" >&2
  exit 1
fi
if gh release view "$TAG" --repo "$REPO" >/dev/null 2>&1; then
  echo "Release ${TAG} already exists; not overwriting or duplicating assets." >&2
  exit 1
fi
if gh api "repos/$REPO/git/ref/tags/$TAG" >/dev/null 2>&1; then
  echo "Tag ${TAG} already exists without a release. Inspect it manually first." >&2
  exit 1
fi
MAIN_SHA="$(gh api "repos/$REPO/git/ref/heads/main" --jq '.object.sha')"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/operator-complex-beta.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
# Verify that all packaged Python modules match current remote main.
gh api "repos/$REPO/git/trees/$MAIN_SHA?recursive=1" > "$STAGE/main-tree.json"
python3 "$ROOT/scripts/prepare_beta_release.py" "$TAG" "$WIN_ZIP" "$MAC_ZIP" \
  --github-tree "$STAGE/main-tree.json" --output "$STAGE/assets"
cat >> "$STAGE/assets/RELEASE_NOTES.md" <<EOF

Снимок исходников GitHub для этой беты: [\`${MAIN_SHA}\`](https://github.com/${REPO}/commit/${MAIN_SHA}).
EOF
printf '\nPublishing ${TAG} as a pre-release at commit %.12s...\n' "$MAIN_SHA"
gh release create "$TAG" \
  "$STAGE/assets/OperatorComplex-$TAG-Windows-x64.zip" \
  "$STAGE/assets/OperatorComplex-$TAG-macOS-arm64.zip" \
  "$STAGE/assets/SHA256SUMS.txt" \
  --repo "$REPO" --target "$MAIN_SHA" --prerelease \
  --title "Operator Complex ${TAG}" \
  --notes-file "$STAGE/assets/RELEASE_NOTES.md"
printf '\nRelease created: https://github.com/%s/releases/tag/%s\n' "$REPO" "$TAG"
printf 'Check that GitHub shows exactly 3 assets (Windows, macOS and SHA256SUMS).\n'