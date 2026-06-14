"""
前瞻规划器 — 宏动作 + 自适应时间窗 + 迭代加深 DFS
规格: docs/planner-design.md

替换贪心评分器(advisor.py)的原因:
  贪心只看单步瞬时性价比,结构性地低估乘法科技。科技的价值随底数
  (Generator owned 数)增长而增长,贪心看不到未来,导致"发电机总优先
  于科技"的错误排序。
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Optional

from static_data import NodeDef

# ────────────────────────────────────────────────────────────────────────────
# 可调常量 (也可通过 config.json 中同名键覆盖,由 plan() 接受 override 字典)
# ────────────────────────────────────────────────────────────────────────────
BATCH_TIERS     = [1, 5, 10, 15, 20, 25]   # 发电机宏动作批量档位
HORIZON_MULT    = 2.5     # T = max_wait × HORIZON_MULT
MIN_HORIZON     = 60.0    # 最小规划窗口 (秒)
MAX_HORIZON     = 7200.0  # 最大规划窗口 (秒，= 2 小时)
DEFAULT_HORIZON = 300.0   # rate=0 时兜底 (秒)
MAX_DEPTH       = 6       # IDDFS 最大深度
MAX_EXPANSIONS  = 50_000  # 搜索展开总节点数上限

_ADDITIVE_CATEGORIES = frozenset({"UPGRADE", "UPGRADE_TECH"})


# ────────────────────────────────────────────────────────────────────────────
# §2  State
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class State:
    currency: float
    owned: dict[str, float]   # uid -> 已购买数量；未出现的节点视为 0
    elapsed: float = 0.0      # 从规划起点已模拟的秒数


# ────────────────────────────────────────────────────────────────────────────
# §5  宏动作
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class Macro:
    uid: str
    count: int   # 发电机: BATCH_TIERS 之一；科技: 恒为 1


# ────────────────────────────────────────────────────────────────────────────
# 输出结构
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class PlanStep:
    macro: Macro
    wait_seconds: float   # 本步需要攒钱等待的总时间
    elapsed_after: float  # 执行完本步后的累计模拟时间


@dataclass
class PlanResult:
    steps: list[PlanStep]          # 最优宏动作序列（含每步时间信息）
    horizon: float                  # 规划时间窗 (秒)
    initial_production: float       # 规划起点产出率 (/秒)
    final_production: float         # 序列末尾预计产出率 (/秒)
    expansions: int                 # 搜索展开节点总数
    search_ms: float                # 搜索耗时 (毫秒)
    truncated: bool                 # True = 达到 MAX_EXPANSIONS 后截断
    max_depth_completed: int        # IDDFS 已完整探索的最大深度
    initial_currency: float         # 规划起点货币


# ────────────────────────────────────────────────────────────────────────────
# 内部: 预计算 STANDARD 效果索引 (O(n) 预处理, 避免内层循环 O(n²))
# ────────────────────────────────────────────────────────────────────────────
def _build_effects_index(
    nodes: dict[str, NodeDef],
) -> dict[str, list[tuple[str, float]]]:
    """target_uid -> [(source_uid, production), ...]，仅含 STANDARD 效果。"""
    idx: dict[str, list[tuple[str, float]]] = {}
    for uid, node in nodes.items():
        for eff in node.effects:
            if eff.effect_type == "STANDARD":
                idx.setdefault(eff.target, []).append((uid, eff.production))
    return idx


# ────────────────────────────────────────────────────────────────────────────
# §3  产出 / 倍率公式（与已修正的 incomeMultiplier 模型一致）
# ────────────────────────────────────────────────────────────────────────────
def _compute_multiplier(
    target_uid: str,
    owned: dict[str, float],
    nodes: dict[str, NodeDef],
    effects_idx: dict[str, list[tuple[str, float]]],
) -> float:
    """目标节点当前生效的总倍率（仅统计 owned >= 1 的来源节点）。"""
    target = nodes[target_uid]
    prods = [p for src, p in effects_idx.get(target_uid, []) if owned.get(src, 0) >= 1]

    if target.node_type == "PROGRESS_BAR":
        pos = [p for p in prods if p > 0]
        return math.prod(pos) if pos else 1.0
    if target.category in _ADDITIVE_CATEGORIES:
        return math.prod(1 + p for p in prods) if prods else 1.0
    return 1.0


def compute_total_production(
    state: State,
    nodes: dict[str, NodeDef],
    effects_idx: dict[str, list[tuple[str, float]]],
    gen_uids: list[str],
) -> float:
    """所有 Generator 节点的当前每秒总产出。"""
    total = 0.0
    for uid in gen_uids:
        count = state.owned.get(uid, 0)
        if count <= 0:
            continue
        node = nodes[uid]
        mult = _compute_multiplier(uid, state.owned, nodes, effects_idx)
        total += node.income_a * count * mult
    return total


# ────────────────────────────────────────────────────────────────────────────
# §4  费用公式
# ────────────────────────────────────────────────────────────────────────────
def _next_cost(uid: str, owned_count: float, nodes: dict[str, NodeDef]) -> float:
    n = nodes[uid]
    return n.effective_base_cost * (n.multiplier ** owned_count)


# ────────────────────────────────────────────────────────────────────────────
# §6  候选节点过滤
# ────────────────────────────────────────────────────────────────────────────
def _meets_requirements(
    uid: str, owned: dict[str, float], nodes: dict[str, NodeDef]
) -> bool:
    for req in nodes[uid].requirements:
        if owned.get(req.target, 0) < max(1, req.need):
            return False
    return True


def _candidates(state: State, nodes: dict[str, NodeDef]) -> list[str]:
    result = []
    for uid, node in nodes.items():
        if node.effective_base_cost <= 0:
            continue
        if node.income_a == 0 and state.owned.get(uid, 0) >= 1:
            continue  # 一次性科技已购买
        if not _meets_requirements(uid, state.owned, nodes):
            continue
        result.append(uid)
    return result


# ────────────────────────────────────────────────────────────────────────────
# §5  宏动作生成
# ────────────────────────────────────────────────────────────────────────────
def generate_macros(state: State, nodes: dict[str, NodeDef]) -> list[Macro]:
    """
    对每个候选节点生成宏动作列表。
    Generator: count ∈ BATCH_TIERS；Research: count=1（一次性）。
    """
    macros: list[Macro] = []
    for uid in _candidates(state, nodes):
        node = nodes[uid]
        if node.income_a > 0:
            for count in BATCH_TIERS:
                macros.append(Macro(uid=uid, count=count))
        else:
            macros.append(Macro(uid=uid, count=1))
    return macros


# ────────────────────────────────────────────────────────────────────────────
# §7  模拟器（纯函数）
# ────────────────────────────────────────────────────────────────────────────
def apply_macro(
    state: State,
    macro: Macro,
    nodes: dict[str, NodeDef],
    effects_idx: dict[str, list[tuple[str, float]]],
    gen_uids: list[str],
) -> Optional[State]:
    """
    执行宏动作，返回新状态。
    逐个购买：每次先检查是否需要等待，rate 在每次购买后因 owned 变化而隐式更新。
    死局（rate<=0 且钱不够）返回 None。
    """
    new = State(currency=state.currency, owned=dict(state.owned), elapsed=state.elapsed)
    for _ in range(macro.count):
        cost = _next_cost(macro.uid, new.owned.get(macro.uid, 0), nodes)
        if new.currency < cost:
            rate = compute_total_production(new, nodes, effects_idx, gen_uids)
            if rate <= 0:
                return None
            wait = (cost - new.currency) / rate
            new.currency += rate * wait   # 等价于 new.currency = cost（含浮点近似）
            new.elapsed += wait
        new.currency -= cost
        new.owned[macro.uid] = new.owned.get(macro.uid, 0) + 1
    return new


# ────────────────────────────────────────────────────────────────────────────
# §8  自适应时间窗
# ────────────────────────────────────────────────────────────────────────────
def adaptive_horizon(
    state: State,
    nodes: dict[str, NodeDef],
    effects_idx: dict[str, list[tuple[str, float]]],
    gen_uids: list[str],
) -> float:
    rate = compute_total_production(state, nodes, effects_idx, gen_uids)
    if rate <= 0:
        return DEFAULT_HORIZON

    cand_uids = _candidates(state, nodes)
    if not cand_uids:
        return MIN_HORIZON

    costs = [_next_cost(uid, state.owned.get(uid, 0), nodes) for uid in cand_uids]
    waits = [(c - state.currency) / rate for c in costs if c > state.currency]
    # 若全买得起，以最贵候选的"等效等待时间"作基准，保证窗口有意义
    max_wait = max(waits) if waits else max(costs) / rate
    return max(MIN_HORIZON, min(MAX_HORIZON, max_wait * HORIZON_MULT))


# ────────────────────────────────────────────────────────────────────────────
# §10  目标函数
# ────────────────────────────────────────────────────────────────────────────
def objective(
    state: State,
    nodes: dict[str, NodeDef],
    effects_idx: dict[str, list[tuple[str, float]]],
    gen_uids: list[str],
) -> float:
    """窗口末瞬时产出率（高产出率 → 后续攒钱快 → 长期进展好）。"""
    return compute_total_production(state, nodes, effects_idx, gen_uids)
    # 备选: 加权货币项（实测后决定是否启用）
    # W1, W2 = 1.0, 1e-9
    # return compute_total_production(state, nodes, effects_idx, gen_uids) * W1 \
    #        + state.currency * W2


# ────────────────────────────────────────────────────────────────────────────
# §9  深度限制 DFS（IDDFS 内层）
# ────────────────────────────────────────────────────────────────────────────
def _search_dl(
    state: State,
    horizon: float,
    depth: int,
    max_depth: int,
    nodes: dict[str, NodeDef],
    effects_idx: dict[str, list[tuple[str, float]]],
    gen_uids: list[str],
    counter: list[int],           # counter[0]: 累计展开节点数（跨迭代共享）
) -> tuple[float, list[Macro]]:
    """
    深度限制 DFS。
    终止条件: depth >= max_depth 或 elapsed >= horizon。
    展开计数超过 MAX_EXPANSIONS 时中止当前层剩余分支（截断）。
    """
    if depth >= max_depth or state.elapsed >= horizon:
        return objective(state, nodes, effects_idx, gen_uids), []

    best_val = objective(state, nodes, effects_idx, gen_uids)
    best_seq: list[Macro] = []

    for macro in generate_macros(state, nodes):
        if counter[0] >= MAX_EXPANSIONS:
            break
        counter[0] += 1

        nxt = apply_macro(state, macro, nodes, effects_idx, gen_uids)
        if nxt is None or nxt.elapsed > horizon:
            continue

        val, seq = _search_dl(
            nxt, horizon, depth + 1, max_depth, nodes, effects_idx, gen_uids, counter
        )
        if val > best_val:
            best_val = val
            best_seq = [macro] + seq

    return best_val, best_seq


# ────────────────────────────────────────────────────────────────────────────
# 公开 API
# ────────────────────────────────────────────────────────────────────────────
def plan(
    currency: float,
    owned_map: dict[str, float],
    nodes: dict[str, NodeDef],
) -> PlanResult:
    """
    迭代加深 DFS 搜索最优宏动作序列。

    IDDFS 保证:
      - depth=1 所有单步序列完整探索（全局最优 1 步）
      - depth=2 所有两步序列完整探索（全局最优 2 步）
      - depth=k 在 MAX_EXPANSIONS 允许范围内尽量探索
      - 跨深度取最佳结果（更深的部分探索若找到更优解则采纳）
    """
    effects_idx = _build_effects_index(nodes)
    gen_uids = [uid for uid, n in nodes.items() if n.income_a > 0]

    initial_state = State(currency=currency, owned=dict(owned_map), elapsed=0.0)
    horizon = adaptive_horizon(initial_state, nodes, effects_idx, gen_uids)
    initial_prod = compute_total_production(initial_state, nodes, effects_idx, gen_uids)

    counter = [0]
    best_val = float("-inf")
    best_seq: list[Macro] = []
    truncated = False
    max_depth_completed = 0

    t0 = time.monotonic()
    for max_d in range(1, MAX_DEPTH + 1):
        val, seq = _search_dl(
            initial_state, horizon, 0, max_d,
            nodes, effects_idx, gen_uids, counter,
        )
        if val > best_val:
            best_val = val
            best_seq = seq
        if counter[0] >= MAX_EXPANSIONS:
            truncated = True
            break
        max_depth_completed = max_d
    search_ms = (time.monotonic() - t0) * 1000

    # 重放序列，提取每步时间信息
    steps: list[PlanStep] = []
    cur = initial_state
    for macro in best_seq:
        elapsed_before = cur.elapsed
        nxt = apply_macro(cur, macro, nodes, effects_idx, gen_uids)
        if nxt is None:
            break
        steps.append(PlanStep(
            macro=macro,
            wait_seconds=nxt.elapsed - elapsed_before,
            elapsed_after=nxt.elapsed,
        ))
        cur = nxt

    final_prod = compute_total_production(cur, nodes, effects_idx, gen_uids)

    return PlanResult(
        steps=steps,
        horizon=horizon,
        initial_production=initial_prod,
        final_production=final_prod,
        expansions=counter[0],
        search_ms=search_ms,
        truncated=truncated,
        max_depth_completed=max_depth_completed,
        initial_currency=currency,
    )
