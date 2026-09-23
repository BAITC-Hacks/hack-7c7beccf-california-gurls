"""Доступ к данным. Два режима хранения с одинаковыми SQL-запросами:
- postgres — PostgreSQL (docker compose, DATABASE_URL);
- local    — DuckDB в памяти поверх output/db/*.parquet (запуск без базы: python run.py && uvicorn ...).
STORAGE=auto (по умолчанию) пробует PostgreSQL и, если он недоступен, переключается на local.

Все gid наружу отдаются СТРОКАМИ: они ~1e17 и не помещаются в Number JavaScript."""
import json
import os
import threading
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import networkx as nx

ROOT = Path(__file__).resolve().parent.parent
DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/moneygraph")
DB_DIR = Path(os.getenv("DB_DIR", ROOT / "output" / "db"))
MARKS_FILE = ROOT / "output" / "analyst_marks.json"

NODE_FIELDS = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence", "depth", "is_seed",
               "in_deg", "out_deg", "in_sum", "out_sum", "pass_ratio", "seed_reach", "seed_payers",
               "fast_share", "max_payers_same_day", "active_days", "truncated", "pagerank", "betweenness",
               "component", "cycles", "reciprocal", "hub_payers", "second_level",
               "split_out", "split_in", "split_tx", "near_threshold_share",
               "role_stability", "alt_role", "anomaly", "anomaly_score", "anomaly_text", "routes_mid",
               "c_role", "c_money", "c_seed", "c_central"]

_lock = threading.Lock()


def _pg_available() -> bool:
    try:
        import psycopg
        with psycopg.connect(DSN, connect_timeout=2) as c:
            c.execute("SELECT 1 FROM nodes LIMIT 1")
        return True
    except Exception:
        return False


@lru_cache(maxsize=1)
def backend() -> str:
    mode = os.getenv("STORAGE", "auto").lower()
    if mode == "postgres" or (mode == "auto" and _pg_available()):
        return "postgres"
    if not (DB_DIR / "nodes.parquet").exists():
        raise RuntimeError(f"Нет данных для интерфейса: сначала выполните `python run.py` (ожидается {DB_DIR})")
    return "local"


@lru_cache(maxsize=1)
def _duck():
    import duckdb
    con = duckdb.connect(":memory:")
    for p in sorted(DB_DIR.glob("*.parquet")):
        con.execute(f"CREATE TABLE {p.stem} AS SELECT * FROM read_parquet('{p.as_posix()}')")
    con.execute("CREATE TABLE analyst_marks (gid TEXT PRIMARY KEY, status TEXT, comment TEXT, updated_at TIMESTAMP)")
    if MARKS_FILE.exists():
        for m in json.loads(MARKS_FILE.read_text(encoding="utf-8")):
            con.execute("INSERT INTO analyst_marks VALUES (?, ?, ?, ?)",
                        (m["gid"], m["status"], m.get("comment", ""), m.get("updated_at")))
    return con


def q(sql: str, params=None) -> list[dict]:
    if backend() == "postgres":
        import psycopg
        from psycopg.rows import dict_row
        with psycopg.connect(DSN, row_factory=dict_row) as c:
            cur = c.execute(sql, params)
            rows = cur.fetchall() if cur.description else []
            c.commit()
            return [_clean(r) for r in rows]
    with _lock:
        cur = _duck().cursor()
        cur.execute(sql.replace("%s", "?"), list(params) if params else None)
        if cur.description is None:
            return []
        cols = [d[0] for d in cur.description]
        return [_clean(dict(zip(cols, r))) for r in cur.fetchall()]


def _clean(r: dict) -> dict:
    for k in ("gid", "src", "dst", "a", "b", "c"):
        if k in r and r[k] is not None:
            r[k] = str(r[k])
    for k in ("date", "day", "updated_at"):
        if k in r and r[k] is not None:
            r[k] = str(r[k])
    for k, v in r.items():  # NaN → None, чтобы JSON был валидным
        if isinstance(v, float) and v != v:
            r[k] = None
    return r


