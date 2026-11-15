# book-feedback Worker

Source for the Cloudflare Worker at <https://feedback.ceph-s3.ir>
(account `53895845b7cfe401510ca1843235f3fc`, script name `book-feedback`,
D1 database `book-feedback`).

Routes:

- `POST /v1/vote` — section feedback
- `POST /v1/subscribe` — newsletter signup (honeypot, origin check, rate limit)
- `GET /v1/confirm?t=` — double opt-in confirmation
- `GET|POST /v1/unsubscribe?t=` — unsubscribe (POST is for one-click `List-Unsubscribe`)
- `POST /v1/notify-release` — mail confirmed subscribers about a new edition (`MAIL_HOOK_KEY`)
- `GET /stats`, `/stats.json`, `/stats/subscribers.csv` — `STATS_KEY`
- `GET /stats/alerts.json?since=` — downvotes and new subscribers since an ISO timestamp (`STATS_KEY`)

Mail is sent with Cloudflare Email Sending (`send_email` binding named `EMAIL`,
from `book@ceph-s3.ir`) only when that binding exists. Until `MAIL_LIVE=1` is
set, the Worker will only send to the test allowlist (`ramin.najarbashi@gmail.com`).
See `docs/PUBLISHING.md`.

Deploy through the Cloudflare API (multipart Worker script upload) and keep
existing `secret_text` bindings (`HASH_SALT`, `STATS_KEY`, `MAIL_HOOK_KEY`,
optional `CF_ANALYTICS_TOKEN`). Do not commit secrets.
