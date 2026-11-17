#!/usr/bin/env python3
"""Load passages (from build_chunks.py) into the book-ask Worker.

    BOOK_ASK_ADMIN_KEY=... python3 infra/book-ask/ingest.py build/ask-chunks.jsonl [--reset]

The Worker embeds each batch with Workers AI (bge-m3) and stores it in D1.
The admin key is read from the environment and never printed.
"""
import json
import os
import sys
import time
import urllib.request

ENDPOINT = os.environ.get("BOOK_ASK_URL", "https://ask.ceph-s3.ir") + "/v1/admin/ingest"
KEY = os.environ["BOOK_ASK_ADMIN_KEY"]
BATCH = 16


def post(payload):
    req = urllib.request.Request(ENDPOINT, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Bearer {KEY}",
                                          "User-Agent": "book-ask-ingest/1"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            if attempt == 4:
                raise
            print(f"retry after {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))


def main():
    path = sys.argv[1]
    start = int(os.environ.get("START", "0"))
    chunks = [json.loads(line) for line in open(path, encoding="utf-8")]
    for i, c in enumerate(chunks, 1):
        c["rid"] = i
    if "--reset" in sys.argv:
        print(post({"reset": True}), file=sys.stderr)
    for i in range(start, len(chunks), BATCH):
        post({"chunks": chunks[i:i + BATCH]})
        if (i // BATCH) % 10 == 0:
            print(f"{i + BATCH}/{len(chunks)}", file=sys.stderr, flush=True)
    print(f"done: {len(chunks)} passages", file=sys.stderr)


if __name__ == "__main__":
    main()
