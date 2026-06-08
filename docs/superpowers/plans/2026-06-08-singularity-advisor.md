# Singularity Advisor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个实时监听 Cell to Singularity 游戏存档、解析当前活动状态并在终端输出最优购买建议的 Python 工具。

**Architecture:** `file_watcher.py` 用 watchdog 监听两个存档文件，选最新的传给 `save_parser.py` 做二进制解析，结果存入 `game_state.py`；`advisor.py` 结合 `static_data.py` 中的节点定义，用贪心算法计算性价比排序，`main.py` 负责串联并打印结果。

**Tech Stack:** Python 3.10+, watchdog 4.x, 标准库（struct, pathlib, json, datetime）

---

## File Structure

| 文件 | 职责 |
|------|------|
| `config.json` | 存档路径、文件名、top_n 配置 |
| `requirements.txt` | 仅 watchdog |
| `README.md` | 安装与使用说明 |
| `save_parser.py` | BinaryFormatter 二进制解析，返回货币和节点 owned 值 |
| `file_watcher.py` | watchdog 封装，选最新文件触发回调 |
| `game_state.py` | 维护解析后的最新状态，提供 get_currency / get_node_owned |
| `static_data.py` | 硬编码节点定义（Generator / Research） |
| `advisor.py` | 贪心性价比计算，返回排序后的购买建议 |
| `main.py` | 入口：启动监听，格式化打印建议 |
| `tests/test_save_parser.py` | 解析器单元测试 |
| `tests/test_advisor.py` | advisor 算法单元测试 |

---

### Task 1: 项目脚手架

**Files:**
- Create: `config.json`
- Create: `requirements.txt`
- Create: `README.md`

- [ ] **Step 1: 创建 config.json**

```json
{
  "save_dir": "C:\\Users\\Lenovo\\AppData\\LocalLow\\ComputerLunch\\Cell To Singularity",
  "save_files": ["savedGames.gd", "savedGames2.gd"],
  "top_n": 3
}
```

- [ ] **Step 2: 创建 requirements.txt**

```
watchdog>=4.0.0
```

- [ ] **Step 3: 创建 README.md**

```markdown
# Singularity Advisor

Cell to Singularity 限时活动最优决策辅助工具。实时读取游戏存档，推荐性价比最高的购买顺序。

## 安装

```bash
pip install -r requirements.txt
```

## 使用

```bash
python main.py
```

程序会自动监听存档文件，每次存档更新时在终端打印当前货币和购买建议。

## 配置

编辑 `config.json`：
- `save_dir`：存档目录路径（默认已配置为 Windows 默认路径）
- `save_files`：两个存档文件名（一般不需要修改）
- `top_n`：显示前 N 条建议（默认 3）

## 存档路径

`C:\Users\<用户名>\AppData\LocalLow\ComputerLunch\Cell To Singularity\`
```

- [ ] **Step 4: 安装依赖**

```bash
pip install -r requirements.txt
```

Expected: 成功安装 watchdog

- [ ] **Step 5: 提交**

```bash
git add config.json requirements.txt README.md
git commit -m "chore: add project scaffold"
```

---

### Task 2: save_parser.py — 二进制解析器

**Files:**
- Create: `save_parser.py`
- Create: `tests/test_save_parser.py`

- [ ] **Step 1: 创建 tests/ 目录并写失败测试**

