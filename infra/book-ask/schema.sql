-- D1 database "book-ask" (Worker book-ask)
CREATE TABLE IF NOT EXISTS chunks (rid INTEGER PRIMARY KEY, id TEXT UNIQUE NOT NULL, lang TEXT NOT NULL, slug TEXT NOT NULL,
  title TEXT NOT NULL, section TEXT NOT NULL, url TEXT NOT NULL, text TEXT NOT NULL, emb BLOB);
CREATE INDEX IF NOT EXISTS chunks_lang ON chunks(lang);
CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(title, section, text, content='chunks', content_rowid='rid',
  tokenize='unicode61 remove_diacritics 2');
-- answered questions per day and language; no question text, no IP
CREATE TABLE IF NOT EXISTS ask_daily (day TEXT NOT NULL, lang TEXT NOT NULL, n INTEGER NOT NULL DEFAULT 0,
  nohit INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(day, lang));
-- per-IP rate limit: salted hash of (window, slot, IP), expires with the window
CREATE TABLE IF NOT EXISTS rl (k TEXT PRIMARY KEY, n INTEGER NOT NULL, exp INTEGER NOT NULL);
