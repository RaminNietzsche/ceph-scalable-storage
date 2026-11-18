#!/usr/bin/env python3
"""Open or update the weekly CI report issue. Used by .github/workflows/weekly.yml.

Reads lychee.md (lychee-action, Markdown format) and ceph-commands.md
(tools/check_ceph_commands.py). With --dry-run it only prints the issue body.
"""
from __future__ import annotations
import os, pathlib, re, subprocess, sys


def lychee_section() -> str:
    p = pathlib.Path("lychee.md")
    text = p.read_text(encoding="utf-8", errors="replace") if p.exists() else ""
    m = re.search(r"Errors\s*\|\s*(\d+)", text)
    if not m:
        code = os.environ.get("LYCHEE_EXIT", "?")
        return (f"_lychee did not produce a report (exit code {code}); see the job log. "
                "A configuration or command-line error looks like this._")
    total = re.search(r"Total\s*\|\s*(\d+)", text)
    if int(m.group(1)) == 0:
        n = total.group(1) if total else "all"
        return f"No broken external links ({n} links checked)."
    # keep the per-file error lists, drop the summary table and the footer link
    body = text[text.find("## Errors per input"):] if "## Errors per input" in text else text
    return body.strip()[:60000]


def main() -> int:
    run = f"{os.environ.get('GITHUB_SERVER_URL')}/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ.get('GITHUB_RUN_ID')}"
    parts = ["# Weekly CI report", "", f"Run: {run}", "", "## External links (lychee)", lychee_section(), ""]
    p = pathlib.Path("ceph-commands.md")
    parts += ["## Ceph command check",
              p.read_text(encoding="utf-8", errors="replace")[:60000] if p.exists() else "_no report produced_", ""]
    body = "\n".join(parts).rstrip() + "\n"
    pathlib.Path("/tmp/weekly-issue.md").write_text(body, encoding="utf-8")
    if "--dry-run" in sys.argv[1:]:
        print(body)
        return 0
    title = "Weekly CI report: external links and Ceph commands"
    out = subprocess.check_output(["gh", "issue", "list", "-S", f"in:title {title}", "--state", "open", "--json", "number", "-q", ".[0].number"], text=True).strip()
    if out:
        subprocess.check_call(["gh", "issue", "edit", out, "--body-file", "/tmp/weekly-issue.md"])
        print("updated issue", out)
        return 0
    subprocess.check_call(["gh", "label", "create", "ci-report", "--description", "Scheduled CI reports", "--color", "BFD4F2", "--force"])
    subprocess.check_call(["gh", "issue", "create", "--title", title, "--label", "ci-report", "--body-file", "/tmp/weekly-issue.md"])
    return 0

if __name__ == "__main__":
    sys.exit(main())
