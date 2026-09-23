"""Аналитические функции над графом. Используются и REST-эндпоинтами, и AI-ассистентом
(как инструменты function calling). Ассистент отвечает ТОЛЬКО по их результатам."""
import networkx as nx

from . import store


def get_node(gid: str) -> dict:
    n = store.node(str(gid))
    if not n:
        return {"error": f"узел {gid} не найден"}
    nb = store.neighbors(gid)
    n["top_incoming"] = nb["incoming"][:10]
    n["top_outgoing"] = nb["outgoing"][:10]
    return n


def get_neighbors(gid: str, direction: str = "both", hops: int = 1) -> dict:
    hops = max(1, min(int(hops), 3))
    sub = store.ego(gid, hops, direction, limit=150)
    return {"n_nodes": len(sub["nodes"]),
            "nodes": sorted(sub["nodes"], key=lambda x: -x["priority_score"])[:40],
            "edges": sorted(sub["edges"], key=lambda x: -x["sum_kzt"])[:60]}


def common_receivers(gids: list[str], max_hops: int = 3) -> dict:
    """Кто получает деньги (напрямую или через цепочку) сразу от нескольких указанных узлов."""
    G = store.graph()
    reach = {}
    for g in gids:
        if g not in G:
            continue
        lengths = nx.single_source_shortest_path_length(G, g, cutoff=max_hops)
        for n, dist in lengths.items():
            if n != g:
                reach.setdefault(n, {})[g] = dist
    common = [{"gid": n, "from_count": len(src), "from": src, **{k: G.nodes[n][k] for k in ("role", "priority_score", "is_seed")}}
              for n, src in reach.items() if len(src) >= 2]
    common.sort(key=lambda x: (-x["from_count"], -x["priority_score"]))
    return {"queried": gids, "common_receivers": common[:20]}


def trace_path(src: str, dst: str) -> dict:
    G = store.graph()
    try:
        path = nx.shortest_path(G, src, dst)
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return {"path": None, "note": "направленного пути денег нет"}
    return {"path": [{"gid": n, "role": G.nodes[n]["role"]} for n in path],
            "hops": [{"src": u, "dst": v, "sum_kzt": G[u][v]["sum_kzt"]} for u, v in zip(path, path[1:])]}


def top_nodes(role: str | None = None, cluster_id: int | None = None, n: int = 10, include_seed: bool = True) -> list:
    sql, p = "SELECT gid, role, role_score, cluster_id, priority_score, is_seed, evidence FROM nodes WHERE TRUE", []
    if role:
        sql += " AND role = %s"; p.append(role)
    if cluster_id is not None:
        sql += " AND cluster_id = %s"; p.append(int(cluster_id))
    if not include_seed:
        sql += " AND NOT is_seed"
    sql += " ORDER BY priority_score DESC LIMIT %s"; p.append(min(int(n), 50))
    return store.q(sql, p)


def cluster_summary(cluster_id: int) -> dict:
    c = store.q("SELECT * FROM clusters WHERE cluster_id = %s", (int(cluster_id),))
    if not c:
        return {"error": "кластер не найден"}
    return {**c[0], "top_nodes": top_nodes(cluster_id=cluster_id, n=8)}


def simulate_removal(gids: list[str] | None = None, top_n: int | None = None) -> dict:
    """Оценка устойчивости: что станет с сетью, если заблокировать узлы."""
    G = store.graph()
    if not gids:
        gids = [r["gid"] for r in top_nodes(n=top_n or 10, include_seed=False)]
    seeds = {n for n, d in G.nodes(data=True) if d["is_seed"]}

    def stats(H):
        comps = sorted((len(c) for c in nx.weakly_connected_components(H)), reverse=True)
        reach = set()
        for s in seeds & set(H.nodes):
            reach |= nx.descendants(H, s)
        flow = sum(d["sum_kzt"] for u, v, d in H.edges(data=True))
        return {"components": len(comps), "largest_component": comps[0] if comps else 0,
                "nodes_reachable_from_seed": len(reach), "total_flow_kzt": round(flow)}

    before = stats(G)
    H = G.copy()
    H.remove_nodes_from(gids)
    after = stats(H)
    return {"removed": gids, "before": before, "after": after,
            "flow_cut_share": round(1 - after["total_flow_kzt"] / max(before["total_flow_kzt"], 1), 3),
            "reach_cut_share": round(1 - after["nodes_reachable_from_seed"] / max(before["nodes_reachable_from_seed"], 1), 3)}


