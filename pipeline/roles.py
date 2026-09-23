"""Правила ролей. Каждая роль — формальное правило с порогом из config.yaml.
Второй проход: консолидатор, которому платят ≥N узлов-хабов и до которого доходят деньги ≥M seed,
повышается до coordinator («сборщик второго уровня»).
Роли проверяются по приоритету: coordinator → distributor → consolidator → transit →
terminal → boundary → peripheral. Узел получает первую роль, правило которой выполнено.

role_score (0–1) показывает, насколько сильно выражен признак: 0.5 — ровно на пороге,
1.0 — максимум в сети.
"""
import numpy as np
import pandas as pd

ROLE_ORDER = ["coordinator", "distributor", "consolidator", "transit", "terminal", "boundary", "peripheral"]


def money(x: float) -> str:
    if x >= 1e6:
        return f"{x / 1e6:.1f} млн ₸".replace(".", ",")
    if x >= 1e3:
        return f"{x / 1e3:.0f} тыс ₸"
    return f"{x:.0f} ₸"


def _sat(x: pd.Series, thr: float) -> pd.Series:
    """0.5 на пороге → 1.0 на максимуме сети (логарифмическая шкала)."""
    top = max(float(x.max()), thr * 1.0001)
    v = np.log(np.maximum(x, 1e-9) / thr) / np.log(top / thr)
    return 0.5 + 0.5 * np.clip(v, 0, 1)


def assign_roles(f: pd.DataFrame, cfg: dict, edges: pd.DataFrame | None = None) -> pd.DataFrame:
    r = cfg["roles"]
    f = f.copy()
    pr = f.pass_ratio

    rules = {
        "coordinator": (f.in_deg >= r["coordinator"]["min_in_deg"]) & (f.out_deg >= r["coordinator"]["min_out_deg"]),
        "distributor": f.out_deg >= r["distributor"]["min_out_deg"],
        "consolidator": f.in_deg >= r["consolidator"]["min_in_deg"],
        "transit": (~f.is_seed) & (f.in_sum >= r["transit"]["min_in_sum"]) & (f.out_deg > 0)
                   & pr.between(r["transit"]["pass_ratio_min"], r["transit"]["pass_ratio_max"]),
        "terminal": (~f.truncated) & (f.in_deg > 0) & ((f.out_deg == 0) | (pr <= r["terminal"]["max_pass_ratio"]))
                    & ((f.in_sum >= r["terminal"]["min_in_sum"]) | (f.in_deg >= r["terminal"]["or_min_in_deg"])),
        "boundary": f.truncated if r.get("use_boundary_role", True) else pd.Series(False, index=f.index),
    }
    scores = {
        "coordinator": (_sat(f.in_deg, r["coordinator"]["min_in_deg"]) + _sat(f.out_deg, r["coordinator"]["min_out_deg"])) / 2,
        "distributor": _sat(f.out_deg, r["distributor"]["min_out_deg"]),
        "consolidator": np.minimum(1, _sat(f.in_deg, r["consolidator"]["min_in_deg"]) + 0.05 * f.seed_payers.clip(0, 4)),
        "transit": 0.5 + 0.3 * (1 - (pr - 1).abs().fillna(1) / 0.2).clip(0, 1) + 0.2 * f.fast_share,
        "terminal": 0.5 + 0.5 * f.in_sum.rank(pct=True),
        "boundary": pd.Series(0.9, index=f.index),
    }

    role = pd.Series("peripheral", index=f.index)
    score = 1 - 0.5 * np.maximum.reduce([
        (f.in_deg / r["consolidator"]["min_in_deg"]).clip(0, 1),
        (f.out_deg / r["distributor"]["min_out_deg"]).clip(0, 1),
    ])
    for name in reversed(ROLE_ORDER[:-1]):   # в обратном порядке, чтобы старшие роли перезаписали младшие
        m = rules[name].fillna(False)
        role[m] = name
        score[m] = scores[name][m]
    f["role"] = role
    f["role_score"] = score.clip(0, 1)

    # второй проход: сборщик второго уровня (ему платят узлы, уже признанные хабами)
    f["hub_payers"] = 0
    f["second_level"] = False
    if edges is not None:
        hubs = set(f.index[f.role.isin(["coordinator", "consolidator", "distributor"])])
        hp = edges[edges.src.isin(hubs)].groupby("dst").src.nunique()
        f["hub_payers"] = hp.reindex(f.index).fillna(0).astype(int)
        c = r["coordinator"]
        m2 = (f.role == "consolidator") & (f.hub_payers >= c["min_hub_payers"]) & (f.seed_reach >= c["min_seed_reach"])
        f.loc[m2, "role"] = "coordinator"
        f.loc[m2, "second_level"] = True
        f.loc[m2, "role_score"] = (_sat(f.hub_payers, c["min_hub_payers"]) * 0.6
                                   + _sat(f.seed_reach.clip(lower=1), c["min_seed_reach"]) * 0.4)[m2]
    f["role_score"] = f.role_score.clip(0, 1).round(3)
    f["evidence"] = [evidence(row) for row in f.itertuples()]
    return f


