import pandas as pd
import requests
from unittest.mock import patch
from datetime import date
from scanner.sources.eastmoney import EastmoneySource


def _fake_df():
    # 模拟 akshare stock_zh_a_hist_min_em 的返回(时间为收盘时刻,列名按 spike 文档)
    return pd.DataFrame({
        "时间": ["2026-07-21 10:30:00", "2026-07-21 10:45:00"],
        "收盘": [10.11, 10.22],
    })


def test_eastmoney_normalizes_to_bars():
    with patch("scanner.sources.eastmoney.ak.stock_zh_a_hist_min_em", return_value=_fake_df()):
        bars = EastmoneySource().fetch_15min("000001", days=5)
    assert len(bars) == 2
    assert bars[0].close == 10.11
    assert bars[0].dt.strftime("%Y-%m-%d %H:%M") == "2026-07-21 10:30"
    assert str(bars[0].dt.tzinfo) == "Asia/Shanghai"


def test_eastmoney_sorted_ascending():
    df = pd.DataFrame({"时间": ["2026-07-21 10:45:00", "2026-07-21 10:30:00"], "收盘": [2.0, 1.0]})
    with patch("scanner.sources.eastmoney.ak.stock_zh_a_hist_min_em", return_value=df):
        bars = EastmoneySource().fetch_15min("000001")
    assert [b.close for b in bars] == [1.0, 2.0]


import time
import pytest


@pytest.mark.smoke
def test_eastmoney_smoke_real():
    last = None
    for attempt in range(5):
        try:
            bars = EastmoneySource().fetch_15min("000001", days=5)
            break
        except (requests.exceptions.RequestException, ConnectionError, TimeoutError) as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    else:
        pytest.skip(f"东财 5 次重试仍不可达(境内抖动),非解析问题:{last}")
    assert len(bars) >= 16                      # 至少一天
    times = {b.dt.strftime("%H:%M") for b in bars}
    assert "15:00" in times and "10:30" in times
