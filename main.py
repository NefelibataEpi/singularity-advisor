"""
程序入口。
加载配置，初始化节点数据，启动存档文件监听，每次更新时打印规划序列。
"""
import json
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from file_watcher import SaveFileWatcher
from game_state import GameState
from planner import PlanResult, PlanStep, plan
from static_data import NodeDef, load_nodes

_ADDITIVE_CATEGORIES = frozenset({"UPGRADE", "UPGRADE_TECH"})


def load_config(path: str = "config.json") -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _fmt_num(value: float) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value:,.0f}"
    return f"{value:.2f}"


def _fmt_time(seconds: float) -> str:
    if seconds < 1:
        return "瞬间"
    if seconds < 60:
        return f"{seconds:.0f}秒"
    if seconds < 3600:
        m = seconds / 60
        return f"{m:.0f}分钟"
    h = seconds / 3600
    return f"{h:.1f}小时"


def _node_label(uid: str, nodes: dict[str, NodeDef]) -> str:
    """优先用中文标题，无标题则截取 uid 末段。"""
    node = nodes.get(uid)
    if node and node.title:
        return node.title
    return uid.split("_")[-1]


def _effect_desc(step: PlanStep, nodes: dict[str, NodeDef]) -> str:
    """
    为 Research 宏动作生成效果摘要，例如 "→ 古花 ×2.0 | 蜜蜂 ×3.0"。
    Generator 返回空字符串。
    """
    uid = step.macro.uid
    node = nodes.get(uid)
    if node is None or node.income_a > 0:
        return ""

    parts: list[str] = []
    for eff in node.effects:
        if eff.effect_type != "STANDARD":
            continue
        t = nodes.get(eff.target)
        if t is None:
            continue
        label = _node_label(eff.target, nodes)
        p = eff.production
        if t.node_type == "PROGRESS_BAR":
            parts.append(f"{label} ×{p:.1f}")
        elif t.category in _ADDITIVE_CATEGORIES:
            parts.append(f"{label} ×{1 + p:.1f}")
    return ("  → " + " | ".join(parts)) if parts else ""


def print_plan(result: PlanResult, nodes: dict[str, NodeDef], top_n: int = 8) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"\n[{ts}] 货币: {_fmt_num(result.initial_currency)}"
          f"  当前产出: {_fmt_num(result.initial_production)}/秒")

    # 搜索统计
    trunc_note = " ⚠️搜索截断" if result.truncated else ""
    print(f"[规划] 窗口 ~{_fmt_time(result.horizon)}  "
          f"深度 {result.max_depth_completed}{'(部分)' if result.truncated else ''}  "
          f"展开 {result.expansions:,} 节点  "
          f"耗时 {result.search_ms:.0f}ms{trunc_note}")

    if not result.steps:
        print("  （无可行序列）")
        return

    # 序列展示（前 top_n 步）
    show_steps = result.steps[:top_n]
    for i, step in enumerate(show_steps, 1):
        uid = step.macro.uid
        node = nodes.get(uid)
        label = _node_label(uid, nodes)

        if node and node.income_a > 0:
            action = f"冲 {step.macro.count}× {label} ({uid})"
        else:
            action = f"买  {label} ({uid})"

        timing = ""
        if step.wait_seconds > 0.5:
            timing = f"  ⏳攒钱 {_fmt_time(step.wait_seconds)}"

        eff = _effect_desc(step, nodes)
        print(f"  第{i}步: {action}{eff}{timing}")

    if len(result.steps) > top_n:
        print(f"  ... 共 {len(result.steps)} 步（仅展示前 {top_n} 步）")

    print(f"  预计窗口末产出: {_fmt_num(result.initial_production)}/秒"
          f" → {_fmt_num(result.final_production)}/秒")


def main() -> None:
    config = load_config()
    save_dir = Path(config["save_dir"])
    exports_dir = Path(config["exports_dir"])
    file_a = save_dir / config["save_files"][0]
    file_b = save_dir / config["save_files"][1]
    top_n = config.get("top_n", 8)

    if not save_dir.exists():
        print(f"错误：存档目录不存在：{save_dir}")
        print("请确认：")
        print("  1. 游戏至少运行并保存过一次")
        print("  2. config.json 中的 save_dir 路径正确")
        sys.exit(1)

    if not exports_dir.exists():
        print(f"错误：导出目录不存在：{exports_dir}")
        print("请确认 BepInEx 插件已正确安装并导出过活动数据")
        sys.exit(1)

    nodes = load_nodes(exports_dir)
    theme = next(iter(nodes)).split("_")[1] if nodes else "?"
    print(f"已加载 {len(nodes)} 个节点（活动：{theme}）")

    state = GameState()

    def _run_plan(path: Path) -> None:
        state.refresh(path)
        result = plan(
            currency=state.get_currency(),
            owned_map=state.get_all_nodes(),
            nodes=nodes,
        )
        print_plan(result, nodes, top_n)

    candidates = [f for f in (file_a, file_b) if f.exists()]
    if candidates:
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        _run_plan(newest)

    watcher = SaveFileWatcher(file_a, file_b, _run_plan)
    watcher.start()
    print("\n监听存档变化中... 按 Ctrl+C 退出\n")

    def _shutdown(sig, frame):
        print("\n正在退出...")
        watcher.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)

    while True:
        time.sleep(1)


if __name__ == "__main__":
    main()