def evidence(x) -> str:
    """Человекочитаемое обоснование роли, ≤200 символов. Формулировки — гипотезы."""
    seed_note = " (seed: входящие неполны)" if x.is_seed else ""
    pr = "" if np.isnan(x.pass_ratio) else f", отдаёт дальше {x.pass_ratio:.0%} полученного"
    if x.inflow_incomplete and not x.is_seed and not np.isnan(x.pass_ratio):
        pr = f", отдаёт в {x.pass_ratio:.1f}× больше видимого входа — есть внешние источники"
    r = x.role
    if r == "coordinator" and x.second_level:
        s = (f"Сборщик 2-го уровня: платят {x.hub_payers} узлов-хабов (сборщики/распределители), "
             f"до узла доходят деньги {x.seed_reach} seed; вход {money(x.in_sum)}{pr}")
    elif r == "coordinator":
        s = (f"Признаки координации: получает от {x.in_deg} плательщиков ({money(x.in_sum)}), "
             f"рассылает {x.out_deg} получателям ({money(x.out_sum)}){seed_note}")
    elif r == "distributor":
        s = f"Веерное распределение: {x.out_deg} получателей, {money(x.out_sum)}{pr}{seed_note}"
    elif r == "consolidator":
        s = (f"Признаки консолидации: получает от {x.in_deg} разных плательщиков"
             f"{f' (из них seed: {x.seed_payers})' if x.seed_payers else ''}, {money(x.in_sum)}{pr}")
    elif r == "transit":
        s = (f"Признаки транзита: пропускает {x.pass_ratio:.0%} полученного ({money(x.in_sum)})"
             f"{f', {x.fast_share:.0%} уходит дальше за ≤2 дня' if x.fast_share > 0 else ''}")
    elif r == "terminal":
        s = (f"Конечный получатель: {money(x.in_sum)} от {x.in_deg} плательщиков, "
             f"{'исходящих нет' if x.out_deg == 0 else f'дальше уходит {x.pass_ratio:.0%}'} (колено {x.depth})")
    elif r == "boundary":
        s = (f"Граница выгрузки: {x.depth}-е колено, исходящие не выгружались. Получил {money(x.in_sum)} "
             f"от {x.in_deg}; роль не определить без доп. выгрузки")
    else:
        if x.in_deg == 0 and x.out_deg == 0:
            s = "Нет переводов ≥5 000 ₸ в выгрузке" + (" (seed)" if x.is_seed else "")
        else:
            s = (f"Признаков роли не выявлено: вход {x.in_deg} ({money(x.in_sum)}), "
                 f"выход {x.out_deg} ({money(x.out_sum)}){seed_note}")
    if x.reciprocal and len(s) < 160:
        s += f"; встречные переводы: {x.reciprocal} контрагент(ов)"
    return s[:200]
