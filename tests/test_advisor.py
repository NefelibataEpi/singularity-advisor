"""
advisor.py 测试。
前半部分：用最小内联数据验证算法各分支的正确性。
后半部分：用真实 pollen JSON + 模拟存档做端到端冒烟测试（人工核对用，不设 assert）。
"""
import math
import pathlib
import pytest
from static_data import NodeDef, Effect, Requirement, load_nodes
from advisor import recommend, Recommendation


# ──────────────────────────────────────────────
# 辅助：构造最小 NodeDef
# ──────────────────────────────────────────────

def _gen(uid, income, cost, mult=1.15, effects=None, reqs=None,
         node_type="BASE", category="UPGRADE") -> NodeDef:
    return NodeDef(
        uid=uid,
        income_a=income,
        effective_base_cost=cost,
        multiplier=mult,
        node_type=node_type,
        category=category,
        effects=effects or [],
        requirements=reqs or [],
    )


def _research(uid, cost, effects, mult=1.1, reqs=None) -> NodeDef:
    has_payout = any(e.effect_type == "PAYOUT" for e in effects)
    return NodeDef(
        uid=uid,
        income_a=0.0,
        effective_base_cost=cost,
        multiplier=mult,
        node_type="BASE",
        category="RESEARCH",
        effects=effects,
        requirements=reqs or [],
        has_payout=has_payout,
    )


# ──────────────────────────────────────────────
# Generator 基础行为
# ──────────────────────────────────────────────

def test_generator_score_at_owned_zero():
    nodes = {"g_a": _gen("g_a", income=1.0, cost=40.0, mult=1.1)}
    recs = recommend(currency=100.0, owned_map={}, nodes=nodes)
    assert len(recs) == 1
    assert recs[0].key == "g_a"
    assert recs[0].cost == pytest.approx(40.0)
    assert recs[0].score == pytest.approx(1.0 / 40.0)


def test_generator_cost_scales_with_owned():
    nodes = {"g_a": _gen("g_a", income=1.0, cost=40.0, mult=1.1)}
    recs = recommend(currency=500.0, owned_map={"g_a": 3.0}, nodes=nodes)
    expected_cost = 40.0 * (1.1 ** 3)
    assert recs[0].cost == pytest.approx(expected_cost)
    assert recs[0].score == pytest.approx(1.0 / expected_cost)


def test_generator_excluded_when_cannot_afford():
    nodes = {"g_a": _gen("g_a", income=1.0, cost=100.0)}
    recs = recommend(currency=50.0, owned_map={}, nodes=nodes)
    assert len(recs) == 1
    assert recs[0].affordable is False
    assert recs[0].shortfall == pytest.approx(50.0)


# ──────────────────────────────────────────────
# Research（STANDARD 效果）
# ──────────────────────────────────────────────

def test_research_standard_delta_upgrade():
    # g_a: UPGRADE/BASE, income=1.0, owned=5, no prior multipliers
    # current_prod = 1.0 × 5 × 1.0 = 5.0
    # r1: STANDARD p=3 on g_a (UPGRADE) → Δ = current_prod × p = 5.0 × 3.0 = 15.0
    # score = 15.0 / 500.0 = 0.03
    nodes = {
        "g_a": _gen("g_a", income=1.0, cost=40.0),
        "r1": _research("r1", cost=500.0, effects=[
            Effect(target="g_a", production=3.0, effect_type="STANDARD"),
        ]),
    }
    recs = recommend(currency=1000.0, owned_map={"g_a": 5.0}, nodes=nodes)
    r1 = next(r for r in recs if r.key == "r1")
    assert r1.delta == pytest.approx(15.0)
    assert r1.score == pytest.approx(15.0 / 500.0)


def test_research_standard_delta_progress_bar():
    # g_pb: PROGRESS_BAR, income=450, owned=2, no prior STANDARD effects → current_mult=1
    # r1: STANDARD p=2 on g_pb → new_mult = 1×2 = 2
    # Δ = 450 × 2 × (2 − 1) = 900
    # score = 900 / 1000 = 0.9
    nodes = {
        "g_pb": _gen("g_pb", income=450.0, cost=500.0, node_type="PROGRESS_BAR"),
        "r1":   _research("r1", cost=1000.0, effects=[
            Effect(target="g_pb", production=2.0, effect_type="STANDARD"),
        ]),
    }
    recs = recommend(currency=2000.0, owned_map={"g_pb": 2.0}, nodes=nodes)
    r1 = next(r for r in recs if r.key == "r1")
    assert r1.delta == pytest.approx(900.0)
    assert r1.score == pytest.approx(0.9)


