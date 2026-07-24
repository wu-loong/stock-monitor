import json
from unittest.mock import patch
import pandas as pd
from scanner.universe import resolve_universe, load_universe, save_universe


def _csi_df(codes):
    return pd.DataFrame({"成分券代码": codes})


def test_resolve_dedupes_and_sorts_and_merges_pools():
    def fake_csi(symbol):
        return {"000300": _csi_df(["600000", "300750"]),
                "000905": _csi_df(["000001"]),
                "000852": _csi_df([]),
                "000688": _csi_df(["688981"])}[symbol]
    fake_codes = pd.DataFrame({"code": ["600000", "300750", "301001", "000001", "688981"]})
    with patch("scanner.universe.ak.index_stock_cons_csindex", side_effect=fake_csi), \
         patch("scanner.universe.ak.stock_info_a_code_name", return_value=fake_codes):
        rows = resolve_universe()
    syms = [r["symbol"] for r in rows]
    assert syms == sorted(syms)                       # 升序
    assert len(syms) == len(set(syms))                # 去重
    assert "301001" in syms                            # 全创业板(301)纳入
    hs = next(r for r in rows if r["symbol"] == "600000")
    assert "hs300" in hs["pools"]                      # pool 标注


def test_save_and_load_roundtrip(tmp_path):
    rows = [{"symbol": "000001", "pools": ["zz500"]}, {"symbol": "600000", "pools": ["hs300"]}]
    p = tmp_path / "u.json"
    save_universe(rows, str(p))
    assert load_universe(str(p)) == rows