# ---------- граф в памяти ----------
@lru_cache(maxsize=1)
def graph() -> nx.DiGraph:
    G = nx.DiGraph()
    for n in q("SELECT gid, role, cluster_id, priority_score, is_seed FROM nodes"):
        G.add_node(n["gid"], **n)
    for e in q("SELECT src, dst, sum_kzt, n_tx FROM edges"):
        G.add_edge(e["src"], e["dst"], sum_kzt=e["sum_kzt"], n_tx=e["n_tx"])
    return G


def node(gid: str) -> dict | None:
    rows = q(f"SELECT {', '.join(NODE_FIELDS)} FROM nodes WHERE gid = %s", (int(gid),))
    if not rows:
        return None
    n = rows[0]
    n["mark"] = get_mark(gid)
    return n


def neighbors(gid: str) -> dict:
    ins = q("""SELECT e.src AS gid, e.sum_kzt, e.n_tx, n.role, n.is_seed, n.priority_score
               FROM edges e JOIN nodes n ON n.gid = e.src WHERE e.dst = %s ORDER BY e.sum_kzt DESC""", (int(gid),))
    outs = q("""SELECT e.dst AS gid, e.sum_kzt, e.n_tx, n.role, n.is_seed, n.priority_score
                FROM edges e JOIN nodes n ON n.gid = e.dst WHERE e.src = %s ORDER BY e.sum_kzt DESC""", (int(gid),))
    return {"incoming": ins, "outgoing": outs}


def transactions(gid: str) -> list[dict]:
    return q("""SELECT src, dst, date, sum_kzt FROM transactions WHERE src = %s OR dst = %s
                ORDER BY date, sum_kzt DESC""", (int(gid), int(gid)))


def ego(gid: str, hops: int = 1, direction: str = "both", limit: int = 400) -> dict:
    G = graph()
    if gid not in G:
        return {"nodes": [], "edges": []}
    seen, frontier = {gid}, {gid}
    for _ in range(hops):
        nxt = set()
        for n in frontier:
            if direction in ("both", "in"):
                nxt |= set(G.predecessors(n))
            if direction in ("both", "out"):
                nxt |= set(G.successors(n))
        nxt -= seen
        seen |= nxt
        frontier = nxt
        if len(seen) > limit:
            break
    sub = G.subgraph(list(seen)[:limit])
    return {"nodes": [dict(G.nodes[n]) for n in sub],
            "edges": [{"src": u, "dst": v, **d} for u, v, d in sub.edges(data=True)]}


# ---------- отметки аналитика ----------
def get_mark(gid: str) -> dict | None:
    rows = q("SELECT gid, status, comment, updated_at FROM analyst_marks WHERE gid = %s", (str(gid),))
    return rows[0] if rows else None


def all_marks() -> list[dict]:
    return q("""SELECT m.gid, m.status, m.comment, m.updated_at, n.role, n.priority_score
                FROM analyst_marks m LEFT JOIN nodes n ON n.gid::text = m.gid ORDER BY m.updated_at DESC""")


def set_mark(gid: str, status: str | None, comment: str = "") -> dict | None:
    if status in (None, "", "clear"):
        q("DELETE FROM analyst_marks WHERE gid = %s", (str(gid),))
    else:
        q("""INSERT INTO analyst_marks (gid, status, comment, updated_at) VALUES (%s, %s, %s, %s)
             ON CONFLICT (gid) DO UPDATE SET status = excluded.status, comment = excluded.comment,
             updated_at = excluded.updated_at""", (str(gid), status, comment, datetime.now()))
    if backend() == "local":  # в локальном режиме отметки переживают перезапуск через JSON
        MARKS_FILE.write_text(json.dumps(q("SELECT * FROM analyst_marks"), ensure_ascii=False, indent=1),
                              encoding="utf-8")
    return get_mark(gid)
