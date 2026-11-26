---
id: upgrade
lang: en
---

::: {.tldr}

- Move one major release at a time, to the latest point release of each: Reef 18.2 → Squid 19.2 → Tentacle 20.2. From Squid 19.2.6 or later, go only to Tentacle 20.2.4 or later.
- Before each step: `HEALTH_OK`, every PG `active+clean`, a backup of keyrings, config and maps, and free capacity for one failure domain.
- cephadm keeps the order for you (mgr, mon, crash, osd, mds, rgw, then the rest) and raises `require_osd_release` at the end; that flag, and every new on-disk feature you enable, is one-way.
- Squid 19.2.6 and Tentacle 20.2.4 add the `aes256k` cephx key type: cephadm rotates the daemon keys, but the client keys are yours to rotate, and the old type must stay allowed until the last client has a new key.

```bash
ceph orch upgrade start --ceph-version 19.2.7
```

[![The upgrade path: checks before the upgrade, Reef to Squid, the cephx key types, then Squid to Tentacle, with require-osd-release as the one-way step of each release](figures/app/f01_upgrade_path.png)](#fig-app-upgrade-path)

:::

This appendix is a runbook for taking a production cluster from Reef (18.2) through Squid (19.2) to Tentacle (20.2). Chapter 19 explains how a cephadm upgrade works; here the same mechanism is laid out as a procedure, with the checks to run before each step, the release changes that can break something on the way, and an honest account of what can be undone. The point releases named here (Squid 19.2.7 and Tentacle 20.2.5) are the latest ones at the time of writing; before you start, check docs.ceph.com/en/latest/releases and use the latest point release of the target series. Key upgrade and key-rotation commands are also summarized in [Appendix B: Command Cheat Sheet](#appB).

![The upgrade path in four stages: checks before the upgrade; Reef to the latest Squid point release in the cephadm order, ending with require-osd-release squid; moving the cephx keys to aes256k; and Squid to Tentacle 20.2.4 or later, ending with require-osd-release tentacle. The two require-osd-release steps are one-way](figures/app/f01_upgrade_path.png){#fig-app-upgrade-path}

# Supported paths

Ceph supports an upgrade across at most two major releases, and only to the latest point release of the target series: a release is tested only against the releases that existed when it shipped.

| From | To | Supported? | Notes |
|---|---|---|---|
| Quincy 17.2 | Squid 19.2 | Yes | The Squid notes allow Quincy or Reef as the starting point |
| Reef 18.2 | Squid 19.2 | Yes | The first step of this appendix |
| Reef 18.2 | Tentacle 20.2 | Yes | Allowed by the Tentacle notes; a two-step path through Squid is easier to stop and verify |
| Squid 19.2 | Tentacle 20.2 | Yes | The second step of this appendix |
| Squid 19.2.6 or later | Tentacle earlier than 20.2.4 | No | Tentacle daemons before 20.2.4 do not know the new key types and fail to start |
| Quincy or older | Tentacle 20.2 | No | First upgrade to Reef or Squid |
| Any release | An earlier major release | No | There is no downgrade; see "Pausing, stopping and rolling back" |

::: {.note}
Two steps take longer than one, but each step ends with a stable, fully supported cluster on which you can run for a few days, and each step has fewer simultaneous changes to debug.
:::

# Pre-upgrade checklist

Run the whole list before each step, not only before the first one. Nothing in the list changes the cluster except the flags at the end.

| Check | Command | Expected / why |
|---|---|---|
| Overall health | `ceph health detail` | `HEALTH_OK`, or only warnings you understand and have muted with an expiry |
| PG state | `ceph pg stat` | Every PG `active+clean`; no `down`, `recovering`, `incomplete`, `undersized` or `backfilling` PGs |
| Daemon versions | `ceph versions` | One version per daemon type; finish any earlier upgrade first |
| Hosts | `ceph orch host ls` | Every host online and none in maintenance; cephadm refuses to start otherwise |
| Monitor quorum | `ceph quorum_status --format json-pretty` | Every monitor in quorum, so one can restart at a time |
| Standby manager | `ceph mgr stat` | At least one standby mgr; without it cephadm raises `UPGRADE_NO_STANDBY_MGR` |
| `require_osd_release` | `ceph osd dump \| grep require_osd_release` | At least `quincy` before Squid and at least `reef` before Tentacle |
| Client compatibility | `ceph features` and `ceph osd get-require-min-compat-client` | Know the oldest client release that is connected; the upgrade does not raise `min_compat_client` |
| Kernel clients | `ceph features` (per-group `release`) | Note the kernels that mount RBD or CephFS: they decide the cephx key type later |
| Free capacity | `ceph osd df tree` and `ceph df` | Enough headroom to lose one failure domain without reaching `nearfull` |
| CephFS | `ceph fs status` | Note `max_mds` and standby-replay of each file system; cephadm sets `max_mds` to 1 during the MDS phase |
| RGW multisite | `radosgw-admin sync status` | Metadata and data caught up in every zone before you start |
| Release notes | docs.ceph.com/en/latest/releases | Read the target release and every point release in between, including the "Critical Upgrade Steps" |

## Back up before you start

An upgrade does not delete data, but a mistake with keys or configuration can lock you out of a healthy cluster. Save the following on the admin host and copy it off the cluster:

```bash
mkdir -p /root/ceph-pre-upgrade && cd /root/ceph-pre-upgrade
ceph config dump --format json > config-dump.json
ceph config generate-minimal-conf > ceph.conf.minimal
ceph mon getmap -o monmap.bin
ceph osd getmap -o osdmap.bin
ceph osd getcrushmap -o crushmap.bin
ceph fs dump --format json > fsmap.json
ceph orch ls --export > service-specs.yaml
radosgw-admin period get > period.json
ceph auth export -o auth-export.keyring
chmod 600 auth-export.keyring
```

::: {.warn}
`auth-export.keyring` contains every key of the cluster, including `client.admin`. Store it encrypted, outside the cluster and outside any repository, and delete the working copy when the upgrade is finished. Never paste its content into a ticket or a chat.
:::

## Flags and the autoscaler

Stop the PG autoscaler for the duration of the upgrade: PG splits or merges in the middle of an upgrade slow it down, and a new release can change the default `mon_target_pg_per_osd`. Recent cephadm releases pause the autoscaler on their own, but setting the flag yourself also covers package-based clusters.

```bash
ceph osd pool set noautoscale
ceph osd set noout
```

With cephadm, `noout` is optional, since every OSD restart is gated by `ok-to-stop`. With packages, set it, and remove it at the end. Unset both flags only after the step is complete and the cluster is healthy again.

# Release changes that matter for the upgrade

The tables list only the changes that can break something during or right after the upgrade. Appendix H lists the other notable changes of each release.

## Reef to Squid

| Area | Change | What to do |
|---|---|---|
| Point release | 19.2.0 had a balancer-module problem on upgrade, fixed in 19.2.1 | Go straight to the latest Squid point release |
| RADOS | `POOL_APP_NOT_ENABLED` is raised for every pool without an application tag | Tag each pool with `ceph osd pool application enable` before the upgrade |
| RADOS | During the upgrade a PG may flip between two acting sets (bug 62338) | Finish the upgrade; if needed, raise `osd_async_recovery_min_cost` until it is done |
| Monitor | `mon_cluster_log_file_level` and `mon_cluster_log_to_syslog_level` were removed | Move the setting to `mon_cluster_log_level` |
| CephFS | The automatic metadata balancer is off by default (`balance_automate`) | Turn it on again only if you relied on it |
| CephFS | `root_squash` in `mds` caps needs the `client_mds_auth_caps` client feature | Upgrade those clients, or the MDS raises `MDS_CLIENTS_BROKEN_ROOTSQUASH` |
| RGW | radosgw validates `rgw_realm` at startup | Fix or remove a wrong `rgw_realm`, or startup fails with "failed to load realm" |
| RGW | The `notification_v2` topic format is not enabled on upgrade | Enable the zone feature only after every RGW in every zone runs Squid |
| cephx | `ceph auth rotate` appears | Rotate keys in place instead of deleting and recreating them |

## Squid to Tentacle

| Area | Change | What to do |
|---|---|---|
| Point release | From Squid 19.2.6 or later, Tentacle before 20.2.4 fails to start | Go to Tentacle 20.2.4 or later |
| MGR | The `restful` and `zabbix` modules were removed | Move to the `dashboard` API and to `prometheus` before the upgrade |
| RADOS | The default EC plugin of new clusters is ISA-L; upgraded clusters keep their default | Nothing changes for existing pools; choose the plugin explicitly in new profiles |
| RADOS | FastEC (`allow_ec_optimizations`) needs every mon and OSD on Tentacle | Enable it per pool only after the step; it cannot be turned off |
| RADOS | A stretch CRUSH rule with several `take` steps can move data after the upgrade | Check the stretch rules before the upgrade |
| RADOS | `osd_repair_during_recovery` was removed | Remove it from the configuration |
| CephFS | Changing `max_mds` on an unhealthy cluster needs `--yes-i-really-mean-it` | Restore `max_mds` only after the cluster is healthy |
| RBD | `rbd device map` uses msgr2 by default | Pass `-o ms_mode=legacy` only for hosts that need msgr1 |
| RGW | `LastModified` is truncated to the second, so it may appear to move backwards during the upgrade | Warn applications that compare timestamps |
| RGW | Tenant-level IAM APIs are deprecated in favour of accounts | Plan the move to accounts; nothing breaks yet |

## Security point releases: the new cephx key type

Squid 19.2.6 and Tentacle 20.2.4 fix CVE-2025-30156, an authentication bypass caused by the unauthenticated AES-128-CBC encryption of the old `aes` key type. They add a new key type, `aes256k` (AES256-CTS-HMAC-SHA384-192), and six health checks that report what still uses the old type. On an upgraded cluster both types stay allowed, and nothing stops working by itself; the work is to move every key to `aes256k` in the right order. The Linux kernel client supports `aes256k` from Linux 7.0 (and in distribution backports); older kernels need to keep an `aes` key.

# Step by step with cephadm

## Step 1: Reef to Squid

Check that every host can pull the image, start the upgrade and follow it:

```bash
ceph orch upgrade check --image quay.io/ceph/ceph:v19.2.7
ceph orch upgrade start --image quay.io/ceph/ceph:v19.2.7
ceph orch upgrade status
ceph -W cephadm
```

cephadm upgrades the daemons in a fixed order: `mgr`, `mon`, `crash`, `osd`, `mds`, `rgw`, `rbd-mirror`, `cephfs-mirror`, `ceph-exporter`, the gateways (`iscsi`, `nfs`, `nvmeof`, `smb`) and finally the monitoring stack. It restarts a monitor only while the others keep quorum, and an OSD only after `ok-to-stop` says that no PG becomes inactive. For CephFS it reduces `max_mds` to 1 and restores it afterwards. When every OSD runs Squid, it sets `require_osd_release squid` itself.

## Staggered upgrade

On a large cluster, upgrade in stages, so that you can stop and watch between them. The order still applies: cephadm refuses a stage that would upgrade a daemon type before the types that come earlier.

```bash
ceph orch upgrade start --image quay.io/ceph/ceph:v19.2.7 --daemon-types mgr,mon
ceph orch upgrade start --image quay.io/ceph/ceph:v19.2.7 --daemon-types crash,osd --hosts <host1>,<host2>
ceph orch upgrade start --image quay.io/ceph/ceph:v19.2.7 --daemon-types mds
ceph orch upgrade start --image quay.io/ceph/ceph:v19.2.7 --services <rgw-service> --limit 1
ceph orch upgrade start --image quay.io/ceph/ceph:v19.2.7
```

The last command upgrades everything that is left. On a multisite RGW deployment, upgrade one zone (one cluster) at a time and wait for `radosgw-admin sync status` to catch up before the next one; enable new zone features only when every zone runs the new release.

## After each step

```bash
ceph versions
ceph osd dump | grep require_osd_release
ceph mon dump | grep min_mon_release
ceph health detail
ceph crash ls-new
```

`ceph versions` must show a single version for each daemon type, `require_osd_release` and `min_mon_release` the new release. Then run on the new release for a few days before the next step, and only then enable the features you want from it (see the table in the last section).

## Step 2: move the cephx keys to aes256k

This step needs Squid 19.2.6 or later (or Tentacle 20.2.4 or later). Check that the monitors allow both key types, and choose the type of new keys:

```bash {since=squid}
ceph --format=json mon dump | jq -r '.auth_allowed_ciphers | map(.name) | join(",")'
ceph mon set auth_allowed_ciphers aes,aes256k
ceph mon set auth_preferred_cipher aes256k
ceph health detail | grep AUTH_INSECURE
```

cephadm rotates the keys of the daemons it manages. Client keys are yours: rotate each one only when every host that uses it runs a client that supports `aes256k`, and distribute the new keyring at once. `ceph auth rotate` keeps the caps of the entity; never delete and recreate a key just to change its type, because that also resets its caps.

```bash {since=squid}
ceph auth get-or-create client.admin-backup mon 'allow *' -o client.admin-backup.keyring
ceph --name client.admin-backup --keyring client.admin-backup.keyring auth ls
ceph auth rotate --key-type=aes256k client.app -o client.app.keyring
ceph-authtool --import-keyring client.app.keyring /etc/ceph/ceph.client.app.keyring
ceph --name client.app --keyring /etc/ceph/ceph.client.app.keyring health
ceph health mute AUTH_INSECURE_CLIENT_KEY_TYPE 8w
```

Rotate `client.admin` last, after you have checked that the backup key above works, and remove `client.admin-backup` when you are done. Mute the client warning only for keys you cannot rotate yet, such as those of old kernel clients. When `AUTH_INSECURE_SERVICE_KEY_TYPE` and `AUTH_INSECURE_CLIENT_KEY_TYPE` are both clear, switch the rotating service keys to the new type and forbid the old one:

```bash {since=squid}
ceph mon set auth_service_cipher aes256k
ceph config set mon mon_auth_allow_insecure_key false
ceph mon set auth_allowed_ciphers aes256k
```

::: {.warn}
Remove `aes` from `auth_allowed_ciphers` only when no key of the old type is left. If `client.admin` or a daemon key still uses `aes`, the cluster locks you out and needs the emergency procedure of the upstream cephx documentation. Clients on kernels older than 7.0 need `aes` to stay allowed, with their own `aes` keys.
:::

## Step 3: Squid to Tentacle

Repeat the checklist, then upgrade to the latest Tentacle point release, never to one earlier than 20.2.4:

```bash
ceph orch upgrade check --image quay.io/ceph/ceph:v20.2.5
ceph orch upgrade start --image quay.io/ceph/ceph:v20.2.5
ceph orch upgrade status
```

The order, the checks and the end state are the same as in step 1, with `require_osd_release tentacle` at the end. When the cluster is healthy, unset the flags:

```bash
ceph osd pool unset noautoscale
ceph osd unset noout
```

# Package-based clusters

Without cephadm you keep the order yourself. On Reef and later, the systemd unit names contain the fsid of the cluster; find them with `systemctl -l | grep ceph`. On each host install the new packages first, then restart only the daemon type of the current stage. The block uses Squid as the target; for the second step, write `tentacle` in the last but one line:

```bash {since=squid}
ceph osd set noout
systemctl restart ceph-mon.target
ceph mon dump | grep min_mon_release
systemctl restart ceph-mgr.target
ceph osd ok-to-stop <osd-id>
systemctl restart ceph-osd.target
ceph fs set <fs_name> allow_standby_replay false
ceph fs set <fs_name> max_mds 1
systemctl restart ceph-mds.target
ceph fs set <fs_name> max_mds <original_max_mds>
systemctl restart ceph-radosgw.target
ceph osd require-osd-release squid
ceph osd unset noout
```

Restart the monitors one host at a time and check quorum after each, then the managers, then the OSDs one host (or one failure domain) at a time, waiting for `active+clean` before the next host. For CephFS, reduce each file system to one active MDS, stop the standbys, upgrade the last active one, then start the standbys and restore `max_mds`. RGW comes last. Only when `ceph versions` shows every OSD on the new release, run `require-osd-release`. On package-based clusters the cephx key rotation of step 2 is also manual for the daemon keys; follow the upstream cephx upgrade procedure, which also updates the `osd_key` label of each OSD.

# Monitoring during the upgrade

```bash
ceph orch upgrade status
ceph -W cephadm
ceph versions
ceph orch ps --daemon-type osd
ceph progress
ceph health detail
```

`ceph -s` shows a progress bar for the upgrade, and `ceph versions` shows how many daemons of each type already run the new version. Watch for these warnings: `UPGRADE_FAILED_PULL` (a host cannot pull the image; stop and restart the upgrade with a correct image), `UPGRADE_NO_STANDBY_MGR`, `UPGRADE_OFFLINE_HOST` (the upgrade pauses until you resume it), and new `SLOW_OPS` or inactive PGs, which mean that you should pause and look before continuing. Keep the dashboards of chapter 20 open, especially client latency.

# Pausing, stopping and rolling back

```bash
ceph orch upgrade pause
ceph orch upgrade resume
ceph orch upgrade stop
```

`pause` keeps the target and continues where it stopped; `stop` cancels the upgrade and leaves the cluster in a mixed state, which Ceph supports only temporarily. Neither of them downgrades anything: there is no downgrade to an earlier major release. Honestly, "rollback" in Ceph means a few narrow cases:

| Situation | Reversible? | What you can do |
|---|---|---|
| Only the mgr daemons upgraded | Partly | Redeploy the mgrs with the previous image (`ceph orch daemon redeploy mgr.<id> --image <old-image>`); this is the documented way out of a failed Squid 19.2.6 to old-Tentacle upgrade |
| Some monitors upgraded | No, in practice | Go forward: fix the cause and finish the upgrade; once every monitor runs the new release, `min_mon_release` rises and older monitors cannot join |
| Some OSDs upgraded | No | Go forward; an OSD may convert on-disk metadata when it starts on the new release |
| `require_osd_release` raised | No | The flag cannot be lowered, and OSDs of the earlier release can no longer start |
| A feature enabled after the upgrade (FastEC, `notification_v2`, RGW accounts) | No | Do not enable such features until the release has run well for a while |
| An earlier point release of the same major release | Not supported | It may work, or not; prefer a configuration workaround or a later point release |
| A cephx key rotated | Yes, with care | The new key works on its own; restore the old type only through the documented emergency procedure, which is why the backup admin key exists |
| Back to an earlier major release | Only through a new cluster | Deploy a new cluster on the old release and migrate or restore the data |

::: {.tip}
The best rollback plan is a short one: upgrade a test cluster with the same release, the same features and the same client versions first, and keep the steps small, so that "go forward" is always a small, known step.
:::

# Lessons from a real upgrade: when the keys were the problem

In one production upgrade the author took part in (details that could identify the cluster or its owner are left out), the daemons upgraded without trouble. The problem was the cephx keys and their caps, not the daemons. The cause was found, written up and fixed. The lessons are not specific to that cluster:

1. Read the health checks before you touch a key. After the upgrade, `AUTH_INSECURE_*` warnings are expected; each one names the entities that still use the old key type, and that list is the work plan.
2. Never narrow `auth_allowed_ciphers` before the last client has a new key. Old kernel clients and forgotten automation hosts are the usual ones still on `aes`.
3. Rotate, do not recreate. `ceph auth rotate` keeps the caps; `auth del` followed by `get-or-create` silently drops caps that someone added by hand years ago, and the client then fails with "permission denied" rather than with an authentication error.
4. A key lives in more places than the monitors: the keyring files on every client host, secrets in orchestration systems such as Kubernetes, and for OSDs created with ceph-volume, the `osd_key` label on the device, from which the keyring is written again at activation. A key updated in one place only fails at the next restart, not at once.
5. Keep a working emergency admin key, tested before the change, and remove it afterwards.
6. Rotate in small groups, check each group with a real client operation, and write down the order you used; the same list then serves as the record of the change.

# Sources

- Ceph release notes, Squid and Tentacle (upgrade sections): https://docs.ceph.com/en/latest/releases/
- Upgrading Ceph with cephadm: https://docs.ceph.com/en/latest/cephadm/upgrade/
- Upgrading and rotating cephx keys: https://docs.ceph.com/en/latest/rados/configuration/auth-config-ref/
- CVE-2025-30156: https://docs.ceph.com/en/latest/security/CVE-2025-30156/
- RGW zone features: https://docs.ceph.com/en/latest/radosgw/zone-features/
- FastEC (`allow_ec_optimizations`): https://docs.ceph.com/en/latest/rados/operations/erasure-code/
