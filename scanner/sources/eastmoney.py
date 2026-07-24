from datetime import datetime, timedelta
import akshare as ak
from scanner.model import Bar, TZ

# SPIKE 实测确认:东财时间为收盘时刻,offset=0;列名 ['时间','开盘','收盘',...],时间格式 YYYY-MM-DD HH:MM:SS。
# 东财连接高频抖动(spike 单次 5/5 失败过);本适配器保持"单次尝试、失败即抛",重试策略由
# scan.fetch_all_sources(Task 10)统一承担;若东财整体不可用,3 源交叉校验降级为腾讯+新浪≥2 源。
CLOSE_OFFSET_MIN = 0
_TIME_COL = "时间"
_CLOSE_COL = "收盘"


class EastmoneySource:
    name = "east"

    def fetch_15min(self, symbol: str, days: int = 5) -> list[Bar]:
        df = ak.stock_zh_a_hist_min_em(symbol=symbol, period="15", adjust="")
        bars = []
        for _, row in df.iterrows():
            dt = datetime.strptime(str(row[_TIME_COL]).strip(), "%Y-%m-%d %H:%M:%S")
            dt = dt.replace(tzinfo=TZ) + timedelta(minutes=CLOSE_OFFSET_MIN)
            bars.append(Bar(dt, float(row[_CLOSE_COL])))
        bars.sort(key=lambda b: b.dt)
        # 只保留最近 days 个交易日
        keep = sorted({b.dt.date() for b in bars})[-days:]
        return [b for b in bars if b.dt.date() in set(keep)]
