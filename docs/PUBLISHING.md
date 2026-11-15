# Publishing: GitHub, Pages, releases, Zenodo and the web-edition options

This file is the checklist for running the book's public repository
`RaminNietzsche/ceph-scalable-storage` and its web edition at <https://book.ceph-s3.ir>.

## Workflows

| Workflow | Trigger | What it does |
|---|---|---|
| `.github/workflows/ci.yml` | push to `main`, pull request, manual | `make check`; builds the web edition with `SITE_URL=https://book.ceph-s3.ir`, runs `make check-site` and deploys `build/site` to GitHub Pages with `actions/deploy-pages` (pushes to `main` only); builds the PDFs, EPUB, DOCX and single-file HTML as workflow artifacts |
| `.github/workflows/release.yml` | tag `v*` (or manual with an existing tag) | checks that the tag matches the book version (`tools/check_publish.py --tag`), builds PDF, EPUB, DOCX and single-file HTML for both editions and attaches them, with `SHA256SUMS.txt`, to a GitHub Release whose notes are the version's CHANGELOG section |

Figures are committed, so CI does not render Mermaid (it touches `build/.figures.stamp`);
KaTeX comes from `node_modules` or, without it, from `templates/vendor/katex/`.

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
  connect-src 'self' https://cloudflareinsights.com` plus the `FEEDBACK_ENDPOINT` origin.

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
4. After the first archive, add the concept DOI to `CITATION.cff` (`doi:` and
   `preferred-citation.doi`) and a DOI badge to the README.

## Before making the repository public

- `git ls-files | xargs grep -nIE '(ghp_|github_pat_|AKIA|BEGIN [A-Z ]*PRIVATE KEY|xox[abp]-)'`
  must print nothing; no internal host names or personal e-mail addresses in tracked files.
- Large files: `git count-objects -vH` and
  `git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | sort -k3 -n | tail`.
- Commits use the GitHub no-reply address; for commits to link to the GitHub account it should
  be the `<id>+RaminNietzsche@users.noreply.github.com` form shown under Settings → Emails.
