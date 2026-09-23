"""Валидация без ground truth: встраиваем в реальный граф схему с ИЗВЕСТНЫМИ ролями и проверяем,
что пайплайн её находит, а на контрольной группе (случайные переводы без структуры) — не выдумывает роли.

    python scripts/validate_planted.py            # 10 прогонов, отчёт в docs/validation.md
    python scripts/validate_planted.py --runs 3

Заложенная схема (как описана в кейсе):
    6 seed ─► X consolidator ─► T transit ─► D distributor ─► 14 получателей (4-е колено → boundary)
                         └────► K terminal (крупная сумма, дальше не уходит)
Контроль: 1 seed + 12 узлов со случайными разовыми переводами — ни один не должен стать хабом."""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from pipeline import core, features  # noqa: E402

BASE = 900_000_000_000_000_000
EXPECTED = {"X": "consolidator", "T": "transit", "D": "distributor", "K": "terminal", "R": "boundary"}
HUBS = {"coordinator", "consolidator", "distributor"}


def plant(nodes, edges, tx, rng, run):
    """Возвращает дополненные таблицы и словарь {метка: [gid]}."""
    b = BASE + run * 10_000
    ids = {"S": [b + i for i in range(6)], "X": [b + 100], "T": [b + 101], "D": [b + 102], "K": [b + 103],
           "R": [b + 200 + i for i in range(14)], "NS": [b + 500], "N": [b + 600 + i for i in range(12)]}
    real = nodes.gid.sample(20, random_state=run).tolist()
    t, d0 = [], int(rng.integers(1, 10))
    X, T, D, K = ids["X"][0], ids["T"][0], ids["D"][0], ids["K"][0]
    x_in = 0.0
    for s in ids["S"]:
        for k in range(int(rng.integers(2, 4))):
            amt = float(rng.uniform(50_000, 200_000)); x_in += amt
            t.append((s, X, d0 + k * 3 + int(rng.integers(0, 2)), amt))
        t.append((s, real[int(rng.integers(0, 20))], int(rng.integers(1, 28)), float(rng.uniform(5_000, 30_000))))
    k_amt = x_in * 0.25
    t.append((X, K, d0 + 10, k_amt))
    passed = x_in * 0.7
    for k in range(3):                              # X → T → D: пропуск за 0–1 день
        t.append((X, T, d0 + 3 + k * 3, passed / 3))
        t.append((T, D, d0 + 3 + k * 3 + int(rng.integers(0, 2)), passed / 3 * 0.97))
    for r in ids["R"]:                               # веер
        t.append((D, r, d0 + 12 + int(rng.integers(0, 3)), passed * 0.97 / 14))
    ns = ids["NS"][0]                                # контроль: случайные разовые переводы
    for i, n in enumerate(ids["N"]):
        src = ns if i < 4 else ids["N"][int(rng.integers(0, 4))]
        t.append((src, n, int(rng.integers(1, 30)), float(rng.uniform(5_000, 80_000))))

    ptx = pd.DataFrame(t, columns=["src", "dst", "day", "sum_kzt"])
    ptx["date"] = pd.to_datetime("2026-07-01") + pd.to_timedelta(ptx.day.clip(0, 30), unit="D")
    ptx = ptx.drop(columns="day").astype({"src": "int64", "dst": "int64"})
    depth = {**{g: 0 for g in ids["S"] + ids["NS"]}, X: 1, T: 2, K: 2, D: 3,
             **{g: 4 for g in ids["R"]}, **{g: (1 if i < 4 else 2) for i, g in enumerate(ids["N"])}}
    pn = pd.DataFrame({"gid": list(depth), "depth": list(depth.values())})
    pn["is_seed"] = pn.depth.eq(0)
    pe = (ptx.groupby(["src", "dst"], as_index=False).agg(sum_kzt=("sum_kzt", "sum"), n_tx=("sum_kzt", "size")))
    pe["depth"] = pe.src.map(depth).fillna(4).astype("int8") + 1
    N = pd.concat([nodes, pn], ignore_index=True)
    E = pd.concat([edges, pe], ignore_index=True)
    TX = pd.concat([tx, ptx[["src", "dst", "date", "sum_kzt"]]], ignore_index=True)
    return N, E, TX, ids


