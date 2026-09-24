# -*- coding: utf-8 -*-
"""生成企业 TopN 评分看板 HTML（对齐 industry-evidence-dashboard 视觉风格）。

用法: python3 gen_company_html.py --run <运行目录> [--out 输出文件名]

深绿 header / 指标卡 / 权重滑杆实时重排 / 12 列主表 / 右侧抽屉 23 项 × 3 期 S1-S4 证据卡，
单文件无外部依赖。评分组与满分从 scoring-standard-company.md 读取，不硬编码。
"""
import argparse
import json
import html
import re
import datetime
from pathlib import Path

from common import periods_for, read, rules

_ap = argparse.ArgumentParser()
_ap.add_argument("--run", required=True)
_ap.add_argument("--draft", action="store_true", help="仅输出清晰标注的未完成草稿")
_ap.add_argument("--out", default="company-top50.html")
_args = _ap.parse_args()

RUN = Path(_args.run)
CFG = read(RUN / "run-config.json")
AS_OF = CFG["as_of"]
REGION = CFG["region"]
INDUSTRY = CFG["industry"]
TOP_N = CFG.get("top_n", 30)
PERIODS = list(periods_for(AS_OF))
PERIOD_LABEL = {p: (f"{p} 年" if not p.endswith("YTD") else f"{p[:4]} 年至今") for p in PERIODS}

# 评分组直接从评分标准读取（scores.json 里 metric 的 group 是中文组名）
_rubric, _items, _ = rules()
N_ITEMS = len(_items)
GROUPS = [(g["label"], g["label"], int(g["weight"])) for g in _rubric["groups"]]
DEFW = {k: w for k, _, w in GROUPS}

# Recompute from raw normalized evidence so an obsolete scores file cannot bypass validation.
from score_companies import calculate
s = calculate(RUN)
if s['quality_review']['status'] != 'complete' and not _args.draft:
    raise SystemExit('Top30逐维信息未通过验收；先补齐top30-quality.json中的缺口。内部预览可显式使用--draft。')

obs = json.loads((RUN / "observations.json").read_text(encoding="utf-8"))
pool = json.loads((RUN / "candidate-pool.json").read_text(encoding="utf-8"))
main = s["main"]
EV = {e["id"]: e for e in s["evidence"]}
POOL = {c["id"]: c for c in pool}


def esc(x):
    return html.escape(str(x if x is not None else ""), quote=True)


def fmt(v):
    if v is None:
        return "–"
    try:
        f = float(v)
    except Exception:
        return "–"
    if f != f or f in (float("inf"), float("-inf")):
        return "–"
    r = round(f, 2)
    return str(int(r)) if abs(r - int(r)) < 1e-9 else f"{r:.2f}".rstrip("0").rstrip(".")


def clip(t, n=300):
    t = re.sub(r"\s+", " ", str(t or "")).strip()
    return t if len(t) <= n else t[: n - 1] + "…"


# ---------- 每家企业的组得分 / 摘要 / 证据数 ----------
rows = []
for i, c in enumerate(main, 1):
    gval = {k: 0.0 for k, _, _ in GROUPS}
    graw = {k: 0.0 for k, _, _ in GROUPS}
    ev_cnt = 0
    for m in c["metrics"]:
        gval[m["group"]] += m["weighted_score"] or 0
        graw[m["group"]] += m["raw_score"] or 0
        if m["score_basis"] == "evidence":
            ev_cnt += 1
    # AI 摘要：取权重分最高的两项
    top = sorted(c["metrics"], key=lambda m: -(m["weighted_score"] or 0))[:2]
    top_txt = "；".join(f"{m['label']} {fmt(m['weighted_score'])}/{fmt(m['max'])}" for m in top)
    cov = c["verified_weight"]
    cred = "高" if cov >= 70 else "中高" if cov >= 50 else "中" if cov >= 30 else "低"
    rows.append(dict(rank=i, c=c, gval=gval, graw=graw, ev_cnt=ev_cnt, cred=cred, top_txt=top_txt))

# ---------- 抽屉内容（23 项 × 3 期） ----------
OBS = {(o["company_id"], o["metric_id"]): o for o in obs}
LOG = {l["id"]: l for l in s["search_log"]}


def detail_html(o):
    d=o.get('detail', {}); labels={'entity_scope':'主体与业务范围','time_scope':'事实期间',
        'status_context':'进展/有效状态','fallback_reason':'历史回退说明'}
    parts=[f'<div><b>{label}：</b>{esc(d[key])}</div>' for key,label in labels.items() if d.get(key)]
    labels={'value':'数值','unit':'单位','current_value':'当期值','baseline_value':'可比基数',
        'current_period':'当期区间','comparison_period':'比较区间','basis':'口径','calculation':'计算/直接披露依据'}
    parts += [f'<div><b>{label}：</b>{esc(d.get("measurement",{})[key])}</div>' for key,label in labels.items() if key in d.get('measurement',{})]
    if d.get('limitations'): parts.append('<div><b>信息局限：</b>'+esc('；'.join(d['limitations']))+'</div>')
    parts.append('<div><b>定档理由：</b>'+esc(o.get('rationale',''))+'</div>')
    return '<div class="meta">'+''.join(parts)+'</div>'


