# 项目进度与交接（PROGRESS）

> 最后更新：2026-10-28 12:56（Asia/Shanghai）
> 用途：第二天无缝接上；先读这一页，再读 README。

## 一、现在到哪了

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| 第一步：目录 / 依赖 / 模型 / 单测 | ✅ 完成 | Article / Evidence / Verification，缺失字段显式标记 |
| 第二步：检索 / 解析 / 去重 | ✅ 完成 | 限速、超时、重试、分批、原始响应落盘；真实 NCBI 已验证 |
| 第三步：模型抽取 / 结构化校验 | ✅ 完成 | 真实 deepseek-chat 已跑通；科学规则降级、校验提示、陈述类型（事实/作者解释/推断）均已生效 |
| 第四步：引用核查 / 状态管理 | 🟡 部分 | 本地核查可用；在线标识符校验与语义 judge 还没接进调度 |
| 第五步：调度 / 报告 / 导出 | 🟡 部分 | Markdown 报告可用；CSV 导出未做；失败清单未进报告 |

测试基线：**69 passed, 1 skipped，覆盖率 85%**（2026-10-28 12:53 实测）。

## 二、最近一次真实运行（有证据）

时间：2026-10-28 12:53
输入：阿司匹林如何抑制血小板聚集？检索式 aspirin platelet inhibition，2 篇文献（PMID 35768902、25126950）

~~~text
articles_found=2  evidence_items=10  extraction_failures=0
verified_passed=10  verification_issues=0
~~~

产出：

- 报告：reports/report_20261028T045307Z.md
- 处理后数据：data/processed/evidence_20261028T045307Z.json
- 原始响应：data/raw/pubmed_*_20261028T0452*.json/xml、pmc_efetch_20261028T0453*.xml
- 文献快照：data/raw/articles_20261028T045307Z.json

注意区分：*_153156Z 那批是**没有模型**时的演示（0 条证据）；*_160016Z 是首轮真实模型（7 条），仅作历史对照。

## 三、文件地图

~~~text
config/settings.yaml          运行参数（检索/重试/限速/抽取/LLM/报告）
config/search_queries.yaml    四组检索式（二级预防/一级预防/出血/机制）
src/aspirin_agent/
  schemas.py                  Article / Evidence / Verification / ExtractionBatch
  orchestrator.py             检索 -> 去重 -> 全文 -> 抽取 -> 核查 -> 成稿
  llm_client.py               OpenAI 兼容客户端（重试/JSON 模式回退）
  main.py                     CLI 入口
  tools/pubmed_search.py       ESearch/EFetch、限速、重试、原始落盘
  tools/article_fetch.py       PMC 全文补全、fetch_articles
  tools/deduplication.py       PMID/DOI/标题相似度去重
  tools/evidence_extract.py    结构化抽取 + 科学规则校验
  tools/citation_verify.py     引文定位、标识符/标题/可访问性核查
  tools/report_builder.py      Markdown 报告
  parsers/pubmed_xml.py        PubMed XML
  parsers/fulltext.py          PMC/HTML 全文
  utils/rate_limit.py          限速器
  errors.py                    PubMedError / LLMError / EvidenceExtractionError
prompts/extract_evidence.md    抽取提示词（输出 {"evidence": [...]}）
tests/                         9 个文件，69 passed
~~~

## 四、环境与凭据

- Python 3.11.6；虚拟环境 .venv（已装运行依赖 + pytest + ruff）
- .env 已配置：NCBI_EMAIL、NCBI_API_KEY（36 位）、LLM_API_KEY、LLM_BASE_URL、LLM_MODEL=deepseek-chat
- **密钥不要提交**；.gitignore 已排除 .env
- Git 2.56.0（PortableGit 官方版，D:\Apps\Git），已加入用户 PATH；自带 Git Bash（D:\Apps\Git\git-bash.exe）
- 仓库已初始化（main 分支），已完成首次提交（baseline）；本仓库身份：周洋 <buiqnsnmqmsn67999@gmail.com>
- 当前会话的 PATH 不会自动刷新；新开终端可直接用 git，旧会话用完整路径 D:\Apps\Git\cmd\git.exe
- GitHub 直连把 github.com 解析到 20.205.243.166（超时）；下载 release 资产时用 curl --resolve github.com:443:140.82.112.4 绕过

## 五、怎么跑

~~~powershell
# 进入项目
cd D:\Apps\大肥鱼\aspirin-research-agent

# 离线测试（默认跳过真实网络）
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check src tests

# 真实接口冒烟
$env:RUN_LIVE_TESTS='1'; .\.venv\Scripts\python.exe -m pytest tests\test_live_pubmed.py

# 完整流水线（会消耗模型额度；默认每个检索式 20 篇）
.\.venv\Scripts\aspirin-agent.exe --question "阿司匹林如何抑制血小板聚集？" --query "aspirin platelet inhibition" --max-queries 1
~~~

省钱跑法：把 config/settings.yaml 里的 search.max_results_per_query 临时改小，或直接调 Orchestrator（见最近一次运行的脚本写法）。

## 六、已知问题（明天优先处理）

1. **CSV 导出缺失**：验收要求 Markdown + CSV + JSON；现在只有后两者。
2. **在线核查没接线**：PubMedResolver 已实现，但 orchestrator 没传 resolver；需要配置开关 verification.online_check（默认关，测试不打网络）。
3. **语义 judge 没接线**：verify_citations(..., judge=...) 支持，但调度没传；当前 claim_supported 只代表“引句可逐字定位”。
4. **min_confidence 未使用**：低置信度证据不筛。
5. 单页检索：没有翻页，retmax 上限 1 万。
6. 抽取失败只进 JSON，不进报告。
7. PMC 全文许可/署名未处理；对外转载前需逐篇核对。
8. utils/retry.py（tenacity）与 searcher 手写重试并存，可择一统一。

## 七、明天从这里开始

建议顺序（每步都跑测试再继续）：

0. ✅ 配置 git 身份并首次提交（已完成，9c422db）
1. ✅ 补 statement_type（已完成；真实跑出作者解释条目，报告可见）
2. **CSV 导出**（data/exports/articles.csv、evidence.csv、verifications.csv）
   - 验收：字段含 evidence_id / pmid / status / issues，UTF-8-SIG 可直接用 Excel 打开
3. **在线核查开关 + judge 接线**
   - 验收：默认离线全绿；开启后至少 1 篇真实文献通过/不通过判定合理

## 八、上次验证命令与结果（可复现）

~~~text
ruff check src tests   -> All checks passed!
pytest                 -> 69 passed, 1 skipped
coverage               -> 85%
~~~
