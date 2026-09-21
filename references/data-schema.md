# 数据格式 2.3

## 运行文件
- run-config.json：地区、行业、top_n（默认30）、candidate_cap（默认40；实际为 top_n+10）、input_size、as_of、periods、workflow_version。
- candidate-pool.json：id、name、alias、listing_status、identity_note、region、industry、scope_reason（细分赛道）、eligibility、eligibility_reason。状态流为prescreened→main / prescreened_out；不需要registration_*或设施证据。
- raw/batch*.json：企业对象数组，每项为company_id及metrics数组。
- raw/lists.json：指标记录数组，每条增加company_id。
- raw/shared.json：赛道增长记录数组，每条增加segment，精确匹配企业scope_reason；仅track_growth可共享。
- jev/*.json（可选）：搜索候选、screen/routing/band/verify等Jev辅助决策日志。它们不是证据源，不由ingest_raw.py读取，也不得代替raw中的真实URL/摘录/日期。
- evidence.json、search-log.json、observations.json：由注入器重建，人工采证事实以raw为准。
- observations-scored.json：评分器计算的逐期分数；预筛直接读取，不依赖AI填写weighted_score。
- prescreen-scores.json、prescreen-review.json、universe-review.md：粗排及低覆盖/临界复核记录。
- scores.json：正式Top30、overflow精采备选及prescreened_out粗排落选。
- s1-gap-plan.md/.json：全部候选池（Top30默认约40家）的证据与当年缺口，不只诊断最终30家。

## raw指标记录
每条记录包含id（指标ID）、period（事实期）、period_end（实际覆盖日）、status、fact、rationale、search_state、search_conclusion、sources、searches。verified另需band（逐字匹配规则）、decision_evidence_ids、可选decision_evidence_groups、applicable_for_current。未证实不填band；缺省分由程序决定。

> **头号数据坑（强制）**：`band` **只能是 `scoring-standard-company.md` 里对应指标的标签原文**（如 `"10%-30%"`、`">50%增长"`、`"基本稳定"`、`"Top 3"`）。**绝不可写数字评分（5/4/3/2/1）或浮点（2.5/1.5）**。写入程序一律以标签字符串为键，数字/浮点匹配不到标签会被**静默降级为"查不到"（计 0）且无报错**——某次运行因此一夜之间损失 330 个单元格假缺失、头部企业排名严重失真。写入前**逐格校验 band 是否真的在该指标的 bands 列表内**；不合法就修正或标缺口，禁止硬塞数字。量化指标还须 `detail.measurement`（见下）。详见 [执行经验沉淀](references/execution-lessons.md#3-档位必须存标签字符串这是头号数据坑)。

sources内ID、searches内ID为该指标记录内唯一的局部ID，注入器加主体/指标/期前缀。引用必须使用对应局部ID。禁止旧版仅url/grade/fact的简格式，不能由程序补造日期或检索。

以下仅为格式示例，不是真实企业证据；实际运行替换为读到的事实和实际日期，不能照抄为已执行日志。

```json
[
  {
    "company_id": "C-001",
    "metrics": [
      {
        "id": "revenue_growth",
        "period": "2026YTD",
        "period_end": "2026-06-30",
        "status": "verified",
        "fact": "合成示例：上半年营收120，上年同期100，同口径增长20%。实际记录写单位、币种及主体。",
        "rationale": "120/100-1=20%，对应10%-30%档。",
        "band": "10%-30%",
        "applicable_for_current": true,
        "search_state": "sufficient",
        "search_conclusion": "同一报告给出当期和同比基数，足以定档。",
        "decision_evidence_ids": ["report"],
        "decision_evidence_groups": [["report"]],
        "sources": [
          {
            "id": "report", "period": "2026YTD",
            "url": "https://example.com/synthetic-report.pdf",
            "grade": "S1", "title": "合成半年报", "publisher": "合成企业",
            "locator": "第12页营收表", "excerpt": "合成数据：120；上年同期100。",
            "grade_reason": "示例企业一手披露；真实运行须验证发布方。",
            "published_date": "2026-08-20", "accessed_date": "2026-09-14", "usable": true
          }
        ],
        "searches": [
          {
            "id": "read1", "status": "executed", "query": "读取合成报告第12页",
            "channel": "公司报告", "result_summary": "合成格式示例，非实际调查。",
            "source_grade": "S1", "round": 1, "searched_date": "2026-09-14",
            "result_urls": ["https://example.com/synthetic-report.pdf"],
            "new_evidence_ids": ["report"], "online": true
          }
        ]
      }
    ]
  }
]
```

来源published_date不能推定。无发布日期的当年现状页显式用undated；抓取晚于历史截止日不能据此证明历史现状。同比比较基数可在sources中标period=comparison_base，但每组还须有本期证据。

blocked须实际blocked搜索日志；pending可省略sources/searches，不领取缺省分。saturated必须真实四级日志和最后连续两轮无新增；source_grade_coverage记录各级完成状态，不能用布尔值代替实际日志。

S4始终usable=false，额外保存followup_search_ids、followup_status（upgraded/exhausted/blocked）、followup_conclusion；升级时保存replacement_evidence_ids。这里只转换既有真实记录，不自动生成追溯结论。

优先级为企业记录>名单记录>对应赛道共享记录，是数据具体性优先，不是任意覆盖可信事实；冲突由采证者先解决。同层重复主键会报错，不静默覆盖。注入重建输出可重复执行，原始raw不会修改，粗排落选企业的记录仍保留。

## 2.2 最终选用期的完整信息 detail

每条用于最终Top30评分的raw指标额外包含detail，注入器原样保留。基础字段：entity_scope（实际主体/业务范围）、time_scope（实际覆盖区间）、limitations（局限数组，可空）。原有fact写具体事实，rationale解释为什么对应该档位，source定位到页码/章节或具体页面，不能只有泛泛总结。

数值指标（营收/CAPEX/研发/出口/招聘/赛道增长及研发强度）另需measurement：value（有限数字）、unit、basis（口径）、calculation（公式或报告直接披露说明）。增长项还需current_period和comparison_period。若提供current_value/baseline_value，程序校验正基数及百分比计算，容差0.1个百分点；数值原文直接披露时可不重复提供原值，但必须写可比期间及口径。不能推测未披露的原值。

其他指标需status_context（具体事件进展、有效状态或市场边界），而不是通用“正常”。历史回退时需fallback_reason解释当年为何不可定档及旧事实为何仍适用；该指标当年记录的searches须包含真实已执行S1/S2/S3补查。缺失不能由程序自动补造。

示例detail（合成，非真实事实）：
```json
{"entity_scope":"目标公司合并口径","time_scope":"当年上半年","limitations":[],"measurement":{"value":20,"unit":"%","basis":"同币种同主体营业收入同比","current_period":"当年H1","comparison_period":"上年H1","current_value":120,"baseline_value":100,"calculation":"(120/100-1)×100=20%"}}
```

score_companies.py自动输出内部top30-quality.json。audit_top30.py复核当前Top30的690项完整信息；gen_company_html.py会重算并拒绝输出未经完整度验收的完成版，--draft仅供明显标注的草稿。预筛和质量诊断都为内部数据；结果HTML不内嵌落选/备选主体、粗分或内部审计。

数值维度中的原生定性档位允许measurement.method=qualitative，填写basis、calculation和status_context，不编造value。仅适用于metric-evidence-guide列出的确切档位，不能用于数值阈值或缺省档。
