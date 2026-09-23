"""Единая точка входа: сырые .parquet → метрики → роли → кластеры → приоритет → 3 CSV (+ PostgreSQL).

    python run.py                          # только CSV в output/
    python run.py --db postgresql://...    # + загрузка в PostgreSQL для интерфейса
    (или переменная окружения DATABASE_URL)
"""
import argparse
import os
import time
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
import yaml

from pipeline import clusters, features, priority, roles

NODE_COLS = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]


def layout(G: nx.DiGraph, cid: pd.Series) -> pd.DataFrame:
    """Координаты для экрана: force-directed укладка неориентированного графа."""
    U = G.to_undirected()
    pos = nx.spring_layout(U, weight=None, k=0.6 / np.sqrt(len(U)), iterations=60, seed=42)
    xy = pd.DataFrame(pos, index=["x", "y"]).T
    return (xy * 3000).round(1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="pipeline/config.yaml")
    ap.add_argument("--data", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--db", default=os.getenv("DATABASE_URL"))
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    data_dir, out = a.data or cfg["data_dir"], Path(a.out or cfg["out_dir"])
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    step = lambda s: print(f"[{time.time() - t0:5.1f}s] {s}", flush=True)

    nodes, edges, tx = features.load(data_dir)
    step(f"загружено: {len(nodes)} узлов, {len(edges)} рёбер, {len(tx)} транзакций")
    G = features.build_graph(nodes, edges)
    f = features.node_features(nodes, edges, tx, G, cfg)
    step("метрики посчитаны")
    f = roles.assign_roles(f, cfg, edges)
    step("роли: " + ", ".join(f"{k}={v}" for k, v in f.role.value_counts().items()))
    f["cluster_id"] = clusters.cluster(G, cfg).reindex(f.index)
    step(f"кластеров: {f.cluster_id.nunique()}")
    f = priority.score(f, cfg)
    ct = clusters.cluster_table(f, edges)
    top = priority.top_nodes(f, cfg["top_n"])
    nxt = priority.next_requests(f, edges, cfg.get("next_requests_n", 40))
    f.index.name = "gid"
    fr = f.reset_index()

    # --- обязательные выгрузки фиксированной схемы ---
    fr[NODE_COLS].to_csv(out / "nodes_roles.csv", index=False)
    ct[["cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis"]].to_csv(
        out / "clusters.csv", index=False)
    top[["rank", "gid", "role", "priority_score", "why"]].to_csv(out / "top_nodes.csv", index=False)
    # --- расширенные метрики (для интерфейса и разбора) ---
    fr.to_csv(out / "nodes_metrics.csv", index=False)
    nxt.to_csv(out / "next_requests.csv", index=False)
    step(f"CSV записаны в {out}/")

    if a.db:
        from pipeline import db
        xy = layout(G, f.cluster_id)
        fr = fr.join(xy, on="gid")
        step("укладка графа посчитана")
        db.load_all(a.db, {
            "nodes": (fr, "gid"),
            "edges": (edges, None),
            "transactions": (tx.assign(date=tx.date.dt.date.astype(str)), None),
            "clusters": (ct, "cluster_id"),
            "top_nodes": (top, "rank"),
            "next_requests": (nxt, None),
        })
        step("загружено в PostgreSQL")
    step("готово")


if __name__ == "__main__":
    main()
