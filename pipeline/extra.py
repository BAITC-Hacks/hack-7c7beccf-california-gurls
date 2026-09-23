"""Дополнительные аналитические слои поверх ролей:
- устойчивость роли к порогам (sensitivity analysis) — замена отсутствующему ground truth;
- аномальный профиль узла относительно своего колена (robust z-score);
- повторяющиеся маршруты A→B→C с временной последовательностью."""
import copy

import numpy as np
import pandas as pd

from .roles import assign_roles, money

# пороги, которые варьируем при проверке устойчивости
JITTER_KEYS = [("coordinator", "min_in_deg"), ("coordinator", "min_out_deg"), ("coordinator", "min_hub_payers"),
               ("coordinator", "min_seed_reach"), ("distributor", "min_out_deg"), ("consolidator", "min_in_deg"),
               ("transit", "pass_ratio_min"), ("transit", "pass_ratio_max"), ("transit", "min_in_sum"),
               ("terminal", "max_pass_ratio"), ("terminal", "min_in_sum"), ("terminal", "or_min_in_deg")]


def role_stability(f: pd.DataFrame, cfg: dict, edges: pd.DataFrame) -> pd.DataFrame:
    """Пересчитываем роли N раз, каждый порог умножается на случайный множитель в [1-s, 1+s].
    stability = доля прогонов, где роль узла совпала с базовой; alt_role — самая частая альтернатива."""
    sc = cfg.get("stability", {"runs": 60, "spread": 0.2, "seed": 7})
    rng = np.random.default_rng(sc["seed"])
    base = f.role
    votes = []
    for _ in range(sc["runs"]):
        c = copy.deepcopy(cfg)
        for sect, key in JITTER_KEYS:
            v = c["roles"][sect][key]
            v2 = v * rng.uniform(1 - sc["spread"], 1 + sc["spread"])
            c["roles"][sect][key] = max(1, round(v2)) if isinstance(v, int) else v2
        votes.append(assign_roles(f, c, edges, with_evidence=False).role.rename(None))
    V = pd.concat(votes, axis=1)
    same = V.eq(base, axis=0)
    out = pd.DataFrame(index=f.index)
    out["role_stability"] = same.mean(axis=1).round(3)

    def alt(row, b):
        other = row[row != b]
        return other.value_counts().index[0] if len(other) else ""
    out["alt_role"] = [alt(V.loc[i], base[i]) if out.role_stability[i] < 1 else "" for i in f.index]
    return out


def depth_anomalies(f: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Насколько узел выбивается из своего колена: robust z-score (медиана / MAD) по объёмам и степеням.
    Учитываем только превышение. Для 4-го колена исходящие не оцениваем (их нет в выгрузке)."""
    zthr = cfg.get("anomaly", {}).get("z_threshold", 4.0)
    # степени уже покрыты правилами ролей — здесь ищем необычные ДЕНЬГИ: объёмы и средний размер перевода
    feats = {"in_sum": "вход", "out_sum": "выход", "avg_in_tx": "средний входящий перевод",
             "avg_out_tx": "средний исходящий перевод"}
    f = f.assign(avg_in_tx=(f.in_sum / f.in_tx.where(f.in_tx > 0)).fillna(0),
                 avg_out_tx=(f.out_sum / f.out_tx.where(f.out_tx > 0)).fillna(0))
    Z = pd.DataFrame(index=f.index, columns=list(feats), dtype=float)
    med = {}
    for d, g in f.groupby("depth"):
        for c in feats:
            if c.startswith("out") and d >= cfg["truncation_depth"]:
                Z.loc[g.index, c] = 0.0
                continue
            # сравниваем только с активными узлами колена (у большинства исходящих нет вовсе)
            active = g[c] > 0
            Z.loc[g.index, c] = 0.0
            if active.sum() < 5:
                continue
            x = np.log1p(g.loc[active, c].astype(float))
            m = x.median()
            mad = (x - m).abs().median() * 1.4826
            # нижний предел шкалы: иначе при медиане 1 и MAD 0 «3 плательщика» дали бы огромный z
            scale = max(mad, cfg.get("anomaly", {}).get("min_scale", 0.5))
            Z.loc[x.index, c] = ((x - m) / scale).clip(lower=0)
            med[(d, c)] = g.loc[active, c].median()
    out = pd.DataFrame(index=f.index)
    out["anomaly_score"] = Z.max(axis=1).round(2)
    out["anomaly_feature"] = Z.idxmax(axis=1)
    out["anomaly"] = out.anomaly_score >= zthr

    def text(i):
        if not out.anomaly[i]:
            return ""
        c, d = out.anomaly_feature[i], f.depth[i]
        v, m = f.loc[i, c], med.get((d, c), 0)
        if True:
            return f"{feats[c]} {money(v)} — в {v / m:.0f}× выше медианы активных узлов {d}-го колена ({money(m)})"
        return f"{int(v)} {feats[c]} — при медиане {m:g} у активных узлов {d}-го колена"
    out["anomaly_text"] = [text(i) for i in f.index]
    return out


def repeated_routes(tx: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """Устойчивые маршруты A→B→C: A перевёл B, и B в течение N дней перевёл C; маршрут повторился в ≥K разных дней."""
    rc = cfg.get("routes", {"max_gap_days": 3, "min_repeats": 2})
    a = tx[["src", "dst", "date", "sum_kzt"]].rename(columns={"src": "a", "dst": "b", "date": "d1", "sum_kzt": "s1"})
    b = tx[["src", "dst", "date", "sum_kzt"]].rename(columns={"src": "b", "dst": "c", "date": "d2", "sum_kzt": "s2"})
    m = a.merge(b, on="b")
    m = m[(m.a != m.c) & (m.d2 >= m.d1) & (m.d2 <= m.d1 + pd.Timedelta(days=rc["max_gap_days"]))]
    if m.empty:
        return pd.DataFrame(columns=["a", "b", "c", "repeats", "sum_ab", "sum_bc", "first_day", "last_day"])
    g = (m.groupby(["a", "b", "c"])
          .agg(repeats=("d1", "nunique"), first_day=("d1", "min"), last_day=("d2", "max"))
          .reset_index())
    g = g[g.repeats >= rc["min_repeats"]].copy()
    # суммы — по уникальным переводам каждого звена (merge размножает строки)
    key = m.merge(g[["a", "b", "c"]], on=["a", "b", "c"])
    g = g.merge(key.drop_duplicates(["a", "b", "c", "d1", "s1"]).groupby(["a", "b", "c"]).s1.sum().rename("sum_ab"),
                on=["a", "b", "c"])
    g = g.merge(key.drop_duplicates(["a", "b", "c", "d2", "s2"]).groupby(["a", "b", "c"]).s2.sum().rename("sum_bc"),
                on=["a", "b", "c"])
    for col in ("first_day", "last_day"):
        g[col] = g[col].dt.date.astype(str)
    return g.sort_values(["repeats", "sum_bc"], ascending=False).reset_index(drop=True)
