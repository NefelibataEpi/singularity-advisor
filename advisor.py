"""
贪心推荐算法 — 通用产出增量模型。

核心思路：
  对每个候选节点计算"购买后总产出增量 Δ"，除以当前费用得到性价比，降序排列。

节点分类（依赖 income_a 字段）：
  Generator (income_a > 0)：可重复购买，每次费用 × multiplier。
    Δ = income_a × 该节点上已生效的所有 STANDARD 倍率之积
  Research (income_a == 0)：一次性购买（owned >= 1 即排除）。
    Δ = Σ target_当前产出 × (effect.production - 1)  [仅 STANDARD 效果]
    PAYOUT 效果不计入 Δ，但在输出中标注 [含一次性奖励]

候选筛选条件：
  1. effective_base_cost > 0（排除 cost=0 的占位节点）
  2. Research 节点：owned < 1
  3. 所有 NORM 依赖：target.owned >= max(1, need)
     need=0 → 至少购买过一次；need=-1 在数据中仅出现于 NONE 连线故不会到达此处

费用公式：
  next_cost = effective_base_cost × multiplier^current_owned
  （effective_base_cost 已在 static_data 中根据导出时 owned 反推为 owned=0 时的基础费用）

STANDARD 倍率为乘积关系：
  generator_multiplier[uid] = Π effect.production  (所有已购买 Research 中指向该 generator 的 STANDARD 效果)
"""
from dataclasses import dataclass, field

from static_data import NodeDef


@dataclass
class Recommendation:
    key: str
    score: float
    cost: float
    affordable: bool            # 当前货币 >= cost
    shortfall: float            # 不够时还差多少（affordable 时为 0）
    has_payout: bool = False    # 含 PAYOUT 一次性效果
    delta: float = 0.0          # Δ产出（用于调试）


def _compute_generator_multipliers(
    owned_map: dict[str, float],
    nodes: dict[str, NodeDef],
) -> dict[str, float]:
    """
    计算每个 Generator 上已生效的 STANDARD 倍率之积。
    仅统计 owned >= 1 的 Research 节点的 STANDARD 效果。
    """
    multipliers: dict[str, float] = {}
    for uid, node in nodes.items():
        if node.income_a > 0:
            multipliers[uid] = 1.0

    for uid, node in nodes.items():
        if owned_map.get(uid, 0) < 1:
            continue  # 未购买的节点不贡献效果
        for effect in node.effects:
            if effect.effect_type == "STANDARD" and effect.target in multipliers:
                multipliers[effect.target] *= effect.production

    return multipliers


def _compute_current_productions(
    owned_map: dict[str, float],
    nodes: dict[str, NodeDef],
    gen_multipliers: dict[str, float],
) -> dict[str, float]:
    """
    计算每个 Generator 的当前总产出率：
      production = income_a × owned × gen_multiplier
    """
    productions: dict[str, float] = {}
    for uid, node in nodes.items():
        if node.income_a > 0:
            owned = owned_map.get(uid, 0)
            productions[uid] = node.income_a * owned * gen_multipliers.get(uid, 1.0)
    return productions


def _meets_requirements(
    uid: str,
    owned_map: dict[str, float],
    nodes: dict[str, NodeDef],
) -> bool:
    node = nodes[uid]
    for req in node.requirements:
        min_owned = max(1, req.need)
        if owned_map.get(req.target, 0) < min_owned:
            return False
    return True


def recommend(
    currency: float,
    owned_map: dict[str, float],
    nodes: dict[str, NodeDef],
) -> list[Recommendation]:
    """
    计算所有候选节点的性价比，返回推荐列表。
    排序：可购买节点（affordable=True）按 score 降序在前，
          不可购买节点（affordable=False）按 score 降序在后。

    Args:
        currency:  当前活动货币
        owned_map: {节点uid: owned数量}，来自存档解析
        nodes:     节点静态数据字典
    """
    gen_multipliers = _compute_generator_multipliers(owned_map, nodes)
    productions = _compute_current_productions(owned_map, nodes, gen_multipliers)

    results: list[Recommendation] = []

    for uid, node in nodes.items():
        # 排除 cost=0 的占位节点
        if node.effective_base_cost <= 0:
            continue

        current_owned = owned_map.get(uid, 0)

        # Research 一次性判断：income_a==0 的节点只能买一次
        is_one_time = node.income_a == 0
        if is_one_time and current_owned >= 1:
            continue

        # 检查解锁条件
        if not _meets_requirements(uid, owned_map, nodes):
            continue

        next_cost = node.effective_base_cost * (node.multiplier ** current_owned)

        # 计算 Δ产出
        delta = 0.0

        if node.income_a > 0:
            # Generator：多买一个，增加 income_a × 当前倍率
            delta += node.income_a * gen_multipliers.get(uid, 1.0)

        for effect in node.effects:
            if effect.effect_type == "STANDARD":
                target_prod = productions.get(effect.target, 0.0)
                delta += target_prod * (effect.production - 1)
            # PAYOUT 不计入 delta

        score = delta / next_cost if next_cost > 0 else 0.0
        affordable = currency >= next_cost

        results.append(Recommendation(
            key=uid,
            score=score,
            cost=next_cost,
            affordable=affordable,
            shortfall=max(0.0, next_cost - currency),
            has_payout=node.has_payout,
            delta=delta,
        ))

    # 可购买在前（score 降序），不可购买在后（score 降序）
    results.sort(key=lambda r: (not r.affordable, -r.score))
    return results
