"""FastAPI backend: REST поверх PostgreSQL (или локального DuckDB) + статика фронтенда.

    uvicorn api.main:app --reload
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import assistant, store, tools, whatif

app = FastAPI(title="Tamyr — HackAlem AI")


def _gid(gid: str) -> str:
    """gid — 1–20 цифр; иначе 404, а не 500."""
    gid = gid.strip()
    if not gid.isdigit() or len(gid) > 20:
        raise HTTPException(404, "клиент не найден: gid должен состоять из цифр")
    return gid


def _n(n: int, hi: int = 200) -> int:
    return max(1, min(int(n), hi))


@app.get("/api/config")
def config():
    """Пороги и веса из pipeline/config.yaml — интерфейс показывает, из чего сложился приоритет."""
    import yaml
    return yaml.safe_load(open(Path(__file__).parent.parent / "pipeline" / "config.yaml", encoding="utf-8"))


@app.get("/api/storage")
def storage():
    return {"backend": store.backend()}


@app.get("/api/stats")
def stats():
    s = store.q("""SELECT count(*) AS nodes, sum(is_seed::int) AS seeds,
                   (SELECT count(*) FROM edges) AS edges, (SELECT sum(sum_kzt) FROM edges) AS turnover,
                   (SELECT count(*) FROM clusters) AS clusters FROM nodes""")[0]
    s["roles"] = {r["role"]: r["n"] for r in store.q("SELECT role, count(*) AS n FROM nodes GROUP BY role ORDER BY n DESC")}
    return s


@app.get("/api/graph")
def full_graph():
    """Весь граф с координатами укладки (2–3 тыс. узлов — отдаём целиком)."""
    nodes = store.q("""SELECT gid, role, cluster_id, priority_score, role_score, is_seed, depth, x, y,
                       in_sum + out_sum AS turnover FROM nodes""")
    edges = store.q("SELECT src, dst, sum_kzt, n_tx FROM edges")
    return {"nodes": nodes, "edges": edges}


@app.get("/api/node/{gid}")
def node(gid: str):
    gid = _gid(gid)
    n = store.node(gid)
    if not n:
        raise HTTPException(404, "узел не найден")
    return {**n, **store.neighbors(gid), "transactions": store.transactions(gid)}


@app.get("/api/ego/{gid}")
def ego(gid: str, hops: int = 1, direction: str = "both"):
    gid = _gid(gid)
    if direction not in ("in", "out", "both"):
        raise HTTPException(400, "direction: in | out | both")
    return store.ego(gid, max(1, min(hops, 4)), direction)


@app.get("/api/search")
def search(q: str):
    q = q.strip()
    return store.q("""SELECT gid, role, priority_score, is_seed FROM nodes
                      WHERE gid::text LIKE %s ORDER BY priority_score DESC LIMIT 15""", (f"%{q}%",))


@app.get("/api/top")
def top(n: int = 30):
    return store.q("SELECT * FROM top_nodes ORDER BY rank LIMIT %s", (_n(n),))


@app.get("/api/clusters")
def clusters():
    return store.q("SELECT * FROM clusters ORDER BY cluster_id")


@app.get("/api/path")
def path(src: str, dst: str):
    return tools.trace_path(src, dst)


@app.get("/api/next_requests")
def next_requests(n: int = 40):
    return tools.next_requests(n)


@app.get("/api/cycles/{gid}")
def cycles(gid: str):
    gid = _gid(gid)
    return tools.find_cycles(gid)


@app.get("/api/splitting")
def splitting(gid: str | None = None, n: int = 20):
    return tools.find_splitting(gid, n)


@app.get("/api/routes")
def routes(gid: str | None = None, n: int = 20):
    return tools.find_routes(gid, n)


@app.get("/api/anomalies")
def anomalies(n: int = 30):
    return tools.anomalies(n)


@app.get("/api/flows")
def flows():
    return tools.money_flows()


@app.get("/api/timeline")
def timeline():
    """Все транзакции (≈5 тыс.) для проигрывателя июля."""
    return store.q("SELECT src, dst, date, sum_kzt FROM transactions ORDER BY date")


@app.get("/api/whatif")
def whatif_knobs():
    return whatif.knobs()


class WhatIf(BaseModel):
    overrides: dict[str, float] = {}


@app.post("/api/whatif")
def whatif_run(w: WhatIf):
    allowed = {f"{k['section']}.{k['key']}" for k in whatif.knobs()}
    bad = set(w.overrides) - allowed
    if bad:
        raise HTTPException(400, f"неизвестные пороги: {', '.join(sorted(bad))}")
    return whatif.run(w.overrides)


class Mark(BaseModel):
    status: str | None = None      # confirmed | rejected | review | None (снять)
    comment: str = ""


@app.get("/api/marks")
def marks():
    return store.all_marks()


@app.post("/api/marks/{gid}")
def set_mark(gid: str, m: Mark):
    gid = _gid(gid)
    if m.status not in (None, "", "clear", "confirmed", "rejected", "review"):
        raise HTTPException(400, "status: confirmed | rejected | review | clear")
    return {"gid": gid, "mark": store.set_mark(gid, m.status, m.comment)}


@app.get("/api/resilience")
def resilience(top_n: int = 10):
    return tools.simulate_removal(top_n=top_n)


class Chat(BaseModel):
    messages: list[dict]


@app.post("/api/assistant")
def ask(chat: Chat):
    try:
        return assistant.ask(chat.messages)
    except RuntimeError as e:          # нет ключа или провайдер недоступен
        raise HTTPException(503, str(e))


@app.post("/api/node/{gid}/card")
def card(gid: str):
    gid = _gid(gid)
    try:
        return assistant.node_card(gid)
    except RuntimeError as e:
        raise HTTPException(503, str(e))


app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "frontend", html=True), name="frontend")
