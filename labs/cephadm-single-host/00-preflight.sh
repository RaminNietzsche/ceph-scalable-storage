#!/usr/bin/env bash
# Check the VM before anything is installed. Read-only: changes nothing.
set -euo pipefail
# shellcheck source=SCRIPTDIR/lib.sh
. "$(dirname "$0")/lib.sh"

USAGE="Usage: $0 [--help] [--dry-run]
Checks the host requirements listed in the cephadm documentation (systemd,
Podman or Docker, Python 3, LVM2, time synchronisation) and that every disk
in LAB_DISKS exists and is empty. Changes nothing; exits non-zero on failure.
Runs as root, because reading disk signatures needs it."
parse_common "$USAGE" "$@"
load_env
need_root

fail=0
check() {
  local what="$1"
  shift
  if [[ "$DRY_RUN" == "1" ]]; then
    printf 'would check: %s\n' "$what"
    return 0
  fi
  if "$@" >/dev/null 2>&1; then
    printf 'ok    %s\n' "$what"
  else
    printf 'FAIL  %s\n' "$what"
    fail=1
  fi
}

check "systemd is PID 1" test "$(cat /proc/1/comm 2>/dev/null)" = systemd
check "podman or docker installed" sh -c 'command -v podman || command -v docker'
check "python3 installed" command -v python3
check "python3 is 3.9 or later (needed by Umbrella's cephadm)" python3 -c 'import sys; sys.exit(sys.version_info < (3, 9))'
check "lvm2 installed" command -v lvcreate
check "time synchronisation active" sh -c 'timedatectl show -p NTPSynchronized --value | grep -qx yes'
check "MON_IP $MON_IP is configured on this host" sh -c "ip -o addr show | grep -qw '$MON_IP'"

for disk in $LAB_DISKS; do
  check "$disk is a block device" test -b "$disk"
  check "$disk has no partitions" sh -c "[ \"\$(lsblk -n -o NAME '$disk' | wc -l)\" -eq 1 ]"
  check "$disk has no file system, RAID or LVM signature" sh -c "out=\$(wipefs -n '$disk') && [ -z \"\$out\" ]"
done

if [[ "$fail" -ne 0 ]]; then
  die "preflight failed; fix the FAIL lines above"
fi
log "preflight passed"
