"""Аналитические функции над графом. Используются и REST-эндпоинтами, и AI-ассистентом
(как инструменты function calling). Ассистент отвечает ТОЛЬКО по их результатам."""
import networkx as nx

from . import store


def get_node(gid: str) -> dict:
    n = store.node(gid)
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
