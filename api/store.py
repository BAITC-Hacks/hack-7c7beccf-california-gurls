"""Доступ к данным: PostgreSQL + граф в памяти для обходов.
Все gid наружу отдаются СТРОКАМИ: они ~1e17 и не помещаются в Number JavaScript."""
import os
from functools import lru_cache

import networkx as nx
import psycopg
from psycopg.rows import dict_row

DSN = os.getenv("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/moneygraph")

NODE_FIELDS = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence", "depth", "is_seed",
               "in_deg", "out_deg", "in_sum", "out_sum", "pass_ratio", "seed_reach", "seed_payers",
               "fast_share", "max_payers_same_day", "active_days", "truncated", "pagerank", "betweenness",
               "component", "cycles", "reciprocal", "hub_payers", "second_level"]


def q(sql: str, params=None) -> list[dict]:
    with psycopg.connect(DSN, row_factory=dict_row) as c:
        return [_clean(r) for r in c.execute(sql, params).fetchall()]


def _clean(r: dict) -> dict:
    for k in ("gid", "src", "dst"):
        if k in r and r[k] is not None:
            r[k] = str(r[k])
    if "date" in r and r["date"] is not None:
        r["date"] = str(r["date"])
    return r


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
    return rows[0] if rows else None


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
