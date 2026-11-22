# Publishing: GitHub, Pages, releases, Zenodo and the web-edition options

This file is the checklist for running the book's public repository
`RaminNietzsche/ceph-scalable-storage` and its web edition at <https://book.ceph-s3.ir>.

## Workflows

| Workflow | Trigger | What it does |
|---|---|---|
| `.github/workflows/ci.yml` | push to `main`, pull request, manual | `make check`; builds the web edition with `SITE_URL=https://book.ceph-s3.ir`, runs `make check-site` and deploys `build/site` to GitHub Pages with `actions/deploy-pages` (pushes to `main` only); builds the PDFs, EPUB, DOCX and single-file HTML as workflow artifacts |
| `.github/workflows/release.yml` | tag `v*` (or manual with an existing tag) | checks that the tag matches the book version (`tools/check_publish.py --tag`), builds PDF, EPUB, DOCX and single-file HTML for both editions and attaches them, with `SHA256SUMS.txt`, to a GitHub Release whose notes are the version's CHANGELOG section; then notifies confirmed newsletter subscribers when `MAIL_HOOK_KEY` is set |
| `.github/workflows/preview.yml` | pull request | builds the web edition and, when `CLOUDFLARE_API_TOKEN` is set, uploads it to the `ceph-book-preview` Cloudflare Pages project and comments the `pages.dev` URL on the PR |
| `.github/workflows/weekly.yml` | Mondays 06:00 UTC, or manual | report-only: lychee on external links (`lychee.toml`), and `tools/check_ceph_commands.py`, which checks every Ceph command line in the book against the Ceph source of main and of the release branches its badges name (allowlist: `tools/ceph-commands-allowlist.yaml`); opens or updates a `ci-report` issue |
| `.github/workflows/ci.yml` (`translation-pr`) | pull request | warns when `content/fa` changes without the matching `content/en` path (non-blocking annotations) |

Figures are committed, so CI does not render Mermaid (it touches `build/.figures.stamp`);
KaTeX comes from `node_modules` or, without it, from `templates/vendor/katex/`.
The site and preview workflows install `libavif-bin` (`avifenc`) and cache
`build/avif-cache` so figure AVIFs are produced and reused; `tools/check_avif.py --require`
confirms that `<picture>` lists the AVIF source before WebP.

## One-time repository settings

1. **Pages**: Settings → Pages → Build and deployment → Source: **GitHub Actions**.
   Custom domain: `book.ceph-s3.ir`. The build writes `build/site/CNAME` (from `SITE_URL`, or
   the `CNAME` variable the workflow sets), so the domain survives every deployment.
2. **Variables** (Settings → Secrets and variables → Actions → *Variables*, not secrets; they are
   public values but stay out of the repository):
   - `CF_BEACON_TOKEN`: the Cloudflare Web Analytics token of the `book.ceph-s3.ir` site.
   - `FEEDBACK_ENDPOINT` (optional): an https URL that receives "Was this section helpful?" votes.
   - `NEWSLETTER_ACTION` (optional): an https form URL (POST with field `email`) of a newsletter
     service. Without it the home page offers "Watch releases on GitHub" and the Atom feed.
   - `ASK_ENDPOINT` (optional): the "Ask the book" Worker. The workflow defaults to
     `https://ask.ceph-s3.ir`; set the variable to `none` to build the site without the button.
   Pull-request builds never get these values.
3. **Environment** `github-pages` is created by the first deployment; restrict it to `main`.

## DNS and Cloudflare

`book.ceph-s3.ir` is a CNAME to `raminnietzsche.github.io`, proxied by Cloudflare.

- GitHub Pages issues its own certificate only when it can see its own IPs for the domain. With
  the Cloudflare proxy on, either switch the record to *DNS only* until GitHub shows "Certificate
  issued" and then turn the proxy back on, or leave "Enforce HTTPS" off in GitHub and let
  Cloudflare terminate TLS.
