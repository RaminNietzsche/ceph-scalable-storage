#!/usr/bin/env bash
# Bootstrap a one-host cluster with --single-host-defaults. Skips if this host
# already has a cluster configuration in /etc/ceph.
set -euo pipefail
# shellcheck source=SCRIPTDIR/lib.sh
. "$(dirname "$0")/lib.sh"

USAGE="Usage: $0 [--help] [--dry-run]
Runs 'cephadm bootstrap --mon-ip MON_IP --single-host-defaults'. The flag sets
osd_crush_chooseleaf_type=0, osd_pool_default_size=2 and
mgr_standby_modules=false, so replicas may share this host. Lab use only."
parse_common "$USAGE" "$@"
load_env
need_root

if query test -s /etc/ceph/ceph.conf && query ceph_cli fsid >/dev/null 2>&1; then
  log "a cluster already exists here (fsid $(ceph_cli fsid)); skipping bootstrap"
  exit 0
fi

run cephadm bootstrap --mon-ip "$MON_IP" --single-host-defaults
log "bootstrap finished; the dashboard URL and the initial password were printed above"
