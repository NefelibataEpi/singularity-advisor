"""
游戏状态聚合层。
持有最新一次解析的结果，提供 get_currency 和 get_node_owned 接口。
"""
from pathlib import Path

from save_parser import ParseResult, parse_save_path


class GameState:
    def __init__(self) -> None:
        self._result: ParseResult | None = None

    def refresh(self, path: str | Path) -> None:
        """从文件重新解析，更新内部状态。解析失败时静默保留上次结果。"""
        try:
            self._result = parse_save_path(path)
        except Exception:
            # 游戏正在写入时可能读取失败，保留旧状态等待下次触发
            pass

    def get_currency(self) -> float:
        if self._result is None:
            return 0.0
        return self._result.currency

    def get_node_owned(self, key: str) -> float:
        if self._result is None:
            return 0.0
        node = self._result.nodes.get(key)
        return node.owned if node is not None else 0.0

    def get_all_nodes(self) -> dict[str, float]:
        """返回所有 lte_* 节点的 {key: owned_value} 字典。"""
        if self._result is None:
            return {}
        return {k: v.owned for k, v in self._result.nodes.items()}
