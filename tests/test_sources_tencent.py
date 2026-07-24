from unittest.mock import patch, MagicMock
from scanner.sources.tencent import TencentSource


def _fake_resp():
    # SPIKE 实测:时间是紧凑串 YYYYMMDDHHMM(无分隔符),data[secid] 除 m15 外还含 qt/prec,
    # m15 元素 = [time, open, close, high, low, volume, {}, extra];close 在索引 2。
    m = MagicMock()
    m.json.return_value = {"data": {"sz000001": {
        "qt": {}, "prec": "9.9",
        "m15": [
            ["202607211030", "10.0", "10.11", "10.2", "9.9", "1000.00", {}, "0.64"],
            ["202607211045", "10.1", "10.22", "10.3", "10.0", "900.00", {}, "0.55"],
        ]}}}
    return m


def test_tencent_normalizes():
    with patch("scanner.sources.tencent.requests.get", return_value=_fake_resp()):
        bars = TencentSource().fetch_15min("000001", days=5)
    assert len(bars) == 2
    assert bars[0].close == 10.11
    assert bars[0].dt.strftime("%Y-%m-%d %H:%M") == "2026-07-21 10:30"
    assert str(bars[0].dt.tzinfo) == "Asia/Shanghai"


import pytest


@pytest.mark.smoke
def test_tencent_smoke_real():
    bars = TencentSource().fetch_15min("000001", days=5)
    assert len(bars) >= 16
    assert {b.dt.strftime("%H:%M") for b in bars} >= {"10:30", "15:00"}
