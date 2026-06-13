"""
贪心推荐算法 — 通用产出增量模型。

核心思路：
  对每个候选节点计算"购买后总产出增量 Δ"，除以当前费用得到性价比，降序排列。

节点分类（依赖 income_a 字段）：
  Generator (income_a > 0)：可重复购买，每次费用 × multiplier。
    Δ = income_a × 该节点上已生效的 STANDARD 倍率（见倍率公式）
  Research (income_a == 0)：一次性购买（owned >= 1 即排除）。
    Δ = Σ _delta_from_std_effect(target, ...)  [仅 STANDARD 效果]
    PAYOUT 效果不计入 Δ，但在输出中标注 [+PAY]

倍率公式（依赖 target.node_type / target.category）：
  PROGRESS_BAR                        → mult = Π(p for p > 0)，默认 1
  UPGRADE / UPGRADE_TECH，非 PROGRESS_BAR → mult = Π(1 + p)，默认 1
  其他                                 → mult = 1（效果不生效）

Δ 计算（候选节点对目标 T 有一条 STANDARD 效果 production=p）：
  T.node_type == PROGRESS_BAR：
    p > 0  → Δ = income_a[T] × owned[T] × (current_mult[T] × p − current_mult[T])
    p ≤ 0  → Δ = 0（中性，不扣分）
  T.category in (UPGRADE, UPGRADE_TECH)，非 PROGRESS_BAR：
    Δ = current_production[T] × p
  其他：Δ = 0

费用公式：next_cost = effective_base_cost × multiplier^current_owned
"""
import math
from dataclasses import dataclass, field

from static_data import NodeDef

# 使用加法公式 Π(1+p) 的 category 集合
_ADDITIVE_CATEGORIES = frozenset({"UPGRADE", "UPGRADE_TECH"})


@dataclass
class Recommendation:
    key: str
    score: float
    cost: float
    affordable: bool            # 当前货币 >= cost
    shortfall: float            # 不够时还差多少（affordable 时为 0）
    has_payout: bool = False    # 含 PAYOUT 一次性效果
    delta: float = 0.0          # Δ产出（用于调试/展示）


def _multiplier_from_std_effects(node: NodeDef, std_productions: list[float]) -> float:
    """
    根据目标节点类型，将已生效的 STANDARD production 列表合并为倍率。

    PROGRESS_BAR：乘积 Π(p for p > 0)，无正值时返回 1。
    UPGRADE/UPGRADE_TECH（非 PROGRESS_BAR）：Π(1 + p)。
    其他：1（效果不生效）。
    """
    if node.node_type == "PROGRESS_BAR":
        pos = [p for p in std_productions if p > 0]
        return math.prod(pos) if pos else 1.0
    if node.category in _ADDITIVE_CATEGORIES:
        return math.prod(1 + p for p in std_productions) if std_productions else 1.0
    return 1.0


def _compute_gen_multipliers(
    owned_map: dict[str, float],
    nodes: dict[str, NodeDef],
) -> dict[str, float]:
    """
    计算每个 Generator（income_a > 0）上已生效的 STANDARD 倍率。
    仅统计 owned >= 1 的节点贡献的 STANDARD 效果。
    返回 {uid: multiplier}。
    """
    # 收集每个 generator 上的 STANDARD production 列表
    std_by_target: dict[str, list[float]] = {
        uid: [] for uid, node in nodes.items() if node.income_a > 0
    }

    for uid, node in nodes.items():
        if owned_map.get(uid, 0) < 1:
            continue
        for effect in node.effects:
            if effect.effect_type == "STANDARD" and effect.target in std_by_target:
                std_by_target[effect.target].append(effect.production)

    return {
        uid: _multiplier_from_std_effects(nodes[uid], prods)
        for uid, prods in std_by_target.items()
    }


def _compute_current_productions(
    owned_map: dict[str, float],
    nodes: dict[str, NodeDef],
    gen_multipliers: dict[str, float],
) -> dict[str, float]:
    """production = income_a × owned × multiplier"""
    return {
        uid: nodes[uid].income_a * owned_map.get(uid, 0) * gen_multipliers.get(uid, 1.0)
        for uid in gen_multipliers
    }


def _delta_from_std_effect(
    target: NodeDef,
    target_owned: float,
    current_mult: float,
    current_prod: float,
    p: float,
) -> float:
    """
    计算对目标 T 施加一条 STANDARD production=p 效果带来的 Δ产出。

    PROGRESS_BAR, p>0：Δ = income_a × owned × (current_mult×p − current_mult)
    PROGRESS_BAR, p≤0：Δ = 0（中性，不扣分）
    UPGRADE/UPGRADE_TECH：Δ = current_prod × p
    其他：Δ = 0
    """
    if target.node_type == "PROGRESS_BAR":
        if p <= 0:
            return 0.0
        new_mult = current_mult * p
        return target.income_a * target_owned * (new_mult - current_mult)
    if target.category in _ADDITIVE_CATEGORIES:
        return current_prod * p
    return 0.0


def _meets_requirements(uid: str, owned_map: dict[str, float], nodes: dict[str, NodeDef]) -> bool:
    for req in nodes[uid].requirements:
        if owned_map.get(req.target, 0) < max(1, req.need):
            return False
    return True


def recommend(
    currency: float,
    owned_map: dict[str, float],
    nodes: dict[str, NodeDef],
) -> list[Recommendation]:
    """
    计算所有候选节点的性价比，返回推荐列表。
    排序：可购买（affordable=True）按 score 降序在前，不可购买在后。
    """
    gen_multipliers = _compute_gen_multipliers(owned_map, nodes)
    productions     = _compute_current_productions(owned_map, nodes, gen_multipliers)

    results: list[Recommendation] = []

    for uid, node in nodes.items():
        if node.effective_base_cost <= 0:
            continue

        current_owned = owned_map.get(uid, 0)

        if node.income_a == 0 and current_owned >= 1:  # Research 一次性
            continue

        if not _meets_requirements(uid, owned_map, nodes):
            continue

        next_cost = node.effective_base_cost * (node.multiplier ** current_owned)

        delta = 0.0

        if node.income_a > 0:
            # Generator 自身产出增量
            delta += node.income_a * gen_multipliers.get(uid, 1.0)

        for effect in node.effects:
            if effect.effect_type != "STANDARD":
                continue
            t_uid = effect.target
            if t_uid not in nodes:
                continue
            target     = nodes[t_uid]
            t_owned    = owned_map.get(t_uid, 0)
            t_mult     = gen_multipliers.get(t_uid, 1.0)
            t_prod     = productions.get(t_uid, 0.0)
            delta += _delta_from_std_effect(target, t_owned, t_mult, t_prod, effect.production)

        score = delta / next_cost if next_cost > 0 else 0.0

        results.append(Recommendation(
            key=uid,
            score=score,
            cost=next_cost,
            affordable=currency >= next_cost,
            shortfall=max(0.0, next_cost - currency),
            has_payout=node.has_payout,
            delta=delta,
        ))

    results.sort(key=lambda r: (not r.affordable, -r.score))
    return results