def evaluate(cfg, runs=10, seed=0, log=lambda *_: None):
    nodes, edges, tx = features.load(cfg["data_dir"])
    rng = np.random.default_rng(seed)
    rows = []
    for run in range(runs):
        N, E, TX, ids = plant(nodes, edges, tx, rng, run)
        R = core.compute(N, E, TX, cfg, with_layout=False, with_stability=False, log=lambda *_: None)
        f = R["nodes"].set_index("gid")
        nonseed_rank = f[~f.is_seed].priority_score.rank(ascending=False)
        row = {"run": run}
        for lab, exp in EXPECTED.items():
            got = f.loc[ids[lab], "role"]
            row[lab] = float((got == exp).mean())
        row["X_rank"] = int(nonseed_rank[ids["X"][0]])
        cl = f.loc[ids["X"] + ids["T"] + ids["D"] + ids["K"], "cluster_id"]
        row["same_cluster"] = float(cl.eq(cl.mode()[0]).mean())
        row["noise_hubs"] = int(f.loc[ids["N"] + ids["NS"], "role"].isin(HUBS).sum())
        rows.append(row)
        log(f"прогон {run + 1}/{runs}: " + ", ".join(f"{k}={v}" for k, v in row.items() if k != "run"))
    return pd.DataFrame(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10)
    ap.add_argument("--config", default="pipeline/config.yaml")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    df = evaluate(cfg, a.runs, log=print)
    n_nodes = 2248
    lines = [
        "# Валидация на заложенной схеме", "",
        "Эталонной разметки ролей нет, поэтому качество правил проверяется так: в **реальный** граф встраивается группа",
        "с заранее известной структурой, пайплайн запускается целиком, и мы смотрим, какие роли он присвоил.",
        "Параллельно встраивается контрольная группа случайных разовых переводов — там хабов быть не должно.", "",
        "```", "6 seed ─► X consolidator ─► T transit ─► D distributor ─► 14 получателей (4-е колено)",
        "                     └────► K terminal", "контроль: 1 seed + 12 узлов со случайными переводами", "```", "",
        f"Прогонов: **{len(df)}** (суммы, даты и точки подключения к реальной сети случайны в каждом прогоне).", "",
        "| Проверка | Результат |", "|---|---|",
        f"| X распознан как consolidator | **{df.X.mean():.0%}** |",
        f"| T распознан как transit | **{df['T'].mean():.0%}** |",
        f"| D распознан как distributor | **{df.D.mean():.0%}** |",
        f"| K распознан как terminal | **{df.K.mean():.0%}** |",
        f"| 14 получателей 4-го колена → boundary (а не ложный terminal) | **{df.R.mean():.0%}** |",
        f"| Ядро схемы (X, T, D, K) в одном кластере | **{df.same_cluster.mean():.0%}** |",
        f"| Место X в приоритете среди {n_nodes - 81}+ не-seed узлов (медиана) | **{int(df.X_rank.median())}** |",
        f"| Ложные хабы в контрольной группе (из 13 узлов, всего по прогонам) | **{int(df.noise_hubs.sum())}** |", "",
        "**Что это доказывает и что нет.** Схему составили мы сами, поэтому тест показывает, что правила срабатывают так,",
        "как задуманы, на фоне реальной сети, не путают узлы 4-го колена с конечными получателями и не выдумывают хабы",
        "на шуме. Он **не** доказывает, что реальные группы устроены именно так: это проверяется разбором узлов",
        "аналитиком (отметки «подтверждено / отклонено» в интерфейсе) и устойчивостью ролей к порогам (`role_stability`).", "",
        "Запуск: `python scripts/validate_planted.py --runs 10`. Тот же сценарий (1 прогон) входит в `pytest`.",
    ]
    Path("docs").mkdir(exist_ok=True)
    Path("docs/validation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
