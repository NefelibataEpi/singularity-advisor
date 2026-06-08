# Singularity Advisor — Design Spec

**Date:** 2026-06-08  
**Project:** Cell to Singularity 限时活动最优决策辅助工具  
**Status:** Approved

---

## Overview

监听游戏存档文件，实时解析当前活动货币和节点状态，用贪心算法推荐最优购买顺序，在终端打印建议。

---

## Architecture

```
文件系统 (savedGames.gd / savedGames2.gd)
    ↓ file_watcher.py (watchdog, 取最新修改时间)
    ↓ save_parser.py (BinaryFormatter 二进制解析)
    ↓ game_state.py (状态聚合)
    ↓ advisor.py (贪心算法)
    ↓ main.py (终端输出)
         ↑
    static_data.py (硬编码节点静态数据)
```

---

## Modules

### save_parser.py

**输入:** 二进制文件路径  
**输出:** `ParseResult(currency: float, nodes: dict[str, NodeData])`

解析逻辑（已通过实际存档验证）：
- 定位 `eventItems` 字典（包含 `lte_*` 节点）和 `metaVars` 字典（包含 `stat_currency_event`）
- KV pair 格式：字符串 key → `0x09` [4B refID] → 找对应 `ClassWithId`（`0x01` [4B objID][4B metaID=37]）
- `ItemSaveData`（classID=37）字段顺序：`owned`(double 8B), `ownedExponent`(int32 4B), `progress`(double 8B), `dVar1`(double 8B), `dVars`(object), `automationLevel`(int32 4B)
- BigDouble 值 = `owned × 10^ownedExponent`
- 货币 = `stat_currency_event` 的 BigDouble 值

### file_watcher.py

**输入:** 两个文件路径 + 回调函数  
**行为:** 监听两文件，每次任一文件变动时，取修改时间更新的那个，触发回调并传入文件路径

使用 `watchdog` 库的 `FileSystemEventHandler`。

### game_state.py

**职责:** 聚合解析结果，维护最新状态  
**接口:**
- `get_currency() -> float`
- `get_node_owned(key: str) -> float`
- `refresh(file_path: str)` — 内部调用 parser 更新状态

### static_data.py

硬编码节点定义，后续替换：

```python
NodeDef = TypedDict('NodeDef', {
    'type': Literal['Generator', 'Research'],
    'base_cost': float,
    'base_production': float,   # Generator 专用
    'effects': list,
    'requirements': list,
    # Research 专用字段
    'target': str,              # 目标 Generator key
    'multiplier': float,
})
```

### advisor.py

**输入:** 货币, owned状态字典, 静态数据  
**输出:** `list[Recommendation(key, score, cost)]` 降序排列

性价比计算：
- **Generator:** `next_cost = base_cost × 1.15^owned`；`score = base_production / next_cost`；仅当 `currency >= next_cost`
- **Research:** `score = target_generator_production × (multiplier - 1) / cost`；仅当 `currency >= cost` 且 `owned == 0`（只能买一次）
- 两种节点统一按 score 降序排列

`target_generator_production` = `static_data[target].base_production`（当前总产出的简化近似）

### main.py

启动文件监听，每次存档更新时：
1. 调用 `game_state.refresh()`
2. 调用 `advisor.recommend()`
3. 打印时间戳、货币、推荐列表（前3条）

输出格式：
```
[14:23:01] 货币: 1,941
推荐购买: lte_human_g_heart (性价比: 0.0135, 需要: 100)
次选: lte_human_r_blood (性价比: 0.008, 需要: 75)
```

### config.json

```json
{
  "save_dir": "C:\\Users\\Lenovo\\AppData\\LocalLow\\ComputerLunch\\Cell To Singularity",
  "save_files": ["savedGames.gd", "savedGames2.gd"],
  "top_n": 3
}
```

---

## Data Flow

1. watchdog 检测到文件修改事件
2. `file_watcher` 比较两文件 mtime，选最新的传给回调
3. `game_state.refresh(path)` 调用 parser，更新内部状态
4. `advisor.recommend()` 读取 game_state + static_data，计算所有可购买节点的 score
5. `main.py` 格式化打印结果

---

## Error Handling

- 文件读取失败（游戏正在写入）：捕获异常，跳过本次更新，等待下次触发
- 节点 key 在 static_data 中不存在：跳过该节点，不报错
- Research 节点的 target 不在 static_data：跳过该节点

---

## Dependencies

- Python 3.10+
- `watchdog` — 文件系统监听

---

## File Structure

```
singularity-advisor/
├── config.json
├── requirements.txt
├── README.md
├── main.py
├── save_parser.py
├── file_watcher.py
├── game_state.py
├── static_data.py
└── advisor.py
```