def test_progress_bar_zero_production_is_neutral():
    # p=0 on PROGRESS_BAR → Δ = 0 (not negative), score = 0 not negative
    nodes = {
        "g_pb": _gen("g_pb", income=450.0, cost=500.0, node_type="PROGRESS_BAR"),
        "r_bad": _research("r_bad", cost=100.0, effects=[
            Effect(target="g_pb", production=0.0, effect_type="STANDARD"),
        ]),
    }
    recs = recommend(currency=2000.0, owned_map={"g_pb": 5.0}, nodes=nodes)
    r = next(r for r in recs if r.key == "r_bad")
    assert r.delta == pytest.approx(0.0)
    assert r.score == pytest.approx(0.0)


def test_upgrade_p1_gives_positive_delta():
    # p=1 on UPGRADE → Δ = current_prod × 1 = current_prod (should be > 0 if owned > 0)
    nodes = {
        "g_a": _gen("g_a", income=150.0, cost=10000.0),
        "r_mag": _research("r_mag", cost=30_000_000.0, effects=[
            Effect(target="g_a", production=1.0, effect_type="STANDARD"),
        ]),
    }
    recs = recommend(currency=1e9, owned_map={"g_a": 34.0}, nodes=nodes)
    r = next(r for r in recs if r.key == "r_mag")
    # current_prod = 150 × 34 × 1 = 5100; Δ = 5100 × 1 = 5100
    assert r.delta == pytest.approx(5100.0)
    assert r.score > 0


def test_research_excluded_if_already_owned():
    nodes = {
        "g_a": _gen("g_a", income=1.0, cost=40.0),
        "r1": _research("r1", cost=500.0, effects=[
            Effect(target="g_a", production=3.0, effect_type="STANDARD"),
        ]),
    }
    recs = recommend(currency=1000.0, owned_map={"g_a": 1.0, "r1": 1.0}, nodes=nodes)
    keys = [r.key for r in recs]
    assert "r1" not in keys


def test_research_existing_multiplier_stacks_upgrade():
    # g_a: UPGRADE/BASE. r1 owned (p=3) → multiplier = (1+3) = 4
    # current_prod = 1.0 × 5 × 4 = 20
    # r2: p=2 → Δ = current_prod × p = 20 × 2 = 40
    nodes = {
        "g_a": _gen("g_a", income=1.0, cost=40.0),
        "r1": _research("r1", cost=500.0, effects=[
            Effect(target="g_a", production=3.0, effect_type="STANDARD"),
        ]),
        "r2": _research("r2", cost=1000.0, effects=[
            Effect(target="g_a", production=2.0, effect_type="STANDARD"),
        ]),
    }
    owned_map = {"g_a": 5.0, "r1": 1.0}
    recs = recommend(currency=2000.0, owned_map=owned_map, nodes=nodes)
    r2 = next(r for r in recs if r.key == "r2")
    assert r2.delta == pytest.approx(40.0)


def test_research_existing_multiplier_stacks_progress_bar():
    # g_pb: PROGRESS_BAR. r1 owned (p=3) → current_mult = 3
    # current_prod = 450 × 2 × 3 = 2700
    # r2: p=2 → new_mult = 3×2 = 6; Δ = 450 × 2 × (6−3) = 2700
    nodes = {
        "g_pb": _gen("g_pb", income=450.0, cost=500.0, node_type="PROGRESS_BAR"),
        "r1":   _research("r1", cost=500.0, effects=[
            Effect(target="g_pb", production=3.0, effect_type="STANDARD"),
        ]),
        "r2":   _research("r2", cost=1000.0, effects=[
            Effect(target="g_pb", production=2.0, effect_type="STANDARD"),
        ]),
    }
    owned_map = {"g_pb": 2.0, "r1": 1.0}
    recs = recommend(currency=2000.0, owned_map=owned_map, nodes=nodes)
    r2 = next(r for r in recs if r.key == "r2")
    assert r2.delta == pytest.approx(2700.0)


def test_payout_effect_flagged_not_scored():
    nodes = {
        "g_a": _gen("g_a", income=1.0, cost=40.0),
        "r_pay": _research("r_pay", cost=200.0, effects=[
            Effect(target="g_a", production=20.0, effect_type="PAYOUT"),
        ]),
    }
    recs = recommend(currency=1000.0, owned_map={"g_a": 5.0}, nodes=nodes)
    r = next(r for r in recs if r.key == "r_pay")
    assert r.has_payout is True
    assert r.delta == pytest.approx(0.0)  # PAYOUT 不计入 delta


