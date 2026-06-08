"""
贪心推荐算法。
对每个当前可购买节点计算性价比，返回降序排列的购买建议列表。

Generator 性价比 = base_production / next_cost
  其中 next_cost = base_cost × 1.15^owned

Research 性价比 = target_base_production × (multiplier - 1) / cost
  Research 只能买一次（owned == 0 时才参与计算）
"""
from dataclasses import dataclass

from static_data import NodeDef, NODES as _DEFAULT_NODES


@dataclass
class Recommendation:
    key: str
    score: float
    cost: float


def recommend(
    currency: float,
    owned: dict[str, float],
    nodes: dict[str, NodeDef] | None = None,
) -> list[Recommendation]:
    """
    计算所有可购买节点的性价比，返回降序排列的推荐列表。

    Args:
        currency: 当前活动货币
        owned:    {节点key: owned数量} 字典
        nodes:    节点静态数据（默认使用 static_data.NODES）
    """
    if nodes is None:
        nodes = _DEFAULT_NODES

    results: list[Recommendation] = []

    for key, node_def in nodes.items():
        current_owned = owned.get(key, 0.0)

        if node_def["type"] == "Generator":
            cost = node_def["base_cost"] * (1.15 ** current_owned)
            if currency < cost:
                continue
            score = node_def["base_production"] / cost
            results.append(Recommendation(key=key, score=score, cost=cost))

        elif node_def["type"] == "Research":
            if current_owned > 0:
                continue  # Research 只能买一次
            cost = node_def["base_cost"]
            if currency < cost:
                continue
            target_key = node_def["target"]
            target_def = nodes.get(target_key)
            if target_def is None or target_def["type"] != "Generator":
                continue
            score = target_def["base_production"] * (node_def["multiplier"] - 1) / cost
            results.append(Recommendation(key=key, score=score, cost=cost))

    return sorted(results, key=lambda r: r.score, reverse=True)
