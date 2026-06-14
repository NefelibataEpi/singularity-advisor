"""
前瞻规划器 — 宏动作 + 自适应时间窗 + 迭代加深 DFS
规格: docs/planner-design.md
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Optional

from static_data import NodeDef

# ────────────────────────────────────────────────────────────────────────────
# 可调常量
# ────────────────────────────────────────────────────────────────────────────
BATCH_TIERS     = [1, 5, 10, 15, 20, 25]
HORIZON_MULT    = 2.5
MIN_HORIZON     = 60.0
MAX_HORIZON     = 7200.0
DEFAULT_HORIZON = 300.0
MAX_DEPTH       = 6
MAX_EXPANSIONS  = 50_000

_ADDITIVE_CATEGORIES = frozenset({"UPGRADE", "UPGRADE_TECH"})

# ─── 类型别名 ───────────────────────────────────────────────────────────────
_EffIdx = dict[str, list[tuple[str, float]]]   # target -> [(source, production)]


# ────────────────────────────────────────────────────────────────────────────
# §2  State / 输出结构
# ────────────────────────────────────────────────────────────────────────────
@dataclass
class State:
    currency: float
    owned: dict[str, float]
    elapsed: float = 0.0


@dataclass
class Macro:
    uid: str
    count: int


@dataclass
class PlanStep:
    macro: Macro
    wait_seconds: float
    elapsed_after: float


@dataclass
class PlanResult:
    steps: list[PlanStep]
    horizon: float
    initial_production: float
    final_production: float
    expansions: int
    search_ms: float
    truncated: bool
    max_depth_completed: int
    initial_currency: float


# ────────────────────────────────────────────────────────────────────────────
# 预计算索引
# ────────────────────────────────────────────────────────────────────────────
def _build_effects_index(nodes: dict[str, NodeDef]) -> _EffIdx:
    """STANDARD 效果索引: target_uid -> [(source_uid, production)]"""
    idx: _EffIdx = {}
    for uid, node in nodes.items():
        for eff in node.effects:
            if eff.effect_type == "STANDARD":
                idx.setdefault(eff.target, []).append((uid, eff.production))
    return idx


def _build_payout_index(nodes: dict[str, NodeDef]) -> _EffIdx:
    """PAYOUT 效果索引: target_uid -> [(source_uid, production)]"""
    idx: _EffIdx = {}
    for uid, node in nodes.items():
        for eff in node.effects:
            if eff.effect_type == "PAYOUT":
                idx.setdefault(eff.target, []).append((uid, eff.production))
    return idx


# ────────────────────────────────────────────────────────────────────────────
# §3  产出 / 倍率公式
# ────────────────────────────────────────────────────────────────────────────
def _compute_multiplier(
    target_uid: str,
    owned: dict[str, float],
    nodes: dict[str, NodeDef],
    effects_idx: _EffIdx,
) -> float:
    """
    目标节点的 STANDARD 总倍率（仅统计 owned >= 1 的来源节点）。

    PROGRESS_BAR:
      mult = Π(p for p > 0)  ← 来自已购置的 STANDARD 来源
      无任何正值效果 → 返回 0.0（"未自动化"，产出为 0）

    UPGRADE / UPGRADE_TECH（非 PROGRESS_BAR）:
      mult = Π(1 + p)，无效果时返回 1.0

    其他: 1.0
    """
    target = nodes[target_uid]
    prods = [p for src, p in effects_idx.get(target_uid, []) if owned.get(src, 0) >= 1]

    if target.node_type == "PROGRESS_BAR":
        pos = [p for p in prods if p > 0]
        return math.prod(pos) if pos else 0.0   # 0.0 = 未自动化

    if target.category in _ADDITIVE_CATEGORIES:
        return math.prod(1 + p for p in prods) if prods else 1.0

    return 1.0


def _compute_payout_mult(
    target_uid: str,
    owned: dict[str, float],
    payout_idx: _EffIdx,
) -> float:
    """
    目标节点的 PAYOUT 总倍率（对应反编译 PayoutMultiplier(false)）。
    = Π(1 + effect.production) for PAYOUT 效果中来源 owned >= 1 的项；无则为 1.0。
    注意：是 (1 + production)，不是直接 production 的乘积。
    """
    prods = [p for src, p in payout_idx.get(target_uid, []) if owned.get(src, 0) >= 1]
    return math.prod(1.0 + p for p in prods) if prods else 1.0


def compute_total_production(
    state: State,
    nodes: dict[str, NodeDef],
    effects_idx: _EffIdx,
    payout_idx: _EffIdx,
    gen_uids: list[str],
) -> float:
    """
    所有 Generator 节点的当前每秒总产出。

    PROGRESS_BAR 节点（进度条型发电机）:
      mult = compute_multiplier → 0 表示未自动化 → 产出 = 0
      mult > 0 → 已自动化 → 产出 = income_a × owned × payout_mult / (dVar3 / mult)

    其他节点（BASE/UPGRADE 等）:
      产出 = income_a × owned × mult
    """
    total = 0.0
    for uid in gen_uids:
        count = state.owned.get(uid, 0)
        if count <= 0:
            continue
        node = nodes[uid]
        mult = _compute_multiplier(uid, state.owned, nodes, effects_idx)

        if node.node_type == "PROGRESS_BAR":
            if mult <= 0:
                continue   # 未自动化，不产出
            payout_mult = _compute_payout_mult(uid, state.owned, payout_idx)
            # 每秒产出 = income_a × owned × payout_mult / (dVar3 / mult)
            #          = income_a × owned × payout_mult × mult / dVar3
            total += node.income_a * count * payout_mult / (node.dVar3 / mult)
        else:
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
            continue
        if not _meets_requirements(uid, state.owned, nodes):
            continue
        result.append(uid)
    return result


# ────────────────────────────────────────────────────────────────────────────
# §5  宏动作生成
# ────────────────────────────────────────────────────────────────────────────
def generate_macros(state: State, nodes: dict[str, NodeDef]) -> list[Macro]:
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
    effects_idx: _EffIdx,
    payout_idx: _EffIdx,
    gen_uids: list[str],
) -> Optional[State]:
    """
    执行宏动作，返回新状态。
    逐个购买，每次先检查是否需等待，rate 因 owned 变化隐式更新。
    死局（rate<=0 且钱不够）返回 None。
    """
    new = State(currency=state.currency, owned=dict(state.owned), elapsed=state.elapsed)
    for _ in range(macro.count):
        cost = _next_cost(macro.uid, new.owned.get(macro.uid, 0), nodes)
        if new.currency < cost:
            rate = compute_total_production(new, nodes, effects_idx, payout_idx, gen_uids)
            if rate <= 0:
                return None
            wait = (cost - new.currency) / rate
            new.currency += rate * wait
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
    effects_idx: _EffIdx,
    payout_idx: _EffIdx,
    gen_uids: list[str],
) -> float:
    rate = compute_total_production(state, nodes, effects_idx, payout_idx, gen_uids)
    if rate <= 0:
        return DEFAULT_HORIZON

    cand_uids = _candidates(state, nodes)
    if not cand_uids:
        return MIN_HORIZON

    costs = [_next_cost(uid, state.owned.get(uid, 0), nodes) for uid in cand_uids]
    waits = [(c - state.currency) / rate for c in costs if c > state.currency]
    max_wait = max(waits) if waits else max(costs) / rate
    return max(MIN_HORIZON, min(MAX_HORIZON, max_wait * HORIZON_MULT))


# ────────────────────────────────────────────────────────────────────────────
# §10  目标函数
# ────────────────────────────────────────────────────────────────────────────
def objective(
    state: State,
    nodes: dict[str, NodeDef],
    effects_idx: _EffIdx,
    payout_idx: _EffIdx,
    gen_uids: list[str],
) -> float:
    """窗口末瞬时产出率（高产出率 → 后续攒钱快 → 长期进展好）。"""
    return compute_total_production(state, nodes, effects_idx, payout_idx, gen_uids)
    # 备选: 加权货币项（实测后决定是否启用）
    # W1, W2 = 1.0, 1e-9
    # return compute_total_production(...) * W1 + state.currency * W2


# ────────────────────────────────────────────────────────────────────────────
# §9  深度限制 DFS（IDDFS 内层）
# ────────────────────────────────────────────────────────────────────────────
def _search_dl(
    state: State,
    horizon: float,
    depth: int,
    max_depth: int,
    nodes: dict[str, NodeDef],
    effects_idx: _EffIdx,
    payout_idx: _EffIdx,
    gen_uids: list[str],
    counter: list[int],
) -> tuple[float, list[Macro]]:
    if depth >= max_depth or state.elapsed >= horizon:
        return objective(state, nodes, effects_idx, payout_idx, gen_uids), []

    best_val = objective(state, nodes, effects_idx, payout_idx, gen_uids)
    best_seq: list[Macro] = []

    for macro in generate_macros(state, nodes):
        if counter[0] >= MAX_EXPANSIONS:
            break
        counter[0] += 1

        nxt = apply_macro(state, macro, nodes, effects_idx, payout_idx, gen_uids)
        if nxt is None or nxt.elapsed > horizon:
            continue

        val, seq = _search_dl(
            nxt, horizon, depth + 1, max_depth,
            nodes, effects_idx, payout_idx, gen_uids, counter,
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
    IDDFS 保证 depth=1,2,... 逐层完整探索，直到达到 MAX_EXPANSIONS 截断。
    """
    effects_idx = _build_effects_index(nodes)
    payout_idx  = _build_payout_index(nodes)
    gen_uids    = [uid for uid, n in nodes.items() if n.income_a > 0]

    initial_state = State(currency=currency, owned=dict(owned_map), elapsed=0.0)
    horizon = adaptive_horizon(initial_state, nodes, effects_idx, payout_idx, gen_uids)
    initial_prod = compute_total_production(initial_state, nodes, effects_idx, payout_idx, gen_uids)

    counter = [0]
    best_val = float("-inf")
    best_seq: list[Macro] = []
    truncated = False
    max_depth_completed = 0

    t0 = time.monotonic()
    for max_d in range(1, MAX_DEPTH + 1):
        val, seq = _search_dl(
            initial_state, horizon, 0, max_d,
            nodes, effects_idx, payout_idx, gen_uids, counter,
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
        nxt = apply_macro(cur, macro, nodes, effects_idx, payout_idx, gen_uids)
        if nxt is None:
            break
        steps.append(PlanStep(
            macro=macro,
            wait_seconds=nxt.elapsed - elapsed_before,
            elapsed_after=nxt.elapsed,
        ))
        cur = nxt

    final_prod = compute_total_production(cur, nodes, effects_idx, payout_idx, gen_uids)

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
