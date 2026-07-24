CREATE TABLE IF NOT EXISTS run_state (
  trade_date    TEXT PRIMARY KEY,
  universe_json TEXT NOT NULL,
  total_batches INTEGER NOT NULL,
  next_batch    INTEGER NOT NULL,
  status        TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sample_daily (
  trade_date   TEXT NOT NULL,
  symbol       TEXT NOT NULL,
  name         TEXT,
  pool         TEXT,
  a_1030 REAL, b_1030 REAL,
  a_1130 REAL, b_1130 REAL,
  a_1400 REAL, b_1400 REAL,
  a_1500 REAL, b_1500 REAL,
  state_t      TEXT,
  state_prev   TEXT,
  data_quality TEXT,
  PRIMARY KEY (trade_date, symbol)
);

CREATE TABLE IF NOT EXISTS signals (
  trade_date   TEXT NOT NULL,
  symbol       TEXT NOT NULL,
  name         TEXT,
  pool         TEXT,
  close        REAL,
  data_quality TEXT,
  created_at   TEXT NOT NULL,
  PRIMARY KEY (trade_date, symbol)
);
CREATE INDEX IF NOT EXISTS idx_signals_date ON signals(trade_date);
CREATE INDEX IF NOT EXISTS idx_signals_symbol ON signals(symbol);