def build_detail(cid, c):
    order = {m["id"]: i for i, m in enumerate(c["metrics"])}
    out = []
    for m in sorted(c["metrics"], key=lambda m: order[m["id"]]):
        per = {o["period"]: o for o in m["periods"]}
        # 与表格/总分口径一致：采用 scores.json 选定的期间（可能是历史期回退）
        sel = per.get(m["selected_period"]) or per[PERIODS[-1]]
        fallback = m.get("historical_fallback")
        evs = []
        for pid in (sel.get("decision_evidence_ids") or []):
            if pid in EV:
                evs.append(EV[pid])
        # 检索日志来源
        urls = []
        for lid in (sel.get("search_ids") or [])[:2]:
            if lid in LOG:
                urls += [u for u in LOG[lid].get("result_urls", []) if u.startswith("http")]

        periods_html = []
        for p in PERIODS:
            o = per.get(p)
            if not o:
                continue
            basis = o["score_basis"]
            band = o.get("band") or o.get("default_band") or "未定档"
            rs = o.get("raw_score")
            ws = o.get("weighted_score")
            if basis == "evidence":
                tag = f"{fmt(rs)} × {fmt(o.get('source_weight'))} = {fmt(ws)}"
                state = "已定档"
            elif basis == "default":
                tag = f"缺省 {fmt(ws)}"
                state = "缺省分"
            else:
                tag = "0"
                state = "未定档"
            periods_html.append(
                f'<div class="tier-item"><span class="tier-tag tier-p">{esc(PERIOD_LABEL[p])}</span>'
                f'<div class="tier-ev"><b>{esc(band)}</b> · {esc(tag)}'
                f'<span class="hint"> · {esc(state)}</span>'
                f'<div class="pex">{esc(o.get("fact"))}</div></div></div>')

        head_score = fmt(m["weighted_score"])
        fb_txt = "（最新期未定档，回退至最近已定档期）" if fallback else ""
        note = ""
        if m["score_basis"] == "default":
            note = "完成S1-S4检索仍无可核实来源，按评分标准领取缺省分（不乘来源系数）；该分表示公开披露程度，不等于实际表现。"
        elif m["score_basis"] == "unrated":
            note = "尚未证实、访问受阻或无适用档位；保留缺口，当前分数贡献为0，不表示实际表现为0。"
        else:
            note = f"来源系数 {fmt(sel.get('source_weight'))}；证据组已通过同主体同期校验。"

        src_links = ""
        seen = set()
        for e in evs:
            if e["url"] in seen:
                continue
            seen.add(e["url"])
            src_links += (f'<div class="tier-item"><span class="tier-tag tier-{e["grade"].lower()}">{esc(e["grade"])}</span>'
                          f'<div class="tier-ev">{esc(e["excerpt"])}'
                          f'<div class="hint">位置：{esc(e["locator"])}｜发布：{esc(e["published_date"])}｜查阅：{esc(e["accessed_date"])}</div>'
                          f'<a href="{esc(e["url"])}" target="_blank" rel="noopener">{esc(e["publisher"])}</a></div></div>')
        if not src_links:
            for u in urls[:2]:
                if u in seen:
                    continue
                seen.add(u)
                src_links += (f'<div class="tier-item"><span class="tier-tag tier-s4">检索</span>'
                              f'<div class="tier-ev">仅检索到候选来源，未达定档标准'
                              f'<a href="{esc(u)}" target="_blank" rel="noopener">查看检索结果</a></div></div>')

        out.append(f'''<article class="score-item">
<h3>{esc(m["label"])}<span class="pill">{head_score} / {fmt(m["max"])}</span></h3>
<div class="bandrow">分档：<b>{esc((sel.get("band") or sel.get("default_band") or "未定档"))}</b><span class="hint"> · 选用期 {esc(PERIOD_LABEL[sel["period"]])}{fb_txt}</span></div>
<div class="meta">{esc([g[1] for g in GROUPS if g[0]==m["group"]][0])}｜原始分 {fmt(m["raw_score"])}｜加权分 {fmt(m["weighted_score"])}｜满分 {fmt(m["max"])}</div>
<div class="excerpt">{esc(sel.get("fact") or sel.get("rationale"))}</div>
{detail_html(sel)}
<div class="tier-list"><div class="tier-list-title">三期定档与证据</div>{"".join(periods_html)}</div>
<div class="tier-list"><div class="tier-list-title">判定来源（S1–S4）</div>{src_links or '<div class="tier-item"><div class="tier-ev">无可用来源</div></div>'}</div>
<div class="meta vnote">核验备注：{esc(note)}</div>
</article>''')
    return "".join(out)


