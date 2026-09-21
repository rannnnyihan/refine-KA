"""Validate evidence-backed band decisions; compute transparent source-weighted scores."""
import argparse
import datetime as dt
from pathlib import Path
from common import periods_for, date, http_url, nonempty, read, rule_hash, rules, unique, write

def require(condition, message):
    if not condition:
        raise ValueError(message)

def calculate(path, stage="final"):
    p = Path(path); cfg = read(p/'run-config.json')
    cutoff = date(cfg['as_of'])
    PERIODS = periods_for(cfg['as_of'])
    require(isinstance(cfg.get('top_n'), int) and cfg['top_n'] >= 1 and tuple(cfg['periods']) == PERIODS,
            'top_n须为不小于1的整数（由用户指定，默认30），且三期必须齐全')
    TOP_N = cfg['top_n']
    require(3 <= cutoff.year and cutoff <= dt.date.today(), '无效截止日')
    rubric, items, weights = rules(); item_map = {i['id']:i for i in items}
    companies = unique(read(p/'candidate-pool.json'))
    require(bool(companies), '候选池为空，请先实际采证')
    names = [c.get('name','').replace(' ', '').replace('（','(').replace('）',')') for c in companies.values()]
    require(len(names) == len(set(names)), '同一法人名称不能用不同ID重复计入')
    credits = [c['credit_code'] for c in companies.values() if c.get('credit_code')]
    require(len(credits) == len(set(credits)), '统一社会信用代码重复，应合并厂区')
    evidence = unique(read(p/'evidence.json')); searches = unique(read(p/'search-log.json'))
    facilities = unique(read(p/'facility-evidence.json'))
    for e in evidence.values():
        require(e.get('company_id') in companies, f"证据主体未知: {e['id']}")
        require(e.get('grade') in weights and http_url(e.get('url')), f"证据等级/链接无效: {e['id']}")
        for field in ('title','publisher','locator','excerpt','grade_reason','published_date','accessed_date','period'):
            require(nonempty(e.get(field)), f"证据缺少{field}: {e['id']}")
        if e['grade'] == 'S4':
            require(e.get('usable') is False, 'S4仅作线索，不允许直接定档')
        if e['published_date'] == 'undated':
            require(e['period'] == PERIODS[-1] and date(e['accessed_date']) <= cutoff, '无日期页面不得回填历史快照')
        if e['published_date'] != 'undated':
            require(date(e['published_date']) <= cutoff, '不得采用截止日之后的披露')
        require(date(e['accessed_date']) <= dt.date.today(), '抓取日期在未来')
        require(e['period'] in (*PERIODS, 'comparison_base'), '证据期无效')
    for s in searches.values():
        require(s.get('company_id') in companies and s.get('status') in ('executed','blocked'), '搜索日志主体/状态无效')
        require(nonempty(s.get('query')) and nonempty(s.get('channel')) and nonempty(s.get('result_summary')), '日志缺少查询/渠道/结果说明')
        require(s.get('source_grade') in ('S1','S2','S3','S4'), '搜索日志须标注source_grade（S1/S2/S3/S4）')
        require(date(s['searched_date']) <= dt.date.today(), '搜索日期在未来')
        require(isinstance(s.get('round'), int) and s['round'] >= 1, '检索轮次无效')
        require(s.get('metric_ids') and set(s['metric_ids']) <= set(item_map), '日志缺少合法维度')
        require(s.get('periods') and set(s['periods']) <= set(PERIODS), '日志期间无效')
        require(all(http_url(u) for u in s.get('result_urls', [])), '搜索结果URL无效')
        require(set(s.get('new_evidence_ids', [])) <= set(evidence), '搜索日志引用未知证据')
        require(all(evidence[e]['company_id'] == s['company_id'] for e in s.get('new_evidence_ids', [])), '搜索日志证据跨主体')

    followup_warnings = []
    for e in evidence.values():
        if e['grade'] != 'S4':
            continue
        ids = e.get('followup_search_ids', [])
        require(bool(ids) and set(ids) <= set(searches), f"S4必须联网补查并记录日志: {e['id']}")
        logs = [searches[i] for i in ids]
        require(all(s['company_id'] == e['company_id'] and s.get('online') is True for s in logs), 'S4补查必须是同主体的实际联网检索或联网受阻记录')
        require(all(date(s['searched_date']) >= date(e['accessed_date']) for s in logs), '补查时间不能早于发现S4的时间')
        if e['period'] != 'comparison_base':
            require(all(e['period'] in s['periods'] for s in logs), 'S4补查期间不匹配')
        require(all(s.get('target_grades') and set(s['target_grades']) <= {'S1','S2','S3'} for s in logs), '补查必须指向S1/S2/S3原始或可信来源')
        status = e.get('followup_status')
        require(status in ('upgraded','exhausted','blocked'), 'S4必须记录补查结论')
        require(nonempty(e.get('followup_conclusion')), 'S4缺少补查说明')
        if status == 'upgraded':
            replacement = e.get('replacement_evidence_ids', [])
            require(bool(replacement) and set(replacement) <= set(evidence), '升级来源不存在')
            require(all(evidence[r]['company_id'] == e['company_id'] and evidence[r]['grade'] in ('S1','S2','S3') and evidence[r]['usable'] is True and evidence[r]['period'] == e['period'] for r in replacement), '升级来源需同主体、同期间且已核实')
            discovered = {i for s in logs if s['status']=='executed' for i in s.get('new_evidence_ids', [])}
            require(set(replacement) <= discovered, '升级来源必须出现在实际补查结果中')
            require(e['usable'] is False, '升级后原S4保留为线索，评分改用找到的高等级证据')
        elif status == 'exhausted':
            require(all(s['status']=='executed' for s in logs), '补查受阻不能宣称查尽')
            require({'S1','S2','S3'} <= {g for s in logs for g in s['target_grades']}, '未升级时需扩展S1/S2/S3入口')
            rounds = sorted({s['round'] for s in logs})
            require(len(rounds)>=2 and rounds[-1] == rounds[-2]+1, 'S4补查需连续两轮无新增才结束')
            tail = [s for s in logs if s['round'] in rounds[-2:]]
            require(all(not s.get('new_evidence_ids') for s in tail) and len({(s['query'],s['channel']) for s in tail})>=2, 'S4最后两轮须更换查询或入口且无新增')
        else:
            require(e['usable'] is False and any(s['status']=='blocked' for s in logs), 'S4补查受阻不可作为已核实评分证据')
            followup_warnings.append(f"{e['id']}: S4联网补查受阻，未完成来源升级核验")

    def refs(ids, cid):
        require(bool(ids) and set(ids) <= set(evidence), f'缺少有效证据: {cid}')
        require(all(evidence[e]['company_id'] == cid for e in ids), '不能挪用另一主体的证据')
        require(all(evidence[e].get('usable') is True for e in ids), '未核实/仅转载线索不能用于定档或入围')

    for f in facilities.values():
        require(f.get('company_id') in companies, '设施主体未知')
        for field in ('name','region','address','activity','operator','state','procurement_note'):
            require(nonempty(f.get(field)), f'设施缺少{field}')
        refs(f.get('evidence_ids', []), f['company_id'])
    known_keys = set(); observations = {}
    for o in read(p/'observations.json'):
        cid, mid, period = o['company_id'], o['metric_id'], o['period']
        key = (cid, mid, period)
        require(cid in companies and mid in item_map and period in PERIODS and key not in known_keys, f'非法或重复指标记录: {key}')
        known_keys.add(key)
        require(o.get('status') in ('verified','unverified','blocked','rule_gap','pending'), '指标状态无效')
        for field in ('fact','rationale','period_end','search_state','search_conclusion'):
            require(nonempty(o.get(field)), f'{key} 缺少 {field}')
        end = date(o['period_end']); limit = cutoff if period == PERIODS[-1] else date(period+'-12-31')
        require(end.year == int(period[:4]) and end <= limit, f'{key} 数据覆盖日期无效')
        sids = o.get('search_ids', [])
        require((bool(sids) or o['status'] == 'pending') and set(sids) <= set(searches), f'{key} 缺少真实检索日志')
        logs = [searches[s] for s in sids]
        require(all(s['company_id'] == cid and mid in s['metric_ids'] and period in s['periods'] for s in logs), '查询与主体/维度/期间不匹配')
        require(o['search_state'] in ('saturated','blocked','sufficient','pending'), '检索状态无效')
        if o['search_state'] == 'saturated':
            require(all(s['status'] == 'executed' for s in logs), '受阻查询不能宣称饱和')
            rounds = sorted({s['round'] for s in logs})
            require(len(rounds) >= 2 and rounds[-1] == rounds[-2]+1, '需要连续两轮扩展无新增证据')
            tail = [s for s in logs if s['round'] in rounds[-2:]]
            require(all(not s.get('new_evidence_ids') for s in tail), '最后两轮仍有新证据，应继续追查')
            queries = {(s['query'].strip(), s['channel'].strip()) for s in tail}
            require(len(queries) >= 2, '重复查询不能冒充两轮发散')
            # S1-S4四级来源覆盖校验
            coverage = o.get('source_grade_coverage', {})
            require(set(coverage.keys()) == {'S1','S2','S3','S4'}, f'{key} saturated须记录S1-S4四个等级覆盖状态')
            require(all(v is True for v in coverage.values()), f'{key} saturated须S1-S4四个等级均有检索日志')
            require({'S1','S2','S3','S4'} <= {s['source_grade'] for s in logs}, '缺省分须有四级真实日志')
        elif o['search_state'] == 'sufficient':
            require(o['status'] in ('verified','rule_gap') and all(s['status']=='executed' for s in logs), '充分证据须有实际检索记录')
        elif o['search_state'] == 'pending':
            require(o['status'] == 'pending', '待查项不可计分')
        else:
            require(o['status'] == 'blocked' and any(s['status'] == 'blocked' for s in logs), '受阻状态须对应受阻日志')
        decision = o.get('decision_evidence_ids', [])
        score = None; weight = None; selected_group = []; score_basis = 'unrated'; default_band = None
        if o['status'] in ('verified','rule_gap'):
            refs(decision, cid)
            require(all(evidence[e]['period'] in (period,'comparison_base') for e in decision), '证据所属期间与指标不匹配')
            require(any(evidence[e]['period'] == period for e in decision), '只有比较基数不能证明当期指标')
            require(all(evidence[e]['published_date'] != 'undated' or period == PERIODS[-1] for e in decision), '无日期官网不能证明历史年份')
        if o['status'] == 'verified':
            bands = dict(item_map[mid]['bands'])
            require(o.get('band') in bands, f'{key} 档位不在Markdown规则中')
            require(o['band'] not in ('查不到','无法确认排名','无公开信息'), '缺省档位不能标为已证实')
            score = bands[o['band']]
            groups = o.get('decision_evidence_groups', [decision])
            require(isinstance(groups,list) and bool(groups) and all(isinstance(g,list) and bool(g) for g in groups), '独立证据组格式错误')
            require({e for g in groups for e in g} == set(decision), '证据组须与判定证据ID一致')
            require(all(any(evidence[e]['period'] == period for e in g) for g in groups), '每个独立证据组必须有当期证据')
            # Each group is independently sufficient; all members within a group are necessary.
            selected_group = max(groups, key=lambda g:min(weights[evidence[e]['grade']] for e in g))
            weight = min(weights[evidence[e]['grade']] for e in selected_group)
            score_basis = 'evidence'
        elif o['status'] == 'unverified':
            require(o['search_state'] == 'saturated', '缺省分必须完成检索验收')
            bands = item_map[mid]['bands']
            defaults = [(label, v) for label, v in bands if label in ('查不到','无法确认排名','无公开信息')]
            if not defaults:
                # 政策/资质类指标的 0 分地板档（'无'）视作"检索无果"的缺省：
                # 已饱和检索仍查不到国家级资质/荣誉/绿色认证/政策扶持时，取'无'=0 计入排名，
                # 而不是把整维度静默丢弃（这正是电子版比生科版少维度/少分的根因）。
                # rd_intensity 等刻意不设缺省档的指标，其地板不是'无'，不会落入此分支。
                floor_label, floor_score = min(bands, key=lambda kv: kv[1])
                if floor_label == '无':
                    defaults = [(floor_label, floor_score)]
            require(len(defaults) <= 1, '同一指标只能定义一个缺省档位')
            if defaults:
                default_band, score = defaults[0]
                score_basis = 'default'
        else:
            require(not o.get('band'), '受阻/规则待明确不能填写档位')
        if o['status'] == 'unverified':
            require(not o.get('band'), '未证实项不能人为指定档位')
        contribution = score if score_basis == 'default' else (score or 0)*(weight or 0)
        observations[key] = dict(o, raw_score=score, source_weight=weight, weighted_score=contribution,
                                 score_basis=score_basis, default_band=default_band,
                                 selected_evidence_group=selected_group)

    write(p/'observations-scored.json', list(observations.values()))
    results = []; warnings = list(followup_warnings)
    for cid, c in companies.items():
        for field in ('name','region','industry','identity_note','scope_reason','eligibility_reason'):
            require(nonempty(c.get(field)), f'{cid} 缺少 {field}')
        require(c.get('listing_status') in ('listed','unlisted','unknown'), '上市状态无效')
        require(c.get('eligibility') in ('main','reserve','excluded','prescreened','prescreened_out'), '企业准入状态无效')
        require(c['region'] == cfg['region'] and c['industry'] == cfg['industry'], '企业范围与任务不符')
        if c['eligibility'] == 'prescreened' and stage == 'prescreen':
            c = dict(c, eligibility='main')
        if c['eligibility'] != 'main':
            results.append(dict(c, metrics=[], raw_total=0, weighted_total=0, verified_weight=0, current_verified_weight=0))
            continue
        if c.get('scope_evidence_ids'):
            refs(c['scope_evidence_ids'], cid)
        # 地区与行业范围由用户名单确认。
        eligible = [f for f in facilities.values() if f['company_id'] == cid and f['region'] == cfg['region']]
        metrics = []; raw = weighted = coverage = current = default_total = default_count = 0
        # 过期数据窗口：只允许"最近 max_period_lag+1 期"的证据参与当期排名。
        # 默认仅当年和去年参与；前年保留追溯。
        max_lag = int(cfg.get('max_period_lag', 1))
        allowed_periods = set(PERIODS[-(max_lag + 1):])
        for item in items:
            rows = [observations.get((cid,item['id'],period)) for period in PERIODS]
            require(all(rows), f"{cid}/{item['id']} 必须填写三期记录")
            verified = [r for r in reversed(rows)
                        if r['period'] in allowed_periods
                        and r['status'] == 'verified'
                        and r.get('applicable_for_current') is True]
            # Evidence valid for its own period can be obsolete for current ranking.
            if verified:
                selected = verified[0]
            else:
                allowed_rows = [r for r in reversed(rows) if r['period'] in allowed_periods]
                selected = next(
                    (r for r in allowed_rows if r.get('score_basis') in ('evidence', 'default')),
                    rows[-1],
                )
            if selected['status'] == 'verified' and selected.get('applicable_for_current') is not True:
                selected = dict(selected, raw_score=None, weighted_score=0, status='unverified', score_basis='unrated', source_weight=None)
            raw += selected['raw_score'] or 0; weighted += selected['weighted_score']
            if selected['score_basis'] == 'default':
                default_total += selected['weighted_score']; default_count += 1
            if selected['status'] == 'verified':
                coverage += item['max']
                if selected['period'] == PERIODS[-1]: current += item['max']
            metrics.append({'id':item['id'],'label':item['label'],'max':item['max'], 'group':item['group'],
                'periods':rows, 'selected_period':selected['period'], 'raw_score':selected['raw_score'],
                'weighted_score':selected['weighted_score'], 'score_basis':selected['score_basis'],
                'default_band':selected.get('default_band'), 'historical_fallback':selected['period'] != PERIODS[-1]})
            if any(r['status'] in ('blocked','rule_gap') for r in rows):
                warnings.append(f"{c['name']} / {item['label']}: 受阻或评分规则需明确")
        results.append(dict(c, metrics=metrics, raw_total=round(raw,2), weighted_total=round(weighted,2),
            default_total=round(default_total,2), default_count=default_count, evidence_total=round(weighted-default_total,2),
            verified_weight=coverage, current_verified_weight=current, facilities=eligible,
            raw_unrated_count=sum(m['raw_score'] is None for m in metrics),
            current_evidence_count=sum(m['score_basis']=='evidence' and not m['historical_fallback'] for m in metrics),
            historical_evidence_count=sum(m['score_basis']=='evidence' and m['historical_fallback'] for m in metrics)))
    # 维度完整度与证据覆盖率告警（非致命）：防止"整维度被静默丢弃"造成电子 vs 生科式分差。
    main_results = [r for r in results if r['eligibility'] == 'main']
    if main_results:
        n_cells = len(items) * len(main_results)
        per_item = {i['id']: {'unrated': 0, 'evidence': 0, 'total': 0} for i in items}
        for r in main_results:
            for m in r['metrics']:
                per_item[m['id']]['total'] += 1
                if m['raw_score'] is None:
                    per_item[m['id']]['unrated'] += 1
                if m['score_basis'] == 'evidence':
                    per_item[m['id']]['evidence'] += 1
        evidence_cells = sum(v['evidence'] for v in per_item.values())
        for i in items:
            st = per_item[i['id']]
            if st['unrated']:
                if st['unrated'] == st['total']:
                    warnings.append(
                        f'维度"{i["label"]}"在主榜{len(main_results)}家中全部未定档'
                        f'（{st["total"]}/{st["total"]}单元格为unrated），须回填真实检索或标blocked/rule_gap，'
                        f'不能作为"已披露边界"通过验收')
                else:
                    warnings.append(
                        f'维度"{i["label"]}"在主榜仍有{st["unrated"]}个未定档单元格，已被静默计0，'
                        f'建议回填以区分"真0分"与"未研究"')
        if evidence_cells < n_cells:
            warnings.append(f'23维证据尚未齐全：{n_cells-evidence_cells}项使用缺省或未定档；当前结果为阶段性，继续按缺口补证')
        coverage = evidence_cells / n_cells if n_cells else 0
        if coverage < 0.5:
            warnings.append(
                f'主榜证据覆盖率仅{coverage:.0%}（{evidence_cells}/{n_cells}单元格为evidence定档），'
                f'当前排名主要反映"公开披露程度"而非企业真实实力，覆盖率越低排名偏差越大')
    main = sorted([r for r in results if r['eligibility']=='main'], key=lambda r:(-r['weighted_total'],-r['current_verified_weight'],r['id']))
    require(bool(main), '没有满足条件的主榜企业')
    if len(main) < TOP_N: warnings.append(f'已核实主榜仅{len(main)}家，距离Top{TOP_N}仍缺{TOP_N-len(main)}家')

    review = (p/'universe-review.md').read_text(encoding='utf-8')
    require('尚未执行检索' not in review and len(review.strip()) > 50, '请保留用户名单与预筛审计universe-review.md')
    out = {'config':cfg, 'rule_hash':rule_hash(), 'source_weights':weights, 'rubric_version':rubric['version'],
        'status':'provisional' if warnings else 'research_complete_with_disclosed_limits', 'warnings':warnings,
        'main':main[:TOP_N], 'reserve':[r for r in results if r['eligibility']=='reserve'],
        'overflow':main[TOP_N:], 'prescreened_out':[r for r in results if r['eligibility']=='prescreened_out'], 'excluded':[r for r in results if r['eligibility']=='excluded'],
        'evidence':list(evidence.values()), 'search_log':list(searches.values()), 'universe_review':review}
    if stage == 'final':
        from audit_top30 import audit
        out['quality_review'] = audit(out)
        write(p/'top30-quality.json', out['quality_review'])
        if out['quality_review']['status'] != 'complete': out['status'] = 'provisional'
    write(p/('prescreen-scores.json' if stage == 'prescreen' else 'scores.json'), out)
    return out

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--run', required=True)
    result = calculate(parser.parse_args().run)
    print(f"主榜 {len(result['main'])} / {result['config']['top_n']}；状态 {result['status']}；警告 {len(result['warnings'])}")
