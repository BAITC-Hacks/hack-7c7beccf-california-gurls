"""Автотесты: схема выгрузок по ТЗ, инварианты правил, валидация на заложенной схеме.
    pip install pytest && pytest -q"""
import sys
from pathlib import Path

import pandas as pd
import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from pipeline import core, features  # noqa: E402

ROLES = {"coordinator", "consolidator", "distributor", "transit", "terminal", "peripheral", "boundary"}


@pytest.fixture(scope="module")
def cfg():
    c = yaml.safe_load(open(ROOT / "pipeline/config.yaml", encoding="utf-8"))
    c["data_dir"] = str(ROOT / c["data_dir"])
    return c


@pytest.fixture(scope="module")
def result(cfg):
    nodes, edges, tx = features.load(cfg["data_dir"])
    return core.compute(nodes, edges, tx, cfg, with_layout=False, log=lambda *_: None)


def test_every_node_has_role_score_evidence(result):
    n = result["nodes"]
    assert len(n) == 2248
    assert set(n.role) <= ROLES
    assert n.role_score.between(0, 1).all() and n.priority_score.between(0, 1).all()
    assert n.evidence.str.len().gt(0).all() and n.evidence.str.len().le(200).all()
    assert n.cluster_id.notna().all()


def test_clusters_and_top(result):
    ct, top = result["clusters"], result["top"]
    assert {"cluster_id", "n_nodes", "n_seed", "sum_kzt_internal", "top_gids", "hypothesis"} <= set(ct.columns)
    assert set(result["nodes"].cluster_id) <= set(ct.cluster_id)
    assert ct.n_nodes.sum() == 2248
    assert len(top) >= 20 and top.why.str.len().gt(0).all()
    assert top.priority_score.is_monotonic_decreasing


def test_truncated_nodes_are_not_false_sinks(result):
    """Узлы 4-го колена без исходящих — артефакт обхода: они не должны стать terminal."""
    n = result["nodes"]
    assert not ((n.depth == 4) & (n.out_deg == 0) & (n.role == "terminal")).any()


def test_seeds_are_never_transit(result):
    """У seed входящие неполны — коэффициент пропуска для них некорректен."""
    n = result["nodes"]
    assert not (n.is_seed & (n.role == "transit")).any()


def test_fast_share_never_exceeds_what_was_sent(result):
    """Сквозной транзит не может быть больше реально отправленного (без двойного счёта исходящих)."""
    n = result["nodes"]
    ok = n[~n.inflow_incomplete & n.pass_ratio.notna()]
    assert (ok.fast_share <= ok.pass_ratio + 1e-9).all()


def test_rules_match_thresholds(result, cfg):
    """Каждая роль действительно удовлетворяет своему правилу из config.yaml (объяснимость)."""
    n, r = result["nodes"], cfg["roles"]
    d = n[n.role == "distributor"]
    assert (d.out_deg >= r["distributor"]["min_out_deg"]).all()
    c = n[(n.role == "consolidator")]
    assert (c.in_deg >= r["consolidator"]["min_in_deg"]).all()
    t = n[n.role == "transit"]
    assert t.pass_ratio.between(r["transit"]["pass_ratio_min"], r["transit"]["pass_ratio_max"]).all()


def test_deterministic(cfg, result):
    nodes, edges, tx = features.load(cfg["data_dir"])
    again = core.compute(nodes, edges, tx, cfg, with_layout=False, log=lambda *_: None)
    pd.testing.assert_series_equal(result["nodes"].role, again["nodes"].role)
    pd.testing.assert_series_equal(result["nodes"].cluster_id, again["nodes"].cluster_id)


def test_planted_scheme_is_recovered(cfg):
    sys.path.insert(0, str(ROOT / "scripts"))
    from validate_planted import evaluate
    df = evaluate(cfg, runs=1)
    row = df.iloc[0]
    assert row.X == 1 and row["T"] == 1 and row.D == 1 and row.K == 1
    assert row.R == 1                 # обрезанные узлы → boundary
    assert row.noise_hubs == 0        # на шуме хабов нет
