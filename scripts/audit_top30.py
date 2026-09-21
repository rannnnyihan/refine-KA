"""Check final evidence dossiers. Structural completeness is not factual verification."""
import argparse
import math
from pathlib import Path
from common import read,write,nonempty

GROWTH={'revenue_growth','capex_growth','rd_growth','export_growth','hiring_growth','track_growth'}
NUMERIC=GROWTH|{'rd_intensity'}
QUALITATIVE={'capex_growth':{'基本稳定','明显缩减投资'},'hiring_growth':{'明显增长','稳定招聘','大幅缩招或停止招聘'},'track_growth':{'成熟行业','衰退行业'}}


def audit(scores):
    current=scores['config']['periods'][-1];issues=[];complete=0
    def issue(cid,mid,message): issues.append(dict(company_id=cid,metric_id=mid,reason=message))
    for c in scores['main']:
        for m in c['metrics']:
            before=len(issues);cid=c['id'];mid=m['id']
            o=next(x for x in m['periods'] if x['period']==m['selected_period'])
            if m['score_basis']!='evidence':
                issue(cid,mid,'无可定档证据；缺省分或未定档不算完整');continue
            detail=o.get('detail',{})
            for field in ('entity_scope','time_scope'):
                if not nonempty(detail.get(field)): issue(cid,mid,'缺少'+field)
            if not isinstance(detail.get('limitations'),list): issue(cid,mid,'须记录limitations数组，可为空')
            qualitative=detail.get('measurement',{}).get('method')=='qualitative'
            if qualitative:
                if o.get('band') not in QUALITATIVE.get(mid,set()): issue(cid,mid,'此档位不能使用定性数值例外')
                for field in ('basis','calculation'):
                    if not nonempty(detail.get('measurement',{}).get(field)): issue(cid,mid,'定性档位缺少'+field)
                if not nonempty(detail.get('status_context')): issue(cid,mid,'定性档位缺少实际状态/比较说明')
            elif mid in NUMERIC:
                measure=detail.get('measurement',{})
                value=measure.get('value')
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value):
                    issue(cid,mid,'缺少合法数值')
                for field in ('unit','basis','calculation'):
                    if not nonempty(measure.get(field)): issue(cid,mid,'量化依据缺少'+field)
                if mid in GROWTH:
                    for field in ('current_period','comparison_period'):
                        if not nonempty(measure.get(field)): issue(cid,mid,'同比缺少'+field)
                    if measure.get('current_period')==measure.get('comparison_period'): issue(cid,mid,'同比期间不可相同')
                    if 'current_value' in measure or 'baseline_value' in measure:
                        x=measure.get('current_value');b=measure.get('baseline_value')
                        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (x,b)) or b<=0:
                            issue(cid,mid,'同比原值/基数无效；非正基数不能套普通增长率')
                        elif measure.get('unit')=='%' and isinstance(value,(int,float)) and abs((x/b-1)*100-value)>0.1:
                            issue(cid,mid,'同比结果与原值计算不一致')
            elif not nonempty(detail.get('status_context')):
                issue(cid,mid,'缺少事件进展/资质有效性/市场口径说明')
            if m['historical_fallback']:
                if not nonempty(detail.get('fallback_reason')): issue(cid,mid,'历史回退缺少原因及仍适用说明')
                latest=next(x for x in m['periods'] if x['period']==current)
                logs={s['id']:s for s in scores['search_log']}
                checked={logs[s]['source_grade'] for s in latest.get('search_ids',[]) if s in logs and logs[s]['status']=='executed'}
                if not {'S1','S2','S3'}<=checked: issue(cid,mid,'历史回退前尚未完成当年S1/S2/S3实际补查')
            if len(issues)==before: complete+=1
    total=scores['config']['top_n']*23
    if len(scores['main'])!=scores['config']['top_n']:
        issue('', '', '主榜数量不足目标')
    return dict(status='complete' if not issues and complete==total else 'incomplete',
                completed_cells=complete,required_cells=total,issues=issues)


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--run',required=True);args=ap.parse_args();run=Path(args.run)
    result=audit(read(run/'scores.json'));write(run/'top30-quality.json',result)
    print(f"Top30信息完整度：{result['completed_cells']}/{result['required_cells']}；{result['status']}")
    if result['status']!='complete': raise SystemExit(1)

if __name__=='__main__': main()
