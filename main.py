"""
程序入口。
加载配置，初始化节点数据，启动存档文件监听，每次更新时打印推荐。
"""
import json
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from advisor import recommend
from file_watcher import SaveFileWatcher
from game_state import GameState
from static_data import load_nodes


def load_config(path: str = "config.json") -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def format_number(value: float) -> str:
    if value >= 1_000_000_000:
        return f"{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value:,.0f}"
    return f"{value:.2f}"


def print_recommendations(state: GameState, nodes: dict, top_n: int) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    currency = state.get_currency()
    owned_map = state.get_all_nodes()

    print(f"\n[{ts}] 货币: {format_number(currency)}")

    recs = recommend(currency=currency, owned_map=owned_map, nodes=nodes)

    if not recs:
        print("  暂无候选节点")
        return

    # 分开可购买和不可购买
    affordable = [r for r in recs if r.affordable]
    unaffordable = [r for r in recs if not r.affordable]

    print(f"  --- 可购买（{len(affordable)} 个）---")
    for i, rec in enumerate(affordable[:top_n]):
        payout_note = " [含一次性奖励]" if rec.has_payout else ""
        print(f"  #{i+1} {rec.key}")
        print(f"      性价比: {rec.score:.4e}  费用: {format_number(rec.cost)}{payout_note}")

    if unaffordable:
        print(f"  --- 资金不足（仅供参考，前 {top_n} 个）---")
        for rec in unaffordable[:top_n]:
            payout_note = " [含一次性奖励]" if rec.has_payout else ""
            print(f"  >> {rec.key}")
            print(f"      性价比: {rec.score:.4e}  需要: {format_number(rec.cost)}"
                  f"  还差: {format_number(rec.shortfall)}{payout_note}")


def main() -> None:
    config = load_config()
    save_dir = Path(config["save_dir"])
    exports_dir = Path(config["exports_dir"])
    file_a = save_dir / config["save_files"][0]
    file_b = save_dir / config["save_files"][1]
    top_n = config.get("top_n", 5)

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
    print(f"已加载 {len(nodes)} 个节点（活动：{next(iter(nodes)).split('_')[1] if nodes else '?'}）")

    state = GameState()

    candidates = [f for f in (file_a, file_b) if f.exists()]
    if candidates:
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        state.refresh(newest)
        print_recommendations(state, nodes, top_n)

    def on_save_updated(path: Path) -> None:
        state.refresh(path)
        print_recommendations(state, nodes, top_n)

    watcher = SaveFileWatcher(file_a, file_b, on_save_updated)
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
