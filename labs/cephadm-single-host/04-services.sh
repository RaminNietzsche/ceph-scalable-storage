#!/usr/bin/env bash
# Create one of each interface: an RBD pool and image, a CephFS volume, and an RGW
# service with one S3 user. Each step checks first and skips what already exists.
set -euo pipefail
# shellcheck source=SCRIPTDIR/lib.sh
. "$(dirname "$0")/lib.sh"

USAGE="Usage: $0 [--help] [--dry-run]
Creates pool lab-rbd with image img1 (1 GiB), CephFS volume labfs, RGW service
lab and RGW user lab. Already existing items are left unchanged."
parse_common "$USAGE" "$@"
load_env
need_root

if query ceph_cli osd pool ls 2>/dev/null | grep -qx lab-rbd; then
  log "pool lab-rbd exists"
else
  run cephadm shell -- ceph osd pool create lab-rbd
  run cephadm shell -- rbd pool init lab-rbd
fi

if query cephadm shell -- rbd info lab-rbd/img1 >/dev/null 2>&1; then
  log "image lab-rbd/img1 exists"
else
  run cephadm shell -- rbd create lab-rbd/img1 --size 1G
fi

if query ceph_cli fs ls 2>/dev/null | grep -q 'name: labfs,'; then
  log "file system labfs exists"
else
  run cephadm shell -- ceph fs volume create labfs
fi

# 'ceph orch apply' is declarative: applying the same spec again changes nothing.
run cephadm shell -- ceph orch apply rgw lab --placement=1

if query cephadm shell -- radosgw-admin user info --uid lab >/dev/null 2>&1; then
  log "RGW user lab exists"
else
  run cephadm shell -- radosgw-admin user create --uid lab --display-name "Lab user"
fi
log "services requested; see their state with: cephadm shell -- ceph orch ps"
