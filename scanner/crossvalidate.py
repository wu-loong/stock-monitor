from scanner.model import ConsensusBar, PRICE_TOL, EPS


def cross_validate(series_by_source, tol=PRICE_TOL):
    maps = {name: {b.dt: b.close for b in bars} for name, bars in series_by_source.items()}
    all_dts = sorted({dt for m in maps.values() for dt in m})
    out = []
    for dt in all_dts:
        vals = [round(maps[n][dt], 2) for n in maps if dt in maps[n]]
        if not vals:
            out.append(ConsensusBar(dt, None, "missing"))
        elif len(vals) == 1:
            out.append(ConsensusBar(dt, vals[0], "unverified"))
        elif max(vals) - min(vals) <= tol + EPS:
            out.append(ConsensusBar(dt, sum(vals) / len(vals), "confirmed"))
        else:
            out.append(ConsensusBar(dt, None, "conflict"))
    return out
