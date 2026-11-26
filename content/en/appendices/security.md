---
id: security
lang: en
---

::: {.tldr}

- Every S3 request passes the same layers: TLS, authentication (SigV4, SigV2, presigned URL or STS token), authorization (explicit deny first, then identity and bucket policies, then ACLs), rate limits and quotas, and encryption at rest; the gateway's own traffic to RADOS is protected by cephx and msgr2.
- Prefer SigV4, short presigned URLs (SigV4 allows at most seven days; a SigV2 URL has no upper limit) and STS temporary credentials over long-lived keys; rotate keys by adding the new key before removing the old one.
- Write bucket policies and, from Squid, account-based IAM policies; keep ACLs private and turn on Block Public Access. An explicit `Deny` always wins.
- Use SSE-KMS or SSE-S3 with an external KMS (Vault, KMIP or Barbican), TLS on the frontend or a trusted load balancer, `secure` msgr2 mode for the RGW-to-OSD traffic, and Object Lock for data that must not be deleted.
- Do not expose the Admin Ops API to the internet, enable the ops log or bucket logging for an audit trail, and follow the Ceph security advisories and point releases.

```bash
radosgw-admin ratelimit set --ratelimit-scope=user --uid=app1 --max-read-ops=1000 --max-write-ops=200
```