```python
# tests/test_save_parser.py
import struct
import pytest
from save_parser import parse_save_file, ParseResult, NodeData


def _make_dotnet_string(s: str) -> bytes:
    """构造 .NET BinaryFormatter 编码的字符串（长度前缀 + UTF-8）"""
    encoded = s.encode("utf-8")
    return bytes([len(encoded)]) + encoded


def _make_item_data(owned: float, owned_exp: int) -> bytes:
    """构造 ItemSaveData 字节（classID=37 实例的数据部分）"""
    return (
        struct.pack("<d", owned) +       # owned: double 8B
        struct.pack("<i", owned_exp) +   # ownedExponent: int32 4B
        struct.pack("<d", 0.0) +         # progress: double 8B
        struct.pack("<d", 0.0) +         # dVar1: double 8B
        b"\x06" +                        # dVars: Null object
        struct.pack("<i", 0)             # automationLevel: int32 4B
    )


def _make_kv_pair(key: str, ref_id: int) -> bytes:
    """构造一个 KV pair: StringKey + 0x09 + [4B refID]"""
    return _make_dotnet_string(key) + b"\x09" + struct.pack("<i", ref_id)


def _make_class_with_id(obj_id: int, meta_id: int, data: bytes) -> bytes:
    """构造 ClassWithId 记录: 0x01 + [4B objID] + [4B metaID] + data"""
    return b"\x01" + struct.pack("<i", obj_id) + struct.pack("<i", meta_id) + data


def build_minimal_save(currency_owned: float, currency_exp: int,
                        node_key: str, node_owned: float, node_exp: int) -> bytes:
    """
    构造包含 stat_currency_event 和一个 lte_* 节点的最小存档字节流。
    结构：...metaVars dict marker... KV(stat_currency_event, ref=1) ...
          ...eventItems dict marker... KV(node_key, ref=2) ...
          ClassWithId(obj=1, meta=37, currency_data)
          ClassWithId(obj=2, meta=37, node_data)
    """
    currency_data = _make_item_data(currency_owned, currency_exp)
    node_data = _make_item_data(node_owned, node_exp)

    # 简化：直接构造可被扫描的字节序列
    # 先放 metaVars 标记字符串，再放 KV，再放 eventItems 标记，再放 KV，再放两个 ClassWithId
    buf = (
        _make_dotnet_string("metaVars") +
        _make_kv_pair("stat_currency_event", 1) +
        _make_dotnet_string("eventItems") +
        _make_kv_pair(node_key, 2) +
        _make_class_with_id(1, 37, currency_data) +
        _make_class_with_id(2, 37, node_data)
    )
    return buf


def test_parse_currency():
    data = build_minimal_save(
        currency_owned=1941.0, currency_exp=0,
        node_key="lte_human_r_blood", node_owned=1.0, node_exp=0
    )
    result = parse_save_file(data)
    assert isinstance(result, ParseResult)
    assert result.currency == pytest.approx(1941.0)


def test_parse_node_owned():
    data = build_minimal_save(
        currency_owned=500.0, currency_exp=0,
        node_key="lte_human_r_blood", node_owned=3.0, node_exp=0
    )
    result = parse_save_file(data)
    assert "lte_human_r_blood" in result.nodes
    assert result.nodes["lte_human_r_blood"].owned == pytest.approx(3.0)


def test_parse_bigdouble_exponent():
    # 1.5 × 10^3 = 1500
    data = build_minimal_save(
        currency_owned=1.5, currency_exp=3,
        node_key="lte_x", node_owned=2.0, node_exp=2
    )
    result = parse_save_file(data)
    assert result.currency == pytest.approx(1500.0)
    assert result.nodes["lte_x"].owned == pytest.approx(200.0)
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
python -m pytest tests/test_save_parser.py -v
```

Expected: `ImportError: cannot import name 'parse_save_file' from 'save_parser'`

- [ ] **Step 3: 实现 save_parser.py**

