#!/usr/bin/env bash
# Create one OSD on each disk in LAB_DISKS. Disks that cephadm no longer lists as
# available (for example because they already hold an OSD) are skipped.
set -euo pipefail
# shellcheck source=SCRIPTDIR/lib.sh
. "$(dirname "$0")/lib.sh"

USAGE="Usage: $0 [--help] [--dry-run]
For each disk in LAB_DISKS, runs 'ceph orch daemon add osd HOST:DISK' if
'ceph orch device ls' reports the disk as available. Everything on those
disks is destroyed."
parse_common "$USAGE" "$@"
load_env
need_root

available=""
if query true; then
  available="$(ceph_cli orch device ls "$LAB_HOST" --refresh --format json | python3 -c '
import json, sys
for host in json.load(sys.stdin):
    for dev in host.get("devices", []):
        if dev.get("available"):
            print(dev.get("path"))
')"
fi

for disk in $LAB_DISKS; do
  if [[ "$DRY_RUN" == "1" ]] || grep -qx "$disk" <<<"$available"; then
    run cephadm shell -- ceph orch daemon add osd "$LAB_HOST:$disk"
  else
    log "$disk is not listed as available (already an OSD, or not empty); skipping"
  fi
done
log "OSD requests sent; watch them with: cephadm shell -- ceph osd tree"
