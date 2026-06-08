"""
程序入口。
加载配置，启动存档文件监听，每次更新时打印当前状态和购买建议。
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
from static_data import NODES


def load_config(path: str = "config.json") -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def format_number(value: float) -> str:
    if value >= 1_000_000:
        return f"{value / 1_000_000:.2f}M"
    if value >= 1_000:
        return f"{value:,.0f}"
    return f"{value:.2f}"


def print_recommendations(state: GameState, top_n: int) -> None:
    ts = datetime.now().strftime("%H:%M:%S")
    currency = state.get_currency()
    owned = state.get_all_nodes()

    print(f"\n[{ts}] 货币: {format_number(currency)}")

    recs = recommend(currency=currency, owned=owned, nodes=NODES)

    if not recs:
        print("  暂无可购买节点")
        return

    labels = ["推荐购买", "次选    ", "第三选  "]
    for i, rec in enumerate(recs[:top_n]):
        label = labels[i] if i < len(labels) else f"第{i + 1}选  "
        print(f"  {label}: {rec.key} (性价比: {rec.score:.4f}, 需要: {format_number(rec.cost)})")


def main() -> None:
    config = load_config()
    save_dir = Path(config["save_dir"])
    file_a = save_dir / config["save_files"][0]
    file_b = save_dir / config["save_files"][1]
    top_n = config.get("top_n", 3)

    if not save_dir.exists():
        print(f"错误：存档目录不存在：{save_dir}")
        print("请确认：")
        print("  1. 游戏至少运行并保存过一次")
        print("  2. config.json 中的 save_dir 路径正确")
        sys.exit(1)

    state = GameState()

    # 启动时做一次初始解析（取最新文件）
    candidates = [f for f in (file_a, file_b) if f.exists()]
    if candidates:
        newest = max(candidates, key=lambda p: p.stat().st_mtime)
        state.refresh(newest)
        print_recommendations(state, top_n)

    def on_save_updated(path: Path) -> None:
        state.refresh(path)
        print_recommendations(state, top_n)

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
