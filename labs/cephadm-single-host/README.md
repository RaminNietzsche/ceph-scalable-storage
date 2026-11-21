# Lab: a single-host Ceph cluster with cephadm

[فارسی](README.fa.md)

This lab builds a small Ceph cluster on one virtual machine with cephadm: three OSDs,
an RBD pool and image, a CephFS volume, and an RGW service with one S3 user. It
follows the official cephadm documentation, and goes with chapters 1 and 11 of the book.

> **Warning.** Lab use only. `--single-host-defaults` lets replicas share one host, so
> this cluster cannot survive the loss of the host and is not a model for production.

## Prerequisites

- A disposable virtual machine (not a container) with **systemd** as PID 1 and a modern
  Linux distribution. Give it enough memory for a MON, a MGR, the monitoring stack and
  three OSDs; each OSD aims to use `osd_memory_target` (4 GiB by default), which you
  can lower for a lab.
- The host requirements from the cephadm documentation: **Podman** (or Docker),
  **Python 3** (3.9 or later for Umbrella's cephadm), **LVM2**, and time
  synchronisation such as chrony.
- **Three spare, empty disks** (for example `/dev/vdb`, `/dev/vdc`,
  `/dev/vdd`). Everything on them is destroyed.
- A fixed IP address on the VM, and internet access to `download.ceph.com` and
  `quay.io` for the cephadm binary and the container images.
- Root access. Do not mount kernel clients (krbd, the CephFS kernel client) on this
  same host: the Ceph documentation warns that this can deadlock; use another VM as
  the client.

## Steps

```bash
cp lab.env.example lab.env          # then set MON_IP and LAB_DISKS
sudo ./00-preflight.sh              # read-only checks; fix every FAIL first
sudo ./01-install-cephadm.sh        # cephadm for CEPH_RELEASE into /usr/local/sbin
sudo ./02-bootstrap.sh              # cephadm bootstrap --single-host-defaults
sudo ./03-osds.sh                   # one OSD per disk in LAB_DISKS
sudo ./04-services.sh               # RBD pool and image, CephFS volume, RGW and a user
sudo ./05-verify.sh                 # wait for HEALTH_OK, print state, short rbd bench
sudo ./99-teardown.sh --yes-really-destroy   # remove the cluster and zap its disks
```

Every script:

- uses `set -euo pipefail` and reads its settings from `lab.env`;
- is **idempotent**: it checks first and skips what already exists, so it is safe to run again;
- accepts `--help`, and `--dry-run` (or `DRY_RUN=1`), which prints the commands it
  would run without querying or changing anything.

## Exercises

After `05-verify.sh` shows HEALTH_OK, try these, each tied to a chapter:

1. Read `ceph -s`, `ceph osd tree` and `ceph df`, and explain every line (chapter 1).
2. Map `lab-rbd/img1` from a second VM and run `rbd bench` from there (chapter 2).
3. Read the S3 keys of the `lab` user with `radosgw-admin user info --uid lab` and use
   them with `aws s3` against the RGW endpoint shown by `ceph orch ps` (chapter 4).
4. Create a CephFS client restricted to one directory with `ceph fs authorize` and
   mount it from a second VM (chapter 6).
5. Stop one OSD with `ceph orch daemon stop osd.0`, watch the PG states, then start it
   again (chapters 7 and 17).
6. Redeploy one OSD as in a disk replacement (chapter 19).

## Tested on

Honest scope of what was validated in this repository:

- Every script passes `shellcheck` (also run in CI on every push).
- `--help` and `--dry-run` were run for every script, and the refusal paths were
  checked: missing `lab.env`, not root, `99-teardown.sh` without
  `--yes-really-destroy`, and `00-preflight.sh` failing on disks that are in use.
- **No end-to-end run on a real VM has been recorded yet.** The commands are taken
  from the cephadm documentation, but until such a run is reported, treat the lab
  as untested in full. Reports and fixes are welcome through issues and pull requests.

## Sources

- cephadm installation (requirements, curl install, single host):
  <https://docs.ceph.com/en/latest/cephadm/install/>
- OSD service (`ceph orch device ls`, `ceph orch daemon add osd`):
  <https://docs.ceph.com/en/latest/cephadm/services/osd/>
- Purging a cluster (`cephadm rm-cluster`):
  <https://docs.ceph.com/en/latest/cephadm/operations/>
- One-node clusters and the kernel-client warning:
  <https://docs.ceph.com/en/latest/rados/troubleshooting/troubleshooting-pg/>
