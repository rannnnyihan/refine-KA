---
name: company-top50-skill
description: 执行企业Top30联网研究：对用户提供的约200家企业逐家做低成本联网采证并筛出约40家候选池（30主榜+10冗余），再联网采集候选池的23维证据、评分并输出仅含Top30的HTML。
---

# 企业证据筛选 2.3

## 执行责任与完成条件

当用户提供企业名单并要求“按本skill研究、排名或生成HTML”时，这是一项**需要执行智能体亲自完成联网研究的任务**，不是让智能体解释方法、只初始化目录、只生成检索计划或让用户另行采证。执行智能体必须调用可用的网页搜索、浏览器、PDF/年报阅读工具，实际打开来源、提取事实并写入运行数据；Python脚本只负责规划、整理、评分、验收和生成HTML。

收到明确执行请求后，依次完成200家联网粗采、内部筛选约40家、约40家联网精采、Top30逐维补证、评分验收和HTML生成。工作量大、需要很多轮检索、单次搜索结果不全、某些公司没有年报，均不是提前结束任务的理由。不要把“需要较长时间”“当前只能完成一部分”“不能在一次回复完成”作为交付结论；应继续执行后续批次，复用已保存的运行目录，并定期用简短进度更新说明已完成数量和下一步，不向用户重复确认已经授权的联网研究。

只有以下情况才允许停止并说明阻塞：执行环境没有任何联网/网页/PDF读取能力；连续尝试可替代入口后仍发生同一系统性访问阻塞；或用户主动要求暂停。单家公司资料缺失不构成整体阻塞，按来源降级和缺口规则继续其他企业。

完成版的唯一交付条件是：已对输入名单中的每家企业完成规定的粗采；已按联网证据选择约40家；已对约40家采集23维信息并完成初排；当前Top30的23维均经过补证和验收；最终HTML成功生成。未满足时不发送最终答复，不用注册资本、表格原有简介、企业知名度或名单顺序代替联网证据，也不把N/A样式预览冒充结果。

## 输入、过程、交付
用户按行业提供约200家企业及地区，默认Top30。名单已确认准入，不查询企查查、天眼查或其他信用平台，不发现新企业、不核验注册地址。保留同名、集团与子公司的事实边界核对。输入支持CSV/TSV/JSON/TXT/XLSX，最少name，可选alias、listing_status、identity_note、segment（细分赛道）。若输入表格还包含注册资本、企业简介、平台标签或AI生成内容，这些字段只能辅助识别主体，不能参与粗排或充当23维证据。

**内部过程：200→40→30。最终结果UI只展示Top30企业及每家的23维完整事实和评分依据。** 即：200 家输入名单→阶段1逐家联网粗采→约40家候选池（30主榜+10冗余reserve）→精采全部23维→集中把当前Top30补到证据率≥80%→评分验收→生成只含Top30的HTML。粗分、预筛通道、40家候选池、落选/备选企业、研究过程日志只保留在运行目录，不生成结果页表格、折叠面板或隐藏JSON。候选池上限由 `candidate_cap = top_n + 10` 控制。

**实战要点（多轮真实运行沉淀，必读）**：[执行经验沉淀](references/execution-lessons.md) 汇总了 200→40→30 口径、**档位必须存标签字符串（数字评分会静默降级为"查不到"）**、年报优先一次性铺满23维、补证到≥80%、2026未发布vs真查不到、生成HTML不显示草稿水印等全部坑与对策。

核心目标是Top30的690个维度判定有充分、完整、可追溯的信息。缺省分不算证据，简短宣传文案不算完整事实；不能为满分覆盖率强行推断。事实确实不公开时继续可行补证，无法解决则保持草稿及明确缺口，不能伪装为完成版。

