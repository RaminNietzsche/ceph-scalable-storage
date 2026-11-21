#!/usr/bin/env bash
# Install the cephadm binary for CEPH_RELEASE, as in the "Using curl" method of the
# cephadm installation guide. Skips if cephadm is already in PATH.
set -euo pipefail
# shellcheck source=SCRIPTDIR/lib.sh
. "$(dirname "$0")/lib.sh"

USAGE="Usage: $0 [--help] [--dry-run]
Downloads cephadm for CEPH_RELEASE from download.ceph.com into /usr/local/sbin.
Does nothing if a cephadm command is already installed."
parse_common "$USAGE" "$@"
load_env
need_root

if query command -v cephadm >/dev/null 2>&1; then
  log "cephadm already installed: $(command -v cephadm); skipping"
  exit 0
fi

url="https://download.ceph.com/rpm-${CEPH_RELEASE}/el9/noarch/cephadm"
tmp="$(mktemp)"
trap 'rm -f "$tmp"' EXIT
run curl --fail --silent --show-error --location -o "$tmp" "$url"
run install -m 0755 "$tmp" /usr/local/sbin/cephadm
run /usr/local/sbin/cephadm version
log "cephadm installed"
