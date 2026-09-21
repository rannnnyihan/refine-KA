# refine-KA · 企业 Top30 证据筛选 Skill

面向 AI Agent 的企业研究 Skill：**对用户提供的约 200 家企业做联网采证 → 内部筛出约 40 家候选池 → 精采 23 维证据 → 评分并输出 Top30 单文件 HTML**。

本仓库是 **Cursor / Codex Agent Skill**（工作流 2.3），Python 脚本负责规划、整理、评分与验收；**联网检索与阅读原文由执行智能体完成**。可选接入 [Jev](https://typesafe.ai) 决策层，减少搜索初筛与证据路由的阅读量。

## 核心流程

```
200 家输入名单
  → 阶段 1：逐家联网粗采
  → 约 40 家候选池（30 主榜 + 10 冗余）
  → 阶段 2：23 维精采 + 初排
  → 集中补齐当前 Top30（690 个判定，目标证据率 ≥80%）
  → 评分验收 → 生成 HTML（仅展示 Top30）
```

- **不查**企查查、天眼查等信用平台，不自动发现新企业
- 输入表格中的注册资本、简介、平台标签**不能**参与打分或充当证据
- 缺省分不算证据；查不到就标缺口，不臆造

## 23 维评分体系

共 **23 项、100 分**，覆盖五大类：

| 类别 | 指标示例 |
|------|----------|
| 需求与预算 | 营收增长、CAPEX、研发投入、客户预算信号 |
| 市场需求与行业地位 | 赛道增长、市占/排名、出口增长、客户结构 |
| 资本与扩张 | 融资、产能扩张、海外投资、并购 |
| 人才与组织 | 招聘增长、关键岗位、组织扩张 |
| 技术与产品 | 研发强度、技术突破、新品、商业化 |
| 政策与荣誉 | 国家级资质、荣誉榜单、绿色认证、政策扶持 |

完整档位定义见 [`references/scoring-standard-company.md`](references/scoring-standard-company.md)。

## 快速开始

### 环境要求

- Python 3.9+（**仅标准库**，无第三方依赖）
- 执行 Agent 需具备联网搜索、浏览器或 PDF 阅读能力
- 可选：`TYPESAFE_API_KEY`（Jev 决策层）

### 1. 准备企业名单

支持 `.csv` / `.tsv` / `.json` / `.txt`，最少一列企业名：

```csv
name,alias,listing_status,segment
示例科技有限公司,示例科技,未上市,半导体设备
```

### 2. 初始化运行目录

```bash
python scripts/run_research.py init \
  --run runs/my-run \
  --companies inputs/companies.csv \
  --region 上海 \
  --industry 电子 \
  --top-n 30
```

### 3. 按流水线执行

```bash
python scripts/prescreen.py --run runs/my-run --plan
python scripts/plan_search.py --run runs/my-run

# ↓ 执行 Agent 联网采证，写入 raw/batch*.json、raw/lists.json、raw/shared.json

python scripts/ingest_raw.py --run runs/my-run
python scripts/prescreen.py --run runs/my-run --apply
python scripts/plan_search.py --run runs/my-run
python scripts/s1_gapfill.py --run runs/my-run

# ↓ 执行 Agent 对候选池（约 40 家）做 23 维精采

python scripts/ingest_raw.py --run runs/my-run
python scripts/score_companies.py --run runs/my-run
python scripts/audit_top30.py --run runs/my-run
python scripts/gen_company_html.py --run runs/my-run --draft
```

完整流程说明与 Agent 执行责任见 [`SKILL.md`](SKILL.md)。

## Jev 可选决策层

有 `TYPESAFE_API_KEY` 时，可用 Jev 做高频封闭判断（**不是搜索引擎，也不是证据来源**）：

| 步骤 | 命令 | 作用 |
|------|------|------|
| 连通性 | `python scripts/jev_client.py smoke` | 验证 API |
| 搜索初筛 | `python scripts/jev_decide.py screen-search` | 降低开页数 |
| 证据路由 | `python scripts/jev_decide.py route-evidence --formal-metrics` | passage → 23 维 |
| 档位建议 | `python scripts/jev_decide.py judge-band` | 定性指标封闭档位 |
| 语义复核 | `python scripts/jev_decide.py verify-claims` | claim ↔ 原文 |

**推荐完整链路**（不要只跑 route-evidence）：

```
搜索 → jev/*-search.json → screen-search → Agent 开 keep 页
     → jev/*-passages.json → route-evidence → Agent 只对 matches 写 raw
```

- **Jev**：筛链接、路由 passage 到维度（概率 + matches）
- **Agent**：摘录原文、定 band 标签、写 searches、完成 saturated 的 S1–S4 补查
- **Python**：ingest / score / audit（Jev 输出不进 evidence.json）

配置方式（任选其一）：

```bash
export TYPESAFE_API_KEY="your-key"
export SSL_CERT_FILE=$(python3 -m certifi)   # macOS 常见
# 或在 skill 根目录创建 .env（已在 .gitignore，勿提交）
```

详见 [`references/jev-integration.md`](references/jev-integration.md) 与 [`references/execution-lessons.md`](references/execution-lessons.md) 第 10 节。

## 目录结构

```
.
├── SKILL.md                 # Agent 主入口（流程与执行责任）
├── README.md
├── scripts/                 # 规划、注入、评分、验收、HTML 生成
│   ├── run_research.py      # 初始化运行目录
│   ├── prescreen.py         # 粗排与候选池分配
│   ├── plan_search.py       # 生成采证计划
│   ├── ingest_raw.py        # raw → evidence / observations
│   ├── score_companies.py   # 评分与完整度报告
│   ├── s1_gapfill.py        # 缺口诊断
│   ├── audit_top30.py       # Top30 完整信息验收
│   ├── gen_company_html.py  # 单文件 HTML 输出
│   ├── jev_client.py        # Jev HTTP 客户端
│   └── jev_decide.py        # Jev 决策命令
├── references/              # 方法、评分规则、数据格式、验收标准
└── templates/               # JSON 模板与 Jev 示例
```

运行产物（`runs/`、`inputs/`、`.env`）默认不纳入版本控制。

## 头号数据坑

写入 `raw/batch*.json` 时，`band` **必须是评分标准里的标签原文**（如 `"10%-30%"`、`"Top 3"`），**绝不能写数字 5/4/3/2/1**。数字匹配不到标签会被静默降级为「查不到」（计 0）且不报错。

量化指标还须带 `detail.measurement`（value、unit、basis、calculation 等）。详见 [`references/execution-lessons.md`](references/execution-lessons.md)。

## 测试

修改脚本或规则后运行（合成数据，不触发真实企业调查）：

```bash
python scripts/test_skill.py
python scripts/test_jev.py   # 无 key 时不发真实 API
```

## 文档索引

| 文档 | 内容 |
|------|------|
| [SKILL.md](SKILL.md) | Agent 执行入口 |
| [methodology.md](references/methodology.md) | 方法与时间优先级 |
| [scoring-standard-company.md](references/scoring-standard-company.md) | 23 维评分档位 |
| [data-schema.md](references/data-schema.md) | raw / evidence 数据格式 |
| [search-playbook.md](references/search-playbook.md) | 分层采证手册 |
| [execution-lessons.md](references/execution-lessons.md) | 实战踩坑与对策 |
| [jev-integration.md](references/jev-integration.md) | Jev 接入说明 |
| [handoff.md](references/handoff.md) | 维护与变更验证 |

## 在 Agent 中使用

将整个目录作为 Skill 挂载给 Cursor / Codex 等 Agent，对用户说：

> 按本 skill 对 [行业/地区] 的 [N] 家企业做 Top30 研究并生成 HTML。

Agent 应读取 `SKILL.md` 并按流水线联网执行，而不是只生成计划或解释方法。

## License

未指定开源协议；使用前请与仓库维护者确认。
