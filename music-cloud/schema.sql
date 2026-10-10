CREATE TABLE IF NOT EXISTS budgets (
  bucket TEXT PRIMARY KEY,
  used INTEGER NOT NULL CHECK (used > 0 AND used <= ceiling),
  ceiling INTEGER NOT NULL,
  expires INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS search_cache (
  key TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  expires INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS budget_expiry ON budgets(expires);
CREATE INDEX IF NOT EXISTS cache_expiry ON search_cache(expires);
CREATE TABLE IF NOT EXISTS music_libraries (
  uid TEXT PRIMARY KEY,
  payload TEXT NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  updated INTEGER NOT NULL
);
