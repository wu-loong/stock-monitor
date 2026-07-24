// Cloudflare Worker: serves the static dashboard + read-only D1 JSON APIs.
const HEADERS = { "content-type": "application/json; charset=utf-8", "cache-control": "no-store" };
const j = (data, status = 200) => new Response(JSON.stringify(data), { status, headers: HEADERS });

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname;
    if (path === "/api/overview") return overview(url, env);
    if (path === "/api/symbol") return symbolHistory(url, env);
    if (path.startsWith("/api/")) return j({ error: "unknown endpoint" }, 404);
    return env.ASSETS.fetch(request);
  },
};

async function latestDate(env) {
  const r = await env.DB.prepare(
    "SELECT trade_date FROM run_state ORDER BY trade_date DESC LIMIT 1"
  ).all();
  return r.results.length ? r.results[0].trade_date : null;
}

async function overview(url, env) {
  try {
    let date = url.searchParams.get("date");
    if (!date) date = await latestDate(env);
    if (!date) return j({ date: null, status: null, hits: [], counts: { total: 0, bad: 0 }, dates: [] });

    const [st, hits, cnt, dates] = await Promise.all([
      env.DB.prepare("SELECT trade_date,total_batches,next_batch,status,universe_json FROM run_state WHERE trade_date=?").bind(date).all(),
      env.DB.prepare("SELECT symbol,name,pool,close,data_quality FROM signals WHERE trade_date=? ORDER BY symbol").bind(date).all(),
      env.DB.prepare("SELECT COUNT(*) AS total, SUM(CASE WHEN data_quality IN ('data_unavailable','data_conflict') THEN 1 ELSE 0 END) AS bad FROM sample_daily WHERE trade_date=?").bind(date).all(),
      env.DB.prepare("SELECT r.trade_date AS d, r.status AS status, (SELECT COUNT(*) FROM signals s WHERE s.trade_date=r.trade_date) AS hits FROM run_state r ORDER BY r.trade_date DESC LIMIT 12").all(),
    ]);
    const strow = st.results[0] || null;
    let universe = 0;
    if (strow && strow.universe_json) {
      try { universe = JSON.parse(strow.universe_json).length; } catch (_) { universe = 0; }
      delete strow.universe_json;   // don't ship the full symbol list to the client
    }
    const counts = cnt.results[0] || { total: 0, bad: 0 };
    return j({
      date,
      status: strow,
      universe,                                  // 该日应扫描总数(成分池快照大小)
      progress: {
        scanned: counts.total || 0,              // sample_daily 已写行数 = 已扫描
        universe,
        remaining: Math.max(0, universe - (counts.total || 0)),
        batches_done: strow ? strow.next_batch : 0,
        batches_total: strow ? strow.total_batches : 0,
      },
      hits: hits.results,
      counts,
      dates: dates.results,
    });
  } catch (e) {
    return j({ error: String(e && e.message || e) }, 500);
  }
}

async function symbolHistory(url, env) {
  try {
    const code = (url.searchParams.get("code") || "").trim();
    if (!/^\d{6}$/.test(code)) return j({ error: "股票代码需为 6 位数字" }, 400);
    const r = await env.DB.prepare(
      "SELECT trade_date,pool,close,data_quality FROM signals WHERE symbol=? ORDER BY trade_date DESC LIMIT 60"
    ).bind(code).all();
    return j({ code, history: r.results });
  } catch (e) {
    return j({ error: String(e && e.message || e) }, 500);
  }
}