def build_drawer(cid, c, r):
    g = r["gval"]
    cards = "".join(
        f'<div class="group-score"><span>{esc(lbl)}</span><b>{fmt(g[k])} <i>/ {fmt(w)}</i></b></div>'
        for k, lbl, w in GROUPS)
    p = POOL[cid]
    return f'''<div class="drawer-inner">
<div class="drawer-head">
<div class="dh-left">
<h2>{esc(c["name"])}</h2>
<div class="dh-meta">{esc(c.get("identity_note",""))}｜加权总分 <b class="dh-score">{fmt(c["weighted_total"])}</b> / 100
｜原始分 {fmt(c["raw_total"])}｜已证实满分 {fmt(c["verified_weight"])}｜证据 {r["ev_cnt"]}/23｜证据分 {fmt(c["evidence_total"])}｜缺省分 {fmt(c["default_total"])}（{c["default_count"]}项）</div>
<div class="dh-meta">用户名单范围：{esc(REGION)} / {esc(INDUSTRY)}</div>
</div>
<button class="dh-close" onclick="closeDrawer()">关闭</button>
</div>
<div class="drawer-body">
<div class="group-grid">{cards}</div>
<div class="method"><p><b>计分口径</b>：23 项 × 3 期（{esc(" / ".join(PERIOD_LABEL[p] for p in PERIODS))}）。每项按评分标准定档得原始分，
再乘来源系数（S1 1.00 / S2 0.90 / S3 0.75 / S4 0.50）；完成 S1–S4 检索仍无可核实来源的项领取缺省分且不乘系数。
排名采用最新已定档期，缺省项会高估披露不足的企业，请结合「已证实满分」阅读。</p></div>
{build_detail(cid, c)}
</div></div>'''


DRAWERS = {c["id"]: build_drawer(c["id"], c, r) for r, c in zip(rows, main)}

# ---------- 主表 ----------
trs = []
for r in rows:
    c = r["c"]
    g = r["gval"]
    data = " ".join(f'data-g-g{i}="{g[k]:.4f}"' for i, (k, _, _) in enumerate(GROUPS))
    p = POOL[c["id"]]
    seg = clip(p.get("scope_reason", ""), 60)
    tds = "".join(
        f'<td><div class="ovd-i"><div class="ovd-score">{fmt(g[k])}</div>'
        f'<div class="ovd-max">/{fmt(w)}</div></div></td>' for k, _, w in GROUPS)
    trs.append(f'''<tr class="crow" {data} data-cid="{esc(c["id"])}" onclick="openDrawer('{esc(c["id"])}')">
<td class="ovr">{r["rank"]}</td>
<td><div class="ovn-i"><span class="ovn">{esc(c["name"])}</span></div>
<div class="ovsub">{esc(seg)}</div></td>
{tds}
<td><span class="ovs"><b>{fmt(c["weighted_total"])}</b></span></td>
<td class="ovai">{esc(r["top_txt"])}</td>
<td class="ovs">{r["ev_cnt"]}/23</td>
<td><span class="credb cred-{esc(r["cred"])}">{esc(r["cred"])}</span></td>
</tr>''')

wgrid = "".join(f'''<label><span>{esc(lbl)}<span class="wval" id="wv-g{i}">{w}</span></span>
<input type="range" min="0" max="40" step="1" value="{w}" data-k="g{i}"></label>'''
          for i, (_, lbl, w) in enumerate(GROUPS))
DEF_LIST = [w for _, _, w in GROUPS]

# ---------- 评分标准视图 ----------
import subprocess
rub = _rubric
rubric_html = ""
for grp in rub["groups"]:
    body = "".join(
        f'<tr><td>{esc(it["no"])}</td><td>{esc(it["label"])}</td>'
        f'<td>{"；".join(esc(b[0])+" = "+str(b[1]) for b in it["bands"])}</td>'
        f'<td>{esc("、".join(it.get("sources") or []))}</td></tr>' for it in grp["items"])
    rubric_html += (f'<section class="rubric-group"><h3>{esc(grp["label"])}<span>{esc(grp["weight"])} 分</span></h3>'
                    f'<div class="rubric-body"><table><thead><tr><th>#</th><th>指标</th><th>分档</th><th>建议来源</th></tr></thead>'
                    f'<tbody>{body}</tbody></table></div></section>')

_w = s.get("source_weights", {})
SOURCES = [
    (f"S1 系数 {_w.get('S1', 1.0):.2f}", "企业一手披露：年报、审计报告、交易所公告、招股书、官网业务/产品/客户/招聘页面"),
    (f"S2 系数 {_w.get('S2', 0.9):.2f}", "政府与监管：资质、项目、环评、备案、资金、招投标等原始公开记录"),
    (f"S3 系数 {_w.get('S3', 0.75):.2f}", "权威第三方：券商研报、行业协会、招聘与创投平台、专业媒体"),
    (f"S4 系数 {_w.get('S4', 0.5):.2f}", "一般转载与聚合材料；必须联网补查 S1–S3，仅作追溯线索，不参与定档"),
]
sources_html = "".join(
    f'<section class="rubric-group"><h3>{esc(t)}</h3><div class="rubric-body"><p>{esc(d)}</p></div></section>'
    for t, d in SOURCES)

