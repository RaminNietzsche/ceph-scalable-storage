#!/usr/bin/env python3
"""Open or update the weekly CI report issue. Used by .github/workflows/weekly.yml."""
from __future__ import annotations
import os, pathlib, subprocess, sys

def main() -> int:
    parts = ["# Weekly CI report", "",
             f"Run: {os.environ.get('GITHUB_SERVER_URL')}/{os.environ.get('GITHUB_REPOSITORY')}/actions/runs/{os.environ.get('GITHUB_RUN_ID')}", ""]
    for title, path in (("External links (lychee)", "lychee.md"), ("Ceph command check", "ceph-commands.md")):
        parts.append(f"## {title}")
        p = pathlib.Path(path)
        parts.append(p.read_text(encoding="utf-8", errors="replace")[:60000] if p.exists() else "_no report produced_")
        parts.append("")
    body = "\n".join(parts).rstrip() + "\n"
    pathlib.Path("/tmp/weekly-issue.md").write_text(body, encoding="utf-8")
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
