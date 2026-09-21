"""Isolated synthetic regression tests. No real companies, no network access."""
import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from common import ROOT, periods_for, read, rules, write
from run_research import initialize
from score_companies import calculate
import subprocess, sys

def complete_detail(mid):
    from audit_top30 import NUMERIC,GROWTH
    d=dict(entity_scope='合成主体合并口径',time_scope='本期',limitations=[],status_context='合成事件已实施，未冒充真实事实')
    if mid in NUMERIC:
        d['measurement']=dict(value=100,unit='%',basis='合成同口径数据',calculation='报告直接披露100%')
        if mid in GROWTH: d['measurement'].update(current_period='本年同期',comparison_period='上年同期')
    return d

def fixture(path, cutoff=None):
    cutoff = cutoff or dt.date.today().isoformat()
    periods = periods_for(cutoff)
    names=path.parent/(path.name+'-input.json'); write(names,['合成测试主体'])
    initialize(path,'TEST_REGION','TEST_INDUSTRY',cutoff,companies=names)
    cid = 'synthetic-entity'
    _, items, _ = rules()
    c = {'id':cid,'name':'合成测试主体 <script>unsafe</script>','region':'TEST_REGION','industry':'TEST_INDUSTRY',
        'listing_status':'unlisted','identity_note':'合成测试，不对应真实企业', 'scope_reason':'合成分类测试',
        'scope_evidence_ids':['e-'+periods[-1]],'eligibility':'main','eligibility_reason':'合成注册地址已验证',
        'registration_verified':True,'registration_platform':'gsxt','registration_address':'合成市合成区合成路1号',
        'registration_source':'https://www.gsxt.gov.cn/index.html','registration_checked_date':cutoff}
    write(path/'candidate-pool.json',[c])
    ev=[]; logs=[]; obs=[]
    for period in periods:
        end = cutoff if period==periods[-1] else period+'-12-31'
        eid = 'e-'+period
        ev.append({'id':eid,'company_id':cid,'title':'合成报告 </script>','publisher':'测试机构',
            'url':'https://example.com/report','grade':'S1','grade_reason':'合成一手材料','published_date':end,
            'accessed_date':cutoff,'period':period,'locator':'测试章节','excerpt':'仅用于程序验证','usable':True})
        sids=[]
        for r, grade in ((1,'S1'),(2,'S2'),(3,'S3'),(4,'S4')):
            sid=f's-{period}-{r}'; sids.append(sid)
            logs.append({'id':sid,'company_id':cid,'metric_ids':[i['id'] for i in items], 'periods':[period],
                'query':f'合成查询 {period} {grade} 发散{r}', 'channel':f'synthetic-{grade}','source_grade':grade,
                'searched_date':cutoff,'round':r,'status':'executed','result_urls':['https://example.com/report'] if r==1 else [],
                'new_evidence_ids':[eid] if r==1 else [], 'result_summary':'合成测试，未实际进行企业研究'})
        for i in items:
            obs.append({'company_id':cid,'metric_id':i['id'],'period':period,'period_end':end,
                'status':'verified','fact':'合成测试事实','rationale':'测试最高档位计算',
                'decision_evidence_ids':[eid],'search_ids':sids,'search_state':'saturated',
                'search_conclusion':'合成最后两轮无新增', 'source_grade_coverage':{'S1':True,'S2':True,'S3':True,'S4':True},
                'band':i['bands'][0][0],'applicable_for_current':True,'detail':complete_detail(i['id'])})
    write(path/'evidence.json',ev);write(path/'search-log.json',logs);write(path/'observations.json',obs)
    write(path/'facility-evidence.json',[{'id':'f','company_id':cid,'name':'合成设施','region':'TEST_REGION',
        'address':'合成地址','activity':'生产','operator':'合成测试主体','state':'operating',
        'local_production_or_operation':True,'procurement_note':'仅测试','evidence_ids':['e-'+periods[-1]]}])
    (path/'universe-review.md').write_text('# 合成审计\n这是测试用的候选发现说明，覆盖不同入口并说明上市与未上市分布，仅用于校验程序，不包含任何真实企业，不作为真实研究结果。',encoding='utf-8')