fill_pct = sum(r["ev_cnt"] for r in rows) / (N_ITEMS * len(rows)) * 100
n_high = sum(1 for r in rows if r["cred"] == "高")
n_mid = sum(1 for r in rows if r["cred"] in ("中高", "中"))
n_low = sum(1 for r in rows if r["cred"] == "低")

_src_txt = " / ".join(f"S{i} {_w.get(f'S{i}', v):.2f}"
                      for i, v in ((1, 1.0), (2, 0.9), (3, 0.75), (4, 0.5)))
_gap_txt = "" if len(main) >= TOP_N else f"，距目标 Top{TOP_N} 缺 {TOP_N - len(main)} 家"

current_count = sum(c.get('current_evidence_count',0) for c in main)
historical_count = sum(c.get('historical_evidence_count',0) for c in main)
s1_count = sum(1 for c in main for m in c['metrics'] if m['score_basis']=='evidence' and next(o for o in m['periods'] if o['period']==m['selected_period'])['source_weight']==1)
summary_html = (f'<div class="method">当年证据 {current_count}/{N_ITEMS*len(main)}；历史回退 {historical_count}/{N_ITEMS*len(main)}；'
                f'S1定档 {s1_count}/{sum(r["ev_cnt"] for r in rows)}；缺省合计 {sum(c["default_total"] for c in main):.2f} 分 / {sum(c["default_count"] for c in main)} 项。'
                f'状态：{esc(s["status"])}。<br>'+ ('信息完整度验收未完成，请查看各维度标注。' if s.get('quality_review',{}).get('status')!='complete' else '23维信息完整度验收通过。')+'</div>')
