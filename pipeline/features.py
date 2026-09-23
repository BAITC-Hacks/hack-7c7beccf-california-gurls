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
    """Сквозной транзит: какая доля поступлений ушла дальше в течение `days` дней.
    Каждый исходящий перевод распределяется по самым ранним ещё не «израсходованным» поступлениям
    за предыдущие `days` дней (FIFO) — одна и та же сумма не засчитывается дважды,
    поэтому fast_share никогда не превышает долю реально отправленного (pass_ratio)."""
    window = pd.Timedelta(days=days)
    inc = tx[["dst", "date", "sum_kzt"]].rename(columns={"dst": "gid"})
    out = tx[["src", "date", "sum_kzt"]].rename(columns={"src": "gid"})
    out_by = {g: d.sort_values("date") for g, d in out.groupby("gid")}
    res = {}
    for g, d in inc.groupby("gid"):
        total = d.sum_kzt.sum()
        if g not in out_by or total <= 0:
            res[g] = 0.0
            continue
        pool = [[r.date, r.sum_kzt] for r in d.sort_values("date").itertuples()]   # [дата, остаток]
        forwarded = 0.0
        for o in out_by[g].itertuples():
            need = o.sum_kzt
            for p in pool:
                if need <= 0:
                    break
                if p[1] <= 0 or p[0] > o.date or o.date - p[0] > window:
                    continue
                take = min(p[1], need)
                p[1] -= take
                need -= take
                forwarded += take
        res[g] = forwarded / total
    return pd.Series(res, dtype=float)


def activity_bursts(tx: pd.DataFrame) -> pd.DataFrame:
    """Всплеск активности: какая доля месячного оборота узла пришлась на один самый активный день."""
    t = pd.concat([tx[["src", "date", "sum_kzt"]].rename(columns={"src": "gid"}),
                   tx[["dst", "date", "sum_kzt"]].rename(columns={"dst": "gid"})])
    daily = t.groupby(["gid", t.date.dt.date]).sum_kzt.sum()
    g = daily.groupby(level=0)
    out = pd.DataFrame({"burst_share": (g.max() / g.sum()).round(3),
                        "burst_day": g.idxmax().map(lambda x: str(x[1]))})
    return out


def splitting_episodes(tx: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Эпизоды дробления: ≥N переводов между одной парой в один день."""
    c = cfg.get("splitting", {"min_tx_per_day": 3, "near_threshold_max": 10000})
    t = tx.assign(day=tx.date.dt.date)
    g = (t.groupby(["src", "dst", "day"])
          .agg(n_tx=("sum_kzt", "size"), sum_kzt=("sum_kzt", "sum"), min_kzt=("sum_kzt", "min"),
               max_kzt=("sum_kzt", "max"),
               near_threshold=("sum_kzt", lambda x: int((x <= c["near_threshold_max"]).sum())))
          .reset_index())
    g = g[g.n_tx >= c["min_tx_per_day"]].copy()
    days = g.groupby(["src", "dst"]).day.transform("nunique")
    g["pair_split_days"] = days  # в скольких разных днях пара дробила переводы
    return g.sort_values(["pair_split_days", "n_tx"], ascending=False).reset_index(drop=True)


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

    # дробление сумм
    ep = splitting_episodes(tx, cfg)
    f["split_out"] = ep.groupby("src").size().reindex(f.index).fillna(0).astype(int)
    f["split_in"] = ep.groupby("dst").size().reindex(f.index).fillna(0).astype(int)
    f["split_tx"] = (ep.groupby("src").n_tx.sum().reindex(f.index).fillna(0)
                     + ep.groupby("dst").n_tx.sum().reindex(f.index).fillna(0)).astype(int)
    thr = cfg.get("splitting", {}).get("near_threshold_max", 10000)
    all_tx = pd.concat([tx[["src", "sum_kzt"]].rename(columns={"src": "gid"}),
                        tx[["dst", "sum_kzt"]].rename(columns={"dst": "gid"})])
    f["near_threshold_share"] = (all_tx.assign(n=all_tx.sum_kzt <= thr).groupby("gid").n.mean()
                                 .reindex(f.index).fillna(0).round(3))

    # всплески: доля оборота в самый активный день (значимо только при ≥3 активных днях)
    b = activity_bursts(tx).reindex(f.index)
    f["burst_share"] = b.burst_share.fillna(0)
    f["burst_day"] = b.burst_day.fillna("")
    bc_ = cfg.get("burst", {"min_share": 0.6, "min_active_days": 3})
    f["burst"] = (f.burst_share >= bc_["min_share"]) & (f.active_days >= bc_["min_active_days"])

    # центральность: PageRank по направлению денег (вес = сумма) и betweenness
    pr = nx.pagerank(G, weight="sum_kzt")
    f["pagerank"] = pd.Series(pr)
    bc = nx.betweenness_centrality(G, weight=None, k=min(500, len(G)), seed=42)
    f["betweenness"] = pd.Series(bc)

    # возвратные потоки: сколько коротких циклов проходит через узел (деньги возвращаются к отправителю)
    cyc_count, cyc_len2 = {}, {}
    for c in nx.simple_cycles(G, length_bound=cfg.get("max_cycle_len", 4)):
        for n in c:
            cyc_count[n] = cyc_count.get(n, 0) + 1
            if len(c) == 2:
                cyc_len2[n] = cyc_len2.get(n, 0) + 1
    f["cycles"] = pd.Series(cyc_count).reindex(f.index).fillna(0).astype(int)
    f["reciprocal"] = pd.Series(cyc_len2).reindex(f.index).fillna(0).astype(int)

    # компонента связности
    comp = {}
    for i, c in enumerate(sorted(nx.weakly_connected_components(G), key=len, reverse=True)):
        for n in c:
            comp[n] = i
    f["component"] = pd.Series(comp)
    return f
