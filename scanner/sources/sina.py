import json
from datetime import datetime, timedelta
import requests
from scanner.model import Bar, TZ
from scanner.symbols import to_secid

CLOSE_OFFSET_MIN = 0        # SPIKE 实测确认:新浪时间为收盘时刻,offset=0(day 字段 YYYY-MM-DD HH:MM:SS)
# 注:新浪成交量单位为"股"(东财/腾讯为"手",差 100 倍);本项目只用收盘价,不受影响。


class SinaSource:
    name = "sina"

    def fetch_15min(self, symbol: str, days: int = 5) -> list[Bar]:
        sec = to_secid(symbol)
        url = ("https://money.finance.sina.com.cn/quotes_service/api/json_v2.php/"
               f"CN_MarketData.getKLineData?symbol={sec}&scale=15&ma=no&datalen=120")
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        arr = json.loads(r.text)
        bars = []
        for row in arr:
            dt = datetime.strptime(row["day"].strip(), "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=TZ) + timedelta(minutes=CLOSE_OFFSET_MIN)
            bars.append(Bar(dt, float(row["close"])))
        bars.sort(key=lambda b: b.dt)
        keep = set(sorted({b.dt.date() for b in bars})[-days:])
        return [b for b in bars if b.dt.date() in keep]