CSS = """
:root{--ink:#0A2F24;--mut:#6B7280;--line:#E5E7EB;--bg:#F7F8FA;--card:#ffffff;--acc:#0A2F24;--accbg:#E7FFD9;--green:#3DCD58;--amber:#b45309}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font:14px/1.55 Arial,"Microsoft YaHei",sans-serif}
.wrap{max-width:1680px;margin:0 auto}
header{background:#016B01;padding:24px 34px 16px;position:sticky;top:0;z-index:5;display:flex;align-items:center;justify-content:space-between;gap:24px}
.header-main{flex:1;min-width:0}
header h1{font-size:24px;color:#fff;margin:0 0 4px;font-weight:700}
.subtitle{color:rgba(255,255,255,.82);font-size:13px;margin:0 0 2px;letter-spacing:.4px;line-height:1.7}
nav{display:flex;gap:8px;margin-top:14px;flex-wrap:wrap}
nav button{background:rgba(255,255,255,.18);color:#fff;border:1px solid rgba(255,255,255,.28);border-radius:7px;padding:7px 14px;cursor:pointer;font:inherit;font-size:13.5px}
nav button:hover{background:rgba(255,255,255,.3)}
nav button.active{background:#fff;color:#0A2F24;border-color:#fff}
main{padding:22px 34px 38px}
.view{display:none}.view.active{display:block}
.metrics{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px}
.metric-big{padding:16px 20px;background:#fff;border:1px solid var(--line);border-radius:12px;display:flex;flex-direction:column;gap:3px}
.mb-num{font-size:30px;font-weight:700;color:#0A2F24;line-height:1.1}
.mb-label{font-size:13.5px;color:#0A2F24;font-weight:600}
.mb-sub{font-size:12px;color:var(--mut);margin-top:5px;line-height:1.6}
.method{background:#fff;border:1px solid var(--line);border-left:4px solid #0A2F24;border-radius:8px;padding:13px 16px;margin:0 0 16px}
.method p{margin:5px 0;font-size:13.5px}
.toolbar{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin:14px 0}
#q{flex:1 1 240px;padding:9px 12px;border:1px solid var(--line);border-radius:10px;font-size:14px;background:#fff}
.sel{padding:9px 12px;border:1px solid var(--line);border-radius:10px;font-size:13px;background:#fff;color:var(--ink);cursor:pointer}
.chip{border:1px solid var(--line);background:#fff;border-radius:99px;padding:5px 12px;font-size:12.5px;color:var(--ink);cursor:pointer}
.print-btn{margin-left:auto;padding:7px 16px;background:#016B01;color:#fff;border:0;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer}
.hint{font-size:12px;color:var(--mut)}
.weights{background:#f4f7fa;border:1px solid #d9e1e8;border-radius:12px;padding:12px 14px;margin:8px 0 14px}
.wlbl{font-size:12.5px;color:var(--mut);margin-bottom:8px}
.wgrid{display:grid;grid-template-columns:repeat(6,1fr);gap:10px}
.wgrid label{display:flex;flex-direction:column;gap:4px;font-size:12.5px;color:var(--ink);font-weight:600}
.wgrid label>span{display:flex;justify-content:space-between;align-items:baseline}
.wval{font-family:ui-monospace,Menlo,monospace;font-weight:700;color:var(--acc);font-size:13px}
.wgrid input[type=range]{-webkit-appearance:none;appearance:none;width:100%;height:8px;background:#d6e8dc;border-radius:4px;outline:none;cursor:pointer;touch-action:none}
.wgrid input[type=range]::-webkit-slider-thumb{-webkit-appearance:none;width:18px;height:18px;border-radius:50%;background:#0A2F24;border:2px solid #fff;box-shadow:0 1px 3px rgba(10,47,36,.3);cursor:pointer}
.wgrid input[type=range]::-moz-range-thumb{width:18px;height:18px;border-radius:50%;background:#0A2F24;border:2px solid #fff;box-shadow:0 1px 3px rgba(10,47,36,.3);cursor:pointer}
.wtot{font-size:12.5px;color:var(--mut);margin-top:8px}
.panel{background:#fff;border:1px solid var(--line);border-radius:10px;overflow:auto}
table.ov{width:100%;border-collapse:collapse;table-layout:fixed}
table.ov th,table.ov td{padding:12px 10px;border-bottom:1px solid var(--line);font-size:13.5px;text-align:left;vertical-align:middle;line-height:1.45}
table.ov th{background:#0A2F24;color:#fff;font-weight:600;white-space:nowrap;padding:11px 10px;font-size:12.5px}
table.ov th .th-max{display:block;font-weight:400;font-size:10.5px;color:#cbd5e1;margin-top:1px}
table.ov th:nth-child(1),table.ov td:nth-child(1){width:48px;text-align:center}
table.ov th:nth-child(2),table.ov td:nth-child(2){width:250px}
table.ov th:nth-child(3),table.ov td:nth-child(3),table.ov th:nth-child(4),table.ov td:nth-child(4),table.ov th:nth-child(5),table.ov td:nth-child(5),table.ov th:nth-child(6),table.ov td:nth-child(6),table.ov th:nth-child(7),table.ov td:nth-child(7),table.ov th:nth-child(8),table.ov td:nth-child(8){width:82px;text-align:center;padding:10px 5px}
table.ov th:nth-child(9),table.ov td:nth-child(9){width:82px;text-align:center}
table.ov th:nth-child(10),table.ov td:nth-child(10){width:250px}
table.ov th:nth-child(11),table.ov td:nth-child(11){width:60px;text-align:center}
table.ov th:nth-child(12),table.ov td:nth-child(12){width:60px;text-align:center}
.ovd-i{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:1px;line-height:1.15;min-height:34px}
.ovd-score{font-weight:700;color:var(--ink);font-size:14px}
.ovd-max{font-weight:400;color:var(--mut);font-size:10.5px}
.ovr{font-weight:700;color:var(--acc);text-align:center;font-size:14px}
.ovn{font-weight:700;color:var(--ink);font-size:13.5px}
.ovn-i{display:flex;align-items:center;gap:4px}
.ovsub{font-size:11.5px;color:var(--mut);margin-top:3px;line-height:1.4}
.ovs{text-align:center}
.ovs b{font-size:16px;font-weight:700;color:#2A8B3D}
.ovai{font-size:12.5px;color:var(--mut);line-height:1.5}
table.ov tbody tr{cursor:pointer}table.ov tbody tr:hover{background:#F0F6F1}
.credb{display:inline-block;padding:3px 10px;border-radius:8px;font-size:12px;font-weight:600;white-space:nowrap}
.cred-高{background:#e7f6ee;color:#0f8a4d}.cred-中高{background:#fdf3d7;color:#8a6d1a}
.cred-中{background:#fef6ec;color:#92400e}.cred-低{background:#f3f4f6;color:#6b7280}
.rubric-grid{display:grid;grid-template-columns:repeat(2,minmax(320px,1fr));gap:14px}
.rubric-group{background:#fff;border:1px solid var(--line);border-radius:10px;padding:15px}
.rubric-group h3{margin:0 0 10px;color:#0A2F24;display:flex;justify-content:space-between;font-size:15px}
.rubric-group h3 span{font-size:13px;color:var(--mut);font-weight:400}
.rubric-body table{width:100%}
.rubric-body th{background:#0A2F24;color:#fff;text-align:left;padding:7px 9px;font-size:12px}
.rubric-body td{padding:6px 9px;border-bottom:1px solid var(--line);font-size:12px;vertical-align:top}
.rubric-body p{margin:8px 0;font-size:13px}
.scrim{display:none;position:fixed;inset:0;background:rgba(15,34,58,.32);z-index:40}
.scrim.open{display:block}
.drawer{position:fixed;top:0;right:-940px;height:100vh;width:min(940px,97vw);background:#fff;box-shadow:-10px 0 32px rgba(0,0,0,.2);z-index:50;transition:right .18s ease-out;display:flex;flex-direction:column}
.drawer.open{right:0}
.drawer-inner{overflow:auto;flex:1}
.drawer-body{padding:18px 24px 40px}
.drawer-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px;padding:18px 24px;border-bottom:1px solid var(--line);background:#fff;position:sticky;top:0;z-index:2}
.drawer-head h2{margin:0 0 5px;font-size:20px;color:#0A2F24}
.dh-meta{color:var(--mut);font-size:12.5px;margin-top:2px}
.dh-meta b{color:#0A2F24}
.dh-score{color:#2A8B3D;font-weight:700}
.dh-close{background:#0A2F24;color:#fff;border:0;border-radius:6px;padding:6px 14px;cursor:pointer;font:inherit;font-size:13px;height:34px;flex-shrink:0}
.group-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:9px;margin-bottom:15px}
.group-score{border:1px solid var(--line);border-radius:8px;padding:9px;background:#fff}
.group-score span{color:var(--mut);font-size:12px;display:block;margin-bottom:4px}
.group-score b{display:block;color:#0A2F24;font-size:17px}
.group-score b i{font-style:normal;font-size:12px;color:var(--mut);font-weight:400}
.score-item{border:1px solid var(--line);border-radius:9px;padding:13px;margin:10px 0;background:#fff}
.score-item h3{margin:0 0 6px;font-size:15px;color:#0A2F24}
.pill{display:inline-block;margin-left:6px;padding:2px 7px;background:#E7FFD9;color:#0A2F24;border-radius:999px;font-size:12px;font-weight:600}
.bandrow{font-size:13px;margin:2px 0}
.excerpt{margin:8px 0;padding:9px 11px;background:#F7F8FA;border-left:3px solid #0A2F24;font-size:13px;color:#0A2F24}
.meta{font-size:12px;color:var(--mut);margin:4px 0}
.vnote{color:#b45309;font-style:italic}
.tier-list{margin:8px 0;padding:8px 10px;background:#F7F8FA;border:1px solid var(--line);border-radius:8px}
.tier-list-title{font-size:12px;color:var(--mut);font-weight:700;margin-bottom:5px}
.tier-item{display:flex;gap:8px;align-items:flex-start;padding:5px 0;border-bottom:1px dashed var(--line);font-size:12.5px;line-height:1.55}
.tier-item:last-child{border-bottom:0}
.tier-tag{flex-shrink:0;display:inline-block;padding:0 7px;border-radius:4px;font-size:11px;font-weight:700;margin-top:2px;color:#fff}
.tier-s1{background:#0A2F24}.tier-s2{background:#2A8B3D}.tier-s3{background:#8a6d1a}.tier-s4{background:#6B7280}
.tier-p{background:#5b7f9e}
.tier-ev{flex:1;min-width:0;word-break:break-word}
.tier-ev a{color:#0A2F24;font-size:12px;text-decoration:underline;margin-left:4px;word-break:break-all}
.pex{color:var(--mut);font-size:12px;margin-top:2px}
.foot{color:var(--mut);font-size:12px;margin-top:22px;line-height:1.8;padding:0 0 30px}
@media(max-width:1100px){.metrics{grid-template-columns:repeat(2,1fr)}.wgrid{grid-template-columns:repeat(3,1fr)}}
@media(max-width:720px){.drawer{width:100vw}.group-grid{grid-template-columns:1fr}.rubric-grid{grid-template-columns:1fr}main{padding:16px}}
@media print{header{position:static}nav,.toolbar,.weights,.scrim,.drawer{display:none!important}.view{display:block!important}}
"""

