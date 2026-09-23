"""Ядро пайплайна: сырые таблицы → все результаты. Используется run.py, тестами и валидацией."""
import time

import networkx as nx
import numpy as np
import pandas as pd

from . import clusters, extra, features, priority, roles


def layout(G: nx.DiGraph) -> pd.DataFrame:
    """Координаты для экрана: force-directed укладка неориентированного графа."""
    U = G.to_undirected()
    pos = nx.spring_layout(U, weight=None, k=0.6 / np.sqrt(max(len(U), 1)), iterations=60, seed=42)
    return (pd.DataFrame(pos, index=["x", "y"]).T * 3000).round(1)


def compute(nodes, edges, tx, cfg, with_layout=True, with_stability=True, log=print) -> dict:
    t0 = time.time()
    step = lambda s: log(f"[{time.time() - t0:5.1f}s] {s}")

    G = features.build_graph(nodes, edges)
    f = features.node_features(nodes, edges, tx, G, cfg)
    step("метрики посчитаны")
    f = roles.assign_roles(f, cfg, edges)
    step("роли: " + ", ".join(f"{k}={v}" for k, v in f.role.value_counts().items()))
    if with_stability:
        f = f.join(extra.role_stability(f, cfg, edges))
        step(f"устойчивость ролей: {cfg['stability']['runs']} прогонов, средняя {f.role_stability.mean():.2f}")
    else:
        f["role_stability"], f["alt_role"] = 1.0, ""
    f = f.join(extra.depth_anomalies(f, cfg))
    routes = extra.repeated_routes(tx, cfg)
    f["routes_mid"] = routes.groupby("b").size().reindex(f.index).fillna(0).astype(int)
    step(f"аномалий по колену: {int(f.anomaly.sum())}, устойчивых маршрутов A→B→C: {len(routes)}")
    f["cluster_id"] = clusters.cluster(G, cfg).reindex(f.index)
    step(f"кластеров: {f.cluster_id.nunique()}")
    f = priority.score(f, cfg)
    ct = clusters.cluster_table(f, edges)
    top = priority.top_nodes(f, cfg["top_n"])
    nxt = priority.next_requests(f, edges, cfg.get("next_requests_n", 40))
    split = features.splitting_episodes(tx, cfg)
    f.index.name = "gid"
    fr = f.reset_index()
    if with_layout:
        fr = fr.join(layout(G), on="gid")
        step("укладка графа посчитана")
    return {"nodes": fr, "clusters": ct, "top": top, "next_requests": nxt, "splitting": split,
            "routes": routes, "edges": edges, "tx": tx, "graph": G}
