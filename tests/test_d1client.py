from scanner.d1client import SqliteD1Client


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
