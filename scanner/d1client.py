import json
import sqlite3
import subprocess
from typing import Protocol


class D1Client(Protocol):
    def query(self, sql: str) -> list: ...
    def execute(self, sql: str) -> None: ...


class SqliteD1Client:
    def __init__(self, path=":memory:"):
        self._conn = sqlite3.connect(path)
        self._conn.row_factory = sqlite3.Row

    def query(self, sql: str) -> list:
        cur = self._conn.execute(sql)
        return [dict(r) for r in cur.fetchall()]

    def execute(self, sql: str) -> None:
        self._conn.executescript(sql)
        self._conn.commit()


class WranglerD1Client:
    def __init__(self, db="stock-monitor", remote=True, wrangler=("npx", "wrangler")):
        self._db = db
        self._flag = "--remote" if remote else "--local"
        self._wrangler = list(wrangler)

    def _run(self, sql, json_out):
        cmd = self._wrangler + ["d1", "execute", self._db, self._flag, "--command", sql]
        if json_out:
            cmd.append("--json")
        out = subprocess.run(cmd, capture_output=True, text=True, check=True).stdout
        return out

    def query(self, sql: str) -> list:
        out = self._run(sql, json_out=True)
        data = json.loads(out)
        return data[0]["results"] if data else []

    def execute(self, sql: str) -> None:
        self._run(sql, json_out=False)
