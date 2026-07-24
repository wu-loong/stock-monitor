from scanner.model import ScanResult, SAMPLE_TIMES
from scanner.crossvalidate import cross_validate
from scanner.indicators import sample_index, windows_for, _ab_at
from scanner.signals import detect_hit


_Q_RANK = {"confirmed": 0, "unverified": 1, "conflict": 2, "missing": 3}


def evaluate_symbol(symbol, series_by_source, target_date):
    bars = cross_validate(series_by_source)   # list[ConsensusBar] 升序
    dates = sorted({b.dt.date() for b in bars})
    prev_list = [d for d in dates if d < target_date]
    prev = prev_list[-1] if prev_list else None

    # 采集 needed set + 判断可算性
    needed = set()
    computable = target_date in dates and prev is not None
    if computable:
        for d in (prev, target_date):
            for t in SAMPLE_TIMES:
                i = sample_index(bars, d, t)
                if i is None:
                    computable = False
                    continue
                win = windows_for(bars, i)
                if win is None:
                    computable = False
                    continue
                w15, w60 = win
                needed.update(w15)
                needed.update(w60)

    # 质量
    if not computable:
        quality = "data_unavailable"
    else:
        quals = {bars[j].quality for j in needed}
        worst = max(quals, key=lambda q: _Q_RANK[q])
        quality = {"missing": "data_unavailable", "conflict": "data_conflict",
                   "unverified": "unverified", "confirmed": "confirmed"}[worst]

    # 状态与命中(state_for_date 在 indicators 中对 None close 已返回 incomplete)
    from scanner.indicators import state_for_date
    state_t = state_for_date(bars, target_date) if target_date in dates else "incomplete"
    state_prev = state_for_date(bars, prev) if prev else "incomplete"
    hit, _ = detect_hit(bars, target_date) if computable else (False, None)
    if quality in ("data_unavailable", "data_conflict"):
        hit = False

    # 采样明细与收盘价
    samples = {}
    for t in SAMPLE_TIMES:
        i = sample_index(bars, target_date, t)
        a, b = (_ab_at(bars, i) if i is not None else (None, None))
        key = t.replace(":", "")
        samples[f"a_{key}"] = a
        samples[f"b_{key}"] = b
    i1500 = sample_index(bars, target_date, "15:00")
    close = bars[i1500].close if i1500 is not None else None

    return ScanResult(symbol=symbol, hit=hit, state_t=state_t, state_prev=state_prev,
                      quality=quality, close=close, samples=samples)
