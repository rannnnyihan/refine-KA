"""Internal low-cost shortlist: evidence score plus supported low-disclosure opportunities."""
import argparse
from pathlib import Path
from common import read,write,rules

MODES={'full':['track_growth','national_qualification','honor_list','green_certification','policy_support',
               'revenue_growth','capex_growth','rd_growth','export_growth','rd_intensity']}
FINANCIAL={'revenue_growth','capex_growth','rd_growth','export_growth','rd_intensity'}
# Business signals must be company-specific; shared growth and generic honours cannot qualify alone.
SIGNALS={'customer_budget','customer_quality','financing','capacity','overseas_investment','ma',
         'tech_breakthrough','new_product','commercialization','market_rank'}


def latest_verified(observations,cid,near):
    chosen={}
    for o in observations:
        if o['company_id']!=cid or o['period'] not in near or o['status']!='verified' or not o.get('applicable_for_current'):
            continue
        mid=o['metric_id']
        if mid not in chosen or o['period']>chosen[mid]['period']: chosen[mid]=o
    return chosen


def prescreen_score(observations,cid,metrics,near,weights=None):
    selected=latest_verified(observations,cid,near)
    selected={k:v for k,v in selected.items() if k in metrics}
    return sum(o['weighted_score'] for o in selected.values()),len(selected)


def select_shortlist(pool,observations,items,periods,top_n=30,cap=40):
    imap={i['id']:i for i in items};coarse=set(MODES['full']); near=set(periods[-2:]);rows=[]
    for c in pool:
        if c['eligibility'] not in ('prescreened','main','prescreened_out'): continue
        chosen=latest_verified(observations,c['id'],near)
        base=[o for mid,o in chosen.items() if mid in coarse]
        signal=[o for mid,o in chosen.items() if mid in SIGNALS and
                o['raw_score']/imap[mid]['max']>=0.6 and o['source_weight']>=0.75]
        signal.sort(key=lambda o:-(o['weighted_score']/imap[o['metric_id']]['max']))
        financial=sum(mid in chosen for mid in FINANCIAL)
        eligible=(financial<3 and len(signal)>=2 and any(o['source_weight']>=0.9 for o in signal))
        rows.append(dict(company_id=c['id'],score=round(sum(o['weighted_score'] for o in base),3),
            covered=len(base),financial_covered=financial,
            opportunity_eligible=eligible,signal_metrics=[o['metric_id'] for o in signal],
            opportunity_score=sum(o['weighted_score']/imap[o['metric_id']]['max'] for o in signal[:3]),
            current_signals=sum(o['period']==periods[-1] for o in signal),
            signal_groups=len({imap[o['metric_id']]['group'] for o in signal})))
    if not any(r['covered'] or r['signal_metrics'] for r in rows):
        raise ValueError('尚无可用证据，不能按名单顺序淘汰企业')
    rows.sort(key=lambda r:(-r['score'],-r['covered'],r['company_id']))
    selected={r['company_id']:'base' for r in rows[:min(top_n,cap)]}
    opportunities=[r for r in rows if r['company_id'] not in selected and r['opportunity_eligible']]
    opportunities.sort(key=lambda r:(-r['opportunity_score'],-r['current_signals'],-r['signal_groups'],r['company_id']))
    for r in opportunities[:max(0,cap-len(selected))]: selected[r['company_id']]='opportunity'
    for r in rows:
        if len(selected)>=cap: break
        selected.setdefault(r['company_id'],'base_fill')
    for rank,r in enumerate(rows,1):
        r['base_rank']=rank;r['selection_route']=selected.get(r['company_id'],'out')
        r['needs_review']=r['financial_covered']<3 or abs(rank-cap)<=5
    return selected,rows


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--run',required=True)
    ap.add_argument('--plan',action='store_true');ap.add_argument('--apply',action='store_true')
    ap.add_argument('--force',action='store_true');args=ap.parse_args()
    run=Path(args.run);cfg=read(run/'run-config.json');pool=read(run/'candidate-pool.json');_,items,_=rules()
    if args.plan:
        lines=['# 内部低成本预筛计划',
            '全部企业先查官网业务/产品及新闻/项目；有最新年报/股东披露则一次抽取，缺失不反复追财报。',
            '共享增长按赛道建立；名单批量匹配；财报5项顺手提取。基础10项共44分。',
            '对每家用相近浏览深度记录客户、产品、技术、产能、融资等公司特有证据，不只给无年报企业查这些信息。',
            f"精采 {cfg['candidate_cap']} 家：基础通道 {cfg['top_n']} 家，其余优先有已证实业务信号的低财务披露企业。",
            '机会通道需至少2个不同业务维度达到原档位满分60%，其中至少1项S1/S2；财务证实不足3项。',
            '机会排序取最强3项标准化证据分之和，同分比较当年信号及类别覆盖，再按ID；不足名额由基础排序补齐。',
            '这只是精采名额分配，不是最终评分。无上市身份加分，不把没找到数据解释成企业表现差。',
            '复核低覆盖、两通道临界候选；原始事实保留内部文件，不输出至结果HTML。']
        (run/'prescreen-plan.md').write_text('\n'.join(lines),encoding='utf-8');print('已写入内部预筛计划');return
    if not args.apply: ap.error('指定 --plan 或 --apply')
    if not any(c['eligibility']=='prescreened' for c in pool) and not args.force:
        raise ValueError('已预筛；补证后重新预筛需 --force')
    # 200→40 不是名单字段排序。每个待筛主体必须先留下至少一次真实在线检索日志，
    # 防止只研究少数知名企业、再按注册资本/名单顺序补足候选池。
    expected={c['id'] for c in pool if c['eligibility']=='prescreened'}
    logs=read(run/'search-log.json')
    searched={x.get('company_id') for x in logs
              if x.get('status')=='executed' and x.get('online') is True
              and (x.get('query') or x.get('result_urls'))}
    missing=sorted(expected-searched)
    if missing:
        preview='、'.join(missing[:12])
        suffix=f'等{len(missing)}家' if len(missing)>12 else ''
        raise ValueError(f'不能执行{cfg["candidate_cap"]}家筛选：尚有企业未完成真实联网粗采：{preview}{suffix}')
    from score_companies import calculate
    calculate(run,stage='prescreen')
    selected,review=select_shortlist(pool,read(run/'observations-scored.json'),items,cfg['periods'],cfg['top_n'],cfg['candidate_cap'])
    lookup={r['company_id']:r for r in review}
    for c in pool:
        if c['id'] not in lookup: continue
        r=lookup[c['id']]
        c.update(prescreen_score=r['score'],prescreen_covered=r['covered'],prescreen_rank=r['base_rank'],
                 selection_route=r['selection_route'],eligibility='main' if c['id'] in selected else 'prescreened_out',
                 eligibility_reason='内部精采分配：'+r['selection_route'])
    write(run/'candidate-pool.json',pool);write(run/'prescreen-review.json',review)
    with (run/'universe-review.md').open('a',encoding='utf-8') as f:
        f.write(f'\n内部预筛完成：{len(selected)}家进入精采，机会通道{sum(v=="opportunity" for v in selected.values())}家；详见prescreen-review.json。\n')
    print(f'内部精采名单已选定：{len(selected)}家')

if __name__=='__main__': main()
