"""Portable standard-library helpers; no regional/company seed data."""
import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
def periods_for(cutoff):
    year = dt.date.fromisoformat(cutoff).year
    return (str(year-2), str(year-1), f'{year}YTD')

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def write(path, value):
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

def md_config(name):
    blocks = re.findall(r'```json\s*\n(.*?)\n```', (ROOT/'references'/name).read_text(encoding='utf-8'), re.S)
    if len(blocks) != 1:
        raise ValueError(f'{name}: 必须且只能有一个JSON规则块')
    return json.loads(blocks[0])

def rules():
    rubric = md_config('scoring-standard-company.md')
    items = [dict(i, group=g['label']) for g in rubric['groups'] for i in g['items']]
    assert len(items) == 23 and len({i['id'] for i in items}) == 23
    assert sum(i['max'] for i in items) == rubric['total'] == 100
    weights = md_config('evidence-sources.md')['weights']
    assert 1 >= weights['S1'] > weights['S2'] > weights['S3'] > weights['S4'] > 0
    return rubric, items, weights

def rule_hash():
    h = hashlib.sha256()
    for p in sorted((ROOT/'references').glob('*.md')):
        h.update(p.name.encode()); h.update(p.read_bytes())
    return h.hexdigest()

def http_url(value):
    u = urlparse(value or '')
    return u.scheme in ('https', 'http') and bool(u.netloc) and not u.username

def date(value):
    return dt.date.fromisoformat(value)

def nonempty(value):
    return isinstance(value, str) and bool(value.strip())

def unique(rows, key='id'):
    result = {}
    for r in rows:
        if not nonempty(r.get(key)) or r[key] in result:
            raise ValueError(f'缺失或重复ID: {r.get(key)}')
        result[r[key]] = r
    return result
