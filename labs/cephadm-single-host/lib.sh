#!/usr/bin/env bash
# Shared helpers for the single-host cephadm lab. Sourced by the numbered scripts.
# shellcheck shell=bash

LAB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRY_RUN="${DRY_RUN:-0}"

log() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[lab dry-run] %s\n' "$*" >&2
  else
    printf '[lab] %s\n' "$*" >&2
  fi
}
die() { printf '[lab] error: %s\n' "$*" >&2; exit 1; }

# Print a command; run it unless this is a dry run.
run() {
  printf '+ %s\n' "$*" >&2
  if [[ "$DRY_RUN" == "1" ]]; then
    return 0
  fi
  "$@"
}

# Read-only query. In a dry run nothing is queried and the call fails,
# so every "already done?" check reports "not done" and the plan is printed in full.
query() {
  if [[ "$DRY_RUN" == "1" ]]; then
    return 1
  fi
  "$@"
}

# The ceph CLI inside the cephadm container, so ceph-common is not needed on the host.
ceph_cli() {
  cephadm shell -- ceph "$@"
}

load_env() {
  local env_file="${LAB_ENV:-$LAB_DIR/lab.env}"
  if [[ -f "$env_file" ]]; then
    # shellcheck source=/dev/null
    . "$env_file"
  elif [[ "$DRY_RUN" != "1" ]]; then
    die "missing $env_file; copy lab.env.example to lab.env and edit it"
  fi
  CEPH_RELEASE="${CEPH_RELEASE:-tentacle}"
  LAB_HOST="${LAB_HOST:-$(hostname -s)}"
  if [[ "$DRY_RUN" == "1" ]]; then
    # Placeholders so that a dry run can print the plan without a lab.env.
    MON_IP="${MON_IP:-192.0.2.10}"
    LAB_DISKS="${LAB_DISKS:-/dev/vdb /dev/vdc /dev/vdd}"
  fi
  [[ -n "${MON_IP:-}" ]] || die "MON_IP is not set in lab.env"
  [[ -n "${LAB_DISKS:-}" ]] || die "LAB_DISKS is not set in lab.env"
}

need_root() {
  if [[ "$DRY_RUN" != "1" && "$(id -u)" -ne 0 ]]; then
    die "run as root (or set DRY_RUN=1 to print the plan only)"
  fi
}

# Common flags: -h/--help and -n/--dry-run. $1 is the usage text.
parse_common() {
  local usage="$1"
  shift
  local arg
  for arg in "$@"; do
    case "$arg" in
      -h|--help) printf '%s\n' "$usage"; exit 0 ;;
      -n|--dry-run) DRY_RUN=1 ;;
      *) ;;
    esac
  done
}
