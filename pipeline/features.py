"""Загрузка данных и расчёт метрик узлов."""
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd


def load(data_dir: str):
    d = Path(data_dir)
    edges = pd.read_parquet(d / "edges.parquet")
    nodes = pd.read_parquet(d / "nodes.parquet")
    tx = pd.read_parquet(d / "transactions.parquet")
    tx["date"] = pd.to_datetime(tx["date"])
    for df in (edges, tx):
        df["src"] = df["src"].astype("int64")
        df["dst"] = df["dst"].astype("int64")
    nodes["gid"] = nodes["gid"].astype("int64")
    return nodes, edges, tx


def build_graph(nodes, edges) -> nx.DiGraph:
    G = nx.DiGraph()
    G.add_nodes_from(nodes.gid)
    for r in edges.itertuples(index=False):
        G.add_edge(r.src, r.dst, sum_kzt=float(r.sum_kzt), n_tx=int(r.n_tx),
                   w=float(np.log1p(r.sum_kzt)))
    return G


def fast_forward_share(tx: pd.DataFrame, days: int) -> pd.Series:
    """Доля входящих денег узла, после которых в течение `days` дней был исходящий перевод
    (не меньше 50% входящей суммы). Признак сквозного транзита."""
    inc = tx[["dst", "date", "sum_kzt"]].rename(columns={"dst": "gid", "date": "d_in", "sum_kzt": "s_in"})
    out = tx[["src", "date", "sum_kzt"]].rename(columns={"src": "gid", "date": "d_out", "sum_kzt": "s_out"})
    inc = inc.reset_index().rename(columns={"index": "in_id"})
    m = inc.merge(out, on="gid")
    m = m[(m.d_out >= m.d_in) & (m.d_out <= m.d_in + pd.Timedelta(days=days))]
    fwd = m.groupby("in_id").s_out.sum()
    inc["fwd"] = inc.in_id.map(fwd).fillna(0)
    inc["is_fast"] = inc.fwd >= 0.5 * inc.s_in
    g = inc.groupby("gid")
    return (g.apply(lambda x: x.loc[x.is_fast, "s_in"].sum() / x.s_in.sum(), include_groups=False))


def node_features(nodes, edges, tx, G, cfg) -> pd.DataFrame:
    f = nodes.set_index("gid").copy()
    f["is_seed"] = f.is_seed.astype(bool)

    inn = edges.groupby("dst").agg(in_deg=("src", "nunique"), in_sum=("sum_kzt", "sum"), in_tx=("n_tx", "sum"))
    out = edges.groupby("src").agg(out_deg=("dst", "nunique"), out_sum=("sum_kzt", "sum"), out_tx=("n_tx", "sum"))
    f = f.join(inn).join(out)
    for c in ["in_deg", "in_sum", "in_tx", "out_deg", "out_sum", "out_tx"]:
        f[c] = f[c].fillna(0)
    for c in ["in_deg", "out_deg", "in_tx", "out_tx"]:
        f[c] = f[c].astype(int)

    # коэффициент пропуска: сколько из полученного ушло дальше
    f["pass_ratio"] = np.where(f.in_sum > 0, f.out_sum / f.in_sum.where(f.in_sum > 0, 1), np.nan)
    f["truncated"] = (f.depth >= cfg["truncation_depth"]) & (f.out_deg == 0)
    # входящие неполны: seed (граф собран от них) или отдаёт больше, чем получил
    f["inflow_incomplete"] = f.is_seed | (f.out_sum > f.in_sum * 1.2)

    seeds = set(f.index[f.is_seed])
    f["seed_payers"] = [sum(1 for p in G.predecessors(n) if p in seeds) for n in f.index]
    # охват seed: сколько seed-клиентов финансово «доходят» до узла по любой цепочке
    f["seed_reach"] = [len(nx.ancestors(G, n) & seeds) for n in f.index]

    # временные признаки
    f["fast_share"] = fast_forward_share(tx, cfg["fast_days"]).reindex(f.index).fillna(0)
    day_payers = tx.groupby(["dst", tx.date.dt.date]).src.nunique()
    f["max_payers_same_day"] = day_payers.groupby(level=0).max().reindex(f.index).fillna(0).astype(int)
    f["active_days"] = (pd.concat([tx[["src", "date"]].rename(columns={"src": "gid"}),
                                   tx[["dst", "date"]].rename(columns={"dst": "gid"})])
                        .groupby("gid").date.nunique().reindex(f.index).fillna(0).astype(int))

    # центральность: PageRank по направлению денег (вес = сумма) и betweenness
    pr = nx.pagerank(G, weight="sum_kzt")
    f["pagerank"] = pd.Series(pr)
    bc = nx.betweenness_centrality(G, weight=None, k=min(500, len(G)), seed=42)
    f["betweenness"] = pd.Series(bc)

    # компонента связности
    comp = {}
    for i, c in enumerate(sorted(nx.weakly_connected_components(G), key=len, reverse=True)):
        for n in c:
            comp[n] = i
    f["component"] = pd.Series(comp)
    return f