# ──────────────────────────────────────────────
# 解锁条件
# ──────────────────────────────────────────────

def test_requirement_blocks_when_not_met():
    # g_b requires g_a owned >= max(1, 0) = 1
    nodes = {
        "g_a": _gen("g_a", income=1.0, cost=10.0),
        "g_b": _gen("g_b", income=5.0, cost=50.0, reqs=[
            Requirement(target="g_a", need=0),
        ]),
    }
    recs = recommend(currency=1000.0, owned_map={}, nodes=nodes)
    keys = [r.key for r in recs]
    assert "g_b" not in keys
    assert "g_a" in keys


def test_requirement_passes_when_met():
    nodes = {
        "g_a": _gen("g_a", income=1.0, cost=10.0),
        "g_b": _gen("g_b", income=5.0, cost=50.0, reqs=[
            Requirement(target="g_a", need=0),
        ]),
    }
    recs = recommend(currency=1000.0, owned_map={"g_a": 1.0}, nodes=nodes)
    keys = [r.key for r in recs]
    assert "g_b" in keys


# ──────────────────────────────────────────────
# 排序：affordable 在前，unaffordable 在后
# ──────────────────────────────────────────────

def test_sort_affordable_before_unaffordable():
    nodes = {
        "cheap": _gen("cheap", income=0.01, cost=10.0),    # affordable, low score
        "expensive": _gen("expensive", income=100.0, cost=99999.0),  # unaffordable, high score
    }
    recs = recommend(currency=50.0, owned_map={}, nodes=nodes)
    assert recs[0].key == "cheap"       # affordable 排前
    assert recs[1].key == "expensive"   # unaffordable 排后


# ──────────────────────────────────────────────
# 端到端冒烟测试（真实 pollen 数据，人工核对）
# ──────────────────────────────────────────────

EXPORTS_DIR = pathlib.Path(
    r"F:\Data\steam\steamapps\common\Cell to Singularity"
    r"\BepInEx\plugins\SingularityAdvisor\exports"
)


@pytest.mark.skipif(not EXPORTS_DIR.exists(), reason="exports 目录不存在，跳过端到端测试")
def test_pollen_smoke_start_node_only():
    """
    场景：刚开始活动，只买了 start_node（owned=1），货币=1941。
    预期：g_flowers（cost=40）和 g_bees（cost=500）均应出现且可购买。
    g_flowers score = 1/40 = 0.025；g_bees score 更高（450/500=0.9），故 g_bees 应排 #1。
    """
    nodes = load_nodes(EXPORTS_DIR)
    owned_map = {"lte_pollen_start_node": 1.0}
    recs = recommend(currency=1941.0, owned_map=owned_map, nodes=nodes)

    affordable = [r for r in recs if r.affordable]
    print(f"\n[smoke] 可购买节点数: {len(affordable)}")
    for r in affordable[:10]:
        print(f"  {r.key}: score={r.score:.4e} cost={r.cost:.2f} Δ={r.delta:.4f}")

    keys = [r.key for r in affordable]
    assert "lte_pollen_g_flowers" in keys
    assert "lte_pollen_g_bees" in keys

    # g_bees score 应高于 g_flowers
    bees = next(r for r in affordable if r.key == "lte_pollen_g_bees")
    flowers = next(r for r in affordable if r.key == "lte_pollen_g_flowers")
    assert bees.score > flowers.score


@pytest.mark.skipif(not EXPORTS_DIR.exists(), reason="exports 目录不存在，跳过端到端测试")
def test_pollen_smoke_full_list():
    """
    打印完整推荐列表（所有节点 owned=0，货币=1941）供人工核对。
    不设自动断言，验证算法不抛异常即可。
    """
    nodes = load_nodes(EXPORTS_DIR)
    owned_map: dict[str, float] = {}
    recs = recommend(currency=1941.0, owned_map=owned_map, nodes=nodes)

    print(f"\n[smoke] 完整推荐列表（all owned=0, currency=1941）")
    affordable = [r for r in recs if r.affordable]
    unaffordable = [r for r in recs if not r.affordable]
    print(f"  可购买: {len(affordable)} 个")
    for r in affordable:
        payout = " [PAYOUT]" if r.has_payout else ""
        print(f"    {r.key}: score={r.score:.4e} cost={r.cost:.2f}{payout}")
    print(f"  不可购买: {len(unaffordable)} 个（前10）")
    for r in unaffordable[:10]:
        payout = " [PAYOUT]" if r.has_payout else ""
        print(f"    {r.key}: score={r.score:.4e} cost={r.cost:.2e} 差{r.shortfall:.2e}{payout}")

    assert len(recs) > 0
