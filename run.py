"""Единая точка входа: сырые .parquet → метрики → роли → кластеры → приоритет → выгрузки.

    python run.py                          # CSV в output/ + таблицы для интерфейса в output/db/
    python run.py --db postgresql://...    # + загрузка в PostgreSQL (или переменная DATABASE_URL)
    python run.py --fast                   # только CSV: без укладки и проверки устойчивости (~3 с)
"""
import argparse
import json
import os
import time
from pathlib import Path

import yaml

from pipeline import core, features, integrity

NODE_COLS = ["gid", "role", "role_score", "cluster_id", "priority_score", "evidence"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="pipeline/config.yaml")
    ap.add_argument("--data", default=None)
    ap.add_argument("--out", default=None)
    ap.add_argument("--db", default=os.getenv("DATABASE_URL"))
    ap.add_argument("--fast", action="store_true", help="только CSV, без укладки и устойчивости")
    a = ap.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    data_dir, out = a.data or cfg["data_dir"], Path(a.out or cfg["out_dir"])
    (out / "db").mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    nodes, edges, tx = features.load(data_dir)
    print(f"загружено: {len(nodes)} узлов, {len(edges)} рёбер, {len(tx)} транзакций", flush=True)
    with_ui = not a.fast or bool(a.db)          # таблицам интерфейса нужны координаты узлов
    R = core.compute(nodes, edges, tx, cfg, with_layout=with_ui, with_stability=not a.fast,
                     log=lambda s: print(s, flush=True))
    fr = R["nodes"]

    # --- обязательные выгрузки фиксированной схемы ---
    fr[NODE_COLS].to_csv(out / "nodes_roles.csv", index=False)
    R["clusters"][["cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis"]].to_csv(
        out / "clusters.csv", index=False)
    R["top"][["rank", "gid", "role", "priority_score", "why"]].to_csv(out / "top_nodes.csv", index=False)
    # --- расширенные выгрузки ---
    fr.drop(columns=[c for c in ("x", "y") if c in fr], errors="ignore").to_csv(out / "nodes_metrics.csv", index=False)
    R["next_requests"].to_csv(out / "next_requests.csv", index=False)
    R["splitting"].to_csv(out / "splitting.csv", index=False)
    R["routes"].to_csv(out / "routes.csv", index=False)

    # --- таблицы для интерфейса: одинаковые для PostgreSQL и локального режима (DuckDB) ---
    tables = {
        "nodes": (fr, "gid"),
        "edges": (edges, None),
        "transactions": (tx.assign(date=tx.date.dt.date.astype(str)), None),
        "clusters": (R["clusters"], "cluster_id"),
        "top_nodes": (R["top"], "rank"),
        "next_requests": (R["next_requests"], None),
        "splitting": (R["splitting"].assign(day=R["splitting"].day.astype(str)), None),
        "routes": (R["routes"], None),
    }
    if with_ui:
        for name, (df, _) in tables.items():
            df.to_parquet(out / "db" / f"{name}.parquet", index=False)
    print(f"выгрузки записаны в {out}/" + ("" if with_ui else " (режим --fast: таблицы интерфейса не обновлялись)"),
          flush=True)

    # отпечатки целостности: какие данные, конфиг и код дали эти выводы
    root = Path(__file__).resolve().parent
    man = integrity.build_manifest(root, Path(data_dir), out, Path(a.config))
    (out / "manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"отпечаток прогона SHA-256: {man['run_fingerprint'][:16]}…", flush=True)

    if a.db:
        from pipeline import db
        db.load_all(a.db, tables)
        print("загружено в PostgreSQL", flush=True)
    print(f"готово за {time.time() - t0:.1f} с")


if __name__ == "__main__":
    main()
