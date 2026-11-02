# 项目进度与交接（PROGRESS）

> 最后更新：2026-10-28 13:00（Asia/Shanghai）
> 用途：第二天无缝接上；先读这一页，再读 README。

## 一、现在到哪了

| 阶段 | 状态 | 说明 |
| --- | --- | --- |
| 第一步：目录 / 依赖 / 模型 / 单测 | ✅ 完成 | Article / Evidence / Verification，缺失字段显式标记 |
| 第二步：检索 / 解析 / 去重 | ✅ 完成 | 限速、超时、重试、分批、原始响应落盘；真实 NCBI 已验证 |
| 第三步：模型抽取 / 结构化校验 | ✅ 完成 | 真实 deepseek-chat 已跑通；科学规则降级、校验提示、陈述类型（事实/作者解释/推断）均已生效 |
| 第四步：引用核查 / 状态管理 | ✅ 完成 | 引文定位、在线 esummary/Crossref 校验、语义 judge、状态回写；开关默认关 |
| 第五步：调度 / 报告 / 导出 | 🟡 部分 | Markdown + CSV（UTF-8-SIG）+ JSON 已齐；抽取失败清单未进报告 |

测试基线：**82 passed, 1 skipped，覆盖率 87%**（2026-10-28 13:00 实测）。

## 二、最近一次真实运行（有证据）

时间：2026-10-28 13:00
输入：阿司匹林如何抑制血小板聚集？检索式 aspirin platelet inhibition，1 篇（PMID 40991180）；在线校验与语义判定均开启

~~~text
articles_found=1  evidence_items=7  extraction_failures=0
verified_passed=0  verification_issues=7
~~~

结果：7 条全部 partial，原因是该文献无 PMC 全文，只有摘要；在线标识符校验 7/7 通过，语义判定 7/7 支持。

产出：

- 报告：reports/report_20261028T050035Z.md
- 处理后数据：data/processed/evidence_20261028T050035Z.json
- CSV：data/exports/articles_20261028T050035Z.csv、evidence_*.csv、verifications_*.csv（UTF-8-SIG）
- 原始响应：data/raw/pubmed_*_20261028T0500*.json/xml
- 文献快照：data/raw/articles_20261028T050035Z.json

注意区分：*_153156Z 无模型演示；*_160016Z 首轮真实模型（7 条）；*_045307Z 第二轮（10 条，补陈述类型）；*_045448Z 为 CSV 验证批；*_050035Z 为在线+语义核查批。

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
tests/                         10 个文件，82 passed
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

## 六、已知问题（按优先级）

1. **评测仍以小样本为主**：v5 12 篇 177 条，169/177（95%），召回 18/18；精度下降主要来自引句不完整/超额推断。
2. **min_confidence 未使用**：低置信度证据不筛。
3. 单页检索：没有翻页，retmax 上限 1 万。
4. 抽取失败清单只进 JSON/CSV，不进报告正文。
5. PMC 全文许可/署名未处理；对外转载前需逐篇核对。
6. utils/retry.py（tenacity）与 searcher 手写重试并存，可择一统一。
7. 语义 judge 会增加模型调用成本，目前无缓存/批量优化。
8. 在线核查每次重跑都会重复请求，未做本地缓存。

## 七、明天从这里开始

建议顺序（每步都跑测试再继续）：

0. ✅ 配置 git 身份并首次提交（已完成，9c422db）
1. ✅ 补 statement_type（已完成；真实跑出作者解释条目，报告可见）
2. ✅ CSV 导出（已完成；三张表带 run_id，UTF-8-SIG，真实跑批验证）
3. ✅ 在线核查开关 + 语义 judge（已完成；真实跑 1 篇，online=True、claim=True）
4. **收尾项**：min_confidence 过滤、失败清单进报告、检索分页
5. **评测**：v3 99%/83% → v4 97%/94% → v5 95%/100%（precision/recall）；v5 已设为默认

