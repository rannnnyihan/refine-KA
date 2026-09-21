"""Report evidence gaps for all shortlisted companies, including current-year gaps."""
import argparse
from pathlib import Path
from common import read, write, rules


def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--run',required=True)
    args=ap.parse_args(); run=Path(args.run); cfg=read(run/'run-config.json')
    _,items,_=rules(); current=cfg['periods'][-1]
    pool=[c for c in read(run/'candidate-pool.json') if c['eligibility']=='main']
    if not pool: pool=[c for c in read(run/'candidate-pool.json') if c['eligibility']=='prescreened']
    obs=read(run/'observations.json'); indexed={}
    for o in obs:
        if o['status']=='verified' and o.get('applicable_for_current') and o['period'] in cfg['periods'][-2:]:
            key=(o['company_id'],o['metric_id'])
            if key not in indexed or o['period']>indexed[key]['period']: indexed[key]=o
    gaps={}; current_count=0; any_count=0
    for c in pool:
        rows=[]
        for i in items:
            o=indexed.get((c['id'],i['id']))
            any_count+=bool(o); current_count+=bool(o and o['period']==current)
            if not o or o['period']!=current:
                rows.append(dict(metric=i['id'],label=i['label'],status='historical_fallback' if o else 'missing',
                    selected_period=o['period'] if o else None, sources=i.get('sources',[]),
                    priority=['当年 S1','当年 S2','当年 S3','去年 S1','去年 S2','去年 S3']))
        gaps[c['id']]=rows
    total=len(pool)*len(items)
    quality=read(run/'top30-quality.json') if (run/'top30-quality.json').exists() else {}
    result=dict(total=total,evidence_count=any_count,current_count=current_count,gaps=gaps,top30_quality=quality)
    write(run/'s1-gap-plan.json',result)
    lines=['# 23维证据缺口',f'研究对象 {len(pool)} 家；证据覆盖 {any_count}/{total}；当年覆盖 {current_count}/{total}',
           '当年 S1 → 当年 S2 → 当年 S3 → 去年 S1 → 去年 S2 → 去年 S3。S4 仅追溯线索；缺省分不算证据。',
           '历史已有证据仍显示当年缺口；不为补满旧年格子挤占当年研究。']
    if quality:
        lines.append(f"当前Top30完整信息：{quality['completed_cells']}/{quality['required_cells']}；具体缺项见top30-quality.json（每轮先重算评分）。")
    for c in pool:
        lines.append('\n## '+c['name'])
        for g in gaps[c['id']]: lines.append(f"- {g['label']}：{g['status']}；参考入口：{'、'.join(g['sources'])}")
    (run/'s1-gap-plan.md').write_text('\n'.join(lines),encoding='utf-8')
    print(f'证据覆盖 {any_count}/{total}；当年覆盖 {current_count}/{total}')

if __name__=='__main__': main()
