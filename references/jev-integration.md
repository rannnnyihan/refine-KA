# Jev 决策层接入（2.3）

## 定位

Jev 是**决策层，不是搜索引擎，也不是证据来源**。本 skill 使用 Jev 的目标是减少执行智能体反复阅读和判断的轮次：

`网页搜索工具 / Search API → Jev 初筛 → 打开少量高价值页面 → Jev 证据路由/档位建议/语义复核 → 现有 raw → Python 确定性评分`

Jev 输出不得写进 `sources` 当来源，不得把 Jev 的概率当事实，不得用 Jev 取代实际网页访问、原文摘录、发布日期和 URL 记录。

## 为什么不用 MCP 作为唯一方案

本 skill 面向不同执行智能体，不假设 Codex、Claude Code 或某个 MCP 客户端。Jev 通过 `scripts/jev_client.py` 直接调用 TypeSafe HTTP API，因此只要执行环境能运行 Python 并访问网络即可复用。MCP 可以作为交互式调试手段，但不是生产依赖。

## 配置

```bash
export TYPESAFE_API_KEY="..."
# 可选
export TYPESAFE_BASE_URL="https://api.typesafe.ai"
export TYPESAFE_DEFAULT_MODEL="jev-latest"
export JEV_TIMEOUT_SECONDS="30"
export JEV_MAX_RETRIES="3"

python scripts/jev_client.py config
# 只有需要验证 key 时才发起最小收费请求：
python scripts/jev_client.py smoke
```

也可在 skill 根目录放置 `.env`：

```text
TYPESAFE_API_KEY=<your-key>
```

API key 默认优先从环境变量读取；本交付包同时支持 skill 根目录 `.env` 作为本地回退配置。环境变量会覆盖 `.env`。`.env` 属于敏感配置，不应进入公开仓库；若把此 Skill 分发给不应共享同一额度的人，应删除 `.env`，让对方配置自己的 `TYPESAFE_API_KEY`。无 key 时按原人工/LLM判断流程继续；禁止伪造 Jev 结果。

## 1. 粗采：搜索结果先筛再开网页

搜索工具真实返回 title/snippet/url 后，先保存一个临时候选 JSON（格式见 `templates/jev-search-results.example.json`），再执行：

```bash
python scripts/jev_decide.py screen-search \
  --input <run>/jev/C-001-search.json \
  --output <run>/jev/C-001-screened.json \
  --company "企业全称" --company-id C-001 \
  --industry "行业" --region "地区"
```

默认建议阈值：`entity_probability >= 0.60` 且 `open_probability >= 0.68` 才 `keep=true`。阈值是起点，不是经过本项目校准的真理；正式大规模使用前应用一小批企业做 A/B 校准，重点看漏掉有效 S1/S2 证据的比例。

**不可只打开 keep=true 的结果后就宣布“查无证据”**。Jev 只是省阅读量。某指标要进入 saturated / 缺省路径，仍须满足 `search-acceptance.md` 的真实补查与日志要求。

## 2. 粗采45面/自定义面：证据 passage 路由

项目代码目前只内置23维正式评分规则，以及预筛直接使用的10个基础指标+10个机会信号；**并没有内置一份“45个粗采面”的机器可读清单**。如果业务上粗采确实采用45面，执行者必须把45面明确保存成 labels JSON，再传给 Jev；不能让 Jev 自己补齐或发明45面。

labels 格式：

```json
{
  "labels": [
    {"id": "face_01", "description": "明确描述什么事实算命中"},
    {"id": "face_02", "description": "..."}
  ]
}
```

对已打开页面提取的 passage：

```bash
python scripts/jev_decide.py route-evidence \
  --input <run>/jev/C-001-passages.json \
  --output <run>/jev/C-001-routed.json \
  --company "企业全称" \
  --labels <run>/jev/coarse-faces.json \
  --threshold 0.70
```

一段 passage 可同时命中多个面。输出的 `label_probabilities` 和 `matches` 只用于路由和优先级，不直接形成 raw 事实。

## 3. 精采23维：一次读页面，多维复用

候选池进入23维精采后，同一 passage 可直接用现有正式指标做路由：

```bash
python scripts/jev_decide.py route-evidence \
  --input <run>/jev/C-001-passages.json \
  --output <run>/jev/C-001-23m.json \
  --company "企业全称" \
  --formal-metrics
```

然后只把高概率匹配的 passage 交给执行智能体做事实抽取、期间核对和 raw 填写。这样可以避免“一个年报为23个指标重复读23次”。

## 4. 定性指标：档位建议

已有原文证据后，可让 Jev 对**单个正式指标**给一个封闭档位建议：

```bash
python scripts/jev_decide.py judge-band \
  --input <run>/jev/capacity-candidates.json \
  --output <run>/jev/capacity-bands.json \
  --metric capacity
```

输入每项至少含 `id` 与 `evidence`/`excerpt`/`text`，可选 `fact/company_name/period/title/url`。Jev 会在评分规则原始 band 标签和 `__INSUFFICIENT__` 中选择。

- 选择 `__INSUFFICIENT__`：不得写 verified band。
- 数字增长、比例、金额等仍由 Python/明确算式计算；Jev 只辅助判断语义、主体、时间和定性档位。
- 最终写入 raw 的 `band` 仍必须是评分标准中的**标签字符串**，不是分数。

## 5. 最终语义复核

