#!/usr/bin/env bash
# Destroy the lab cluster on this host and zap its OSD disks, following the
# "Purging a cluster" steps of the cephadm documentation.
set -euo pipefail
# shellcheck source=SCRIPTDIR/lib.sh
. "$(dirname "$0")/lib.sh"

USAGE="Usage: $0 --yes-really-destroy [--help] [--dry-run]
Disables the cephadm mgr module, reads the fsid, and runs
'cephadm rm-cluster --force --zap-osds --fsid FSID'. All data in the cluster
and on its OSD disks is lost. Does nothing if no cluster is found."
parse_common "$USAGE" "$@"
load_env
need_root

confirmed=0
for arg in "$@"; do
  if [[ "$arg" == "--yes-really-destroy" ]]; then
    confirmed=1
  fi
done
if [[ "$confirmed" -ne 1 && "$DRY_RUN" != "1" ]]; then
  die "refusing to destroy without --yes-really-destroy"
fi

fsid="FSID"
if query test -s /etc/ceph/ceph.conf; then
  fsid="$(ceph_cli fsid)"
elif [[ "$DRY_RUN" != "1" ]]; then
  log "no /etc/ceph/ceph.conf on this host; nothing to remove"
  exit 0
fi

run cephadm shell -- ceph mgr module disable cephadm
run cephadm rm-cluster --force --zap-osds --fsid "$fsid"
log "cluster $fsid removed"