开始前读 [方法](references/methodology.md)、[来源优先级](references/evidence-sources.md)、[评分规则](references/scoring-standard-company.md)、[执行经验沉淀](references/execution-lessons.md)。采证时读 [逐维证据标准](references/metric-evidence-guide.md)、[检索手册](references/search-playbook.md)、[数据格式](references/data-schema.md)。验收读 [检索验收](references/search-acceptance.md)，输出读 [HTML约束](references/html-format.md)。NS归类按需读 [行业映射](references/ns-industry-mapping.md)，不改变用户名单范围。 若环境设置了 `TYPESAFE_API_KEY`，同时读 [Jev决策层接入](references/jev-integration.md)，用 Jev 做搜索结果初筛、证据路由和定性档位建议；Jev不是搜索引擎也不是证据来源。

## 内部低成本预筛
1. 先从企业全称出发，结合地区和行业/细分赛道，**对名单中的每一家企业实际联网检索**。共享层一次按细分赛道建立依据；名单层批量匹配。每家企业都用相近深度浏览官网业务/产品与新闻/项目，记录实际查询、打开的页面和明确事实；有最新年报/股东披露再一次抽取财务信息，无年报则改查官网、政府项目/公示、母公司或股东年报和权威第三方，不视作差企业。200家全部完成粗采前不得进入约40家候选池筛选。
2. 基础通道按共享1项+名单4项+财报5项（现规则共44分）选30家。其余最多10个名额优先给未入选且财务信息少、有业务实证的企业：财务证实不足3/5项，至少2个业务维度达到本项满分60%的正向档位，且至少1项S1/S2。业务维度限客户预算/结构、融资、产能、海外投资、并购、技术、新品、商业化、市场排名；共享增长、泛泛荣誉不能单独入选。取最强3项标准化证据分合计作内部机会排序，同分按当年信号数、业务类别数、ID；没有足够合格机会候选时按基础排序补齐。
3. 不给上市身份加分；未知不当负面事实。两通道阈值只是透明的初始名额分配规则，未经实证校准，不宣称必然低误杀。复核两通道临界及低覆盖企业，补查仅限官网/已获报告等低成本材料，必要时重排；不扩张约40家精采上限。过程保存在prescreen-review.json和universe-review.md。


## Jev 可选决策层（面向任意 Skill/Agent，不依赖 Codex）
Jev 通过 `scripts/jev_client.py` 直接调用 TypeSafe API；API key 只从环境变量 `TYPESAFE_API_KEY` 读取。执行环境有 key 时，优先把它用在高频、封闭判断上；没有 key 时原流程照常执行，不得伪造 Jev 输出。

推荐分工：**搜索工具负责找，Jev负责筛/路由/判断，Python负责规则与数学，执行智能体负责打开原文、提取事实和处理低置信度/冲突项。** 完整链应为：搜索候选写入 `jev/*-search.json` → `screen-search`（候选多时必做）→ 打开 keep 页 → passage 写入 `jev/*-passages.json` → `route-evidence --formal-metrics` → **执行智能体仅对 Jev matches 精读并写 raw**；定性项可用 `judge-band`；写入 raw 前可用 `verify-claims` 复核。禁止只跑 route 而跳过 search/screen，或用脚本生成假 saturated 日志。

如果业务粗采采用“45个面”，这45面必须由业务方/skill明确写成 labels JSON 后传给 `route-evidence --labels`；**当前代码不内置45面清单，Jev不得自行发明。** `screen-search` 的 keep/skip 也只是优先级：未打开的候选不能据此直接宣布“查无证据”，saturated/缺省仍必须满足真实检索验收。详见 [Jev决策层接入](references/jev-integration.md) 与 [执行经验沉淀](references/execution-lessons.md) 第10节。

## 候选池精采、Top30深查
先用最新年报和官网填充所有可证实维度，再逐项按**当年S1→当年S2→当年S3→去年S1→去年S2→去年S3**补缺。年份按事实所属期，今年发布的去年年报仍属去年。S4只作追溯线索，前年只作比较，不参与当前分数。

**年报优先、一次铺满23维**：精采阶段先批量读最新年报/官网，一次抽取营收、CAPEX、研发、出口/境外收入、研发强度、前五大客户、定增/发债等可证维度（详见[执行经验沉淀](references/execution-lessons.md) 第2节），不要逐维单独搜或只做10项粗排指标就停；剩余需单独检索的维度（客户预算、市占、海外投资、并购、招聘、关键岗位、组织扩张、商业化等）再逐条补。

