"""
BinaryFormatter 存档解析器。
解析 Cell to Singularity 的 savedGames.gd / savedGames2.gd 文件，
提取活动货币（stat_currency_event）和所有 lte_* 节点的 owned 值。
"""
import struct
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class NodeData:
    owned: float        # owned × 10^ownedExponent 的最终值
    raw_owned: float    # 原始 owned double
    owned_exponent: int # 原始 ownedExponent int32


@dataclass
class ParseResult:
    currency: float
    nodes: dict[str, NodeData] = field(default_factory=dict)


def _find_string_pos(data: bytes, target: str) -> int:
    """找到 .NET 编码字符串在字节流中的起始位置（含长度前缀字节），未找到返回 -1。"""
    encoded = target.encode("utf-8")
    pattern = bytes([len(encoded)]) + encoded
    return data.find(pattern)


def _build_ref_map(data: bytes) -> dict[int, int]:
    """
    扫描字节流，建立 objID → ItemSaveData 数据起始位置的映射。
    ClassWithId 格式：0x01 [4B objID] [4B metaID=37] [data...]
    返回 {objID: data_start_pos}
    """
    ref_map: dict[int, int] = {}
    i = 0
    while i < len(data) - 9:
        if data[i] == 0x01:
            try:
                obj_id = struct.unpack_from("<i", data, i + 1)[0]
                meta_id = struct.unpack_from("<i", data, i + 5)[0]
                if meta_id == 37 and 0 < obj_id < 100_000:
                    ref_map[obj_id] = i + 9  # 数据从标记头（1+4+4字节）之后开始
            except struct.error:
                pass
        i += 1
    return ref_map


def _parse_item_save_data(data: bytes, pos: int) -> NodeData:
    """
    解析 ItemSaveData（classID=37）实例数据。
    字段顺序：owned(8B double), ownedExponent(4B int32),
              progress(8B double), dVar1(8B double),
              dVars(1B Null=0x06), automationLevel(4B int32)
    """
    raw_owned = struct.unpack_from("<d", data, pos)[0]
    owned_exp = struct.unpack_from("<i", data, pos + 8)[0]
    owned_value = raw_owned * (10 ** owned_exp)
    return NodeData(owned=owned_value, raw_owned=raw_owned, owned_exponent=owned_exp)


def _extract_kv_pairs(data: bytes, section_start: int, ref_map: dict[int, int]) -> dict[str, NodeData]:
    """
    从 section_start 开始扫描 KV pairs。
    KV 格式：<.NET string key> 0x09 [4B refID]
    """
    result: dict[str, NodeData] = {}
    pos = section_start
    while pos < len(data) - 10:
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
        # 紧跟 0x09 标记，之后是 4B refID
        if data[end] == 0x09 and end + 5 <= len(data):
            ref_id = struct.unpack_from("<i", data, end + 1)[0]
            if ref_id in ref_map:
                result[key] = _parse_item_save_data(data, ref_map[ref_id])
            pos = end + 5
        else:
            pos += 1
    return result


def parse_save_file(data: bytes) -> ParseResult:
    """
    解析存档二进制数据，返回 ParseResult。
    接受 bytes 直接传入（方便单元测试）。
    """
    ref_map = _build_ref_map(data)

    meta_vars_pos = _find_string_pos(data, "metaVars")
    event_items_pos = _find_string_pos(data, "eventItems")

    currency = 0.0
    nodes: dict[str, NodeData] = {}

    if meta_vars_pos >= 0:
        # 跳过 "metaVars" 字符串本身（长度前缀1B + 字符串内容）
        start = meta_vars_pos + 1 + len("metaVars")
        kv = _extract_kv_pairs(data, start, ref_map)
        if "stat_currency_event" in kv:
            currency = kv["stat_currency_event"].owned

    if event_items_pos >= 0:
        start = event_items_pos + 1 + len("eventItems")
        kv = _extract_kv_pairs(data, start, ref_map)
        nodes = {k: v for k, v in kv.items() if k.startswith("lte_")}

    return ParseResult(currency=currency, nodes=nodes)


def parse_save_path(path: str | Path) -> ParseResult:
    """从文件路径读取并解析存档。"""
    data = Path(path).read_bytes()
    return parse_save_file(data)
