"""Лаборатория порогов: пересчёт ролей с изменёнными порогами «на лету» (~0.1 с).
Использует ту же функцию правил, что и пайплайн (pipeline.roles.assign_roles) — никакой отдельной логики."""
import copy
from functools import lru_cache
from pathlib import Path

import pandas as pd
import yaml

from pipeline.roles import ROLE_ORDER, assign_roles

from . import store

CFG_PATH = Path(__file__).resolve().parent.parent / "pipeline" / "config.yaml"

# что можно двигать в интерфейсе: (секция, ключ, подпись, мин, макс, шаг)
KNOBS = [
    ("consolidator", "min_in_deg", "Консолидатор: мин. плательщиков", 2, 15, 1),
    ("distributor", "min_out_deg", "Распределитель: мин. получателей", 3, 40, 1),
    ("coordinator", "min_in_deg", "Координатор: мин. плательщиков", 2, 15, 1),
    ("coordinator", "min_out_deg", "Координатор: мин. получателей", 3, 40, 1),
    ("coordinator", "min_hub_payers", "Сборщик 2-го уровня: мин. хабов-плательщиков", 2, 12, 1),
    ("transit", "pass_ratio_min", "Транзит: пропуск от", 0.5, 1.0, 0.05),
    ("transit", "pass_ratio_max", "Транзит: пропуск до", 1.0, 1.6, 0.05),
    ("transit", "min_in_sum", "Транзит: мин. входящих, ₸", 0, 500000, 10000),
    ("terminal", "min_in_sum", "Конечный получатель: мин. входящих, ₸", 0, 2000000, 50000),
]


@lru_cache(maxsize=1)
def _base():
    cfg = yaml.safe_load(open(CFG_PATH, encoding="utf-8"))
    f = pd.DataFrame(store.q("SELECT * FROM nodes"))
    f["gid"] = f.gid.astype("int64")
    f = f.set_index("gid")
    for c in ("is_seed", "truncated", "inflow_incomplete"):
        f[c] = f[c].astype(bool)
    f["pass_ratio"] = pd.to_numeric(f.pass_ratio, errors="coerce")
    e = pd.DataFrame(store.q("SELECT src, dst FROM edges"))
    e["src"], e["dst"] = e.src.astype("int64"), e.dst.astype("int64")
    return cfg, f, e


def knobs() -> list:
    cfg, _, _ = _base()
    return [{"section": s, "key": k, "label": lab, "min": lo, "max": hi, "step": st,
             "value": cfg["roles"][s][k]} for s, k, lab, lo, hi, st in KNOBS]


def run(overrides: dict) -> dict:
    cfg, f, e = _base()
    c = copy.deepcopy(cfg)
    for key, v in overrides.items():
        sect, k = key.split(".")
        orig = c["roles"][sect][k]
        c["roles"][sect][k] = int(round(v)) if isinstance(orig, int) else float(v)
    new = assign_roles(f, c, e, with_evidence=False).role
    base = f.role
    changed = new[new != base]
    trans = (pd.DataFrame({"from": base[changed.index], "to": changed})
             .value_counts().rename("n").reset_index().sort_values("n", ascending=False))
    top_changed = (f.loc[changed.index, ["priority_score"]].assign(old=base[changed.index], new=changed)
                   .sort_values("priority_score", ascending=False).head(15))
    return {
        "counts": [{"role": r, "base": int((base == r).sum()), "new": int((new == r).sum())} for r in ROLE_ORDER],
        "changed": int(len(changed)),
        "transitions": trans.to_dict("records"),
        "top_changed": [{"gid": str(g), "old": x.old, "new": x.new, "priority_score": x.priority_score}
                        for g, x in top_changed.iterrows()],
        "roles": {str(g): r for g, r in changed.items()},   # только изменившиеся — для перекраски графа
    }