[![The layers of an S3 request in RGW: TLS, authentication, authorization, rate limits and quotas, encryption at rest, and the cephx and msgr2 link to RADOS, with the ops log alongside](figures/app/f02_rgw_security_layers.png)](#fig-app-rgw-security-layers)

:::

This appendix gathers the security of the RADOS Gateway in one place: what an attacker can try against an S3 endpoint, how RGW authenticates and authorizes a request, how data is encrypted in transit and at rest, how to stop deletion and abuse, and a hardening checklist with the configuration options that matter. Chapter 4 introduces users, policies and encryption; chapter 41 follows a request through the gateway in the code; this appendix is the operator's view of the same path. Every option name below is taken from `src/common/options/rgw.yaml.in`, and the key commands are also in [Appendix B: Command Cheat Sheet](#appB).

![The layers of an S3 request in RGW, from the client to RADOS: TLS at the beast frontend or the load balancer; authentication with SigV4, SigV2, a presigned URL or an STS token; authorization with explicit deny, identity and bucket policies and ACLs; rate limits and quotas; encryption at rest with SSE-S3, SSE-KMS or SSE-C; and the link to the OSDs with cephx and msgr2 secure mode. The ops log and bucket logging record each request](figures/app/f02_rgw_security_layers.png){#fig-app-rgw-security-layers}

# Threat model

Begin with what you are protecting and from whom. For a typical S3 gateway the useful list is short:

| Threat | Example | Main defence |
|---|---|---|
| Stolen or leaked credentials | An access key in a public Git repository, a presigned URL in a chat | Short-lived STS credentials, short presigned URLs, key rotation, least-privilege policies |
| Public data by mistake | A bucket policy with `"Principal": "*"`, a `public-read` ACL | Block Public Access, review of policies, no ACLs |
| A tenant reaching another tenant's data | A shared namespace, a too-wide policy | Accounts or tenants, policies scoped to ARNs, separate placement for sensitive data |
| Eavesdropping or tampering on the wire | Plain HTTP on a shared network, `crc` msgr2 mode | TLS to the client, `secure` msgr2 mode to the OSDs |
| Disclosure of data at rest | A stolen disk, a decommissioned host | SSE with an external KMS, encrypted OSDs (chapter 11) |
| Deletion or ransomware | A compromised key deletes or overwrites objects | Versioning, Object Lock, MFA delete, a separate replica (chapter 5) |
| Abuse and denial of service | A client floods the gateway with requests or fills the cluster | Rate limits, quotas, a load balancer with connection limits |
| Abuse of the management plane | Admin Ops API reachable from the internet, a user with admin caps | A separate admin endpoint, `rgw_enable_apis`, minimal caps |
| Missing audit trail | No record of who deleted an object | Ops log, bucket logging, usage log, central log collection |

The gateway is also a client of the cluster: it holds a cephx key with broad rights on the RGW pools. Anything that runs on an RGW host can use that key, so treat the RGW hosts as part of the storage cluster, not as ordinary web servers.

# Authentication: users, keys and signatures

## Users, subusers and keys

An RGW user (chapter 4, [Creating a radosgw user](#sec-04-4-1)) has one or more S3 key pairs; a subuser has its own Swift key and a limited access level. Create service users with the least access they need, and suspend a user instead of deleting it while you investigate an incident:

```bash
radosgw-admin user create --uid=app1 --display-name="Application 1"
radosgw-admin subuser create --uid=app1 --subuser=app1:swift --access=read --key-type=swift --gen-secret
radosgw-admin user suspend --uid=app1
radosgw-admin user enable --uid=app1
```

`radosgw-admin user info --uid=app1` shows the keys, caps and quotas of a user; it prints the secret keys, so do not paste its output into a ticket.

## SigV4 and SigV2

RGW accepts AWS Signature Version 4 and the older Version 2. SigV4 signs the request with a key derived from the secret, the date, the region and the service, so a captured signature is valid only for that request and a short time; SigV2 signs with the secret itself and is weaker. Chapter 41 ([The SigV4 signature](#sec-41-3)) follows the check step by step in the code. Configure clients and SDKs to use SigV4; most current SDKs do so by default. Clock skew matters for both: keep NTP on the gateway hosts.

With Keystone (chapter 4, [Integrating with OpenStack Keystone](#sec-04-7)) or LDAP, `rgw_s3_auth_order` decides the order in which the authentication engines are tried, and `rgw_s3_auth_use_keystone` enables the Keystone engine. Enable only the engines you use.

## Presigned URLs and their limits

A presigned URL carries the signature in its query string, so whoever has the URL can perform that one operation until it expires. RGW checks the limits that AWS documents: for SigV4 the `X-Amz-Expires` value must be between 1 second and 604800 seconds (seven days). A SigV2 presigned URL carries an absolute `Expires` time, and RGW only checks that this time has not passed, so a SigV2 URL can be valid for years. Give URLs the shortest lifetime that works, generate them with SigV4, and remember that a URL stays valid until it expires even if the user no longer needs it; the only way to revoke it early is to remove the key that signed it.

When no application needs presigned URLs, turn them off completely; the option exists from Squid:

```bash {since=squid}
ceph config set client.rgw rgw_s3_auth_disable_signature_url true
```

## Rotating keys

Rotate a key without an outage by adding the new key first, moving the clients, and only then removing the old key. From Squid, a key can be deactivated before it is removed, which gives a quick way back:

```bash
radosgw-admin key create --uid=app1 --key-type=s3 --gen-access-key --gen-secret
radosgw-admin key rm --uid=app1 --key-type=s3 --access-key=OLDACCESSKEY
```

```bash {since=squid}
radosgw-admin key create --uid=app1 --key-type=s3 --access-key=OLDACCESSKEY --key-active=false
```

The cephx key of the gateway itself is rotated like any other daemon key; see [Step 2: move the cephx keys to aes256k](#appJ) in the upgrade guide.

# Authorization: policies and ACLs

## The evaluation order

RGW evaluates a request in the order of the AWS policy model; the logic is in `evaluate_iam_policies()` in `rgw_common.cc`:

1. An explicit `Deny` in an identity policy, the bucket policy or a session policy denies the request.
2. Otherwise an `Allow` from the bucket policy or from an identity policy allows it. With an STS session, the session policy must also allow the action.
3. For a cross-account request between accounts (from Squid), both the identity policy of the caller and the bucket policy of the owner must allow it.
4. If no policy decides, RGW falls back to the ACLs of the bucket and the object.

![Policy evaluation in RGW: an explicit Deny in any policy denies the request; otherwise an Allow from an identity or bucket policy (and the session policy for STS) allows it; a cross-account request needs an Allow from both sides; without a decision RGW falls back to the ACLs, and without a grant the request is denied](figures/app/f03_rgw_policy_eval.png){#fig-app-rgw-policy-eval}

## Bucket policies

A bucket policy (chapter 4, [Bucket policy and IAM](#sec-04-11-3)) is the main tool for access between users. Two conditions are worth adding to nearly every policy: deny requests that did not arrive over TLS, and limit sensitive buckets to known networks.

```json
{"Version":"2012-10-17","Statement":[
  {"Sid":"DenyPlainHTTP","Effect":"Deny","Principal":"*","Action":"s3:*",
   "Resource":["arn:aws:s3:::reports","arn:aws:s3:::reports/*"],
   "Condition":{"Bool":{"aws:SecureTransport":"false"}}},
  {"Sid":"OfficeOnly","Effect":"Deny","Principal":"*","Action":"s3:*",
   "Resource":["arn:aws:s3:::reports","arn:aws:s3:::reports/*"],
   "Condition":{"NotIpAddress":{"aws:SourceIp":["10.20.0.0/16"]}}}]}
```

`aws:SecureTransport` is true only when RGW itself terminates TLS, or when `rgw_trust_forwarded_https` is enabled behind a load balancer that sets `X-Forwarded-Proto`. `aws:SourceIp` is the address that RGW sees: behind a load balancer set `rgw_remote_addr_param` to the header that carries the client address (for example `HTTP_X_FORWARDED_FOR`), and make sure the load balancer overwrites that header rather than passing on a value from the client.

By default `rgw_policy_reject_invalid_principals` is true, so RGW rejects a policy whose principal does not exist; keep it that way, since a typo in a principal would otherwise create a policy that silently does nothing.

## ACLs and their pitfalls

ACLs are older than policies and coarse: `READ` on a bucket means listing, `WRITE` means creating and overwriting any object, and the canned ACLs `public-read` and `public-read-write` open a bucket to the whole internet. An ACL granted to the `AuthenticatedUsers` group grants access to every user of the cluster, not only to users of your organization. Keep ACLs private, grant access with policies, and turn on Block Public Access for every bucket that is not meant to be public:

```bash
aws $EP s3api put-public-access-block --bucket reports \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
```

With `RestrictPublicBuckets`, RGW denies a request that a public bucket policy would allow if the requester is not in the bucket owner's account.

## Accounts, IAM users, groups and roles

From Squid, an account ([Tenants and accounts](#sec-04-4-4)) owns users, groups, roles and their policies, and the account root user manages them through the IAM API. The cluster administrator creates the account and its root user once; after that the account manages itself:

```bash {since=squid}
radosgw-admin account create --account-name=acme --email=ops@acme.example
radosgw-admin user create --uid=acme-root --display-name="ACME root" --account-id=<account-id> --account-root --gen-access-key --gen-secret
radosgw-admin user policy attach --uid=app1 --policy-arn=arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess
```

```bash {since=squid}
aws $EP iam create-user --user-name app2
aws $EP iam put-user-policy --user-name app2 --policy-name rw-builds --policy-document file://rw-builds.json
```

Use the account root user only to create IAM users and roles, like the root user of an AWS account. The Tentacle release notes deprecate the older tenant-level IAM features in favour of accounts; for a new design use accounts.

# STS: temporary credentials

STS issues temporary credentials (access key, secret and session token) for a role. Enable it on every gateway with the same key; in Reef the key is 16 hexadecimal characters, and from Squid the option description asks for a base64 key from `ceph-authtool --gen-print-key`, so follow the description of your release:

```bash
ceph config set client.rgw rgw_s3_auth_use_sts true
ceph config set client.rgw rgw_sts_key <key>
ceph config set client.rgw rgw_sts_max_session_duration 3600
```

## AssumeRole

A role has a trust policy (who may assume it) and permission policies (what it may do):

```bash
radosgw-admin role create --role-name=Reports --assume-role-policy-doc=file://trust.json
radosgw-admin role-policy put --role-name=Reports --policy-name=read-reports --policy-doc=file://read-reports.json
```

```bash
aws $EP sts assume-role --role-arn arn:aws:iam:::role/Reports --role-session-name nightly --duration-seconds 900
```

The client then signs its requests with the temporary keys and the session token. A leaked temporary key is useful only until the session ends, which is why STS is the best replacement for long-lived keys in jobs and pipelines.

## AssumeRoleWithWebIdentity and OIDC

With AssumeRoleWithWebIdentity, a client that has a token from an OpenID Connect provider (Keycloak, Dex or a Kubernetes service-account issuer) receives temporary credentials without having any RGW key at all. Register the provider, then use its claims in the role's trust policy:

```bash
aws $EP iam create-open-id-connect-provider --url https://sso.example.com/realms/ceph \
  --client-id-list ceph-s3 --thumbprint-list <thumbprint>
aws $EP sts assume-role-with-web-identity --role-arn arn:aws:iam:::role/Reports \
  --role-session-name alice --web-identity-token "$TOKEN"
```

Limit the trust policy to the `aud` (client id) and, if possible, to the `sub` or a group claim; a trust policy that accepts any token from the provider lets every user of the identity provider assume the role.

# Encryption

## In transit: TLS

Terminate TLS either at RGW's beast frontend or at a load balancer such as the cephadm ingress service (chapter 4, [A load balancer with the ingress service](#sec-04-3-2)). Beast accepts `ssl_port`, `ssl_certificate`, `ssl_private_key`, `ssl_options` and `ssl_ciphers` in `rgw_frontends`:

```bash
ceph config set client.rgw rgw_frontends "beast ssl_port=443 ssl_certificate=config://rgw/cert/rgw.pem ssl_options=no_sslv2:no_sslv3:no_tlsv1:no_tlsv1_1"
```

If TLS ends at the load balancer, the link from the load balancer to RGW is plain HTTP; keep it on a private network, and only then set `rgw_trust_forwarded_https = true`. Because `rgw_crypt_require_ssl` is true by default, RGW refuses requests with encryption key headers that do not arrive over TLS (or over a trusted forwarded HTTPS connection).

## At rest: SSE-S3, SSE-KMS and SSE-C

| Mode | Who holds the key | RGW options | Notes |
|---|---|---|---|
| SSE-C | The client sends the key with every request | none | RGW never stores the key; lose it and the object is lost |
| SSE-KMS | An external KMS: Vault, KMIP or Barbican | `rgw_crypt_s3_kms_backend`, `rgw_crypt_vault_*`, `rgw_crypt_kmip_*`, `rgw_barbican_url` | The client names the key id; good for per-tenant keys |
| SSE-S3 | RGW, with keys kept in Vault | `rgw_crypt_sse_s3_backend` (only `vault`), `rgw_crypt_sse_s3_vault_*` | Can be the bucket default with put-bucket-encryption |

A Vault configuration for SSE-KMS with the transit engine and a token file:

```bash
ceph config set client.rgw rgw_crypt_s3_kms_backend vault
ceph config set client.rgw rgw_crypt_vault_addr https://vault.example.com:8200
ceph config set client.rgw rgw_crypt_vault_auth token
ceph config set client.rgw rgw_crypt_vault_token_file /etc/ceph/vault.token
ceph config set client.rgw rgw_crypt_vault_secret_engine transit
ceph config set client.rgw rgw_crypt_vault_prefix /v1/transit
```

For KMIP, set `rgw_crypt_s3_kms_backend = kmip` together with `rgw_crypt_kmip_addr`, `rgw_crypt_kmip_ca_path`, `rgw_crypt_kmip_client_cert` and `rgw_crypt_kmip_client_key`. Do not use `rgw_crypt_s3_kms_encryption_keys` or `rgw_crypt_default_encryption_key` in production: they keep the keys in the Ceph configuration and exist for testing. Keep `rgw_crypt_suppress_logs` at its default `true`, so that keys never reach the logs (the lesson of CVE-2018-16889).

Make encryption the bucket default so that clients cannot forget it, and deny unencrypted uploads in the bucket policy with the `s3:x-amz-server-side-encryption` condition key:

```bash
aws $EP s3api put-bucket-encryption --bucket reports \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
```

## Inside the cluster: msgr2 secure mode

The gateway talks to the monitors and OSDs over msgr2. In the default `crc` mode the data is authenticated by cephx but not encrypted on the wire; in `secure` mode every frame is encrypted with AES-GCM (chapter 26, [secure mode: AES-128-GCM on the wire](#sec-26-4)). On a network that you do not fully control, require secure mode for the RGW clients and, if the OSDs and monitors can afford the CPU, for the cluster as well:

```bash
ceph config set client.rgw ms_client_mode secure
ceph config set global ms_service_mode secure
ceph config set global ms_cluster_mode secure
```

Server-side encryption already protects object data at rest and on the OSD network; secure mode also protects metadata, the bucket index and the omap traffic. CVE-2020-1759 (nonce reuse in secure mode) is a reminder to run a point release that has the published fixes.

# Object Lock, versioning and MFA delete

Versioning keeps earlier versions of an object when it is overwritten or deleted; Object Lock (chapter 4, [Versioning and object lock](#sec-04-11-1)) prevents a version from being deleted or overwritten until a retention date, which is the core of a WORM or ransomware-resistant bucket. Object Lock must be enabled when the bucket is created and turns versioning on:

```bash
aws $EP s3api create-bucket --bucket audit --object-lock-enabled-for-bucket
aws $EP s3api put-object-lock-configuration --bucket audit \
  --object-lock-configuration '{"ObjectLockEnabled":"Enabled","Rule":{"DefaultRetention":{"Mode":"COMPLIANCE","Days":365}}}'
```

In `GOVERNANCE` mode a user with `s3:BypassGovernanceRetention` can still remove a version by sending `x-amz-bypass-governance-retention`; in `COMPLIANCE` mode nobody can, including the administrator through S3. Grant the bypass permission to nobody by default, and test compliance retention on a test bucket first, because it cannot be shortened.

RGW also supports MFA delete with TOTP tokens: create a TOTP device for the user, then enable MFA delete on the bucket's versioning with the device serial and a current code. After that, deleting a version or changing the versioning state needs a valid code in the `x-amz-mfa` header:

```bash
radosgw-admin mfa create --uid=admin1 --totp-serial=admin1-totp --totp-seed=<base32-seed>
aws $EP s3api put-bucket-versioning --bucket audit \
  --versioning-configuration Status=Enabled,MFADelete=Enabled --mfa "admin1-totp 123456"
```

MFA delete is rarely used in practice: it protects against a stolen key, but not against a stolen key together with the TOTP seed, and it makes automation harder. Object Lock in compliance mode, together with a replica in another zone, is the stronger protection.

# Tenant isolation

RGW has two levels of separation (chapter 4, [Tenants and accounts](#sec-04-4-4)): a tenant separates the bucket namespace (`tenant:bucket`, ARN `arn:aws:s3::tenant:bucket`), and an account (from Squid) separates users, roles and policies as well. Neither separates the data on disk: every tenant's objects live in the same RGW pools unless you give a tenant its own placement target and storage class with separate pools (chapter 4, [Lifecycle, storage classes and placement](#sec-04-11-2)). For strict isolation, with different encryption keys, different failure domains or different admins, use separate placement with separate pools and per-tenant KMS keys, or a separate zone. Check every policy with `"Principal":"*"` carefully: across tenants it can reach users that you did not think of.

# Rate limits and quotas

Rate limits (from the request side) and quotas (from the capacity side) are the main defence against a client that misbehaves, by mistake or on purpose ([Quotas and rate limits](#sec-04-4-2)). RGW counts operations and bytes per user, per bucket and for anonymous requests over a time window, and replies with `503 SlowDown` when the limit is reached; chapter 41 ([Rate limits](#sec-41-6)) shows how the counters work:

```bash
radosgw-admin ratelimit set --ratelimit-scope=user --uid=app1 --max-read-ops=1000 --max-write-ops=200 --max-write-bytes=104857600
radosgw-admin ratelimit enable --ratelimit-scope=user --uid=app1
radosgw-admin global ratelimit set --ratelimit-scope=anonymous --max-read-ops=100
radosgw-admin global ratelimit enable --ratelimit-scope=anonymous
radosgw-admin quota set --quota-scope=bucket --uid=app1 --max-objects=10000000 --max-size=5T
radosgw-admin quota enable --quota-scope=bucket --uid=app1
```

The limits are counted in each RGW instance separately, so with four gateways behind a load balancer a client can reach up to four times the configured value; divide accordingly. Set default quotas for new users with `rgw_user_default_quota_max_size` and `rgw_bucket_default_quota_max_objects`, and limit the number of buckets per user with `rgw_user_max_buckets`. A load balancer with connection limits and request timeouts is still needed in front: rate limiting happens after RGW has accepted and parsed the request.

# Hardening checklist

| Area | Check | Option or command |
|---|---|---|
| Frontend | TLS 1.2 or later only, strong ciphers, certificate from the config store | `rgw_frontends` with `ssl_options` and `ssl_ciphers` |
| Frontend | Limit request headers and idle connections | `max_header_size` and `request_timeout_ms` in `rgw_frontends` |
| Frontend | Behind a load balancer: trust its headers only if it sets them itself | `rgw_trust_forwarded_https`, `rgw_remote_addr_param` |
| APIs | Enable only the APIs you use; remove `admin` from the public gateways | `rgw_enable_apis` |
| Admin API | Serve the Admin Ops API on a separate, internal RGW instance | `rgw_admin_entry`, `rgw_enable_apis` |
| Admin users | Give admin caps only to the users that need them, read-only where possible | `radosgw-admin caps add --uid=monitor --caps="buckets=read;users=read;usage=read"` |
| Authentication | Turn off presigned URLs where nobody needs them | `rgw_s3_auth_disable_signature_url` (Squid and later) |
| Authentication | Enable only the authentication engines you use | `rgw_s3_auth_order`, `rgw_s3_auth_use_keystone`, `rgw_s3_auth_use_sts` |
| Policies | Reject policies with unknown principals | `rgw_policy_reject_invalid_principals` (default true) |
| Public data | Block Public Access on all private buckets | `put-public-access-block` |
| CORS | Allow only the origins and headers that a web application needs; never `*` with credentials | `put-bucket-cors`, `rgw_cors_rules_max_num` |
| Static websites | Enable the s3website API only on the gateways that serve sites | `rgw_enable_static_website`, `rgw_enable_apis` |
| Encryption | External KMS, default bucket encryption, no keys in the config | `rgw_crypt_s3_kms_backend`, `rgw_crypt_suppress_logs` |
| Cluster link | msgr2 secure mode for RGW | `ms_client_mode` |
| Logging | Ops log to a file or socket collected centrally | `rgw_enable_ops_log`, `rgw_ops_log_file_path` |
| Updates | Run the latest point release of your major release | [Appendix I](#appJ) |

The Admin Ops API (chapter 4, [The Admin Ops REST API](#sec-04-12-3)) can create users, read keys and remove buckets. Keep it away from the internet: run the public gateways with an `rgw_enable_apis` value that does not contain `admin`, and a separate internal gateway that does. CORS rules are a common source of mistakes: an allowed origin of `*` combined with credentials, or reflected headers, lets any web page use the visitor's session. CVE-2020-10753 and CVE-2021-3524 were header-injection bugs in RGW's CORS handling, fixed in their point releases; run a version with those fixes and keep CORS rules minimal.

# Logging and auditing

RGW has three request records, each with a different purpose:

| Record | What it holds | How to enable |
|---|---|---|
| Ops log | One entry per request: time, user, bucket, object, operation, status, bytes | `rgw_enable_ops_log`, with `rgw_ops_log_file_path` or `rgw_ops_log_socket_path`; `rgw_ops_log_rados` writes it to RADOS |
| Bucket logging (Tentacle and later) | S3 server access logs of one bucket, written as objects to another bucket | `put-bucket-logging` on the source bucket |
| Usage log | Totals of operations and bytes per user and bucket, for billing | `rgw_enable_usage_log`, then `radosgw-admin usage show` |

```bash
ceph config set client.rgw rgw_enable_ops_log true
ceph config set client.rgw rgw_ops_log_file_path /var/log/ceph/rgw-ops.log
ceph config set client.rgw rgw_log_http_headers http_x_forwarded_for,http_user_agent
```

```bash {since=tentacle}
radosgw-admin bucket logging info --bucket=reports
radosgw-admin bucket logging flush --bucket=reports
```

For an audit trail, send the ops log to a central log system that the storage administrators cannot change, keep the target bucket of bucket logging in a separate account with Object Lock, and record the `radosgw-admin` commands run on the admin hosts. The usage log is not an audit trail: it keeps totals, not individual requests.

Questions that the logs should be able to answer after an incident: which access key made the requests, from which address, which objects were read or deleted, and since when. Test this before you need it: delete a test object and find the entry.

# Security updates and advisories

Ceph publishes its advisories in three places: the security page of the documentation (docs.ceph.com/en/latest/security/), which lists the past CVEs with the fixed releases; the GitHub security advisories of the ceph/ceph repository; and the ceph-announce mailing list, which announces the point releases. Security fixes are released as point releases of the maintained major releases, so "update" usually means moving to the latest point release of your own release with a normal rolling upgrade (chapter 19 and [Appendix I](#appJ)).

A practical process:

1. Subscribe to ceph-announce and watch the advisories of the ceph/ceph repository, and follow your distribution's or vendor's security feed if you use packaged builds.
2. For each advisory, decide whether it affects you: the component (RGW, cephx, the dashboard), the API or feature, and the releases.
3. Upgrade a test cluster first, then production, gateways first if the fix is in RGW only.
4. If an upgrade has to wait, apply the mitigation that the advisory names, for example disabling an API in `rgw_enable_apis` or blocking a request pattern at the load balancer.
5. Report a new vulnerability privately to security@ceph.io, not in a public tracker, and wait for the coordinated release before discussing details.

Examples from the public list that are relevant to RGW: CVE-2018-16889 (encryption keys in the logs), CVE-2019-3821 (file descriptor exhaustion), CVE-2020-1760 (an XSS through header splitting), CVE-2020-10753 and CVE-2021-3524 (header injection through CORS) and CVE-2023-46159 (a denial of service). Each was fixed in a point release; the lesson is the same every time: a supported release, kept at its latest point release.

# Sources

- RGW configuration reference (`src/common/options/rgw.yaml.in`): https://docs.ceph.com/en/latest/radosgw/config-ref/
- Authentication, STS and OIDC in RGW: https://docs.ceph.com/en/latest/radosgw/STS/
- Accounts and the IAM API: https://docs.ceph.com/en/latest/radosgw/account/
- Bucket policies: https://docs.ceph.com/en/latest/radosgw/bucketpolicy/
- Server-side encryption: https://docs.ceph.com/en/latest/radosgw/encryption/
- Rate limits and quotas: https://docs.ceph.com/en/latest/radosgw/admin/
- Bucket logging: https://docs.ceph.com/en/latest/radosgw/bucket_logging/
- msgr2 and secure mode: https://docs.ceph.com/en/latest/rados/configuration/msgr2/
- Ceph security and past CVEs: https://docs.ceph.com/en/latest/security/
- AWS Signature Version 4 and presigned URLs: https://docs.aws.amazon.com/AmazonS3/latest/API/sigv4-query-string-auth.html
