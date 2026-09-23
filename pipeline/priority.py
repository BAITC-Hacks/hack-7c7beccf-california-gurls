"""Приоритет для аналитика: взвешенная сумма интерпретируемых компонент (все — перцентили 0–1).

priority = w_role·(вес роли × role_score) + w_money·объём + w_seed·охват seed + w_cent·центральность
затем × seed_multiplier для seed (они уже известны) и нормировка в 0–1.
"""
import numpy as np
import pandas as pd

from .roles import money

ROLE_RU = {"coordinator": "координатор", "distributor": "распределитель", "consolidator": "консолидатор",
           "transit": "транзит", "terminal": "конечный получатель", "boundary": "граница выгрузки",
           "peripheral": "периферия"}


def score(f: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    p = cfg["priority"]
    w = p["weights"]
    f = f.copy()
    f["c_role"] = f.role.map(p["role_weight"]) * f.role_score
    f["c_money"] = (f.in_sum + f.out_sum).rank(pct=True)
    f["c_seed"] = f.seed_reach.rank(pct=True) * (f.seed_reach > 0)
    f["c_central"] = (f.pagerank.rank(pct=True) + f.betweenness.rank(pct=True)) / 2
    raw = (w["role"] * f.c_role + w["money"] * f.c_money + w["seed_exposure"] * f.c_seed
           + w["centrality"] * f.c_central)
    raw = raw * np.where(f.is_seed, p["seed_multiplier"], 1.0)
    f["priority_score"] = ((raw - raw.min()) / (raw.max() - raw.min())).round(4)
    return f


def top_nodes(f: pd.DataFrame, n: int) -> pd.DataFrame:
    t = f.sort_values("priority_score", ascending=False).head(n)
    rows = []
    for rank, (gid, x) in enumerate(t.iterrows(), 1):
        rows.append({"rank": rank, "gid": gid, "role": x.role, "priority_score": x.priority_score,
                     "cluster_id": x.cluster_id, "is_seed": x.is_seed, "why": why(x)})
    return pd.DataFrame(rows)


def why(x) -> str:
    parts = [f"{ROLE_RU[x.role].capitalize()} (уверенность {x.role_score:.2f}): {x.evidence}."]
    parts.append(f"Деньги от {x.seed_reach} seed доходят до узла по цепочкам" if x.seed_reach else "Не связан с seed по входящим цепочкам")
    parts.append(f"оборот {money(x.in_sum + x.out_sum)}; центральность выше, чем у {x.c_central:.0%} узлов")
    if x.fast_share >= 0.5:
        parts.append(f"{x.fast_share:.0%} входящих уходит дальше за ≤2 дня")
    if x.max_payers_same_day >= 3:
        parts.append(f"до {x.max_payers_same_day} плательщиков в один день")
    if x.cycles:
        parts.append(f"участвует в {x.cycles} возвратных цепочках (деньги возвращаются к отправителю)")
    if x.is_seed:
        parts.append("уже известен (seed), приоритет понижен")
    return "; ".join(parts)


def next_requests(f: pd.DataFrame, edges: pd.DataFrame, n: int) -> pd.DataFrame:
    """Оценка полноты: какие данные запросить следующими, чтобы закрыть белые пятна.
    1) исходящие узлов 4-го колена, куда пришли заметные деньги от приоритетных узлов;
    2) входящие из-за пределов выборки для узлов, которые отдают больше, чем получили."""
    prio = f.priority_score
    payer_prio = edges.assign(p=edges.src.map(prio)).groupby("dst").p.max()
    rows = []
    b = f[f.role == "boundary"].copy()
    b["payer_prio"] = payer_prio.reindex(b.index).fillna(0)
    b["score"] = b.in_sum.rank(pct=True) * 0.5 + b.payer_prio * 0.3 + b.seed_reach.rank(pct=True) * 0.2
    for gid, x in b.nlargest(n // 2, "score").iterrows():
        rows.append({"gid": gid, "request": "исходящие переводы (узел за границей выгрузки)",
                     "score": round(x.score, 3), "cluster_id": x.cluster_id,
                     "reason": f"получил {money(x.in_sum)} от {x.in_deg} плательщ., макс. приоритет плательщика "
                               f"{x.payer_prio:.2f}, seed выше по цепочке: {x.seed_reach}; куда ушли деньги — неизвестно"})
    g = f[(~f.is_seed) & (f.out_sum > f.in_sum * 1.2) & (f.out_deg > 0)].copy()
    g["gap"] = g.out_sum - g.in_sum
    g["score"] = g.gap.rank(pct=True) * 0.6 + g.priority_score * 0.4
    for gid, x in g.nlargest(n - len(rows), "score").iterrows():
        rows.append({"gid": gid, "request": "входящие переводы из-за пределов выборки",
                     "score": round(x.score, 3), "cluster_id": x.cluster_id,
                     "reason": f"отдал {money(x.out_sum)}, а видимый вход только {money(x.in_sum)}: "
                               f"не хватает {money(x.gap)} — источник средств неизвестен ({ROLE_RU[x.role]})"})
    df = pd.DataFrame(rows)
    # чередуем два типа запросов, чтобы оба были видны в начале списка
    df["rank_in_type"] = df.groupby("request").score.rank(ascending=False, method="first")
    return (df.sort_values(["rank_in_type", "score"], ascending=[True, False])
              .drop(columns="rank_in_type").reset_index(drop=True))
