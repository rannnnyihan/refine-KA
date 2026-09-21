# 维护与运行 2.3

SKILL.md为唯一流程入口：用户提供企业→内部低成本预筛约40家→精采、深化当前Top30的23维信息→仅Top30结果UI。

run_research.py导入名单；prescreen.py以基础/低财务披露业务机会双通道分配精采名额；plan_search.py组织检索；ingest_raw.py转换真实raw来源与detail；score_companies.py计算及生成完整度报告；s1_gapfill.py诊断约40家证据缺口；audit_top30.py检查最终30家的完整信息；gen_company_html.py重算、验收并生成单文件。脚本依赖Python标准库，联网由执行智能体完成。

规则阈值及来源系数读取对应Markdown唯一JSON块。改流程同步脚本、方法、数据格式和验收；metric-evidence-guide定义逐维信息要求。修改后运行 `python scripts/test_skill.py`，都是隔离合成数据，不触发真实企业调查。

生成器拒绝未通过验收的完成版；显式--draft可生成清晰草稿。不要改标志位、用虚假detail或剔除资料难找的高分企业来通过验收。结构与计算检查不能证明来源真实，人工/AI仍须读原文。

原发现、注册查询、固定年份、虚构检索日志、强推研发强度、全量历史格子精采方案已停用。粗排与备选不再出现在HTML，包括隐藏JSON。旧运行保持原样，旧资料推定日期/日志不可当作新版真实审计记录。

2.2补充执行责任：用户要求运行本skill即授权执行智能体完成联网采证。脚本无内置搜索API不等于skill离线。执行者不得只初始化、只计划、以工作量大为由停止，或用输入表格的注册资本/简介代替200家联网粗采；应按批次持续执行至最终HTML通过验收，除非发生系统性联网阻塞或用户暂停。


## 2.3 Jev 可选决策层
新增 `scripts/jev_client.py` 与 `scripts/jev_decide.py`。它们直接使用 TypeSafe HTTP API，不依赖 Codex/MCP，便于把整个目录作为 Skill 交给其他执行智能体。Jev 只处理搜索结果筛选、passage 路由、定性档位建议和 claim-evidence 复核；不联网搜索、不写 raw、不参与最终数学评分。

配置只用环境变量 `TYPESAFE_API_KEY`；不要把 key 写进仓库。修改 Jev 层后除 `python scripts/test_skill.py` 外，再运行 `python scripts/test_jev.py`。无 key 的测试不得发真实 API。