JS = """
const KS=%s, DEF=%s;
let W=DEF.slice();
const rows=[...document.querySelectorAll('tr.crow')];
function recompute(){
  let sum=0; for(let i=0;i<W.length;i++){sum+=W[i];var e=document.getElementById('wv-'+KS[i]); if(e)e.textContent=W[i];}
  var ws=document.getElementById('wsum'); if(ws)ws.textContent=sum;
  rows.forEach(tr=>{
    let tot=0;
    for(let i=0;i<W.length;i++){ tot+=parseFloat(tr.getAttribute('data-g-'+KS[i])||0)*(W[i]/DEF[i]); }
    var b=tr.querySelector('.ovs b'); if(b)b.textContent=tot.toFixed(2);
    tr.setAttribute('data-tot',tot.toFixed(4));
  });
  const tb=document.getElementById('ov');
  if(tb){
    [...tb.querySelectorAll('tr.crow')].sort((a,b)=>parseFloat(b.getAttribute('data-tot'))-parseFloat(a.getAttribute('data-tot')))
      .forEach((tr,i)=>{ tb.appendChild(tr); var r=tr.querySelector('.ovr'); if(r)r.textContent=i+1; });
  }
  try{filter();}catch(e){}
}
function updBg(inp){
  const pct=(inp.value-inp.min)/(inp.max-inp.min);
  inp.style.background='linear-gradient(to right,#0A2F24 0%%,#0A2F24 '+(pct*100)+'%%,#d6e8dc '+(pct*100)+'%%,#d6e8dc 100%%)';
}
function distribute(ci){
  W[ci]=Math.min(W[ci],100);
  const rest=100-W[ci];
  const idx=[]; for(let i=0;i<W.length;i++) if(i!==ci) idx.push(i);
  let cur=0; idx.forEach(i=>cur+=W[i]);
  if(cur<=0){ idx.forEach(i=>W[i]=rest/idx.length); }
  else { idx.forEach(i=>W[i]=Math.round(W[i]/cur*rest)); }
  let diff=100-W.reduce((a,b)=>a+b,0);
  if(diff!==0){ let j=idx[0]; W[j]+=diff; if(W[j]<0)W[j]=0; }
  KS.forEach((k,i)=>{ const inp=document.querySelector('input[data-k="'+k+'"]'); inp.value=W[i]; updBg(inp); });
  recompute();
}
document.querySelectorAll('.wgrid input[type=range]').forEach(inp=>{
  updBg(inp);
  const handler=()=>{ const i=KS.indexOf(inp.dataset.k); if(i<0)return; W[i]=parseInt(inp.value); distribute(i); };
  inp.addEventListener('input',handler);
  inp.addEventListener('change',handler);
});
document.getElementById('wreset').addEventListener('click',()=>{
  W=DEF.slice();
  KS.forEach((k,i)=>{const inp=document.querySelector('input[data-k="'+k+'"]');inp.value=W[i];updBg(inp);});
  recompute();
});
function filter(){
  const q=document.getElementById('q').value.trim().toLowerCase();
  const f=document.getElementById('fsel').value;
  let n=0;
  rows.forEach(tr=>{
    const txt=tr.innerText.toLowerCase();
    const tot=parseFloat(tr.getAttribute('data-tot')||tr.querySelector('.ovs b').textContent);
    let ok=!q||txt.includes(q);
    if(ok&&f==='70') ok=tot>=70;
    else if(ok&&f==='60') ok=tot>=60&&tot<70;
    else if(ok&&f==='0') ok=tot<60;
    tr.style.display=ok?'':'none'; if(ok)n++;
  });
  document.getElementById('cnt').textContent='命中 '+n+' 家';
}
document.getElementById('q').addEventListener('input',filter);
document.getElementById('fsel').addEventListener('change',filter);
document.querySelectorAll('nav button[data-view]').forEach(b=>b.addEventListener('click',()=>{
  document.querySelectorAll('nav button[data-view]').forEach(x=>x.classList.remove('active'));
  b.classList.add('active');
  document.querySelectorAll('.view').forEach(v=>v.classList.remove('active'));
  document.getElementById('view-'+b.dataset.view).classList.add('active');
}));
function openDrawer(id){
  const box=document.getElementById('drawer');
  box.innerHTML=DRAWERS[id]||'<div class="drawer-inner"><div class="drawer-body">无详情</div></div>';
  box.classList.add('open'); document.getElementById('scrim').classList.add('open');
  document.body.style.overflow='hidden';
}
function closeDrawer(){
  document.getElementById('drawer').classList.remove('open');
  document.getElementById('scrim').classList.remove('open');
  document.body.style.overflow='';
}
document.getElementById('scrim').addEventListener('click',closeDrawer);
document.addEventListener('keydown',e=>{if(e.key==='Escape')closeDrawer();});
document.getElementById('print').addEventListener('click',()=>window.print());
recompute();
""" % (json.dumps(["g%d" % i for i in range(len(GROUPS))]), json.dumps(DEF_LIST))