def find_cycles(gid: str, max_len: int = 4) -> dict:
    """Возвратные потоки через узел: цепочки, где деньги возвращаются к отправителю."""
    G = store.graph()
    if gid not in G:
        return {"error": f"узел {gid} не найден"}
    H = G.subgraph(nx.single_source_shortest_path_length(G.to_undirected(as_view=True), gid, cutoff=max_len))
    cyc = [c for c in nx.simple_cycles(H, length_bound=max_len) if gid in c]
    out = []
    for c in sorted(cyc, key=len)[:15]:
        k = c.index(gid)
        c = c[k:] + c[:k]
        hops = list(zip(c, c[1:] + c[:1]))
        out.append({"chain": c + [gid], "sums_kzt": [G[u][v]["sum_kzt"] for u, v in hops],
                    "roles": [G.nodes[n]["role"] for n in c]})
    return {"gid": gid, "n_cycles": len(cyc), "cycles": out}


def next_requests(n: int = 15) -> list:
    """Какие данные запросить следующими, чтобы закрыть белые пятна выгрузки."""
    return store.q("SELECT * FROM next_requests LIMIT %s", (min(int(n), 50),))


def find_splitting(gid: str | None = None, n: int = 20) -> dict:
    """Дробление: несколько переводов одной паре в один день. Для узла или топ по сети."""
    if gid:
        rows = store.q("SELECT * FROM splitting WHERE src = %s OR dst = %s ORDER BY day", (int(gid), int(gid)))
    else:
        rows = store.q("SELECT * FROM splitting ORDER BY pair_split_days DESC, n_tx DESC LIMIT %s", (min(int(n), 50),))
    return {"gid": gid, "episodes": rows, "n_episodes": len(rows)}


def find_routes(gid: str | None = None, n: int = 20) -> dict:
    """Повторяющиеся маршруты A→B→C (A платит B, B в течение 3 дней платит C, повторилось ≥3 раз)."""
    if gid:
        rows = store.q("""SELECT * FROM routes WHERE a = %s OR b = %s OR c = %s
                          ORDER BY repeats DESC LIMIT %s""", (int(gid), int(gid), int(gid), min(int(n), 50)))
    else:
        rows = store.q("SELECT * FROM routes ORDER BY repeats DESC, sum_bc DESC LIMIT %s", (min(int(n), 50),))
    return {"gid": gid, "routes": rows}


def anomalies(n: int = 20) -> list:
    """Узлы, чьи денежные показатели аномальны для своего колена (robust z-score)."""
    return store.q("""SELECT gid, role, depth, anomaly_score, anomaly_text, priority_score FROM nodes
                      WHERE anomaly ORDER BY anomaly_score DESC LIMIT %s""", (min(int(n), 50),))


def money_flows() -> dict:
    """Потоки денег по коленам и ролям: откуда (колено, роль) → куда (колено, роль), сумма."""
    rows = store.q("""SELECT s.depth AS d1, s.role AS r1, t.depth AS d2, t.role AS r2,
                             sum(e.sum_kzt) AS sum_kzt, count(*) AS n_edges
                      FROM edges e JOIN nodes s ON s.gid = e.src JOIN nodes t ON t.gid = e.dst
                      GROUP BY s.depth, s.role, t.depth, t.role""")
    return {"flows": rows}
