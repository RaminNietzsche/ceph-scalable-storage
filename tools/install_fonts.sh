#!/usr/bin/env bash
# Install the book fonts unless fontconfig already finds them. No root needed:
#   Linux: ~/.local/share/fonts/ceph-scalable-storage
#   macOS: ~/Library/Fonts/ceph-scalable-storage (scanned by Homebrew fontconfig)
# Override with FONT_DIR=... . Versions are pinned. Debian/Ubuntu users can instead run
#   apt-get install fonts-vazirmatn fonts-inter fonts-jetbrains-mono fonts-dejavu-core
# Source Serif has no Debian package and is always fetched from the Adobe release.
#   tools/install_fonts.sh          install whatever is missing
#   tools/install_fonts.sh --check  only report; exit 1 if any font is missing
# `make fonts` (a prerequisite of pdf, html and site) runs this only when needed.
set -euo pipefail

command -v fc-match >/dev/null || {
  echo "fonts: fontconfig (fc-match) not found; install it first (apt-get install fontconfig / brew install fontconfig)" >&2
  exit 1
}

# family|substring the matched file name must contain (same test as tools/build_site.py)
SPECS=("Vazirmatn|vazirmatn" "Inter|inter" "JetBrains Mono|jetbrains" "Source Serif 4,Source Serif Pro|sourceserif")

have() {  # family[,alternative...] needle
  local fam f
  IFS=, read -r -a fams <<<"$1"
  for fam in "${fams[@]}"; do
    f="$(fc-match -f '%{file}' "$fam" 2>/dev/null || true)"
    f="$(basename "$f" | tr '[:upper:]' '[:lower:]' | tr -d ' _-')"
    [[ "$f" == *"$2"* ]] && return 0
  done
  return 1
}

missing() {
  local s out=()
  for s in "${SPECS[@]}"; do have "${s%%|*}" "${s#*|}" || out+=("${s%%[|,]*}"); done
  printf '%s\n' "${out[@]+"${out[@]}"}"
}

if [[ "${1:-}" == "--check" ]]; then
  m="$(missing)"
  if [[ -n "$m" ]]; then echo "fonts: missing: $(echo "$m" | paste -sd, -)"; exit 1; fi
  echo "fonts: ok"; exit 0
fi

if [[ "$(uname -s)" == Darwin ]]; then DEF="$HOME/Library/Fonts/ceph-scalable-storage"
else DEF="$HOME/.local/share/fonts/ceph-scalable-storage"; fi
DEST="${FONT_DIR:-$DEF}"
mkdir -p "$DEST"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

fetch_zip() {  # name url glob
  echo "fonts: fetching $1"
  curl -fsSL -o "$tmp/$1.zip" "$2"
  unzip -q -o "$tmp/$1.zip" -d "$tmp/$1"
  find "$tmp/$1" -type f -ipath "$3" -exec cp {} "$DEST/" \;
}

have Vazirmatn vazirmatn       || fetch_zip vazirmatn https://github.com/rastikerdar/vazirmatn/releases/download/v33.003/vazirmatn-v33.003.zip '*/fonts/ttf/*.ttf'
have Inter inter               || fetch_zip inter https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip '*Inter*.ttf'
have "JetBrains Mono" jetbrains || fetch_zip jetbrains https://github.com/JetBrains/JetBrainsMono/releases/download/v2.304/JetBrainsMono-2.304.zip '*/fonts/[tv]*/*.ttf'
have "Source Serif 4,Source Serif Pro" sourceserif || fetch_zip sourceserif https://github.com/adobe-fonts/source-serif/releases/download/4.005R/source-serif-4.005_Desktop.zip '*/TTF/*.ttf'
fc-cache -f "$DEST" >/dev/null 2>&1 || fc-cache -f >/dev/null 2>&1 || true

m="$(missing)"
if [[ -n "$m" ]]; then
  echo "fonts: still not found by fontconfig after install: $(echo "$m" | paste -sd, -)" >&2
  echo "fonts: make sure $DEST is in a directory fontconfig scans (fc-list : file | grep $DEST), or set FONT_DIR" >&2
  exit 1
fi
echo "fonts: ok ($DEST)"