DRAWER_JSON = json.dumps(DRAWERS, ensure_ascii=False)

doc = f'''<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(REGION)} · {esc(INDUSTRY)}企业 Top{TOP_N} 评分看板</title>
<style>{CSS}</style></head><body>
<div class="wrap">
<header>
<div class="header-main">
<h1>{esc(REGION)} {esc(INDUSTRY)} Company Ranking Dashboard</h1>
<div class="subtitle">{esc(REGION)} · {esc(INDUSTRY)}｜用户名单 · {N_ITEMS}维证据 · 当年优先｜检索截止 {AS_OF}</div>
<nav>
<button class="active" data-view="ranking">企业排名</button>
<button data-view="rubric">评分标准</button>
<button data-view="sources">数据来源</button>
<button id="print">导出 PDF</button>
</nav>
</div>
</header>
<main>
<section class="view active" id="view-ranking">
<div class="metrics">
<div class="metric-big"><div class="mb-num">{len(main)}</div><div class="mb-label">家主榜企业</div>
<div class="mb-sub">展示最终 Top{TOP_N} 的逐维事实与评分依据</div></div>
<div class="metric-big"><div class="mb-num">{fill_pct:.0f}%</div><div class="mb-label">证据定档率</div>
<div class="mb-sub">{sum(r["ev_cnt"] for r in rows)} / {N_ITEMS*len(rows)} 项由 S1–S3 真实来源定档</div></div>
<div class="metric-big"><div class="mb-num">{sum(r["c"]["verified_weight"] for r in rows)/len(rows):.0f}</div><div class="mb-label">平均已证实满分</div>
<div class="mb-sub">满分 100；缺口主要来自 CAPEX、招聘、绿色认证等非强制披露项</div></div>
<div class="metric-big"><div class="mb-num">{n_high}/{n_mid}/{n_low}</div><div class="mb-label">置信度 高/中/低</div>
<div class="mb-sub">按已证实满分分档：≥70 高，50–70 中高，30–50 中，&lt;30 低</div></div>
</div>
<div class="method"><p><b>怎么读这张表</b>：总分 = {len(GROUPS)} 组加权分合计（满分 {sum(DEFW.values())}）。每组内 {N_ITEMS} 项先按评分标准定档得原始分，
再乘来源系数（{_src_txt}）。完成 S1–S4 检索仍无可核实来源的项领取缺省分且不乘系数，
因此<b>披露充分的企业天然占优</b>，总分表示的是「公开证据支持的优先级」，不等于企业真实实力——
请同时看「已证实满分」与「证据 X/{N_ITEMS}」两列。点击任意行可展开 {N_ITEMS} 项 × 3 期的完整证据卡。<br>
<b>证据优先级</b>：当年S1 → 当年S2 → 当年S3 → 去年S1 → 去年S2 → 去年S3；S4仅追溯，不定档。<br><b>取期规则</b>：每个指标只取最新一期有证据的档位，且<b>仅最近两期（{PERIOD_LABEL[PERIODS[-2]]} / {PERIOD_LABEL[PERIODS[-1]]}）的证据参与当期排名</b>；
{PERIOD_LABEL[PERIODS[0]]} 年及更早的事实仍在证据卡中保留供追溯，但不再计入总分，
以免一次性历史高增长（如某年出口暴增）长期撑高名次。</p></div>
{summary_html}
<div class="toolbar"><input id="q" placeholder="搜索企业名称、代码或业务方向…">
<select id="fsel" class="sel"><option value="">全部分数</option><option value="70">总分 ≥ 70</option><option value="60">总分 60–70</option><option value="0">总分 &lt; 60</option></select>
<span id="cnt" class="hint"></span>
</div>
<div class="weights">
<div class="wlbl">{len(GROUPS)} 组权重调节（仅在这{len(main)}家内重排，不重新筛选候选；默认 {"/".join(str(w) for *_, w in GROUPS)}，合计恒 {sum(DEFW.values())}）</div>
<div class="wgrid">{wgrid}</div>
<div class="wtot">当前权重合计 <b id="wsum">100</b> 分 · <button id="wreset" class="chip" type="button">恢复默认</button></div>
</div>
<div class="panel"><table class="ov"><thead><tr>
<th>排名</th><th>企业</th>
{''.join(f'<th>{esc(lbl)}<div class="th-max">{w}分</div></th>' for _, lbl, w in GROUPS)}
<th>总分<div class="th-max">/100</div></th><th>AI 摘要</th><th>证据</th><th>置信度</th>
</tr></thead><tbody id="ov">{"".join(trs)}</tbody></table></div>
<div class="foot">
<b>采证口径</b>：按 S1–S4 四级检索法，对每家企业 {N_ITEMS} 项 × 3 期（{esc(" / ".join(PERIOD_LABEL[p] for p in PERIODS))}）保留已采事实与待查状态，
按共享/名单/财报分层采证，充分证据命中即停；仅未知项需查尽后领取缺省分。<br>
<b>缺格与缺省分</b>：完成检索后结果为搜不到或无的项，按评分标准领取「查不到 / 无法确认排名 / 无公开信息 / 无」缺省分，不乘来源系数；
无此类缺省档的项（如研发强度、赛道增长）保持未定档计 0 分。缺省分不计入证据覆盖率。<br>
<b>已知限制</b>：① 主榜 {len(main)} 家（目标 Top{TOP_N}）{_gap_txt}；② CAPEX 增长、招聘人数、绿色认证等指标普遍缺乏公开口径，
对未上市企业与红筹架构企业尤为明显；③ 发布日逐条记录，无日期来源明确标记；④ 本表不构成投资建议，也不等同市场份额排名。<br>
检索截止 {AS_OF}｜规则版本 {esc(s["rubric_version"])}｜来源系数 {esc(json.dumps(s["source_weights"], ensure_ascii=False))}
</div>
</section>
<section class="view" id="view-rubric">
<div class="method"><p>{N_ITEMS} 项企业评分标准（原始满分 {rub["total"]}）。档位由 AI 阅读证据后匹配，程序负责校验与计算。</p></div>
<div class="rubric-grid">{rubric_html}</div>
</section>
<section class="view" id="view-sources">
<div class="method"><p>S1–S4 来源分级与加权系数。多来源不取算术平均，也不按来源篇数给分；
同一事实有多条独立充分证据时取最高等级，一个判定需拼接多条证据时取必需证据中的最低系数。</p></div>
<div class="rubric-grid">{sources_html}</div>
</section>
</main>
</div>
<div class="scrim" id="scrim"></div>
<aside class="drawer" id="drawer"></aside>
<script>const DRAWERS={DRAWER_JSON};</script>
<script>{JS}</script>
</body></html>'''

out = RUN / _args.out
out.write_text(doc, encoding="utf-8")
print("written:", out, len(doc), "bytes")
print(f"main: {len(main)} / Top{TOP_N} | drawers: {len(DRAWERS)} | fill rate: {fill_pct:.1f}%")