## 八、上次验证命令与结果（可复现）

~~~text
ruff check src tests scripts -> All checks passed!
pytest                       -> 86 passed, 1 skipped
coverage                     -> 87%
~~~

## 九、评测记录（2026-10-28 13:32）

发现并修复两个真问题：

1. **参考文献 ID 覆盖本篇 ID**：解析器用 .//ArticleIdList 扫到了参考文献里的 ArticleId，
   PMID 35768902 自己的 PMCID（PMC9976777）被参考文献的 PMC2947304 覆盖，抓回来的全文是另一篇脂氧素论文。
   已改为只读 PubmedData/ArticleIdList，并加回归测试。
2. **长全文 JSON 截断**：一次抽 10+ 条时输出会被截断。默认提到 4000，并加了一次 8000 tokens 的自动重试。

干净 A/B（5 篇，temperature=0）：

| 版本 | 证据数 | 支持率 | quote 逐字率 |
| --- | --- | --- | --- |
| v1 | 43 | 40/43（93%） | 100% |
| v2（claim 不得超出引句） | 44 | 42/44（95%） | 100% |
| v3（一条证据只对应一个结果） | 59 | 57/59（97%） | 100% |

结论：v3 把 RCT 的证据数从 7 提到 14，支持率 97%；剩下 2 条失败都是 claim 多写了
quote 里没有的队列标签（Duke）。

v3 已设为默认（config: extraction.prompt = prompts/extract_evidence_v3.md）。
真实冒烟 1 篇（PMID 35768902）：14 条证据、0 失败、14 条全部 passed。

人工抽查 v3 10 条：9/10 一致。唯一分歧是 35768902-E03——auto-strict 因 claim 写了 quote 里没有的
“Duke 队列”判不支持，人工认为队列标签属于文献背景，应算支持。按人工口径为 58/59（98%）。

### 扩展集（2026-10-28 17:40）

- gold set 扩到 12 篇：新增 ARRIVE 一级预防 RCT、PCI 术后停药 RCT、3 篇 meta 分析、
  1 篇生物等效性研究、1 篇 PK/PD 综述
- 135 条证据，0 抽取失败；auto-strict 134/135（99%），quote 逐字 100%
- 唯一失败 40888723-E02：claim 写了“12 个月复合终点”，quote 只有 93 人 / 5.5%，
  缺时间窗与终点定义
- 人工抽查 10/10 一致（含唯一失败 40888723-E02），99% 维持；抽查含已知失败，非纯随机。

作废批次：20261028T050422Z、T053026Z、T053135Z、T053206Z（解析器修复前，含错误全文或抽取失败）。

## 十、召回评测（2026-11-02）

- 4 篇 / 18 条关键结论（2 条方法类金标已排除）
- 覆盖 15/18（83%）
- 未覆盖：
  - R5：作者推测“体重增加降低预防效力可能由其他机制解释”
  - A5：“中等风险人群的问题未能回答”这半句
  - G5：每 1000 人服用 10 年的绝对风险估计（1 例死亡 + 1 例致残性卒中）
- 结论：抽取偏重“结果”，漏“作者解释 / 适用性声明 / 绝对风险”
- 脚本：scripts/recall_eval.py；金标：eval/recall_gold.yaml
\n\n### v5 迭代（2026-11-02）\n\n| 版本 | 证据数 | precision | recall |\n| --- | --- | --- | --- |\n| v3 | 135 | 99% | 83% |\n| v4 | 185 | 97% | 94% |\n| v5 | 177 | 95% | 100% |\n\n- v5 新增：明确比较句（similar/comparable/no significant difference）单独成条，quote 必须含比较双方\n- R3 补上；R3 金标同时去掉了 n=66/随机分组这类设计细节\n- 代价：精度 95%，8 条失败，主要是引句不完整（缺时间窗/终点/映射）或把作者暗示写成明示\n- v5 已设为默认（config: extraction.prompt = prompts/extract_evidence_v5.md）\n
