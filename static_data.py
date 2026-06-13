"""
从 BepInEx 插件导出的 JSON 加载活动节点静态数据。

加载逻辑：
  1. 读取 exports_dir 中最新修改的 .json 文件
  2. 筛选所有 uid 以 "lte_" 开头且 cost.a > 0 的节点（有实际购买费用）
  3. 按 uid 第二段（theme）分组，选节点数最多的 theme 作为当前活动
  4. 解析每个节点并返回 NODES 字典

BigDouble 转换：mantissa × 10^exponent → float
"""
import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Effect:
    target: str     # 目标节点 uid
    production: float   # STANDARD: 乘数（例如 3 表示 ×3 倍率）；PAYOUT: 一次性奖励数量
    effect_type: str    # "STANDARD" 或 "PAYOUT"


@dataclass
class Requirement:
    target: str     # 依赖节点 uid
    need: int       # 最低需要 owned 数量（0 → max(1,0)=1，即至少买过一次）
    # 仅 connectionType=="NORM" 的 Requirement 会被加载（NONE 类型为纯视觉连线，不作限制）


@dataclass
class NodeDef:
    uid: str
    income_a: float         # baseIncomeRate.a，> 0 代表 Generator（可重复买）；== 0 代表 Research（一次性）
    effective_base_cost: float  # 真实 owned=0 时的费用 = exported_cost_a / multiplier^exported_owned
    multiplier: float       # 每购买一次费用乘以此系数
    node_type: str = "BASE"     # "PROGRESS_BAR" | "BASE" | "NONE" 等，决定倍率公式
    category: str = "UPGRADE"   # "UPGRADE" | "UPGRADE_TECH" | "RESEARCH" | "TROPHY" | "NONE"
    effects: list[Effect] = field(default_factory=list)
    requirements: list[Requirement] = field(default_factory=list)
    has_payout: bool = False    # 是否含 PAYOUT 效果（仅用于展示标注，不计分）


def _to_float(bd: dict) -> float:
    """BigDouble {'mantissa': m, 'exponent': e} → m × 10^e"""
    return bd["mantissa"] * (10 ** bd["exponent"])


def _parse_node(raw: dict) -> NodeDef:
    income_a = _to_float(raw["baseIncomeRate"]["a"])
    cost_a = _to_float(raw["cost"]["a"])
    exported_owned = raw["owned"]
    multiplier = raw["multiplier"]

    # 反推 owned=0 时的真实基础费用
    if exported_owned > 0 and multiplier > 0:
        effective_base_cost = cost_a / (multiplier ** exported_owned)
    else:
        effective_base_cost = cost_a

    effects: list[Effect] = []
    has_payout = False
    for e in raw.get("effects", []):
        etype = e.get("type", "")
        if etype == "PAYOUT":
            has_payout = True
        effects.append(Effect(
            target=e["id"],
            production=e["production"],
            effect_type=etype,
        ))

    requirements: list[Requirement] = []
    for r in raw.get("required", []):
        if r.get("connectionType") != "NORM":
            # NONE 类型只是视觉连线，不作为解锁条件
            continue
        requirements.append(Requirement(
            target=r["id"],
            need=r["need"],
        ))

    return NodeDef(
        uid=raw["uid"],
        income_a=income_a,
        effective_base_cost=effective_base_cost,
        multiplier=multiplier,
        node_type=raw.get("nodeType", "BASE"),
        category=raw.get("category", "UPGRADE"),
        effects=effects,
        requirements=requirements,
        has_payout=has_payout,
    )


def load_nodes(exports_dir: str | Path) -> dict[str, NodeDef]:
    """
    加载 exports_dir 中最新 .json 文件，返回 {uid: NodeDef} 字典。
    选取节点数最多的 theme（uid 第二段），以兼容任意活动。
    """
    exports_dir = Path(exports_dir)
    jsons = sorted(exports_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not jsons:
        raise FileNotFoundError(f"exports_dir 中没有找到 .json 文件：{exports_dir}")

    data = json.loads(jsons[0].read_bytes().decode("utf-8-sig"))

    # 筛选 lte_* 且 cost.a > 0
    lte_nodes = [
        n for n in data["nodes"]
        if n["uid"].startswith("lte_") and _to_float(n["cost"]["a"]) > 0
    ]

    # 按 theme 分组（uid 格式 lte_<theme>_<name>）
    from collections import defaultdict
    theme_groups: dict[str, list[dict]] = defaultdict(list)
    for n in lte_nodes:
        parts = n["uid"].split("_")
        if len(parts) >= 3:
            theme_groups[parts[1]].append(n)

    if not theme_groups:
        raise ValueError("未找到符合格式 lte_<theme>_<name> 的节点")

    # 选节点数最多的 theme
    best_theme = max(theme_groups, key=lambda t: len(theme_groups[t]))
    active_nodes = theme_groups[best_theme]

    return {n["uid"]: _parse_node(n) for n in active_nodes}


# 模块级别的全局变量，需由 main.py 调用 load_nodes() 初始化后赋值
NODES: dict[str, NodeDef] = {}
