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
    """
    currency_data = _make_item_data(currency_owned, currency_exp)
    node_data = _make_item_data(node_owned, node_exp)

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