对准备写入的 claim + 原文 evidence：

```bash
python scripts/jev_decide.py verify-claims \
  --input <run>/jev/claims.json \
  --output <run>/jev/claims-verified.json
```

建议把 `support_probability` 很高且 `contradiction_probability` 很低的记录作为低风险项；中间区间、冲突项、主体/时间复杂项交回执行智能体精读。**Jev 不能替代 `audit_top30.py`，也不能替代人/LLM读原文。**

## 临时文件与审计

建议统一放在 `<run>/jev/`：

- `*-search.json`：搜索工具真实返回的候选；
- `*-screened.json`：Jev 搜索结果筛选；
- `*-passages.json`：执行智能体实际打开网页后提取的 passage；
- `*-routed.json`：Jev 多标签路由；
- `*-bands.json`：档位建议；
- `*-verified.json`：claim-evidence 语义复核。

这些文件是**决策辅助日志**，不是证据源。真正的审计事实仍进入 `raw/batch*.json`，再由 `ingest_raw.py` 生成 `evidence.json` / `search-log.json` / `observations.json`。

## Dry-run

没有 key 时可检查数据格式：

```bash
python scripts/jev_decide.py --dry-run screen-search ...
```

Dry-run 的概率全部是占位零值，只能验证 schema，**绝不能用于筛选或评分**。

## 推荐完整链路（实战沉淀）

以下顺序来自商飞 / 合合信息 / 信正木业等多轮运行，优先级高于「只跑 route-evidence」的捷径。

```
网页搜索（Agent）
  → 保存 *-search.json
  → jev screen-search（可选但推荐）
  → 只打开 keep=true 的 URL（Agent）
  → 提取 passage → *-passages.json（Agent）
  → jev route-evidence --formal-metrics
  → 只对 matches 精读：fact / band / measurement / searches（Agent）
  → （可选）judge-band / verify-claims
  → raw/batch*.json → ingest → score
```

### 四步分工（Jev vs Agent）

| 步骤 | 谁做 | 输出 | 不能做什么 |
|------|------|------|------------|
| **screen-search** | Jev | keep/skip + 概率 | 不能代替开页；skip 的链接若某维要 saturated 仍须单独补搜 |
| **route-evidence** | Jev | 每段 passage × 23 维概率 + `matches` | 不能写 raw；不能定 band；不能算同比 |
| **精读写 raw** | Agent | sources / searches / band / detail | 不能只信 Jev 概率就 verified |
| **score / audit** | Python | 分数、完整度、warnings | 不读网页 |

**route-evidence 与 Agent 手工路由的区别**：Jev 对每段 passage 固定问 23+1 个封闭问题，返回 0–1 概率；Agent 若一步完成「读 passage + 定档 + 写 raw」，容易漏维或把一段财务摘要过度贴到无关维。推荐 **Jev 出 matches 清单，Agent 只对 matches 做 authoritative 定档**。

### 何时必须 screen-search

- 粗采 / 缺口补证：同一企业 **≥8 条** 搜索候选，或有明显误命中（其他公司年报、同行业龙头）
- 200→40 批量粗采：几乎总是值得做

### 何时可跳过 screen-search

- 目标 URL 已确定（如科创板 `688615` → cninfo 2024 年报 PDF）
- 单企业 demo 且候选 ≤3 条且均相关
- **跳过 screen 不等于跳过检索**；缺口维 saturated 仍须 S1→S4 真实日志

### 补证阶段（最容易漏 Jev 的环节）

对 `capacity` / `ma` / `green_certification` 等缺口维：

1. 按维单独搜索 → 追加到 `*-search.json`（或分维 `*-search-<metric>.json`）
2. **screen-search** 后再开页（不要脚本批量生成假 saturated 日志）
3. 新 passage → **route-evidence** → 更新 raw → 重跑 ingest / score

合合信息补证教训：初跑仅 route 未 screen、19/20 证据来自同一 PDF；补证后加多源 + route，证据条数与 URL 数才上升。

### macOS SSL

若 `route-evidence` / `screen-search` 报 `CERTIFICATE_VERIFY_FAILED`：

```bash
export SSL_CERT_FILE=$(python3 -m certifi)
```

### 单企业最小 Jev 命令（复制即用）

```bash
export TYPESAFE_API_KEY="..."
export SSL_CERT_FILE=$(python3 -m certifi)

python scripts/jev_decide.py screen-search \
  --input  runs/<run>/jev/C-001-search.json \
  --output runs/<run>/jev/C-001-screened.json \
  --company "企业全称" --company-id C-001 \
  --industry "行业" --region "地区"

python scripts/jev_decide.py route-evidence \
  --input  runs/<run>/jev/C-001-passages.json \
  --output runs/<run>/jev/C-001-routed.json \
  --company "企业全称" \
  --formal-metrics
```

`route-evidence` 仅需 `--input --output --company`（加 `--formal-metrics`）；不要传 `--company-id`（当前 CLI 不支持）。

### artifacts 验收清单

跑完 Jev 后检查 `<run>/jev/`：

- [ ] 有 search 则应有 screened（或文档说明为何跳过）
- [ ] 有 passages 则应有 routed
- [ ] `routing-summary.json`（可选）：passage id → metric 对照，方便写 raw
- [ ] raw 里 `detail.status_context` 可注明「Jev P00x 路由命中」，但 **band 仍由 Agent 对照 rubric 确定**
