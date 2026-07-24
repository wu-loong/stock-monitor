from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

TZ = ZoneInfo("Asia/Shanghai")
SAMPLE_TIMES = ("10:30", "11:30", "14:00", "15:00")
HOURLY_WINDOW = 5
MIN15_WINDOW = 20
PRICE_TOL = 0.05          # 跨源一致的绝对下限(元);低价股用。原 0.01 太严,盘中两源常差几分钱
PRICE_TOL_REL = 0.005     # 跨源一致的相对容差(0.5% × 均价);高价股用。取二者较大值
EPS = 1e-9


@dataclass(frozen=True)
class Bar:
    dt: datetime           # tz-aware Asia/Shanghai, bar close time
    close: float


@dataclass(frozen=True)
class ConsensusBar:
    dt: datetime
    close: float | None
    quality: str           # 'confirmed' | 'unverified' | 'conflict' | 'missing'


@dataclass(frozen=True)
class ScanResult:
    symbol: str
    hit: bool
    state_t: str
    state_prev: str
    quality: str           # 'confirmed'|'unverified'|'data_conflict'|'data_unavailable'
    close: float | None    # 目标日 15:00 收盘价
    samples: dict          # {"a_1030":.., "b_1030":.., ... , "a_1500":.., "b_1500":..}