```python
# save_parser.py
"""
BinaryFormatter 存档解析器。
解析 Cell to Singularity 的 savedGames.gd / savedGames2.gd 文件，
提取活动货币和所有 lte_* 节点的 owned 值。
"""
import struct
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class NodeData:
    owned: float          # owned × 10^ownedExponent 的最终值
    raw_owned: float      # 原始 owned double
    owned_exponent: int   # 原始 ownedExponent int32


@dataclass
class ParseResult:
    currency: float
    nodes: dict[str, NodeData] = field(default_factory=dict)


def _read_dotnet_string(data: bytes, pos: int) -> tuple[str, int]:
    """读取 .NET BinaryFormatter 编码的字符串，返回 (字符串, 新位置)。"""
    length = data[pos]
    pos += 1
    return data[pos:pos + length].decode("utf-8", errors="replace"), pos + length


def _find_all_strings(data: bytes) -> list[tuple[int, str]]:
    """扫描字节流，找出所有看起来像 .NET 字符串的位置和内容。"""
    results = []
    i = 0
    while i < len(data) - 1:
        length = data[i]
        if 1 <= length <= 127:
            end = i + 1 + length
            if end <= len(data):
                try:
                    s = data[i + 1:end].decode("utf-8")
                    if all(32 <= ord(c) < 127 or ord(c) > 127 for c in s):
                        results.append((i, s))
                except UnicodeDecodeError:
                    pass
        i += 1
    return results


def _find_string_pos(data: bytes, target: str) -> int:
    """找到目标字符串在字节流中的起始位置，未找到返回 -1。"""
    encoded = target.encode("utf-8")
    length_byte = bytes([len(encoded)])
    pattern = length_byte + encoded
    idx = data.find(pattern)
    return idx


def _parse_item_save_data(data: bytes, pos: int) -> tuple[NodeData, int]:
    """
    解析 ItemSaveData（classID=37）实例数据。
    字段顺序：owned(8B double), ownedExponent(4B int32),
              progress(8B double), dVar1(8B double),
              dVars(object, 1B Null=0x06), automationLevel(4B int32)
    """
    raw_owned = struct.unpack_from("<d", data, pos)[0]
    pos += 8
    owned_exp = struct.unpack_from("<i", data, pos)[0]
    pos += 4
    pos += 8   # progress
    pos += 8   # dVar1
    # dVars: 跳过对象标记（假设为 Null=0x06，占 1 字节）
    pos += 1
    pos += 4   # automationLevel
    owned_value = raw_owned * (10 ** owned_exp)
    return NodeData(owned=owned_value, raw_owned=raw_owned, owned_exponent=owned_exp), pos


def _build_ref_map(data: bytes) -> dict[int, int]:
    """
    扫描字节流，建立 refID → ClassWithId 数据位置的映射。
    ClassWithId 格式：0x01 [4B objID] [4B metaID=37] [data...]
    返回 {objID: data_start_pos}
    """
    ref_map = {}
    i = 0
    while i < len(data) - 9:
        if data[i] == 0x01:
            try:
                obj_id = struct.unpack_from("<i", data, i + 1)[0]
                meta_id = struct.unpack_from("<i", data, i + 5)[0]
                if meta_id == 37 and 0 < obj_id < 100000:
                    ref_map[obj_id] = i + 9  # 数据从 0x01+4+4 之后开始
            except struct.error:
                pass
        i += 1
    return ref_map


def _extract_kv_pairs(data: bytes, section_start: int, ref_map: dict[int, int]) -> dict[str, NodeData]:
    """
    从 section_start 开始扫描 KV pairs，直到没有更多合法条目。
    KV 格式：<string key> 0x09 [4B refID]
    """
    result = {}
    pos = section_start
    while pos < len(data) - 10:
        # 尝试读取字符串
        str_len = data[pos]
        if not (1 <= str_len <= 127):
            pos += 1
            continue
        end = pos + 1 + str_len
        if end >= len(data):
            break
        try:
            key = data[pos + 1:end].decode("utf-8")
        except UnicodeDecodeError:
            pos += 1
            continue
        # 紧跟 0x09
        if end < len(data) and data[end] == 0x09:
            ref_id_pos = end + 1
            if ref_id_pos + 4 <= len(data):
                ref_id = struct.unpack_from("<i", data, ref_id_pos)[0]
                if ref_id in ref_map:
                    node_data, _ = _parse_item_save_data(data, ref_map[ref_id])
                    result[key] = node_data
                pos = ref_id_pos + 4
                continue
        pos += 1
    return result


def parse_save_file(data: bytes) -> ParseResult:
    """
    解析存档二进制数据，返回 ParseResult。
    接受 bytes（方便测试）或从文件读取后传入。
    """
    ref_map = _build_ref_map(data)

    # 定位 metaVars 和 eventItems 段
    meta_vars_pos = _find_string_pos(data, "metaVars")
    event_items_pos = _find_string_pos(data, "eventItems")

    currency = 0.0
    nodes: dict[str, NodeData] = {}

    if meta_vars_pos >= 0:
        start = meta_vars_pos + len("metaVars") + 1  # 跳过长度前缀字节和字符串本身
        kv = _extract_kv_pairs(data, start, ref_map)
        if "stat_currency_event" in kv:
            currency = kv["stat_currency_event"].owned

    if event_items_pos >= 0:
        start = event_items_pos + len("eventItems") + 1
        kv = _extract_kv_pairs(data, start, ref_map)
        nodes = {k: v for k, v in kv.items() if k.startswith("lte_")}

    return ParseResult(currency=currency, nodes=nodes)


def parse_save_path(path: str | Path) -> ParseResult:
    """从文件路径读取并解析存档。"""
    data = Path(path).read_bytes()
    return parse_save_file(data)
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
python -m pytest tests/test_save_parser.py -v
```

Expected: 3 passed

- [ ] **Step 5: 提交**

```bash
git add save_parser.py tests/test_save_parser.py
git commit -m "feat: implement BinaryFormatter save parser"
```

---

### Task 3: file_watcher.py — 文件监听器

**Files:**
- Create: `file_watcher.py`

- [ ] **Step 1: 实现 file_watcher.py**