候选池（约40家）均开展23维精采形成初排，然后集中补齐当前Top30的690个判定，另复核第25–35名附近可改变边界的证据缺口。**证据定档率目标 ≥80% 再交付**（低于50%时排名主要反映"公开披露程度"而非真实实力，须在页面与答复中说明）。补证后重算，若新企业进入Top30，必须对新进入者完成同样验收，不能沿用旧30家已完成的结论。不因企业资料难找把它人工移出主榜，不用覆盖率门槛替代真实评分排名。

每维保留主体、事实期间、具体事实、数值与单位/事件进展、来源位置及日期、定档理由、局限。同比必须同主体同口径同长度，计算有依据；定性指标必须落实事件阶段和有效性。历史回退需实际补查当年S1/S2/S3并说明仍适用原因。充分证据命中即停，不凑轮次；完整度以信息支撑判断，不以字数或来源篇数衡量。

三期保留追溯，历史空格可以pending；不为补满69格挤占当年研究。无信息不强推研发强度、不用人员占比冒充费用率、不用项目总投资冒充CAPEX同比。评分保留23项100分档位，缺省仅内部阶段性计分，不算完整交付。

## 运行顺序
以下在skill目录执行，运行目录为独立新路径。**整个skill必须联网执行**：执行智能体负责调用联网工具搜索和阅读；脚本本身不内置搜索API，只处理执行智能体采集的真实材料。不能因为脚本不联网而跳过采证阶段。

```bash
python scripts/run_research.py init --run <运行目录> --companies <名单文件> --region <地区> --industry <行业>
python scripts/prescreen.py --run <运行目录> --plan
python scripts/plan_search.py --run <运行目录>
# 实际低成本采证。若有 TYPESAFE_API_KEY：搜索结果先写 <run>/jev/*-search.json，
# 用 scripts/jev_decide.py screen-search 初筛后再打开页面；打开后的 passage 可 route-evidence。
# Jev 只产出辅助决策，真实事实/URL/日期仍写 raw/shared.json、lists.json、batch*.json。
python scripts/ingest_raw.py --run <运行目录>
python scripts/prescreen.py --run <运行目录> --apply
# 需要重筛时先补证并注入，再 --apply --force
python scripts/plan_search.py --run <运行目录>
python scripts/s1_gapfill.py --run <运行目录>
# 实际精采候选池（约40家）：年报/官网 passage 可先 route-evidence --formal-metrics，
# 定性项可 judge-band，写入 raw 前可 verify-claims；最终仍由执行智能体核原文并更新raw/detail。
python scripts/ingest_raw.py --run <运行目录>
python scripts/score_companies.py --run <运行目录>
# 看 warnings / top30-quality.json 的 issues：只补当前Top30（及第25–35名临界）缺口，循环重算到证据率≥80%
python scripts/audit_top30.py --run <运行目录>
python scripts/gen_company_html.py --run <运行目录> --draft
```

**写 findings/raw 的硬约束（头号数据坑）**：每条已证实记录的 `band` **只能是评分标准里的标签原文**（如 `"10%-30%"`、`">50%增长"`、`"基本稳定"`、`"Top 3"`），**绝不能写数字评分（5/4/3/2/1）或浮点（2.5/1.5）**——数字匹配不到标签会被静默降级为"查不到"（计0）且不报错。量化指标（`revenue_growth`/`capex_growth`/`rd_growth`/`export_growth`/`hiring_growth`/`track_growth`/`rd_intensity`）**必须带 `detail.measurement`**（value/unit/basis/calculation；增长项还需 current_period/comparison_period）。详见 [执行经验沉淀](references/execution-lessons.md)。

生成器会重新评分并验收；未通过则拒绝生成完成版。内部预览须显式加`--draft`，页面明显标草稿。不得为通过验收填写虚假的detail字段。检查只是结构与部分算式核验，执行智能体仍须阅读原始材料核对事实、档位和时效。

修改后按 [维护说明](references/handoff.md) 验证。只修改skill不启动真实企业研究，不覆盖旧运行结果。
