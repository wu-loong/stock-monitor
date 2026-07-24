import os
import scanner.d1client as d1client
from scanner.d1client import SqliteD1Client, WranglerD1Client


def test_sqlite_execute_and_query():
    c = SqliteD1Client(":memory:")
    c.execute("CREATE TABLE t (a TEXT PRIMARY KEY, b INTEGER);")
    c.execute("INSERT INTO t (a,b) VALUES ('x',1); INSERT INTO t (a,b) VALUES ('y',2);")
    rows = c.query("SELECT a,b FROM t ORDER BY a;")
    assert rows == [{"a": "x", "b": 1}, {"a": "y", "b": 2}]


def test_sqlite_upsert_idempotent():
    c = SqliteD1Client(":memory:")
    c.execute("CREATE TABLE t (a TEXT PRIMARY KEY, b INTEGER);")
    stmt = "INSERT INTO t (a,b) VALUES ('x',1) ON CONFLICT(a) DO UPDATE SET b=excluded.b;"
    c.execute(stmt)
    c.execute(stmt.replace(",1)", ",9)"))
    assert c.query("SELECT b FROM t WHERE a='x';") == [{"b": 9}]


def test_wrangler_execute_uses_file_for_large_sql_not_command(monkeypatch):
    """300 支股票一批 ≈209 KiB SQL,单条 --command argv 会超 Linux MAX_ARG_STRLEN
    (128 KiB)导致 execve 报 'Argument list too long'。execute 必须落临时 .sql 文件,
    用 --file 传给 wrangler,而不是 --command。本测试不联网、不 spawn 真实 wrangler,
    只 monkeypatch subprocess.run 捕获 argv 并在调用瞬间读取临时文件内容。"""
    big_sql = "INSERT INTO t (a) VALUES ('x');\n" * 8000  # 数百 KiB,远超 128 KiB
    assert len(big_sql) > 128 * 1024

    captured = {}

    class FakeCompleted:
        stdout = ""

    def fake_run(cmd, capture_output=True, text=True, check=True):
        captured["cmd"] = cmd
        # 在 fake run 内部(临时文件被 finally 清理之前)读取文件内容
        file_idx = cmd.index("--file") + 1
        path = cmd[file_idx]
        assert os.path.exists(path)
        with open(path) as f:
            captured["file_content"] = f.read()
        return FakeCompleted()

    monkeypatch.setattr(d1client.subprocess, "run", fake_run)

    client = WranglerD1Client(db="stock-monitor", remote=True)
    client.execute(big_sql)

    cmd = captured["cmd"]
    assert "--file" in cmd
    assert "--command" not in cmd
    assert captured["file_content"] == big_sql
    # 临时文件应在 execute 返回后被清理(finally 删除)
    path = cmd[cmd.index("--file") + 1]
    assert not os.path.exists(path)
