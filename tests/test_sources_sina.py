import json
from unittest.mock import patch, MagicMock
from scanner.sources.sina import SinaSource


def _fake_resp():
    m = MagicMock()
    m.text = json.dumps([
        {"day": "2026-07-21 10:30:00", "open": "10.0", "high": "10.2", "low": "9.9", "close": "10.11", "volume": "1000"},
        {"day": "2026-07-21 10:45:00", "open": "10.1", "high": "10.3", "low": "10.0", "close": "10.22", "volume": "900"},
    ])
    return m


def test_sina_normalizes():
    with patch("scanner.sources.sina.requests.get", return_value=_fake_resp()):
        bars = SinaSource().fetch_15min("000001", days=5)
    assert len(bars) == 2
    assert bars[0].close == 10.11
    assert bars[0].dt.strftime("%Y-%m-%d %H:%M") == "2026-07-21 10:30"
    assert str(bars[0].dt.tzinfo) == "Asia/Shanghai"


import pytest


@pytest.mark.smoke
def test_sina_smoke_real():
    bars = SinaSource().fetch_15min("000001", days=5)
    assert len(bars) >= 16
    assert {b.dt.strftime("%H:%M") for b in bars} >= {"10:30", "15:00"}
