# book-ask Worker

"Ask the book" for the web edition: answers questions about Ceph from the text of this
book only, in Persian or English, with links to the sections it used.

- Worker `book-ask` at <https://ask.ceph-s3.ir> (account `53895845b7cfe401510ca1843235f3fc`,
  custom domain on zone `ceph-s3.ir`)
- D1 database `book-ask` (`3ad9af50-2dfb-44fe-95a6-370bcd79ed78`), schema in `schema.sql`
- Workers AI: `@cf/baai/bge-m3` (embeddings) and `@cf/google/gemma-4-26b-a4b-it` (answers,
  `CHAT_MODEL` binding; thinking is turned off)

## How it answers

1. The question is turned into an FTS5 query (stop words dropped, prefix match for Latin terms)
   and the 40 best passages of the question's language are taken by bm25 (title, section and
   text weighted 4:3:1); the other language fills in when fewer than 8 match.
2. The candidates are re-ranked by cosine similarity with the question's bge-m3 embedding
   (stored int8-quantised next to each passage), at most 3 per page, 6 in total.
3. The chat model gets the numbered passages and must answer only from them, in the
   question's language, citing `[n]`. The response is `{answer, lang, sources[{n, title,
   section, url, cited}], model}`.

## Routes

- `POST /v1/ask` `{"q": "..."}`: up to 500 characters. CORS only for `https://book.ceph-s3.ir`
  (other browser origins get 403). Limits: 5 questions a minute and 30 an hour per IP, and
  `DAILY_CAP` (200) answered questions a day in total, which keeps Workers AI inside the free
  10,000 neurons a day.
- `GET /v1/health`
- `POST /v1/admin/ingest`, `GET /v1/admin/stats`: `Authorization: Bearer <admin key>`. The
  Worker holds only the SHA-256 of the key (`ADMIN_KEY_SHA256`); the key itself is kept
  outside the repository.

## Privacy

The question text is never stored or logged (Workers observability is off). D1 keeps a daily
count per language (answered / not found) and, for the rate limit, a salted hash of the
time window and IP that expires with the window. The IP itself is never stored.

## Re-indexing after a content change

```sh
make site LANG=fa && make site LANG=en
python3 infra/book-ask/build_chunks.py > build/ask-chunks.jsonl
BOOK_ASK_ADMIN_KEY=... python3 infra/book-ask/ingest.py build/ask-chunks.jsonl --reset
```

`--reset` empties the tables first. About 2,900 passages take two to three minutes and about
1,500 neurons.

## Deploying

Upload `worker.js` as an ES module through the Cloudflare API (multipart Worker script upload)
with these bindings: `ai` `AI`; `d1` `DB`; `ratelimit` `RL` (namespace `2201`, 6 per 60 s);
`plain_text` `ADMIN_KEY_SHA256`, `DAILY_CAP`, `CHAT_MODEL`. Keep observability disabled.
