"""FastAPI backend: REST поверх PostgreSQL + статика фронтенда.

    uvicorn api.main:app --reload
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import assistant, store, tools

app = FastAPI(title="Граф денег — HackAlem AI")


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
    n = store.node(gid)
    if not n:
        raise HTTPException(404, "узел не найден")
    return {**n, **store.neighbors(gid), "transactions": store.transactions(gid)}


@app.get("/api/ego/{gid}")
def ego(gid: str, hops: int = 1, direction: str = "both"):
    return store.ego(gid, max(1, min(hops, 4)), direction)


@app.get("/api/search")
def search(q: str):
    q = q.strip()
    return store.q("""SELECT gid, role, priority_score, is_seed FROM nodes
                      WHERE gid::text LIKE %s ORDER BY priority_score DESC LIMIT 15""", (f"%{q}%",))


@app.get("/api/top")
def top(n: int = 30):
    return store.q("SELECT * FROM top_nodes ORDER BY rank LIMIT %s", (n,))


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
    return tools.find_cycles(gid)


@app.get("/api/resilience")
def resilience(top_n: int = 10):
    return tools.simulate_removal(top_n=top_n)


class Chat(BaseModel):
    messages: list[dict]


@app.post("/api/assistant")
def ask(chat: Chat):
    try:
        return assistant.ask(chat.messages)
    except RuntimeError as e:
        raise HTTPException(503, str(e))


@app.post("/api/node/{gid}/card")
def card(gid: str):
    try:
        return assistant.node_card(gid)
    except RuntimeError as e:
        raise HTTPException(503, str(e))


app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "frontend", html=True), name="frontend")