```python
# file_watcher.py
"""
存档文件监听器。
监听两个存档文件，取最新修改时间的那个，文件变动时触发回调。
"""
import time
from pathlib import Path
from typing import Callable

from watchdog.events import FileSystemEventHandler, FileSystemEvent
from watchdog.observers import Observer


class _SaveFileHandler(FileSystemEventHandler):
    def __init__(self, file_a: Path, file_b: Path, callback: Callable[[Path], None]):
        self._file_a = file_a
        self._file_b = file_b
        self._callback = callback
        self._watched = {str(file_a), str(file_b)}

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        if event.src_path not in self._watched:
            return
        newest = self._pick_newest()
        if newest is not None:
            self._callback(newest)

    def _pick_newest(self) -> Path | None:
        """返回两个文件中修改时间更新的那个；若文件不存在则跳过。"""
        candidates = []
        for f in (self._file_a, self._file_b):
            try:
                candidates.append((f.stat().st_mtime, f))
            except FileNotFoundError:
                pass
        if not candidates:
            return None
        return max(candidates)[1]


class SaveFileWatcher:
    """监听两个存档文件，任一变动时以最新文件路径触发 callback。"""

    def __init__(self, file_a: Path, file_b: Path, callback: Callable[[Path], None]):
        self._handler = _SaveFileHandler(file_a, file_b, callback)
        self._observer = Observer()
        # watchdog 监听目录，不直接监听文件
        watch_dir = str(file_a.parent)
        self._observer.schedule(self._handler, watch_dir, recursive=False)

    def start(self) -> None:
        self._observer.start()

    def stop(self) -> None:
        self._observer.stop()
        self._observer.join()
```

- [ ] **Step 2: 提交**

```bash
git add file_watcher.py
git commit -m "feat: implement save file watcher"
```

---

### Task 4: game_state.py — 游戏状态

**Files:**
- Create: `game_state.py`

- [ ] **Step 1: 实现 game_state.py**

```python
# game_state.py
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
            pass  # 游戏正在写入时可能读取失败，保留旧状态

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
```

- [ ] **Step 2: 提交**

```bash
git add game_state.py
git commit -m "feat: implement game state aggregator"
```

---

### Task 5: static_data.py — 静态节点数据

**Files:**
- Create: `static_data.py`

- [ ] **Step 1: 实现 static_data.py**

```python
# static_data.py
"""
静态节点数据（占位）。
后续根据实际游戏数据替换 NODES 字典的内容。

每个节点字段说明：
  type          : "Generator" 可重复购买产生货币；"Research" 只买一次给目标乘倍率
  base_cost     : 第一次购买的基础费用
  base_production: Generator 每个单位每秒产出（Research 节点无此字段）
  target        : Research 节点的目标 Generator key
  multiplier    : Research 节点购买后目标产出的乘数
  effects       : 预留，描述其他效果
  requirements  : 前置解锁条件（暂未使用）
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
    target: str         # 目标 Generator 的 key
    multiplier: float   # 购买后目标产出乘以此值
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
```

- [ ] **Step 2: 提交**

```bash
git add static_data.py
git commit -m "feat: add static node data placeholder"
```

---

### Task 6: advisor.py — 贪心推荐算法

**Files:**
- Create: `advisor.py`
- Create: `tests/test_advisor.py`

- [ ] **Step 1: 写失败测试**

