#!/usr/bin/env bash
# Wait for HEALTH_OK (up to LAB_WAIT seconds, default 900), then print the state
# and run a short RBD write benchmark. Writes only to lab-rbd/img1.
set -euo pipefail
# shellcheck source=SCRIPTDIR/lib.sh
. "$(dirname "$0")/lib.sh"

USAGE="Usage: $0 [--help] [--dry-run]
Polls 'ceph health' until HEALTH_OK or LAB_WAIT seconds (default 900), prints
'ceph -s', 'ceph osd tree' and 'ceph orch ps', and runs a 64 MiB 'rbd bench'
write to lab-rbd/img1."
parse_common "$USAGE" "$@"
load_env
need_root

wait_s="${LAB_WAIT:-900}"
if [[ "$DRY_RUN" != "1" ]]; then
  deadline=$((SECONDS + wait_s))
  until [[ "$(ceph_cli health)" == HEALTH_OK* ]]; do
    if (( SECONDS >= deadline )); then
      ceph_cli health detail || true
      die "not HEALTH_OK after ${wait_s}s"
    fi
    sleep 15
  done
fi
run cephadm shell -- ceph -s
run cephadm shell -- ceph osd tree
run cephadm shell -- ceph orch ps
run cephadm shell -- rbd bench --io-type write --io-size 4M --io-total 64M lab-rbd/img1
log "verify finished"
