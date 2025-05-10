#!/usr/bin/env bash
# Install the book fonts into ~/.local/share/fonts (no root needed) unless fontconfig
# already finds them. Versions are pinned; Debian/Ubuntu users can instead run
#   apt-get install fonts-vazirmatn fonts-inter fonts-jetbrains-mono fonts-dejavu-core
# Source Serif has no Debian package and is always fetched from the Adobe release.
set -euo pipefail
DEST="${FONT_DIR:-$HOME/.local/share/fonts/ceph-scalable-storage}"
mkdir -p "$DEST"
tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' EXIT

have() { fc-list : family | grep -qi "$1"; }

fetch_zip() {  # name url glob
  echo "fonts: fetching $1"
  curl -fsSL -o "$tmp/$1.zip" "$2"
  unzip -q -o "$tmp/$1.zip" -d "$tmp/$1"
  find "$tmp/$1" -type f -ipath "$3" -exec cp {} "$DEST/" \;
}

have Vazirmatn      || fetch_zip vazirmatn https://github.com/rastikerdar/vazirmatn/releases/download/v33.003/vazirmatn-v33.003.zip '*/fonts/ttf/*.ttf'
have "^Inter"       || fetch_zip inter https://github.com/rsms/inter/releases/download/v4.1/Inter-4.1.zip '*Inter*.ttf'
have "JetBrains Mono" || fetch_zip jetbrains https://github.com/JetBrains/JetBrainsMono/releases/download/v2.304/JetBrainsMono-2.304.zip '*/fonts/ttf/*.ttf'
have "Source Serif" || fetch_zip sourceserif https://github.com/adobe-fonts/source-serif/releases/download/4.005R/source-serif-4.005_Desktop.zip '*/TTF/*.ttf'
fc-cache -f "$DEST" >/dev/null
echo "fonts: ok ($DEST)"
