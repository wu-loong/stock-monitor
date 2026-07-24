from datetime import datetime, timedelta
import requests
from scanner.model import Bar, TZ
from scanner.symbols import to_secid

CLOSE_OFFSET_MIN = 0        # SPIKE 实测确认:腾讯时间为收盘时刻,offset=0
_CLOSE_IDX = 2


class TencentSource:
    name = "tx"

    def fetch_15min(self, symbol: str, days: int = 5) -> list[Bar]:
        sec = to_secid(symbol)
        # SPIKE 实测:必须用 ifzq.gtimg.cn;web.ifzq.gtimg.cn 会 301 到已失效的 web3.* (NXDOMAIN)
        url = (f"https://ifzq.gtimg.cn/appstock/app/kline/mkline"
               f"?param={sec},m15,,320")
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        node = r.json()["data"][sec]
        rows = node.get("m15") or node.get("qfqm15") or []
        bars = []
        for row in rows:
            dt = datetime.strptime(row[0].strip(), "%Y%m%d%H%M")   # 紧凑格式,无分隔符
            dt = dt.replace(tzinfo=TZ) + timedelta(minutes=CLOSE_OFFSET_MIN)
            bars.append(Bar(dt, float(row[_CLOSE_IDX])))
        bars.sort(key=lambda b: b.dt)
        keep = set(sorted({b.dt.date() for b in bars})[-days:])
        return [b for b in bars if b.dt.date() in keep]
