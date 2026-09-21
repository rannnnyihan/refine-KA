"""Initialize runs from a user-provided company list and generate query plans.

Actual browsing/evidence collection is agent-owned; this script only does
scaffolding, validation, planning and reporting.
"""
import argparse
import csv
import datetime as dt
import json
from pathlib import Path
from common import periods_for, date, read, rules, write

# 名单文件里可能用来表示企业名的列名/键名
NAME_KEYS = ('name', '企业名称', '公司名称', 'company', 'company_name', '主体')
LISTING_KEYS = ('listing_status', '上市状态', 'listed', '是否上市')
NOTE_KEYS = ('identity_note', '备注', 'note', '别名', '说明')
ALIAS_KEYS = ('alias', '简称', '曾用名')


def _pick(row, keys, default=''):
    for k in keys:
        if isinstance(row, dict) and row.get(k) not in (None, ''):
            return str(row[k]).strip()
    return default


def load_companies(fp):
    """读取用户提供的企业名单，支持 .json / .csv / .tsv / .txt。

    最少只需企业名；可选列：listing_status、identity_note、alias。
    返回 [{'name':..., 'listing_status':..., 'identity_note':..., 'alias':...}, ...]
    """
    p = Path(fp)
    if not p.exists():
        raise ValueError(f'名单文件不存在: {fp}')
    rows = []
    if p.suffix.lower() == '.json':
        data = json.loads(p.read_text(encoding='utf-8'))
        if isinstance(data, dict):
            data = data.get('companies') or data.get('items') or data.get('data') or []
        if not isinstance(data, list):
            raise ValueError('JSON 名单须为数组，或含 companies/items/data 数组的对象')
        for x in data:
            rows.append({'name': x} if isinstance(x, str) else x)
    elif p.suffix.lower() in ('.csv', '.tsv'):
        delim = '\t' if p.suffix.lower() == '.tsv' else ','
        with p.open(encoding='utf-8-sig', newline='') as f:
            rows = list(csv.DictReader(f, delimiter=delim))
    else:
        rows = [{'name': ln.strip()} for ln in p.read_text(encoding='utf-8').splitlines()
                if ln.strip() and not ln.strip().startswith('#')]

    out, seen = [], set()
    for i, r in enumerate(rows, 1):
        name = _pick(r, NAME_KEYS)
        if not name:
            raise ValueError(f'名单第 {i} 行缺少企业名（可用列名：{" / ".join(NAME_KEYS)}）')
        normalized=name.replace(' ', '').replace('（','(').replace('）',')')
        if normalized in seen:
            continue
        seen.add(normalized)
        ls = _pick(r, LISTING_KEYS, 'unknown').lower()
        if ls in ('1', 'true', 'yes', 'y', '上市', 'listed'):
            ls = 'listed'
        elif ls in ('0', 'false', 'no', 'n', '未上市', 'unlisted', 'non-listed'):
            ls = 'unlisted'
        elif ls != 'listed':
            ls = 'unknown'
        out.append({'name': name, 'listing_status': ls,
                    'identity_note': _pick(r, NOTE_KEYS), 'alias': _pick(r, ALIAS_KEYS), 'segment': _pick(r, ('segment','细分赛道'))})
    if not out:
        raise ValueError('名单为空')
    return out


