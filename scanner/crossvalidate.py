from scanner.model import ConsensusBar, PRICE_TOL, PRICE_TOL_REL, EPS


def cross_validate(series_by_source, abs_tol=PRICE_TOL, rel_tol=PRICE_TOL_REL):
    """逐时间戳跨源共识。容差 = max(abs_tol, rel_tol × 均价):
    盘中两源 15 分钟 bar 收盘价常差几分钱(不同 tick 聚合),纯 1 分钱绝对容差会把
    大量正常 bar 误判为 conflict。相对容差随价位缩放,只拦"整只错/量级错",放行 penny 噪声。"""
    maps = {name: {b.dt: b.close for b in bars} for name, bars in series_by_source.items()}
    all_dts = sorted({dt for m in maps.values() for dt in m})
    out = []
    for dt in all_dts:
        vals = [round(maps[n][dt], 2) for n in maps if dt in maps[n]]
        if not vals:
            out.append(ConsensusBar(dt, None, "missing"))
        elif len(vals) == 1:
            out.append(ConsensusBar(dt, vals[0], "unverified"))
        else:
            mean = sum(vals) / len(vals)
            tol = max(abs_tol, rel_tol * mean)
            if max(vals) - min(vals) <= tol + EPS:
                out.append(ConsensusBar(dt, mean, "confirmed"))
            else:
                out.append(ConsensusBar(dt, None, "conflict"))
    return out
