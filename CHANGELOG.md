# Changelog

All notable changes to this book are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Book versions are
`MAJOR.MINOR`: a minor version adds or corrects content, and a major version
restructures the book.

## [Unreleased]

### Added

- Chapters 5, 18 and 42 and appendix J link to appendix K; README and CONTRIBUTING list it.
- Appendix K: the sync-thread alert refers to a zone in which no RGW syncs.
- Cheat sheet: nine multisite and DR commands (sync errors, data sync, zone promotion, period pull, RBD demote/force-promote/resync, cephfs-mirror status) linked to appendix K; 187 commands.
- Appendix K: per-directory CephFS mirroring metrics with `ceph fs snapshot mirror status` (Umbrella).
- Appendix K "Multisite and Disaster Recovery: A Practical Guide" / «راهنمای عملی multisite و بازیابی از فاجعه» (both editions, `multisite-dr.html`): topology choices, RPO/RTO with asynchronous replication, monitoring sync (sync status, bucket sync status, sync error list, sync perf counters and `sync_delta` from Tentacle), planned switchover, unplanned failover, failback and resync, split brain, metadata versus data sync, sync policy and the archive zone, RBD mirroring (journal vs snapshot, promote/demote, force-promote, resync), CephFS snapshot mirroring, stretch mode versus multisite, and a DR drill runbook and checklist; TL;DR box, two figures, release badges and the embedded multisite lab.
- Figures app/f04_multisite_failover and app/f05_dr_options (fa/en): the multisite switchover/failover/failback flow and the DR options with their RPO.
- Suggested reading paths (fa/en, `paths.html`): seven paths with ordered chapters, sections, appendices and labs, each step with a reason and an estimated time, plus prerequisites and what you can do afterwards: newcomer, SRE/operator, S3/RGW developer, Kubernetes/platform engineer, storage architect, upgrade in a hurry and code reader/contributor. The page is linked from the sidebar and the home page, has a decision-map figure (app/f10_reading_paths), and lets a reader follow a path: every page of that path then names the next step (the choice stays in localStorage). The preface of the print book carries a short table of the same paths. One data file, `references/reading-paths.yaml`, drives all of it; `make check-paths` (part of `make check`) validates it.
- Cross-references written as [text](#anchor) in prose now render as links in the print book, on the site and in the Pandoc exports (they were printed as raw Markdown).
- Chapters 4 and 41 link to appendix J; README and CONTRIBUTING list it.
- Cheat sheet: eight RGW security commands (key rotation, user suspension, rate limits, presigned URLs, bucket logging, msgr2 secure mode) linked to appendix J and chapter 26; 178 commands.
- Appendix J "RGW Security: From Threat Model to Hardening" / «امنیت RGW: از مدل تهدید تا مقاوم‌سازی» (both editions, `security.html`): threat model, authentication (keys, subusers, SigV4/SigV2, presigned URL limits, key rotation), authorization (evaluation order, bucket policies, ACL pitfalls, Block Public Access, accounts and IAM from Squid), STS and OIDC, encryption (TLS, SSE-S3/SSE-KMS/SSE-C with Vault, KMIP or Barbican, msgr2 secure mode), Object Lock, versioning and MFA delete, tenant isolation, rate limits and quotas, a hardening checklist, logging and auditing, and following Ceph security advisories; TL;DR box, two figures and release badges.
- Figures app/f02_rgw_security_layers and app/f03_rgw_policy_eval (fa/en): the security layers of an S3 request and the RGW policy evaluation order.
- Appendix B again includes the full index of every command used in the chapters (by tool and subcommand, with the chapter of first use) after the 14 curated categories; it had been dropped when the cheat sheet was rewritten (print editions back to 1348 fa pages).
- Linked Appendix B / cheatsheet from the troubleshooting and upgrade appendices and README.md; added make cheatsheet and make check-cheatsheet targets and WeasyPrint dependencies to the CI site job.
- Web cheat sheet (fa/en cheatsheet.html): live search and dangerous-command filter, category jump bar, release-badge links, downloadable A4 PDF (ceph-cheatsheet-{fa,en}.pdf) and links from the sidebar navigation and home page.
- Standalone printable A4 multi-column cheat-sheet PDFs (tools/render_cheatsheet.py -> ceph-cheatsheet-{fa,en}.pdf, 3 pages each with RTL/LTR bidi isolation) and categorized Appendix B in the print PDF and Pandoc exports (tools/build_book.py, tools/export_pandoc.py).
- Bilingual command cheat sheet data (references/cheatsheet.yaml): 170 verified Ceph commands across 14 categories with Persian/English one-line descriptions, book section references, danger flags and release badges; tools/check_cheatsheet.py and tools/check_ceph_commands.py --strict validate every entry against Ceph sources, anchors and prose rules.
- Lab medals for the three new labs: «ترازبان» / Balance Keeper, «تحلیل‌گر دوام SSD» / Endurance Analyst and «معمار Zone» / Zone Architect (50 badges, 23 lab medals); lab index, docs and site checks count 23 labs.
- RGW multisite lab (lab-multisite.html): realm, zonegroup and zone layout builder with master zonegroup and zone, staged changes and period update --commit following rgw_zone.cc commit_period (same master: epoch + 1; new master: new period, realm_epoch + 1; commit only on the master zone), full-mesh, sync-from or sync-policy direction, the radosgw-admin commands for every step (checked with check_ceph_commands --strict) and a replication-lag and outage catch-up model; linked from chapters 5 and 42.
- SSD wear lab (lab-ssdwear.html): write amplification from replication or EC, min_alloc_size rounding, deferred writes and RocksDB metadata with leveled compaction, DWPD/TBW and approximate life per OSD with the model's assumptions spelled out; Ceph defaults, RocksDB options and perf counter names come from the Ceph tree; linked from chapters 12 and 25.
- Balancer lab (lab-balancer.html): upmap rounds ported from OSDMap::calc_pg_upmaps and checked against the compiled Ceph code for 60 clusters, a crush-compat weight-set model, max_deviation and max_optimizations, per-OSD deviation chart and the commands of each round; linked from chapters 19 and 28.
- Appendix I "Upgrade Guide: From Reef to Squid and Tentacle" / «راهنمای ارتقا: از Reef تا Squid و Tentacle» (both editions, `upgrade.html`): supported paths, a pre-upgrade checklist (health, PG state, quorum, standby mgr, `require_osd_release`, client compatibility, capacity, CephFS, multisite) with backups and flags, the release changes that can break an upgrade (from the Squid and Tentacle release notes), the `aes256k` cephx key type of Squid 19.2.6 and Tentacle 20.2.4 and the order to rotate keys in, step-by-step cephadm and staggered upgrades, package-based clusters, monitoring, pausing and stopping, a table of what can and cannot be rolled back, and anonymised lessons from a real upgrade where the keys were the problem; it opens with a TL;DR box and has an upgrade-path figure. Chapter 19 and appendix D point to it.
- Build: appendix figures live in `figures/app/` (rendered, translated and given web variants like chapter figures) and are numbered by appendix letter; a Markdown appendix may open with a TL;DR box; the list-of-figures check counts appendix figures.
- Chapter TL;DR boxes: every chapter (01–42, both editions) now includes one key Ceph CLI command (with its minimum-release badge where applicable) and an overview figure thumbnail with a caption linking to the full figure in the chapter; `tools/check_tldr.py` and `tools/check_features.py` enforce both across Markdown and the built site.
- Gamification: one medal per interactive lab (20 in all), with its own icon and name in both editions; a "Lab medals" gallery section shows them locked or earned, and each lab page shows its own medal.
- Interactive lab: twenty simulators; the Experimenter badge tiers are now 1, 8 and 20 labs; docs/SIMULATORS.md describes the labs that load on demand and their reference data.
- Network lab: public and cluster traffic of replication and EC for a client load, and the data moved and time to rebuild a lost OSD (chapter 13).
- cephx lab: step through the ticket exchange from MON to OSD, see which key protects each part and where wrong-key, replay, retired-secret and expired-ticket attacks stop (chapter 8).
- RBD clone lab: click to write or read clone objects, watch copy-up, copy-on-read, RADOS object clones on the parent and flatten (chapter 3).
- BlueStore space lab: min_alloc_size, classic EC padding versus allow_ec_optimizations, and the compression acceptance test checked against code cut from BlueStore.cc (chapter 12).
- S3 SigV4 lab: build the canonical request, string to sign and HMAC key chain in the page, tamper with a request and see RGW's 403; checked against an independent reference and the AWS example key (chapter 4).
- Monitor quorum lab: partition and fail monitors, check classic majority/leader rules exhaustively and step through election to Paxos lease (chapter 7).
- Scrub lab: compare shallow/deep random schedules and overnight windows; exhaustively check hour/day windows against Ceph C++ (chapter 7).
- mClock lab: explore built-in profiles, per-shard capacity, operation cost and steady-state client/recovery shares (chapter 7).
- Erasure coding lab: split a text into k+m shards with the jerasure or ISA-L Reed-Solomon matrix, fail shards and watch the decode (chapter 13).
- New lab "CephFS subtrees and MDS pinning" / «زیردرخت‌های CephFS و pin کردن روی MDS» (`mdspin`, ch. 6 §6.2.5, `lab-mdspin.html`): the /home, /projects and /scratch tree across MDS ranks, explicit pin inheritance and overrides, distributed ephemeral pins (dirfrags of the parent), random ephemeral pins with the random_max cap and a fixed draw, and max_mds with the paths that move; `rjhash64`, `hash_into_rank_bucket`, the dirfrag and its split floor are ports of the Ceph functions, checked against them compiled unchanged (560 cases).
- New lab "Bucket index shards and dynamic reshard" / «شاردهای نمایه‌ی bucket و reshard پویا» (`reshard`, ch. 4 §4.10.2, `lab-reshard.html`): object count, starting shards, threshold, versioning, multisite and the check interval give the growth path of dynamic reshard (a port of `calculate_preferred_shards` with `reshard_primes`), the delayed reduction after deletes, the keys per shard (`bucket_shard_index`) and the entries an ordered listing reads (`calc_ordered_bucket_list_per_shard`); checked against the Ceph functions compiled unchanged (600 cases) and the chapter 4 examples.
- New lab "Capacity and full-ratio planner" / «برنامه‌ریز ظرفیت و نسبت‌های پُری» (`capacity`, ch. 7 §7.9.4, `lab-capacity.html`): hosts, OSDs, pool type, data stored and an imbalance give each OSD's fill and state against nearfull, backfillfull and full (a port of `OSDService::recalc_full_state`), MAX AVAIL with the OSD that sets it (a port of `PGMap::get_rule_avail` with the float weights of `get_rule_weight_osd_map`), the OSD_NEARFULL, OSD_BACKFILLFULL and OSD_FULL checks, and what losing a host does; checked against the Ceph functions compiled unchanged (360 cases).
- Web edition: the interactive labs added from now on live in their own files (templates/site/sims/lab-NAME.js, listed in labs.yaml) and are loaded, with their strings, only on the pages that show them; tests/sims/test_labs.js checks their strings in both languages, renders every lab in both editions and runs each lab's checks against tests/sims/golden-labs.json; the home page shows a selection of labs with a link to all of them.
- Chapter 10, benchmark reporting now cites the Pilot framework (MASCOTS 2016) on accuracy, precision, comparability, repeatability and overhead control (both editions).
- Chapter 6 now traces the MDS balancer to the SC 2004 paper on dynamic subtree partitioning, and chapters 1 and 6 cite Sage Weil's 2007 dissertation in their sources (both editions).
- Chapter 16, new §16.7.5 "Deduplication: manifest objects in RADOS and full-object dedup in RGW" (both editions): the base-pool and chunk-pool design with double hashing from the developer documentation, the TiDedup design (USENIX ATC 2023), `ceph-dedup-tool --op estimate` as the safe first step, why RBD and CephFS favour background dedup, and the Umbrella technical preview `radosgw-admin dedup` with its data-loss warning and skipped objects; both marked experimental.

## [1.7] - 2026-11-22

### Added

- A capstone project at the end of each part, in the same format (goal, requirements, acceptance criteria, hints that point to chapters, no solution in the book), both editions: chapters 1–21 "build, break and recover" (§21.12.1), Special Part "follow one write through the code" (§22.14.1), Part III "recompute one result yourself" (§33.10.1) and Part IV "trace one object through RGW and RADOS" (§42.10.1).
- A `labs/` directory with a single-host cephadm lab (README in both languages): prerequisites, preflight, install, bootstrap with `--single-host-defaults`, OSDs, RBD/CephFS/RGW, verification and teardown scripts that use `set -euo pipefail`, are idempotent and support `--help` and `--dry-run`; a "Tested on" section limited to what was validated (shellcheck, `--help`, dry runs and refusal paths; no end-to-end run recorded yet). New `make check-labs` target and a `labs` CI job that runs shellcheck; chapters 1 and 11 link to the lab.
- Chapter 6, new §6.8.4 "CephFS, Lustre and BeeGFS: a qualitative comparison" (both editions): building blocks, metadata model, data path, data protection, high availability, POSIX semantics, clients and licence, each taken from that project's own documentation (Ceph, the Lustre Operations Manual and wiki, BeeGFS 8.4), with no performance claims (completes roadmap item 8).
- Chapter 21, new §21.8.2 "Interrupts and irqbalance" (both editions): IRQ affinity from the kernel documentation, what irqbalance does and its banned CPU and IRQ settings, the link to `osd_numa_auto_affinity` and `ceph osd numa-status`, checks to run first, and the measure-before-and-after rule; no values are prescribed, since the Ceph documentation gives none (roadmap item 9).
- Chapter 4, new §4.11.7 "Video on demand: HLS and DASH from RGW" (both editions): manifest media types from RFC 8216 and IANA, Cache-Control at upload, a GetObject-only public policy with a warning and PublicAccessBlock, a bucket CORS rule for browser players, a CDN in front, and lifecycle for stale segments with its day granularity and work window (roadmap item 3).
- Chapter 4, new §4.11.6 "Nextcloud on RGW" (both editions): primary storage versus external storage from the Nextcloud administration manual, a `config.php` object store example, path-style versus virtual-host and its DNS needs, bucket naming, multipart defaults with an abort-incomplete lifecycle rule, multibucket mapping, and why no CORS rule is needed (roadmap item 1).
- Chapter 2, new §2.10.6 "CloudStack: RBD as primary storage" (both editions): pool and least-privilege user, the RADOS fields in the Add Primary Storage form, the single-monitor limit before 4.18 and its DNS workaround, and storage tags with a matching disk offering (roadmap item 7).
- Chapter 2, new §2.10.5 "Windows and VMware hosts", and chapter 6, new §6.4.3 "CephFS on Windows with ceph-dokan" (both editions): the Windows MSI client, supported Windows versions, Secure Boot and the BitLocker warning, `rbd device map/show` on Windows and the persistent `ceph-rbd` service; ESXi 7.0U3+ through the NVMe-oF gateway with `esxcli` lines checked against the Broadcom documentation; `ceph-dokan` mounts, uid/gid and ACL limits, and when to prefer the SMB module (roadmap item 4).
- Chapter 4, new §4.3.3 "Splitting reads and writes in front of RGW" (both editions): two RGW services in one zone behind a self-managed HAProxy, with every directive checked against the HAProxy 3.2 configuration manual (predefined `METH_GET`/`METH_OPTIONS` ACLs, `use_backend`, `option httpchk` with `http-check send`), why POST and multipart uploads go to the write group, why signatures are unaffected, and why a read backend in another zone gives stale reads (asynchronous multisite sync, `--read-only` secondaries) (roadmap item 2).
- Chapter 6, new §6.8.3 "CephFS for HPC: what the Ceph documentation supports" (both editions): no gateway in the data path, more active MDSs and pinning for many clients on separate directories, large directories and dirfrags, cap pressure from scans (`mds_max_caps_per_client`), wide layouts for large files, shared-file writers and non-atomic writes across object boundaries, and LazyIO with its official warning. It deliberately does not compare CephFS with Lustre or BeeGFS (roadmap item 8, partly).
- Troubleshooting appendix, two step-by-step procedures (both editions): "a PG that does not become active" (stale, inactive and unclean; reading `ceph pg <pgid> query` by peering state, with the strings printed by `PeeringState.cc` for GetInfo, Down, Incomplete, WaitUpThru and `peering_blocked_by_history_les_bound`; `ceph osd blocked-by`; why `osd_find_best_info_ignore_history_les` loses acknowledged writes silently) and "slow ops" (`dump_blocked_ops`, `dump_ops_in_flight`, `dump_historic_slow_ops`, `dump_historic_ops_by_duration` with their documented thresholds, reading the longest event, and the causes listed in the official OSD troubleshooting page).
- Chapter 4, new §4.12.3 "The Admin Ops REST API": when to use the HTTP admin API instead of `radosgw-admin`, the caps each operation needs, a least-privilege automation user, signed `curl --aws-sigv4` examples for user info, bucket statistics and a read-change-write user quota, the error responses, and why `rgw_admin_entry` stays `admin` (both editions; roadmap item 5).
- Chapter 8, new §8.10.1 "Primary on SSD, replicas on HDD: pattern and pitfall": primary affinity (with how `OSDMap::_apply_primary_affinity` picks the primary), the SSD-first CRUSH rule from the official documentation, why writes do not get faster, shared hosts and the N+1 selection, reads after an SSD failure, how the read balancer weighs primary affinity, and why a separate pool per device class is usually better (both editions; roadmap item 6).
- Chapter 21, new §21.8.1 "sysctl settings managed by cephadm": `ceph orch tuned-profile` specs, where the file is written, name ordering, maintenance hosts, and the difference from the `tuned` daemon (both editions; part of roadmap item 9).
- Troubleshooting appendix: eleven more health checks from the official health-check reference (cluster and OSD flags, pools without an application, late scrubs, PG count warnings, pool quotas, backfill/recovery blocked by full OSDs, read repairs, BlueStore slow operations, device health, insecure global_id reclaim, and MDS ranks down), each with first commands, the direction of the fix and the chapter.

### Corrected

- Command lines that Ceph does not accept as written (found by the new command check, both editions): `ceph orch apply nvmeof` takes the pool and group as `--pool`/`--group` (the positional form is rejected since Tentacle; chapters 2 and 31); `rgw_keystone_api_version` was removed in Tentacle and `ceph config set` rejects it, so the Keystone example no longer sets it and the tip says why (chapter 4); `ceph log last 50 debug cephadm` instead of `ceph log last cephadm 50` (chapter 11); `ceph pg 5.1a query` with the shards read from `peer_info`, because `ceph pg` does not take a shard id such as `5.1as2` (chapter 13).
- Release badges: `ceph osd pool get threshold` exists only from Tentacle, so the Reef+ block in chapter 19 reads the option with `ceph config get mgr mgr/pg_autoscaler/threshold`; `ceph daemon osd.N messenger dump` appeared in Squid, so that block in chapter 26 is now Squid+.
- Links that moved permanently now point to their new address: RocksDB (`github.com/meta/rocksdb`), the Crimson page on ceph.io, RFC 3720 and deceptive.design.

- HDD OSD shard defaults (1 shard × 5 threads instead of 5 × 1, issue 66289): chapter 7, the chapter 21 summary and review question, and appendix D said Squid or Tentacle; the official notes date the change to Squid point release 19.2.1 (kept in Tentacle and Umbrella), as the chapter 21 table already said. Appendix H lists it under Squid as confirmed.

### Publishing

- Weekly report (`.github/workflows/weekly.yml`): the link check never ran, because lychee 0.24 no longer has `--exclude-mail`; its options now live in `lychee.toml` (web links only, `#fragments` checked, documentation-only hosts excluded, 429 accepted), and the issue says so when lychee produces no report. `tools/check_ceph_commands.py` is rewritten: instead of comparing words with the man pages (which split `cephadm` into `ceph adm` and `radosgw-admin` into `rados gw-admin`, and flagged every pool name, daemon id and manager command), it reads the command tables from a shallow clone of ceph/ceph (MonCommands.h, MgrCommands.h, the manager modules, admin-socket commands, the config option schema, and the rbd, rados, radosgw-admin, cephadm, ceph-volume and offline tool tables) and runs the real `ceph_argparse` parser on every command line, also inside pipes, `$( )` and `cephadm shell --`. Each line is checked on main and on every release from its badge on. Correct lines it cannot model go in `tools/ceph-commands-allowlist.yaml` with a reason. `make check-commands` runs it locally.
- CI (`.github/workflows/ci.yml`, replacing `build.yml`): `make check`, the web edition built for `https://book.ceph-s3.ir` (analytics token from the repository variable `CF_BEACON_TOKEN`, `CNAME` in the output) and deployed to GitHub Pages with `actions/deploy-pages`, plus PDF/EPUB/DOCX artifacts.
- Release workflow (`.github/workflows/release.yml`): a `v*` tag builds the PDFs, EPUB, DOCX and single-file HTML of both editions and attaches them, with checksums and the CHANGELOG notes, to a GitHub Release.
- `.zenodo.json` (book, CC BY-NC-SA 4.0, ORCID, keywords) for a DOI per release through the Zenodo GitHub integration, and `CITATION.cff`; `make check-publish` keeps them in step with the book version. `docs/PUBLISHING.md` lists the repository, Pages, DNS, Cloudflare and Zenodo settings.

### Web edition: edit link, feedback, release notices, analytics

- "Edit this page" / «ویرایش این صفحه» on every chapter opens the chapter's Markdown source on GitHub (`REPO_URL/edit/main/content/<lang>/chapters/<file>.md`; `REPO_URL` and `REPO_BRANCH` are build options).
- "Was this section helpful?" / «این بخش مفید بود؟» at the end of every section of a chapter. A vote goes to `bookEvent()`: an optional `FEEDBACK_ENDPOINT` (sendBeacon, no cookies), analytics that support custom events, and a `book:event` DOM event; a "No" offers a prefilled GitHub issue naming the section anchor. Cloudflare Web Analytics has no custom events, so with it alone the votes are seen only through the endpoint or the issues.
- Home page "Hear about new editions": a signup form when `NEWSLETTER_ACTION` is set, otherwise "Watch releases on GitHub" and an Atom feed, `releases.xml`, generated from this changelog; privacy notes in both languages and in the footer.
- "Ask the book" / «از کتاب بپرس»: a button on every page opens a small panel (loaded on click, no third-party code) that answers questions from the book's own text in the reader's language, with links to the sections it used. Answers come from the `book-ask` Cloudflare Worker (`infra/book-ask`: D1 full-text search with bge-m3 re-ranking and a Workers AI model), enabled with the `ASK_ENDPOINT` build option; questions are not stored or kept with IP addresses, as the footer privacy note says.
- Cookie-less analytics only when configured: `CF_BEACON_TOKEN` (Cloudflare Web Analytics) or `ANALYTICS=plausible`; no token is stored in the repository. `CNAME` is written for the custom domain of `SITE_URL`.
- `tools/check_features.py` (part of `make check-site`) checks the TL;DR boxes, release badges, edit links, feedback rows, newsletter section, feed, CNAME and analytics tags in both editions; `check_site.py` allows the analytics host only when analytics was configured.

### Ceph release labels

- Every code block that runs a Ceph command-line tool carries a release badge, "Reef+", "Squid+", "Tentacle+" (and "Umbrella+" or "main" for the few commands newer than the book's three releases), in the PDF, web, EPUB and DOCX editions. The baseline is Reef (18.2); a block that needs a later release says so on its fence: ```` ```bash {since=squid} ````. On the web the badge links to the matching release section of the new appendix.
- New appendix H «تغییرات Reef، Squid و Tentacle» / "Changes in Reef, Squid and Tentacle": per release, the notable changes the chapters rely on, with links to the chapters, a link to the official release notes and a confirmed / for review status; and the list of command blocks labelled newer than Reef. Data in `references/ceph-release-changes.yaml`.
- `make check-versions` (part of `make check`): fa and en label the same blocks with the same release, labels are valid, and the release-changes data is complete.

### UI consistency (web edition)

- Every control (buttons, `.btn`, chips, toggles, simulator controls, quiz and flashcard buttons, header pills, inputs and selects) now uses the site font (Vazirmatn in Persian, Inter in English) with one size, weight and line-height scale, instead of the browser's system font.
- Badge gallery: a uniform grid with equal-size cards, titles clamped to two lines, descriptions to three, and tier labels and progress bars aligned at the bottom; learning-path and part cards stretch to equal height.
- Interactive lab cards (lab page and home): the icons were empty because the simulator palette (`--sim-a`) was defined only inside `.sim`; it now also applies to the cards. Each card has a preview: the visual part of the simulator's static figure (histogram, sequence diagram, table, OSD logs or object grid) at half size in a 16:9 box, using the theme colours (dark mode included). Without node, a large icon stands in. `shoot_site` checks that all 7 cards show a drawn icon and a non-empty preview (fa, en, dark, home).
- `tools/shoot_site.py --ui-only` checks the computed font of every visible control and the badge card sizes (fa desktop and mobile, light and dark).

### Interactive lab (web edition)

- Eight in-browser simulators, offline and in vanilla JavaScript, embedded in their chapters with `::: {.sim name="…"}` and collected on `lab.html` «آزمایشگاه تعاملی» (sidebar and home page): CRUSH playground (ch. 8, 28), object name to OSD step by step (ch. 8, 28), PG count calculator with the pg_autoscaler's four passes (ch. 7), replication vs erasure coding with EC profile rules (ch. 13), peering/recovery stepper with three scenarios (ch. 35), BlueStore write path (ch. 12), RGW PUT and multipart (ch. 4) and RBD striping mapper (ch. 37). See `docs/SIMULATORS.md`.
- New simulator "From object name to OSD" / «از نام شیء تا OSD» (`placement`, ch. 8 §8.6.1 and ch. 28 §28.8.4, `lab-placement.html`): for a typed object or file name, pool, pg_num, pgp_num, size, failure domain and an editable host/OSD map (weights, out, down), it shows each step: `ceph_str_hash_rjenkins`, `ceph_stable_mod` and the PG id, `raw_pg_to_pps`, every bucket draw of `crush_do_rule` (candidates, hashes and draws, collisions and out rejections that raise r) with a choice of uniform, list, tree, straw or straw2 for all buckets, then the raw, up and acting sets, the primary and the `ceph osd map` line. A comparison places 1000 or 10000 sample objects before and after one change (add an OSD or a host, reweight, mark out, remove an OSD or the second host, convert the algorithm) and shows, for all five algorithms, the replicas moved, the least movement needed and the objects affected.
- RBD mode of the "From object name to OSD" lab (also embedded in ch. 2 §2.2.1 and ch. 37 §37.3, where it opens in that mode with `::: {.sim name="placement" mode="rbd"}`): an image name, an editable image id (a new one made the way `librbd::util::generate_image_id` makes it), size, order, stripe_unit, stripe_count, a byte range and an optional separate data pool. It shows the `rbd_data.<id>.<16 hex digits>` objects the range maps to (`Striper::file_to_extents`, with fancy striping, offsets in each object and the image bytes that fill it; with `--data-pool` the name carries the metadata pool id), then each object's PG, up set and primary with the full five steps on demand, the same for `rbd_directory`, `rbd_id.<name>`, `rbd_header.<id>` and `rbd_object_map.<id>` in the metadata pool, the `rbd create`/`rbd info` lines, and how many PGs and OSDs the whole image touches (first 65536 objects), with replicas and primaries per OSD. `tools/simref/gen_golden.py` now copies `Striper::file_to_extents`, `object_truncate_size`, `get_num_objects` and `get_file_offset` verbatim out of `src/osdc/Striper.cc`, compiles them with g++ (`tools/simref/striper_ref.cc`, against the real `StriperTypes.h`) and adds 160 `file_to_extents` cases, 80 layout cases and the librbd data object names to `tests/sims/golden.json`.
- Erasure-coded mode of the "From object name to OSD" lab (also in ch. 13 §13.2.1 and ch. 27 §27.4, opened with `mode="ec"`): a Replicated / Erasure-coded switch for one object and for RBD images (there the erasure-coded pool is the `--data-pool`, with `allow_ec_overwrites`, and the metadata stays replicated). Inputs k, m, a plugin label (jerasure or isa reed_sol_van), stripe_unit (stripe_width = k × chunk), crush-failure-domain, min_size (default k+1) and a write offset and length. It shows the erasure rule (`chooseleaf indep`, the two tries steps) with every draw grouped by shard position and round (r + n·ftotal), the k+m shards with data and coding chunks, pgids with shard suffix (`1.2as0`), raw and up sets with NONE holes (2147483647 in the `ceph osd map` line), the primary, active and recoverable states and how many more shards can be lost, the same PG with indep and firstn before and after OSDs go out or down, and a stripe × shard grid with each data shard's bytes, shard extents, parity extent and shard sizes. The comparison counts erasure-coded shards by position and adds replicated vs erasure-coded vs erasure-coded-with-firstn movement, with the data moved per object. `tools/simref/ec_ref.cc` compiles `ECUtil`'s `stripe_info_t`, jerasure's `get_chunk_size` and `OSDMap::_raw_to_up_osds`/`_pick_primary` copied from the Ceph source; `tests/sims/golden.json` gains 60 chunk-size cases, 120 stripe layouts and 96 indep maps with out/down OSDs and 1824 NONE entries (existing entries unchanged).
- Persian lab text: Latin words joined by one space ("object set", `ceph osd map`) now stay one left-to-right run, and the striping lab no longer mixes "object set" and "stripe unit" into Persian word order.
- `sim-core.js` now ports `bucket_straw_choose`, `bucket_list_choose`, `bucket_tree_choose` and `bucket_perm_choose` (uniform, with its per-call workspace), `crush_calc_straw`, `crush_make_tree_bucket` and `crush_hash32_rjenkins1_4`; the choose loops call `crush_bucket_choose` and use the uniform rule for r in `crush_choose_indep`. `tools/simref` builds buckets of any algorithm, and `golden.json` adds `crush_hash32_4`, 1600 single-bucket choice sequences and 17632 PG mappings over maps of every algorithm; the tests also check the chapter 28 bucket figures. 29657 checks in all.
- The arithmetic ports Ceph's code and is tested against it: `tools/simref` compiles Ceph's CRUSH C files and runs the real `pg_autoscaler/module.py` to make `tests/sims/golden.json`; `make check-sims` (part of `make check`) compares 8932 PG mappings, all 65536 `crush_ln` values, hashes, autoscaler results and the Striper vectors of `test_striper.cc`.
- Each simulator names the Ceph file and function it follows; RTL-aware sequence diagrams, keyboard access, dark mode and reduced motion; print and no-JavaScript readers get a static figure rendered at build time by `tools/sim_fallback.js`; PDF/EPUB/DOCX print a pointer to the lab.
- Gamification: 5 XP for the first use of each simulator per day (cap 40/day) and a tiered «آزمایشگر» badge.
- Fix: `templates/pandoc/book.lua` now reads the metadata before the divs (two filter passes), so EPUB/DOCX/single-file HTML callouts get their translated labels («نکته», «هشدار», …) instead of the class name.
- `tools/shoot_site.py` drives every simulator (desktop, mobile, dark, en, print media, no-JS); `--sims-only` runs just that part.

### Web edition redesign

- New home page: hero with the cover, a version badge, gradient title, call-to-action buttons and a stats row (chapters, figures, algorithms, parts); a decorative `ceph -s` terminal panel.
- "Where to start" section (`#get-started`) with six reader paths (new to Ceph, deployment, operations, troubleshooting, developer, Part IV specialist).
- "Four parts of the book" cards with chapter chips; Part IV marked as new.
- Header: logo mark and a "Get started" pill; sidebar groups chapters under part labels.
- New slate/cyan/emerald/indigo palette for light and dark themes; own CSS and SVG icons.
- `tools/shoot_site.py` skips the lightbox step on chapters without figures (pending English chapters) and records it as a note.

### Gamification (web edition)

- Optional game layer designed around Self-Determination Theory and the "white hat" Octalysis drives, without dark patterns; see `docs/GAMIFICATION.md` (principles, mechanics, references).
- XP for validated section reading (time on screen plus scrolling to the end, activity and visibility checks, daily caps), finished chapters, flashcards, quiz answers, algorithm boxes, daily goals, weekly challenges and badges; 12 Ceph-themed levels from «کلاینت» to «معمار CRUSH» with a reduced-motion-safe level-up celebration.
- Daily goal (10/20/30 minutes or one section), streak with automatic streak freezes (earned by XP, used only when they cover a whole gap) and rest days on by default; GitHub-style reading heatmap that runs right to left in Persian.
- 27 badges (12 tiered bronze/silver/gold, 7 single, 8 hidden) with a gallery that shows progress toward locked tiers.
- `review.html`: flashcards from each chapter's review questions and the answers appendix, a multiple-choice glossary quiz (options drawn only from the glossary), and Leitner spaced repetition (6 boxes) with a «مرور امروز» queue; chapter pages end with a chapter quiz card.
- `progress.html` dashboard «پیشرفت من»: level and XP bar, streak and freezes, today's goal, heatmap, stats, next-best-chapter nudge, weekly challenges, learning paths (the home page's six paths) and badges; settings to hide all game elements, enable tiny WebAudio sounds (off by default), choose the goal and rest days, and reset game data.
- `certificate.html?p=N`: printable path certificate with a name kept only in the browser.
- Header streak/level chip, subtle toasts in an ARIA live region; print hides all game UI.
- Progress record schema v2 with migration from v1; JSON export/import includes the game state.
- `tools/shoot_site.py` seeds a history and checks/shoots the dashboard, heatmap, badges, flashcards, quiz, level-up toast, chapter quiz card and certificate.

### Reading progress and motion (web edition)

- Reading-progress bar under the header on every page; back-to-top button with a progress ring.
- Per-chapter read state, stored per language in `localStorage` only: marked automatically at 90 % of the chapter, or with the toggle in the chapter header; shown as checkmarks and in-progress rings in the sidebar, chapter chips, home contents and part-card rings.
- Home "progress through the book" panel with a "Continue reading" button that reopens the last page at the saved scroll position.
- Estimated reading time per page (whitespace word count, so Persian words joined by ZWNJ count once; code lines and figures add time) in chapter headers, home contents and part cards.
- Bookmark buttons on section headings, highlighted bookmarked headings and a "My reading" panel listing bookmarks with export/import of progress as JSON and a reset.
- Motion: scroll reveal for cards, figures and headings; hero entrance and animated stat counters; hover micro-interactions; cross-document View Transitions where the browser supports them. All of it is switched off under `prefers-reduced-motion`.
- Mobile header no longer cuts off the book title (the "Get started" pill is hidden below 600 px).
- `tools/shoot_site.py` seeds a reading history and checks the progress panel, continue button, read toggle, bookmarks, the panel's Escape handling and, once with full motion, the hero counters and scroll reveal.

## [1.6] - 2026-11

### Added

- Part IV, "Specialist Part" (chapters 34–42), on RADOS, RBD and RGW, checked against the
  Ceph main branch (November 2026): RADOS object model and op path; pg log, past intervals
  and recovery; snapshots, watch/notify and cls; RBD image layout, striping and object map;
  the librbd I/O path, exclusive lock and caches; rbd-mirror internals; the RGW data model
  (bucket index, OLH versioning, manifest, multipart); the RGW request path (SigV4, quota,
  rate limit, gc, lifecycle); and multisite internals (period commit, log records, sync
  status objects, bilog generations, conflict resolution). 45 new algorithm boxes and 25
  new figures, with answers for every review question.
- English placeholder pages for chapters 34–42, so numbering matches the Persian edition.
- Glossary: 20 new terms (OLH, bilog, mdlog, period, error repo, bilog generation, SigV4,
  placement target, delete marker, multipart upload, RGW gc, RGW rate limit, SnapSet,
  SnapMapper, PastIntervals, divergent entry, watch/notify, hobject_t, PWL, mirror snapshot).
- Bibliography: Ceph developer docs for the bucket index, RGW placement and multisite.

### Changed

- Version 1.6 in metadata, covers (back text lists the specialist part), preface and README.

## [1.5] - 2026-11

### Changed

- The book is presented as an original authored work. Every reference to another book
  (title, authors, publisher, ISBN, rights notice, "not a translation" wording, page
  correspondences and the `original_heading` front-matter field) was removed from the
  front matter, colophon, preface, chapters, appendices, cover, metadata, README, NOTICE,
  CONTRIBUTING and LICENSE. Citations of Ceph documentation and papers are unchanged.
- New cover for both editions (`tools/render_cover.py`): an abstract CRUSH hierarchy and
  placement-group grid on a deep ink background, Vazirmatn / Inter, CC BY-NC-SA note.

### Earlier unreleased changes

- English edition: every chapter (1–33) and its answers is now a placeholder page with the
  note "The English translation of this chapter is in progress…" (`translation: pending`),
  so chapter, section, figure and algorithm numbering stay identical to the Persian edition.
  The existing English drafts (chapters 1–25 and part of 26) are kept on the `en-drafts`
  branch; chapters will be brought back one by one after the Persian pages are reviewed.
- `make fonts` installs the book fonts with `tools/install_fonts.sh` only when fontconfig
  cannot find them (macOS: `~/Library/Fonts`); `pdf`, `html` and `site` depend on it.
- The web book serves high-resolution figures: `make webfig` (`tools/render_web_figures.py`)
  renders mermaid diagrams at 3x and byte-layout figures at 2x as WebP (`srcset` 1x/2x) and
  re-runs the matplotlib scripts as SVG with text converted to paths, so zoomed figures stay
  sharp. Variants live in `build/webfig/`; any figure that fails falls back to the print PNG.
- English web pages are hyphenated at build time (Pyphen en_US patterns insert soft hyphens
  into long words outside code, headings and URLs), so justified text on narrow screens does
  not open wide gaps even where the browser has no English hyphenation dictionary.
- `make html` now builds a multi-page web book (`tools/build_site.py`,
  `templates/site/`): one page per chapter and appendix with stable source anchors,
  collapsible sidebar and in-page contents, previous/next and breadcrumbs, offline
  Persian-aware search, figure lightbox with wheel/drag/pinch zoom, light/dark theme,
  Pygments highlighting with copy buttons, fa/en switcher, print stylesheet and
  self-hosted fonts. The Pandoc single file moved to `make html-single`.
  `make check-site` and `make shoot-site` test the result.

- Relicensed the whole repository (text, figures, templates, tools and scripts)
  under a single licence, CC BY-NC-SA 4.0 (previously CC BY-SA 4.0). Quoted
  upstream code excerpts keep their original licences.

### Added

- The book is now a source repository. The content is Pandoc Markdown with fenced
  divs, organised as `content/fa` and `content/en` with the same structure.
- Shared figures with per-language label strings (`figures/i18n/<lang>.yaml`) and
  generated `<name>.<lang>.mmd` / `.png` variants.
- Single-source bilingual glossary (`glossary/glossary.yaml`) and a CSL-JSON
  bibliography (`references/references.json`).
- A `Makefile` with `LANG=fa|en`. It builds PDF (WeasyPrint), HTML, EPUB and DOCX
  (Pandoc), and runs the `lint`, `spell`, `check-refs`, `check-links` and
  `check-parity` checks. `make all` builds both editions.
- CI workflow (`.github/workflows/build.yml`), `Dockerfile`, pinned
  `requirements.txt` / `package.json`, `.editorconfig`, markdownlint config.
- 53 figure scripts (`figures/scripts/plot_*`, `measure_*`, `compute_*`) and their
  raw data (`figures/data/`). Before this they lived outside the book sources.
- English edition: started (see `content/en`, `make check-parity`).

### Fixed

- Troubleshooting appendix: the `jq` cell lost its escaped pipe
  (`ceph pg <pgid> query | jq .recovery_state`).

## [1.4] — 2026-11-15

### Added

- 18 new figures (350 in total) and 14 new algorithm boxes (143 in total). Many of
  them come from measurements on a Ceph 18.2.7 test cluster:
  - `rbd du` with and without `--exact` (ch. 2);
  - copyset and rebuild models computed exactly with `osdmaptool` (ch. 1);
  - host add / reweight data movement (ch. 8);
  - mgr stats lag against `mgr_stats_period`, and `pg dump` cost per PG (ch. 9);
  - Little's law and block-size sweep with `rados bench` (ch. 10);
  - `numops` against read-modify-write and Lua against client-side reads (ch. 15);
  - PG state timeline and host failure (ch. 17);
  - upmap and PG split (ch. 19);
  - OpTracker stages (ch. 22);
  - BlueStore label bytes and allocator free map (ch. 24);
  - pg-log memory and per-item cost (ch. 33).
- Preface section «تازه‌های نسخه‌ی ۱٫۴».

### Changed

- Version strings in every chapter document that still said 1.2.
- The PromQL table in ch. 20 was checked against the metric names in the mgr
  `prometheus` module and `prometheus_alerts.yml`.

### Fixed

- ch. 15: the `cls_lua` global table is `objclass`, not `cls`. This was checked on
  18.2.7 and against `cls_lua.cc`.
- ch. 15: corrected the error codes for `assert_version` (ERANGE / EOVERFLOW) and
  `cmpxattr` (ECANCELED).
- 1080 pages.

## [1.3] — 2026-11-15

### Added

- About 61 new figures (332 in total) and 52 new algorithm boxes (129 in total).
  They cover striping, object map, fast-diff, bucket-index sharding and resharding,
  datalog and mdlog sharding, dirfrag split and merge, Paxos failure handling,
  dmclock, autoscaler, compression and min_alloc amplification, and more.
- Preface section «تازه‌های نسخه‌ی ۱٫۳».

### Fixed

- ch. 16: the cache-tier eviction condition was inverted. It was checked against
  `PrimaryLogPG::agent_maybe_evict`.
- ch. 24: `range_seg_t` is 80 bytes (checked with a compile test).
- ch. 24: RGW lifecycle marker format, and the worked hash example recomputed.
- `!TABLE` blocks without `!ENDTABLE` (ch. 14, 16, 24).
- 1050 pages.

## [1.2] — 2026-11-15

### Added

- New chapters 30–33: Crimson/Seastar, SPDK and NVMe-oF, scrub/recovery/repair,
  memory and CPU.
- Algorithm boxes (77) with pseudocode, complexity, a worked example and the source
  `file::function` for each. Appendix «فهرست الگوریتم‌ها».
- Byte-layout figure generator. Figures grew from 177 to 271.
- 16 new glossary terms. 954 pages.

## [1.1] — 2026-11-15

### Added

- New section of low-level chapters 23–29: block device and bufferlist, BlueStore
  on-disk format, RocksDB, msgr2, erasure-code math, CRUSH internals, kernel
  clients.
- Expanded chapters 13, 14, 16, 18, 20 and 21.
- 758 pages, 177 figures, 230 references, 290 answers.

## [1.0] — 2026-11-15

### Added

- First complete edition with 22 chapters.
  Chapter 22, "Ceph code architecture", walks end to end through a RADOS write, RBD,
  an RGW PUT and CephFS.
- "From the code" deep dives in every chapter, with short attributed excerpts
  (ceph/ceph, LGPL).
- Review questions with answers, a glossary, a troubleshooting appendix and a
  versions appendix.
- 587 pages, 134 figures, 191 references.

[Unreleased]: #unreleased
[1.4]: #14--2026-11-15
[1.3]: #13--2026-11-15
[1.2]: #12--2026-11-15
[1.1]: #11--2026-11-15
[1.0]: #10--2026-11-15