class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.p=Path(self.tmp.name)/'run';fixture(self.p)
        self.periods=read(self.p/'run-config.json')['periods']
    def tearDown(self): self.tmp.cleanup()
    def mutate(self,name,fn):
        rows=read(self.p/name);fn(rows);write(self.p/name,rows)
    def test_empty_templates(self):
        for name in ('candidate-pool.json','facility-evidence.json'):
            self.assertEqual(read(ROOT/'templates'/name),[])
    def test_full_score_and_three_periods(self):
        d=calculate(self.p);c=d['main'][0]
        self.assertEqual(c['weighted_total'],100);self.assertEqual(c['raw_total'],100)
        self.assertEqual(len(c['metrics']),23);self.assertEqual(len(c['metrics'][0]['periods']),3)
        self.assertEqual(d['status'],'provisional')
    def test_weights_change_ranking_score(self):
        def downgrade(rows):
            for e in rows:e['grade']='S3'
        self.mutate('evidence.json',downgrade)
        self.assertEqual(calculate(self.p)['main'][0]['weighted_total'],75)
    def test_rd_intensity_updated_band(self):
        rubric, items, _ = rules()
        item = next(i for i in items if i['id']=='rd_intensity')
        self.assertEqual(item['bands'],[['研发占营收>15%',4],['研发占营收5%-15%',3],
                                      ['研发占营收3%-4.99%',2.5],['研发占营收<3%',1]])
        self.assertEqual(read(self.p/'run-config.json')['rule_version'],rubric['version'])
        def change(rows):
            for o in rows:
                if o['metric_id']=='rd_intensity':o.update(band='研发占营收3%-4.99%',fact='合成测试研发占营收3.49%')
        self.mutate('observations.json',change)
        c=calculate(self.p)['main'][0]
        self.assertEqual(c['raw_total'],98.5)
        self.assertEqual(c['weighted_total'],98.5)
    def test_rd_intensity_missing_has_no_default_points(self):
        def change(rows):
            for o in rows:
                if o['metric_id']=='rd_intensity':
                    o.update(status='unverified',band=None,decision_evidence_ids=[],applicable_for_current=False)
        self.mutate('observations.json',change)
        c=calculate(self.p)['main'][0]
        self.assertEqual(c['raw_total'],96)
        self.assertEqual(c['weighted_total'],96)
        self.assertEqual(c['raw_unrated_count'],1)
    def test_rd_growth_user_default(self):
        item=next(i for i in rules()[1] if i['no']==3)
        self.assertIn(['查不到',2],item['bands'])
        self.assertEqual(item['max'],5)
    def test_weakest_required_source(self):
        def add(rows):
            e=copy.deepcopy(rows[-1]);e['id']='e-weak';e['grade']='S3';rows.append(e)
        self.mutate('evidence.json',add)
        def change(rows):
            for o in rows:
                if o['period']==self.periods[-1]:o['decision_evidence_ids'].append('e-weak')
        self.mutate('observations.json',change)
        self.assertEqual(calculate(self.p)['main'][0]['weighted_total'],75)
    def test_missing_period_fails(self):
        self.mutate('observations.json',lambda rows:rows.pop())
        with self.assertRaises(ValueError):calculate(self.p)
    def test_future_publication_fails(self):
        future=(dt.date.today()+dt.timedelta(days=1)).isoformat()
        self.mutate('evidence.json',lambda rows:rows[0].update(published_date=future))
        with self.assertRaises(ValueError):calculate(self.p)
    def test_registration_not_required(self):
        self.mutate('candidate-pool.json',lambda rows:rows[0].update(registration_verified=False))
        self.assertEqual(calculate(self.p)['main'][0]['weighted_total'],100)
    def test_no_new_run_overwrite(self):
        with self.assertRaises(ValueError):initialize(self.p,'x','y',dt.date.today().isoformat())
    def test_fake_saturation_fails(self):
        self.mutate('search-log.json',lambda rows:rows[-1].update(new_evidence_ids=['e-'+self.periods[-1]]))
        with self.assertRaises(ValueError):calculate(self.p)
    def test_s1_s4_coverage_required(self):
        def change(rows):
            for o in rows:
                if o['period']==self.periods[-1]:o['source_grade_coverage']={'S1':True,'S2':True,'S3':True,'S4':False}
        self.mutate('observations.json',change)
        with self.assertRaises(ValueError):calculate(self.p)
    def test_unverified_earns_md_default(self):
        def change(rows):
            for o in rows:
                if o['metric_id']=='revenue_growth':o.update(status='unverified',band=None,decision_evidence_ids=[],applicable_for_current=False)
        self.mutate('observations.json',change)
        c=calculate(self.p)['main'][0]
        self.assertEqual(c['weighted_total'],97);self.assertEqual(c['raw_total'],97)
        self.assertEqual(c['default_total'],2);self.assertEqual(c['default_count'],1)
        self.assertEqual(c['verified_weight'],95)
        self.assertIsNone(c['metrics'][0]['periods'][-1]['source_weight'])
    def test_blocked_receives_no_default(self):
        def change(rows):
            for o in rows:
                if o['metric_id']=='revenue_growth':
                    o.update(status='blocked',band=None,decision_evidence_ids=[],applicable_for_current=False)
        self.mutate('observations.json',change)
        c=calculate(self.p)['main'][0]
        self.assertEqual(c['weighted_total'],95)
        self.assertEqual(c['default_total'],0)

    def test_unverified_policy_floor_uses_wu_default(self):
        # 政策/资质类指标（国家级资质等）地板档为'无'=0；未证实（已饱和检索）时应取'无'=0 缺省，
        # 而不是把整维度静默丢成 unrated（这正是电子版比生科版少维度的根因）。
        def change(rows):
            for o in rows:
                if o['metric_id']=='national_qualification':
                    o.update(status='unverified',band=None,decision_evidence_ids=[],applicable_for_current=False)
        self.mutate('observations.json',change)
        c=calculate(self.p)['main'][0]
        self.assertEqual(c['weighted_total'],96)
        self.assertEqual(c['raw_total'],96)
        self.assertEqual(c['default_total'],0)
        self.assertEqual(c['default_count'],1)
        self.assertEqual(c['raw_unrated_count'],0)
        m=c['metrics'][19]
        self.assertEqual(m['raw_score'],0)
        self.assertEqual(m['score_basis'],'default')
        self.assertEqual(m['default_band'],'无')

    def test_unfinished_cannot_claim_default(self):
        def change(rows):
            for o in rows:
                if o['metric_id']=='revenue_growth':
                    o.update(status='unverified',band=None,decision_evidence_ids=[],search_state='pending')
        self.mutate('observations.json',change)
        with self.assertRaises(ValueError): calculate(self.p)

    def test_default_is_not_discounted_by_source(self):
        def change(rows):
            for o in rows:
                if o['metric_id']=='revenue_growth':
                    o.update(status='unverified',band=None,decision_evidence_ids=[],applicable_for_current=False)
        self.mutate('observations.json',change)
        self.mutate('evidence.json',lambda rows:[e.update(grade='S3') for e in rows])
        c=calculate(self.p)['main'][0]
        self.assertEqual(c['weighted_total'],73.25)
        self.assertEqual(c['evidence_total'],71.25)
        self.assertEqual(c['default_total'],2)

    def test_historical_fallback(self):
        def change(rows):
            for o in rows:
                if o['period']==self.periods[-1]:o.update(status='unverified',band=None,decision_evidence_ids=[],applicable_for_current=False)
        self.mutate('observations.json',change)
        c=calculate(self.p)['main'][0]
        self.assertEqual(c['metrics'][0]['selected_period'],self.periods[1]);self.assertEqual(c['current_verified_weight'],0)
    def test_undated_historical_fails(self):
        self.mutate('evidence.json',lambda rows:rows[0].update(published_date='undated'))
        with self.assertRaises(ValueError):calculate(self.p)
    def test_html_safe_embedded_json(self):
        # 用真正在用的生成器渲染，验证 HTML 注入被转义（XSS 回归）
        write(self.p/'scores.json', calculate(self.p))
        subprocess.run([sys.executable, str(ROOT/'scripts'/'gen_company_html.py'),
                        '--run', str(self.p), '--draft'], check=True, cwd=str(ROOT/'scripts'))
        out=(self.p/'company-top50.html').read_text(encoding='utf-8')
        self.assertNotIn('<script>unsafe</script>', out)
        self.assertNotIn('合成报告 </script>', out)
        self.assertNotIn('__DATA__', out)
        self.assertIn('&lt;script&gt;unsafe', out)  # 注入内容被转义，而非原样输出
    def test_duplicate_legal_name_fails(self):
        def change(rows):
            other=copy.deepcopy(rows[0]);other['id']='different-id';rows.append(other)
        self.mutate('candidate-pool.json',change)
        with self.assertRaises(ValueError):calculate(self.p)
    def test_obsolete_evidence_not_scored_currently(self):
        self.mutate('observations.json',lambda rows:[o.update(applicable_for_current=False) for o in rows])
        self.assertEqual(calculate(self.p)['main'][0]['weighted_total'],0)
    def test_skill_structure(self):
        import re
        content=(ROOT/'SKILL.md').read_text(encoding='utf-8')
        self.assertTrue(content.startswith('---\nname: company-top50-skill\ndescription: '))
        for link in re.findall(r'\]\(([^)]+)\)',content):
            self.assertTrue((ROOT/link).is_file(),link)
        self.assertEqual(len(rules()[1]),23)

    def test_year_rollover(self):
        self.assertEqual(periods_for('2030-01-01'),('2028','2029','2030YTD'))
        self.assertEqual(periods_for('2031-01-01'),('2029','2030','2031YTD'))

    def test_future_year_run_with_simulated_clock(self):
        from unittest.mock import patch
        class Clock(dt.date):
            @classmethod
            def today(cls): return cls(2030,9,9)
        p=Path(self.tmp.name)/'future-run'
        with patch('datetime.date',Clock):
            fixture(p)
            d=calculate(p)
            self.assertEqual(d['config']['periods'],['2028','2029','2030YTD'])
            self.assertEqual(d['main'][0]['weighted_total'],100)

    def test_historical_run_stays_fixed(self):
        year=dt.date.today().year-3
        p=Path(self.tmp.name)/'historical'
        fixture(p,f'{year}-09-09')
        self.assertEqual(calculate(p)['config']['periods'],[str(year-2),str(year-1),f'{year}YTD'])

    def test_independent_sources_choose_best_not_average(self):
        def add(rows):
            e=copy.deepcopy(rows[-1]);e.update(id='e-other',grade='S3');rows.append(e)
        self.mutate('evidence.json',add)
        def change(rows):
            for o in rows:
                if o['period']==self.periods[-1]:
                    original=o['decision_evidence_ids'][0]
                    o['decision_evidence_ids']=[original,'e-other']
                    o['decision_evidence_groups']=[[original],['e-other']]
        self.mutate('observations.json',change)
        c=calculate(self.p)['main'][0]
        self.assertEqual(c['weighted_total'],100)
        self.assertEqual(c['metrics'][0]['periods'][-1]['selected_evidence_group'],['e-'+self.periods[-1]])

    def add_s4(self, status=None):
        rows=read(self.p/'evidence.json');e=copy.deepcopy(rows[-1]);e.update(id='s4-clue',grade='S4',usable=False)
        if status:
            e.update(followup_search_ids=['follow-1','follow-2'],followup_status=status,
                     followup_conclusion='隔离合成补查结果，仅用于测试')
            logs=read(self.p/'search-log.json')
            for r in (1,2):
                s=copy.deepcopy(logs[-1]);s.update(id=f'follow-{r}',round=r+3,query=f'测试官网原文补查{r}',
                    source_grade='S1',online=True,target_grades=['S1','S2','S3'],new_evidence_ids=[])
                if status=='upgraded' and r==1:s['new_evidence_ids']=['e-'+self.periods[-1]]
                if status=='blocked':s['status']='blocked'
                logs.append(s)
            write(self.p/'search-log.json',logs)
            if status=='upgraded':e['replacement_evidence_ids']=['e-'+self.periods[-1]]
        rows.append(e);write(self.p/'evidence.json',rows)

    def test_s4_without_online_followup_fails(self):
        self.add_s4()
        with self.assertRaises(ValueError):calculate(self.p)

    def test_s4_upgraded_to_s1(self):
        self.add_s4('upgraded')
        d=calculate(self.p)
        self.assertEqual(d['main'][0]['weighted_total'],100)
        self.assertEqual(d['evidence'][-1]['replacement_evidence_ids'],['e-'+self.periods[-1]])

    def test_s4_fake_offline_followup_fails(self):
        self.add_s4('exhausted')
        self.mutate('search-log.json',lambda rows:rows[-1].update(online=False))
        with self.assertRaises(ValueError):calculate(self.p)

    def test_s4_unverified_after_exhaustion_no_bonus(self):
        self.add_s4('exhausted')
        self.assertEqual(calculate(self.p)['main'][0]['weighted_total'],100)

    def test_s4_blocked_remains_warning(self):
        self.add_s4('blocked')
        self.assertTrue(any('S4联网补查受阻' in w for w in calculate(self.p)['warnings']))

    def test_s4_verified_after_followup_weight(self):
        self.add_s4('exhausted')
        self.mutate('evidence.json',lambda rows:rows[-1].update(usable=True))
        def change(rows):
            for o in rows:
                if o['period']==self.periods[-1]:o['decision_evidence_ids']=['s4-clue']
        self.mutate('observations.json',change)
        with self.assertRaises(ValueError): calculate(self.p)

    def test_current_s2_beats_previous_s1(self):
        self.mutate('evidence.json',lambda rows:rows[-1].update(grade='S2'))
        c=calculate(self.p)['main'][0]
        self.assertEqual(c['weighted_total'],90)
        self.assertTrue(all(m['selected_period']==self.periods[-1] for m in c['metrics']))

    def test_sufficient_one_read_can_stop(self):
        def change(rows):
            for o in rows:
                o['search_state']='sufficient';o['search_ids']=o['search_ids'][:1]
        self.mutate('observations.json',change)
        self.assertEqual(calculate(self.p)['main'][0]['weighted_total'],100)

    def test_current_coverage_denominator(self):
        d=calculate(self.p)
        self.assertFalse(any('证据覆盖率仅' in w for w in d['warnings']))

    def test_pending_has_no_default(self):
        def change(rows):
            for o in rows:
                o.update(status='pending',search_state='pending',search_ids=[],band=None,decision_evidence_ids=[])
        self.mutate('observations.json',change)
        c=calculate(self.p)['main'][0]
        self.assertEqual(c['default_total'],0)
        self.assertEqual(c['raw_unrated_count'],23)

    def test_200_to_40_to_30_pipeline(self):
        from ingest_raw import ingest
        from plan_search import generate
        from prescreen import MODES
        root=Path(self.tmp.name)/'pipeline';names=Path(self.tmp.name)/'names.json'
        write(names,[{'name':f'合成企业{i:03d}','segment':'合成赛道'} for i in range(200)])
        cfg=initialize(root,'合成地区','合成行业',dt.date.today().isoformat(),companies=names)
        self.assertEqual(cfg['top_n'],30);self.assertEqual(cfg['candidate_cap'],40)
        self.assertEqual(generate(root)['metrics'],10)
        config=read(root/'run-config.json');period=config['periods'][-1];day=config['as_of']
        _,items,_=rules();coarse=set(MODES['full'])
        def record(item):
            return dict(id=item['id'],period=period,period_end=day,status='verified',detail=complete_detail(item['id']),
                fact='合成事实，仅用于隔离测试',rationale='测试最高档',band=item['bands'][0][0],
                applicable_for_current=True,search_state='sufficient',search_conclusion='合成单次命中',
                decision_evidence_ids=['e'],sources=[dict(id='e',period=period,url='https://example.com/report',
                    grade='S1',title='合成报告',publisher='合成企业',locator='测试页',excerpt='合成事实',
                    grade_reason='合成来源',published_date=day,accessed_date=day,usable=True)],
                searches=[dict(id='l',status='executed',query='合成阅读',channel='测试',
                    result_summary='合成命中',source_grade='S1',round=1,searched_date=day,
                    result_urls=['https://example.com/report'],new_evidence_ids=['e'],online=True)])
        pool=read(root/'candidate-pool.json')
        raw=[dict(company_id=c['id'],metrics=[record(i) for i in items if i['id'] in coarse]) for c in pool]
        write(root/'raw'/'batch1.json',raw);ingest(root)
        self.assertEqual(read(root/'facility-evidence.json'),[])
        def command(script,*extra):
            subprocess.run([sys.executable,str(ROOT/'scripts'/script),'--run',str(root),*extra],check=True,stdout=subprocess.DEVNULL)
        command('prescreen.py','--apply')
        pool=read(root/'candidate-pool.json'); chosen={c['id'] for c in pool if c['eligibility']=='main'}
        self.assertEqual(len(chosen),40)
        self.assertEqual(sum(c['eligibility']=='prescreened_out' for c in pool),160)
        self.assertEqual(pool[0]['prescreen_score'],44)
        self.assertEqual(generate(root)['companies'],40)
        for company in raw:
            if company['company_id'] in chosen:
                company['metrics'] += [record(i) for i in items if i['id'] not in coarse]
        write(root/'raw'/'batch1.json',raw);ingest(root)
        before=read(root/'observations.json');ingest(root)
        self.assertEqual(before,read(root/'observations.json'))
        d=calculate(root)
        self.assertEqual(len(d['main']),30);self.assertEqual(len(d['overflow']),10)
        self.assertEqual(len(d['prescreened_out']),160)
        self.assertEqual(d['main'][0]['weighted_total'],100)
        self.assertEqual(d['warnings'],[])
        command('s1_gapfill.py');self.assertEqual(read(root/'s1-gap-plan.json')['total'],40*23)
        command('gen_company_html.py')
        html=(root/'company-top50.html').read_text(encoding='utf-8')
        self.assertIn('当年证据 690/690',html)
        self.assertNotIn('合成企业199',html)
        self.assertNotIn('合成企业030',html)
        self.assertNotIn('粗排',html)
        self.assertNotIn('精采备选',html)
        self.assertEqual(d['quality_review']['status'],'complete')
        self.assertNotIn('注册地均在',html);self.assertNotIn('推定',html)
        # Legacy compact evidence must not silently become a scored/default record.
        broken=raw[0]['metrics'][0];del broken['sources'][0]['published_date']
        write(root/'raw'/'batch1.json',raw)
        with self.assertRaises(ValueError):ingest(root)

    def test_low_disclosure_opportunity_not_lost(self):
        from prescreen import select_shortlist,MODES
        _,items,_=rules();imap={i['id']:i for i in items};pool=[];obs=[]
        for n in range(50):
            cid=f'C{n:03d}';pool.append(dict(id=cid,eligibility='prescreened',listing_status='listed'))
            for mid in MODES['full']:
                obs.append(dict(company_id=cid,metric_id=mid,period=self.periods[-1],status='verified',
                    applicable_for_current=True,raw_score=imap[mid]['max'],weighted_score=imap[mid]['max'],source_weight=1))
        pool.append(dict(id='private',eligibility='prescreened',listing_status='unlisted'))
        for mid in ('capacity','commercialization'):
            obs.append(dict(company_id='private',metric_id=mid,period=self.periods[-1],status='verified',
                applicable_for_current=True,raw_score=imap[mid]['max'],weighted_score=imap[mid]['max'],source_weight=1))
        selected,review=select_shortlist(pool,obs,items,self.periods)
        self.assertEqual(selected['private'],'opportunity');self.assertEqual(len(selected),40)
        for c in pool:c['listing_status']='unlisted'
        self.assertEqual(select_shortlist(pool,obs,items,self.periods)[0],selected)
        obs.pop() # One isolated claim cannot receive a reserved opportunity slot.
        self.assertNotIn('private',select_shortlist(pool,obs,items,self.periods)[0])

    def single_company_quality(self):
        d=calculate(self.p);d['config']['top_n']=1
        from audit_top30 import audit
        return d,audit

    def test_quality_requires_all_selected_dimensions(self):
        d,audit=self.single_company_quality()
        self.assertEqual(audit(d)['status'],'complete')
        del d['main'][0]['metrics'][0]['periods'][-1]['detail']
        result=audit(d)
        self.assertEqual(result['status'],'incomplete');self.assertEqual(result['completed_cells'],22)

    def test_quality_checks_numeric_comparison(self):
        d,audit=self.single_company_quality()
        measure=d['main'][0]['metrics'][0]['periods'][-1]['detail']['measurement']
        measure.update(current_value=120,baseline_value=100,value=100)
        self.assertTrue(any('计算不一致' in e['reason'] for e in audit(d)['issues']))
        measure['value']=20
        self.assertEqual(audit(d)['status'],'complete')

    def test_quality_preserves_qualitative_band(self):
        d,audit=self.single_company_quality()
        o=d['main'][0]['metrics'][1]['periods'][-1]
        o['band']='基本稳定';o['detail']['measurement']=dict(method='qualitative',basis='合成正式定性披露',calculation='报告明确说明资本开支稳定')
        self.assertEqual(audit(d)['status'],'complete')
        o['band']='>50%增长'
        self.assertEqual(audit(d)['status'],'incomplete')

    def test_quality_fallback_requires_current_search(self):
        d,audit=self.single_company_quality()
        m=d['main'][0]['metrics'][0];m['selected_period']=self.periods[-2];m['historical_fallback']=True
        o=m['periods'][-2];o['detail']['fallback_reason']='已补查当年，暂未披露同口径值；去年数据仍适用'
        self.assertEqual(audit(d)['status'],'complete')
        m['periods'][-1]['search_ids']=[]
        self.assertTrue(any('实际补查' in e['reason'] for e in audit(d)['issues']))

    def test_generator_refuses_stale_pass_and_draft_mode(self):
        d=calculate(self.p);d['quality_review']['status']='complete';write(self.p/'scores.json',d)
        cmd=[sys.executable,str(ROOT/'scripts'/'gen_company_html.py'),'--run',str(self.p)]
        result=subprocess.run(cmd,capture_output=True,text=True)
        self.assertNotEqual(result.returncode,0)
        subprocess.run(cmd+['--draft'],check=True,stdout=subprocess.DEVNULL)
        html=(self.p/'company-top50.html').read_text(encoding='utf-8')
        self.assertNotIn('【未完成草稿】',html)
        self.assertIn('证据',html)

if __name__ == '__main__':unittest.main(verbosity=2)
