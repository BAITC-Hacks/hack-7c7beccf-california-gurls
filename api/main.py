"""FastAPI backend: REST поверх PostgreSQL (или локального DuckDB) + статика фронтенда.

    uvicorn api.main:app --reload
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from pipeline import integrity

from . import assistant, audit, security, store, tools, whatif

ROOT = Path(__file__).resolve().parent.parent
app = FastAPI(title="Tamyr — HackAlem AI", docs_url=None, redoc_url=None, openapi_url=None)  # схему API не публикуем
app.add_middleware(security.SecurityMiddleware)


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
def node(gid: str, request: Request, ctx: str = "card"):
    gid = _gid(gid)
    n = store.node(gid)
    if not n:
        raise HTTPException(404, "узел не найден")
    if ctx in ("card", "dossier", "report"):      # просмотр карточки клиента фиксируется в журнале
        audit.record(security.analyst(request), f"view_{ctx}", gid)
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
def whatif_run(w: WhatIf, request: Request):
    allowed = {f"{k['section']}.{k['key']}" for k in whatif.knobs()}
    bad = set(w.overrides) - allowed
    if bad:
        raise HTTPException(400, f"неизвестные пороги: {', '.join(sorted(bad))}")
    r = whatif.run(w.overrides)
    if w.overrides:
        audit.record(security.analyst(request), "whatif", "", {"overrides": w.overrides, "changed": r["changed"]})
    return r


class Mark(BaseModel):
    status: str | None = None      # confirmed | rejected | review | None (снять)
    comment: str = ""


@app.get("/api/marks")
def marks():
    return store.all_marks()


@app.post("/api/marks/{gid}")
def set_mark(gid: str, m: Mark, request: Request):
    gid = _gid(gid)
    if m.status not in (None, "", "clear", "confirmed", "rejected", "review"):
        raise HTTPException(400, "status: confirmed | rejected | review | clear")
    comment = (m.comment or "")[:500]
    mark = store.set_mark(gid, m.status, comment)
    audit.record(security.analyst(request), "mark", gid, {"status": m.status or "clear", "comment": comment})
    return {"gid": gid, "mark": mark}


@app.get("/api/resilience")
def resilience(top_n: int = 10):
    return tools.simulate_removal(top_n=top_n)


class Chat(BaseModel):
    messages: list[dict]


@app.post("/api/assistant")
def ask(chat: Chat, request: Request):
    last = next((m.get("content", "") for m in reversed(chat.messages) if m.get("role") == "user"), "")
    audit.record(security.analyst(request), "assistant", "", {"question": str(last)[:300]})
    try:
        return assistant.ask(chat.messages)
    except RuntimeError as e:          # нет ключа или провайдер недоступен
        raise HTTPException(503, str(e))


@app.post("/api/node/{gid}/card")
def card(gid: str, request: Request):
    gid = _gid(gid)
    audit.record(security.analyst(request), "ai_card", gid)
    try:
        return assistant.node_card(gid)
    except RuntimeError as e:
        raise HTTPException(503, str(e))


# ---------- безопасность и комплаенс ----------
@app.get("/api/audit")
def audit_log(n: int = 100):
    return audit.recent(_n(n, 1000))


@app.get("/api/audit/verify")
def audit_verify():
    return audit.verify()


@app.get("/api/integrity")
def integrity_check():
    """Сверка входных данных, конфига, кода и выгрузок с отпечатками SHA-256 из output/manifest.json."""
    return integrity.verify(ROOT, ROOT / "output" / "manifest.json")


@app.get("/api/security")
def security_status():
    return {**security.status(), "storage": store.backend(), "llm_pseudonymization": True}


app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "frontend", html=True), name="frontend")
