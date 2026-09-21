"""Generate stage-specific collection plans; no searches are executed."""
import argparse
from pathlib import Path
from common import read,rules
from prescreen import MODES


def generate(path,per_batch=6):
    if per_batch<1: raise ValueError('批次大小须为正整数')
    run=Path(path); cfg=read(run/'run-config.json'); pool=read(run/'candidate-pool.json')
    stage='coarse' if any(c['eligibility']=='prescreened' for c in pool) else 'detail'
    active=[c for c in pool if c['eligibility']==('prescreened' if stage=='coarse' else 'main')]
    if not active: raise ValueError('没有待研究企业，请先导入名单')
    _,items,_=rules(); selected=[i for i in items if stage=='detail' or i['id'] in MODES['full']]
    lines=[f"# {stage}采证计划：{cfg['industry']} / {cfg['region']}",
        f"企业 {len(active)} 家；本阶段 {len(selected)} 项；截止 {cfg['as_of']}",
        '先读最新年报/官网；当年S1→当年S2→当年S3→去年S1→去年S2→去年S3。',
        '共享层按细分赛道一次建依据；名单层批量匹配，未命中不等于没有；财报一次抽取多项。',
        'raw格式见skill references/data-schema.md；更新已有记录，不按新批次重复写同一企业指标。',
        '若环境有 TYPESAFE_API_KEY，可把搜索结果先交 scripts/jev_decide.py screen-search；打开页面后的passage再做route-evidence。Jev结果只是辅助判断，不是证据。',
        '此文件是计划，不是已执行检索日志。', '\n## 本阶段指标']
    lines.extend(f"- {i['id']}：{i['label']} / {i['max']}分" for i in selected)
    if stage=='coarse': lines.append('每家都按相近浏览深度读取官网业务/产品与新闻/项目，一并保存客户、产能、技术、融资等23维内的可用信号；有年报再提取财务，缺失不反复追查。详见内部prescreen-plan.md。')
    batches=[]
    for segment in sorted({c['scope_reason'] for c in active}):
        group=[c for c in active if c['scope_reason']==segment]
        batches.extend(group[i:i+per_batch] for i in range(0,len(group),per_batch))
    for n,b in enumerate(batches,1):
        lines.append(f'\n## 工作批次 {n} / {b[0]["scope_reason"]}')
        lines.extend(f"- {c['id']} {c['name']}" for c in b)
    out=run/'raw'/'search-plan.md';out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text('\n'.join(lines),encoding='utf-8')
    result=dict(stage=stage,companies=len(active),metrics=len(selected),batches=len(batches))
    print(result);return result

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--run',required=True);ap.add_argument('--per-batch',type=int,default=6)
    args=ap.parse_args();generate(args.run,args.per_batch)
