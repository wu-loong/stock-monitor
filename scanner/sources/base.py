from typing import Protocol
from scanner.model import Bar


class KLineSource(Protocol):
    name: str

    def fetch_15min(self, symbol: str, days: int = 5) -> list[Bar]:
        """返回最近 days 个交易日的 15 分钟收盘 Bar,升序,dt=收盘时刻/Asia-Shanghai。失败抛异常。"""
        ...