- Cloudflare SSL/TLS mode: **Full** (not Flexible, which loops with GitHub's HTTPS redirect).
- Cloudflare Web Analytics: with the proxy on, it can also be enabled automatically on the zone;
  use one of the two (zone injection or the `CF_BEACON_TOKEN` script tag), not both, or visits
  are counted twice.
- `_headers` in the site is for hosts that read it (Netlify, Cloudflare Pages); GitHub Pages
  ignores it. A Content-Security-Policy, if wanted, can be added as a Cloudflare response-header
  transform rule: `script-src 'self' 'unsafe-inline' https://static.cloudflareinsights.com;
  connect-src 'self' https://cloudflareinsights.com` plus the `FEEDBACK_ENDPOINT` and
  `ASK_ENDPOINT` origins.

## Analytics and the "helpful?" buttons

Analytics is injected only when configured at build time: `CF_BEACON_TOKEN` (Cloudflare Web
Analytics, cookie-less) or `ANALYTICS=plausible` with `PLAUSIBLE_DOMAIN`. The site states this in
its footer and next to the newsletter box, in both languages.

Cloudflare Web Analytics counts page views and Web Vitals only; **it has no custom events**. The
"Was this section helpful?" buttons therefore call `bookEvent()` (in `templates/site/site.js`),
which sends the vote

- to `FEEDBACK_ENDPOINT`, when set, as a `navigator.sendBeacon` text body
  `{"event":"section-feedback","props":{"page","section","helpful","lang"},…}` (no cookies,
  no personal data);
- to Plausible, Umami or GoatCounter if one of them is loaded (they do support events);
- as a `book:event` DOM event.

After a "No", the reader is offered a prefilled GitHub issue (label `feedback`) that names the
page and the section anchor; `FEEDBACK_ISSUES=0` turns that off. Create the `feedback` label in
the repository so the issues are labelled.

A minimal endpoint is a Cloudflare Worker that writes each vote to Workers Analytics Engine:

```js
// wrangler.toml: [[analytics_engine_datasets]] binding = "FEEDBACK"
export default {
  async fetch(req, env) {
    if (req.method !== 'POST') return new Response('', { status: 405 });
    const v = JSON.parse(await req.text());
    const p = v.props || {};
    env.FEEDBACK.writeDataPoint({ blobs: [p.page || '', p.section || '', p.helpful || '', p.lang || ''], indexes: [p.page || ''] });
    return new Response('', { status: 204, headers: { 'Access-Control-Allow-Origin': 'https://book.ceph-s3.ir' } });
  }
};
```

## Releases and Zenodo DOIs

1. Bump `version` and the dates in `content/fa/metadata.yaml` and `content/en/metadata.yaml`,
   turn `## [Unreleased]` in `CHANGELOG.md` into `## [X.Y] - YYYY-MM-DD`, and update `version`,
   `date-released` and `preferred-citation.edition` in `CITATION.cff`. `make check` verifies
   that they agree.
2. Tag and push: `git tag -a vX.Y -m "Version X.Y" && git push origin vX.Y`. The release
   workflow builds the books and publishes the GitHub Release.
3. Zenodo, once: sign in at <https://zenodo.org> with GitHub, link ORCID 0009-0000-7622-8130 in
   the Zenodo profile, and switch the repository on under Account → GitHub. Zenodo archives
   **public** repositories only, so this step waits until the repository is public. From then on
   every published GitHub Release is archived with the metadata in `.zenodo.json` (a book,
   CC BY-NC-SA 4.0, ORCID, keywords, no affiliation) and gets a version DOI; the concept DOI
   names all versions.
4. The first archive is in place. The concept DOI (all versions) is
   [10.5281/zenodo.24253822](https://doi.org/10.5281/zenodo.24253822) and the
   version DOI for v1.6 is [10.5281/zenodo.24253823](https://doi.org/10.5281/zenodo.24253823)
   ([record](https://zenodo.org/records/24253823)); v1.7 is
   [10.5281/zenodo.24434974](https://doi.org/10.5281/zenodo.24434974)
   ([record](https://zenodo.org/records/24434974)). They are recorded in
   `CITATION.cff` (`doi:` and `preferred-citation.doi` are the concept DOI;
   `identifiers` lists the concept DOI and each version DOI) and the README has a DOI badge that links to the
   concept DOI. Later GitHub Releases get a new version DOI; the concept DOI
   stays the same. Do not invent a DOI, and do not retag a published version
   to refresh Zenodo.

## Before making the repository public

- `git ls-files | xargs grep -nIE '(ghp_|github_pat_|AKIA|BEGIN [A-Z ]*PRIVATE KEY|xox[abp]-)'`
  must print nothing; no internal host names or personal e-mail addresses in tracked files.
- Large files: `git count-objects -vH` and
  `git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | sort -k3 -n | tail`.
- Commits use the GitHub no-reply address; for commits to link to the GitHub account it should
  be the `<id>+RaminNietzsche@users.noreply.github.com` form shown under Settings → Emails.

## Newsletter email

Double opt-in confirmation and “new edition” notices are sent by the `book-feedback`
Worker (`POST /v1/subscribe`, `GET /v1/confirm`, `POST /v1/notify-release`) through
Cloudflare Email Sending, from `book@ceph-s3.ir`. The release workflow calls
`/v1/notify-release` when `MAIL_HOOK_KEY` is set as a repository secret (and as a
Worker secret of the same name).

Until that service is fully enabled, confirmation mail is not sent and
`MAIL_LIVE` stays off, so the Worker will only send to the test allowlist
(`ramin.najarbashi@gmail.com`). Sending to arbitrary confirmed subscribers needs:

1. Dashboard → Compute → Email Service → Email Sending → Onboard Domain → `ceph-s3.ir`.
   Cloudflare adds MX/SPF/DKIM on the `cf-bounce` subdomain and `_dmarc.ceph-s3.ir`.
   There are no existing mail records on this zone; do not change other DNS
   (book, blog, policygen, feedback).
2. A **Workers Paid** plan, required to send to addresses that are not verified
   Email Routing destinations. Verified destinations are free on the Workers Free
   plan and are enough for a test to `ramin.najarbashi@gmail.com` (add and confirm
   that address under Email Routing → Destination addresses).
3. After onboarding, add a `send_email` binding named `EMAIL` to the
   `book-feedback` Worker. Set Worker secret `MAIL_HOOK_KEY` (already used by
   `release.yml`) and only then set `MAIL_LIVE=1` to mail the real confirmed list.

## Feedback alerts

`GET https://feedback.ceph-s3.ir/stats/alerts.json?since=<ISO-8601>` (default: last 24 hours)
is protected by the same `STATS_KEY` as `/stats` (Bearer, `X-Stats-Key`, or `?key=`).
The JSON lists `helpful=no` votes grouped by page, section and language, and the
new newsletter signups in that window. A daily routine can poll this together
with GitHub issues labelled `feedback`.

## Pull-request previews

`.github/workflows/preview.yml` builds `build/site` for each pull request and uploads
it to Cloudflare Pages project `ceph-book-preview` (direct upload, not a Git
integration). The preview URL is `https://pr-<number>.ceph-book-preview.pages.dev`
and is posted as a PR comment.

The Cloudflare MCP used to maintain this repository cannot create Pages projects
(403). Ramin needs to add one repository secret:

1. [Create an API token](https://dash.cloudflare.com/profile/api-tokens) → Custom token.
2. Account resources: include account `53895845b7cfe401510ca1843235f3fc`.
3. Permissions: **Account — Cloudflare Pages — Edit**, and **Account — Account Settings — Read**
   (wrangler asks for the latter).
4. Settings → Secrets and variables → Actions → Secrets → `CLOUDFLARE_API_TOKEN`.

The first successful deploy creates the `ceph-book-preview` project automatically.
Do not point a custom domain at this project; production stays on GitHub Pages at
https://book.ceph-s3.ir.

## Search engines

`make check-site` already checks `sitemap.xml` (absolute `loc` and `hreflang` when
`SITE_URL` is set), `robots.txt`, Book/Chapter JSON-LD and Open Graph images.
The production sitemap is https://book.ceph-s3.ir/sitemap.xml.

To verify the property, a DNS TXT record on `ceph-s3.ir` (or `book.ceph-s3.ir`) is
enough; it can be added as a Cloudflare DNS TXT without touching the book CNAME,
blog, policygen or feedback records. After you have the token from the console,
it can be added for you:

1. **Google Search Console**: Add property `https://book.ceph-s3.ir` (URL prefix).
   Choose DNS TXT verification and send the token (the `google-site-verification=…`
   value). Then submit the sitemap `https://book.ceph-s3.ir/sitemap.xml`.
2. **Bing Webmaster Tools**: Add the same URL. Bing can import a verified Search
   Console property, or it can issue its own DNS TXT token the same way. Submit
   the same sitemap.

Do not add placeholder TXT records. Wait for the official token from each console.

## "Ask the book"

With `ASK_ENDPOINT` set, every page has an "Ask the book" / «از کتاب بپرس» button. The panel
(`templates/site/ask.js`) is fetched only on the first click, so it costs nothing on page load
and no request leaves the page before the reader asks. A question is POSTed to
`ASK_ENDPOINT/v1/ask` and answered by the `book-ask` Worker from the book's own text, with
links to the sections used. The Worker, its D1 database and the indexing scripts are in
`infra/book-ask/`; re-index after a content release (see its README). The footer privacy note
says where questions go.
