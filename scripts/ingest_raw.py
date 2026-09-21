"""Normalize actual agent-collected raw records. No browsing or invented audit data."""
import argparse
from pathlib import Path
from common import read, write, rules


def ingest(path):
    run = Path(path); cfg = read(run/'run-config.json'); rawdir = run/'raw'
    periods = cfg['periods']; _, items, _ = rules()
    pool = read(run/'candidate-pool.json'); known = {c['id'] for c in pool}
    specific = {}; lists = {}; shared = {}
    for f in sorted(rawdir.glob('batch*.json')):
        for company in read(f):
            cid = company['company_id']
            if cid not in known: raise ValueError(f'未知主体 {cid}')
            for r in company['metrics']:
                key = (cid, r.get('id', r.get('metric_id')), r['period'])
                if key in specific: raise ValueError(f'重复企业记录 {key}；请更新原记录')
                specific[key] = r
    if (rawdir/'lists.json').exists():
        for r in read(rawdir/'lists.json'):
            key = (r['company_id'], r.get('id', r.get('metric_id')), r['period'])
            if key in lists or key[0] not in known: raise ValueError(f'重复/未知名单记录 {key}')
            lists[key] = r
    if (rawdir/'shared.json').exists():
        for r in read(rawdir/'shared.json'):
            mid = r.get('id', r.get('metric_id'))
            if mid != 'track_growth': raise ValueError('共享层仅接受赛道增长率')
            key = (r['segment'], mid, r['period'])
            if key in shared: raise ValueError(f'重复共享记录 {key}')
            shared[key] = r
    valid = {i['id'] for i in items}
    for key in list(specific) + list(lists) + list(shared):
        if key[1] not in valid or key[2] not in periods: raise ValueError(f'无效指标/时期 {key}')
    evidence=[]; logs=[]; observations=[]
    for c in pool:
        if c['eligibility'] in ('excluded','reserve'): continue
        cid = c['id']
        for item in items:
            mid=item['id']
            for period in periods:
                r = specific.get((cid,mid,period)) or lists.get((cid,mid,period)) or shared.get((c['scope_reason'],mid,period))
                prefix=f'{cid}-{mid}-{period}'
                end=cfg['as_of'] if period==periods[-1] else period+'-12-31'
                o=dict(company_id=cid, metric_id=mid, period=period, period_end=end,
                       status='pending', fact='尚未取得证据', rationale='待采证；不计缺省分',
                       search_state='pending', search_conclusion='尚未完成检索', search_ids=[])
                if r:
                    sources=r.get('sources',[]); searches=r.get('searches',[])
                    emap={e['id']:prefix+'-E-'+e['id'] for e in sources}
                    smap={s['id']:prefix+'-L-'+s['id'] for s in searches}
                    if len(emap)!=len(sources) or len(smap)!=len(searches): raise ValueError(f'{prefix} 局部ID重复')
                    for e in sources:
                        for field in ('url','grade','title','publisher','locator','excerpt','grade_reason','published_date','accessed_date','period','usable'):
                            if field not in e: raise ValueError(f'{prefix} 来源缺少 {field}；不得推定日期或核验状态')
                        ev=dict(e,id=emap[e['id']],company_id=cid)
                        if 'followup_search_ids' in e: ev['followup_search_ids']=[smap[x] for x in e['followup_search_ids']]
                        if 'replacement_evidence_ids' in e: ev['replacement_evidence_ids']=[emap[x] for x in e['replacement_evidence_ids']]
                        evidence.append(ev)
                    for s in searches:
                        log=dict(s,id=smap[s['id']],company_id=cid,metric_ids=[mid],periods=[period])
                        log['new_evidence_ids']=[emap[x] for x in s.get('new_evidence_ids',[])]
                        logs.append(log)
                    for key in ('status','fact','rationale','period_end','search_state','search_conclusion','band','applicable_for_current','source_grade_coverage','proxy_method','detail'):
                        if key in r: o[key]=r[key]
                    o['search_ids']=list(smap.values())
                    o['decision_evidence_ids']=[emap[x] for x in r.get('decision_evidence_ids',[])]
                    if 'decision_evidence_groups' in r:
                        o['decision_evidence_groups']=[[emap[x] for x in group] for group in r['decision_evidence_groups']]
                observations.append(o)
    write(run/'evidence.json',evidence); write(run/'search-log.json',logs)
    write(run/'observations.json',observations)
    # Scope comes from the supplied list; do not generate facilities or registration evidence.
    write(run/'facility-evidence.json',[])
    print(f'来源 {len(evidence)}；真实日志 {len(logs)}；指标记录 {len(observations)}（含待查）')

if __name__=='__main__':
    ap=argparse.ArgumentParser(); ap.add_argument('--run',required=True)
    ingest(ap.parse_args().run)