def initialize(path, region, industry, cutoff, top_n=30, companies=None, id_prefix=None):
    p = Path(path)
    if p.exists() and any(p.iterdir()):
        raise ValueError('运行目录非空：请使用新目录，旧数据不会被覆盖')
    if date(cutoff) > dt.date.today() or date(cutoff).year < 3:
        raise ValueError('截止日不能晚于运行当天，且必须能够推导前两年')
    if not region.strip() or not industry.strip():
        raise ValueError('请说明地区和行业')
    # 目标数量由用户指定，默认30；Top30 等更小的目标同样合法
    top_n = int(top_n)
    if top_n < 1:
        raise ValueError('目标数量 top_n 必须是不小于 1 的整数')
    # 候选池封顶：现在是「预筛后的精采名额」，不再是发现上限。
    # Top30 → 40（30 主榜 + 10 冗余 reserve）；Top50 → 60（50 主榜 + 10 冗余）。
    candidate_cap = top_n + 10

    if not companies:
        raise ValueError('请提供企业名单；本 skill 不发现企业')
    pool = []
    if companies:
        pool = load_companies(companies)
        prefix = (id_prefix or 'C').strip().upper()
        pool = [{
            'id': f'{prefix}-{i:03d}',
            'name': c['name'],
            'alias': c.get('alias') or c['name'],
            'region': region,
            'industry': industry,
            'listing_status': c['listing_status'],
            'identity_note': c.get('identity_note') or '用户提供主体',
            'scope_reason': c.get('segment') or industry,
            'scope_evidence_ids': [],
            'eligibility': 'prescreened',
            'eligibility_reason': '用户提供名单，已人工确认符合行业与地区准入；待阶段1粗排后取前 '
                                  f'{candidate_cap} 家进入精采',
            'prescreen_score': None,
        } for i, c in enumerate(pool, 1)]

    p.mkdir(parents=True, exist_ok=True)
    (p/'jev').mkdir(parents=True, exist_ok=True)
    write(p/'run-config.json', {'region':region, 'industry':industry, 'top_n':top_n,
          'candidate_cap':candidate_cap,
          'input_size':len(pool),
          'require_registration_check':False, 'workflow_version':'2.3', 'max_period_lag':1,
          'decision_layer':{'jev':'optional','api_key_env':'TYPESAFE_API_KEY','artifacts_dir':'jev'},
          'as_of':cutoff, 'periods':list(periods_for(cutoff)), 'rule_version':rules()[0]['version'],
          'status':'initialized' if not pool else 'list_loaded'})
    write(p/'candidate-pool.json', pool)
    for name in ('facility-evidence', 'evidence', 'observations', 'search-log'):
        write(p/f'{name}.json', [])

    if pool:
        listed = sum(1 for c in pool if c['listing_status'] == 'listed')
        (p/'universe-review.md').write_text(
            '# 名单接入与预筛审计\n\n'
            f'- 用户提供名单：**{len(pool)}** 家（已人工确认符合「{industry} + {region}」准入）\n'
            f'- 其中上市 {listed} 家、未上市 {sum(1 for c in pool if c["listing_status"] == "unlisted")} 家、'
            f'状态未知 {sum(1 for c in pool if c["listing_status"] == "unknown")} 家\n'
            f'- 不做注册地核验（用户已确认准入）；不查询企业信用平台\n'
            f'- 精采名额 candidate_cap = **{candidate_cap}**，需经阶段1粗排产生\n\n'
            '## 预筛记录\n\n待执行。粗排后在此记录入选/落选依据，以及是否存在误杀。\n',
            encoding='utf-8')

    return {'run':str(p), 'top_n':top_n, 'candidate_cap':candidate_cap,
            'loaded':len(pool),
            'status':'list_loaded; awaiting prescreen' if pool else 'empty; awaiting companies'}

def plan(path):
    from plan_search import generate
    return generate(path, 6)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    subs = parser.add_subparsers(dest='command', required=True)
    s = subs.add_parser('init'); s.add_argument('--run', required=True)
    s.add_argument('--region', required=True); s.add_argument('--industry', required=True)
    s.add_argument('--as-of', default=dt.date.today().isoformat())
    s.add_argument('--top-n', type=int, default=30, help='目标主榜数量，默认30；Top30等时填30。候选池自动封顶：Top30→40（30主榜+10冗余）、Top50→60（防70+发散）')
    s.add_argument('--companies', required=True, help='用户提供的企业名单文件（.json/.csv/.tsv/.txt）。最少只需企业名，可选列 listing_status / identity_note / alias。已人工确认符合行业与地区准入，不做注册核验')
    s.add_argument('--id-prefix', default='C', help='企业ID前缀，默认 C → C-001')
    s = subs.add_parser('plan'); s.add_argument('--run', required=True)
    args = parser.parse_args()
    if args.command == 'init':
        result = initialize(args.run, args.region, args.industry, args.as_of, args.top_n,
                            companies=args.companies, id_prefix=args.id_prefix)
    else:
        result = plan(args.run)
    print(json.dumps(result, ensure_ascii=False))