```python
# tests/test_advisor.py
import pytest
from advisor import recommend, Recommendation
from static_data import NODES


def test_generator_recommendation_score():
    # lte_human_g_heart: base_cost=100, base_production=1.0, owned=0
    # next_cost = 100 * 1.15^0 = 100
    # score = 1.0 / 100 = 0.01
    recs = recommend(
        currency=200.0,
        owned={"lte_human_g_heart": 0.0, "lte_human_r_blood": 0.0},
        nodes=NODES,
    )
    heart = next(r for r in recs if r.key == "lte_human_g_heart")
    assert heart.score == pytest.approx(0.01)
    assert heart.cost == pytest.approx(100.0)


def test_generator_cost_scales_with_owned():
    # lte_human_g_heart: base_cost=100, owned=2
    # next_cost = 100 * 1.15^2 = 132.25
    # score = 1.0 / 132.25
    recs = recommend(
        currency=200.0,
        owned={"lte_human_g_heart": 2.0, "lte_human_r_blood": 0.0},
        nodes=NODES,
    )
    heart = next(r for r in recs if r.key == "lte_human_g_heart")
    assert heart.cost == pytest.approx(100.0 * 1.15 ** 2, rel=1e-4)
    assert heart.score == pytest.approx(1.0 / (100.0 * 1.15 ** 2), rel=1e-4)


def test_research_score():
    # lte_human_r_blood_boost: cost=500, target=lte_human_r_blood
    # target base_production=0.6, multiplier=2.0
    # score = 0.6 * (2.0 - 1) / 500 = 0.6 / 500 = 0.0012
    recs = recommend(
        currency=600.0,
        owned={"lte_human_g_heart": 0.0, "lte_human_r_blood": 0.0, "lte_human_r_blood_boost": 0.0},
        nodes=NODES,
    )
    boost = next(r for r in recs if r.key == "lte_human_r_blood_boost")
    assert boost.score == pytest.approx(0.0012)


def test_research_excluded_if_already_owned():
    # Research 节点 owned > 0 时不应出现在推荐中
    recs = recommend(
        currency=1000.0,
        owned={"lte_human_g_heart": 0.0, "lte_human_r_blood": 0.0, "lte_human_r_blood_boost": 1.0},
        nodes=NODES,
    )
    keys = [r.key for r in recs]
    assert "lte_human_r_blood_boost" not in keys


def test_excluded_if_not_enough_currency():
    # 货币 50，所有节点 cost >= 75，应返回空列表
    recs = recommend(
        currency=50.0,
        owned={"lte_human_g_heart": 0.0, "lte_human_r_blood": 0.0},
        nodes=NODES,
    )
    assert recs == []


def test_sorted_by_score_descending():
    recs = recommend(
        currency=1000.0,
        owned={"lte_human_g_heart": 0.0, "lte_human_r_blood": 0.0, "lte_human_r_blood_boost": 0.0},
        nodes=NODES,
    )
    scores = [r.score for r in recs]
    assert scores == sorted(scores, reverse=True)
```

- [ ] **Step 2: 运行测试，确认失败**

```bash
python -m pytest tests/test_advisor.py -v
```

Expected: `ImportError: cannot import name 'recommend' from 'advisor'`

- [ ] **Step 3: 实现 advisor.py**

```python
# advisor.py
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
        currency:  当前活动货币
        owned:     {节点key: owned数量} 字典
        nodes:     节点静态数据（默认使用 static_data.NODES）
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
                continue  # 只能买一次
            cost = node_def["base_cost"]
            if currency < cost:
                continue
            target_key = node_def["target"]
            target_def = nodes.get(target_key)
            if target_def is None or target_def["type"] != "Generator":
                continue
            target_prod = target_def["base_production"]
            score = target_prod * (node_def["multiplier"] - 1) / cost
            results.append(Recommendation(key=key, score=score, cost=cost))

    return sorted(results, key=lambda r: r.score, reverse=True)
```

- [ ] **Step 4: 运行测试，确认通过**

```bash
python -m pytest tests/test_advisor.py -v
```

Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add advisor.py tests/test_advisor.py
git commit -m "feat: implement greedy advisor with Generator/Research scoring"
```

---

### Task 7: main.py — 入口

**Files:**
- Create: `main.py`

- [ ] **Step 1: 实现 main.py**

```python
# main.py
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
        label = labels[i] if i < len(labels) else f"第{i+1}选  "
        print(f"  {label}: {rec.key} (性价比: {rec.score:.4f}, 需要: {format_number(rec.cost)})")


def main() -> None:
    config = load_config()
    save_dir = Path(config["save_dir"])
    file_a = save_dir / config["save_files"][0]
    file_b = save_dir / config["save_files"][1]
    top_n = config.get("top_n", 3)

    state = GameState()

    # 启动时做一次初始解析（取最新文件）
    for f in sorted([file_a, file_b], key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True):
        if f.exists():
            state.refresh(f)
            print_recommendations(state, top_n)
            break

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
```

- [ ] **Step 2: 运行全部测试确认无回归**

```bash
python -m pytest tests/ -v
```

Expected: 全部 passed

- [ ] **Step 3: 提交**

```bash
git add main.py
git commit -m "feat: implement main entry point with file watching loop"
```

---

### Task 8: 端到端冒烟测试

**Files:** 无新文件

- [ ] **Step 1: 运行全部测试**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: 全部 passed，无 warning

- [ ] **Step 2: 用实际存档做手动验证（如果游戏可用）**

```bash
python main.py
```

Expected: 打印初始货币值和推荐列表，之后每次存档变动（约30秒）自动刷新

- [ ] **Step 3: 最终提交**

```bash
git add .
git commit -m "chore: complete initial implementation"
```
