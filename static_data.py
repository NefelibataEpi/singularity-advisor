"""
静态节点数据（占位）。
后续根据实际游戏数据替换 NODES 字典的内容。

节点字段说明：
  type           : "Generator" 可重复购买产生货币；"Research" 只买一次给目标乘倍率
  base_cost      : 第一次购买的基础费用
  base_production: Generator 每单位每秒产出（Research 节点无此字段）
  target         : Research 节点的目标 Generator key
  multiplier     : Research 节点购买后目标产出的乘数
  effects        : 预留，描述其他效果
  requirements   : 前置解锁条件（暂未使用）
"""
from typing import TypedDict, Literal


class GeneratorDef(TypedDict):
    type: Literal["Generator"]
    base_cost: float
    base_production: float
    effects: list
    requirements: list


class ResearchDef(TypedDict):
    type: Literal["Research"]
    base_cost: float
    target: str       # 目标 Generator 的 key
    multiplier: float # 购买后目标产出乘以此值
    effects: list
    requirements: list


NodeDef = GeneratorDef | ResearchDef

NODES: dict[str, NodeDef] = {
    "lte_human_g_heart": {
        "type": "Generator",
        "base_cost": 100.0,
        "base_production": 1.0,
        "effects": [],
        "requirements": [],
    },
    "lte_human_r_blood": {
        "type": "Generator",
        "base_cost": 75.0,
        "base_production": 0.6,
        "effects": [],
        "requirements": [],
    },
    "lte_human_r_blood_boost": {
        "type": "Research",
        "base_cost": 500.0,
        "target": "lte_human_r_blood",
        "multiplier": 2.0,
        "effects": [],
        "requirements": ["lte_human_r_blood"],
    },
}
