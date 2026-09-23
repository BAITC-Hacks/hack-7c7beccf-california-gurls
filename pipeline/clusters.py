"""Кластеризация: Louvain на неориентированной версии графа, вес ребра = log(1 + сумма).
Узлы без рёбер (seed без переводов ≥5 000 ₸) — в отдельный кластер 0."""
import networkx as nx
import pandas as pd

from .roles import money


def cluster(G: nx.DiGraph, cfg: dict) -> pd.Series:
    U = nx.Graph()
    U.add_nodes_from(G.nodes)
    for u, v, d in G.edges(data=True):
        w = U[u][v]["w"] + d["w"] if U.has_edge(u, v) else d["w"]
        U.add_edge(u, v, w=w)
    isolated = [n for n in U if U.degree(n) == 0]
    U.remove_nodes_from(isolated)
    comms = nx.community.louvain_communities(U, weight="w", resolution=cfg["clustering"]["resolution"],
                                             seed=cfg["clustering"]["seed"])
    # нумерация: по убыванию размера, начиная с 1
    comms = sorted(comms, key=lambda c: (-len(c), min(c)))
    cid = {n: i + 1 for i, c in enumerate(comms) for n in c}
    cid.update({n: 0 for n in isolated})
    return pd.Series(cid, name="cluster_id")


def cluster_table(f: pd.DataFrame, edges: pd.DataFrame) -> pd.DataFrame:
    cid = f.cluster_id
    e = edges.assign(cs=edges.src.map(cid), cd=edges.dst.map(cid))
    internal = e[e.cs == e.cd].groupby("cs").sum_kzt.sum()
    outgoing = e[e.cs != e.cd].groupby("cs").sum_kzt.sum()
    rows = []
    for c, g in f.groupby("cluster_id"):
        top = g.sort_values("priority_score", ascending=False).head(5)
        rows.append({
            "cluster_id": int(c),
            "n_nodes": len(g),
            "n_seed": int(g.is_seed.sum()),
            "sum_kzt_internal": float(internal.get(c, 0.0)),
            "sum_kzt_outgoing": float(outgoing.get(c, 0.0)),
            "top_gids": ";".join(str(x) for x in top.index),
            "roles": ";".join(f"{k}:{v}" for k, v in g.role.value_counts().items() if k != "peripheral"),
            "hypothesis": hypothesis(c, g, internal.get(c, 0.0)),
        })
    return pd.DataFrame(rows).sort_values("cluster_id")


def hypothesis(c, g: pd.DataFrame, internal: float) -> str:
    """Шаблонная гипотеза о назначении кластера по составу ролей."""
    if c == 0:
        return "Seed-клиенты без переводов ≥5 000 ₸ в выгрузке: активность ниже порога или вне банка"
    rc = g.role.value_counts()
    n_seed = int(g.is_seed.sum())
    hubs = g[g.role.isin(["coordinator", "consolidator", "distributor"])].sort_values("priority_score", ascending=False)
    parts = []
    if n_seed >= 2 and rc.get("consolidator", 0) + rc.get("coordinator", 0) > 0:
        h = hubs.index[0]
        parts.append(f"Гипотеза: сбор средств с {n_seed} seed через узел {h} ({hubs.iloc[0].role})")
    elif n_seed >= 2:
        parts.append(f"Гипотеза: группа из {n_seed} seed с общими контрагентами")
    elif n_seed == 1:
        parts.append("Периферия одного seed")
    else:
        parts.append("Узлы без seed, связанные через потоки")
    if rc.get("distributor", 0) + rc.get("coordinator", 0) > 0:
        parts.append(f"веерное распределение ({rc.get('distributor', 0) + rc.get('coordinator', 0)} узл.)")
    if rc.get("transit", 0):
        parts.append(f"транзитные счета: {rc['transit']}")
    if rc.get("terminal", 0):
        parts.append(f"конечные получатели: {rc['terminal']}")
    parts.append(f"внутренний оборот {money(internal)}")
    return "; ".join(parts)[:300]
