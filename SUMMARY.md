# 阿司匹林研究 Agent — 成果汇总

> 更新：2026-10-28
> 定位：从 PubMed 检索阿司匹林文献，抽取可核查证据，生成带引用核查的 Markdown / CSV / JSON 报告。
> 声明：研究辅助工具，不构成医学建议。

## 一、一句话

一个可运行的文献证据流水线：**检索 → 去重 → 全文 → 结构化抽取 → 引用核查 → 报告/CSV/JSON**，
并且有真实 API 运行记录、可复现的评测集与 86 条测试。

## 二、已交付功能

| 环节 | 能力 | 主要文件 |
| --- | --- | --- |
| 检索 | ESearch/EFetch、3/10 次每秒限速、超时、指数退避重试、EFetch 分批、原始响应落盘 | src/aspirin_agent/tools/pubmed_search.py |
| 解析 | PubMed XML、PMC JATS/HTML 全文、出版类型映射、研究模型字段 | parsers/pubmed_xml.py、parsers/fulltext.py |
| 去重 | PMID、DOI、标题相似度（0.92） | tools/deduplication.py |
| 抽取 | v3 提示词、JSON 模式、截断自动重试、Pydantic 校验、综述降级、来源位置修正、陈述类型 | tools/evidence_extract.py、prompts/extract_evidence_v3.md |
| 核查 | 引句逐字定位、标题/可访问性、在线 esummary/Crossref（开关）、语义 judge（开关）、状态机 | tools/citation_verify.py |
| 成稿 | Markdown 报告、三张 CSV（UTF-8-SIG）、原始/处理后 JSON | tools/report_builder.py、tools/csv_export.py |
| 调度 | 依赖可注入、失败隔离、产物落盘、提示词可配置 | orchestrator.py |
| CLI | aspirin-agent 命令、参数化检索式、--no-llm | main.py |

## 三、工程指标

~~~text
ruff check src tests scripts  -> All checks passed
pytest                        -> 86 passed, 1 skipped
coverage                      -> 87%
~~~

- 测试覆盖检索、解析、抓取、去重、抽取、核查、CSV、报告、端到端
- 真实网络测试单独隔离：RUN_LIVE_TESTS=1 才执行
- 默认不联网、不调模型即可跑测试

## 四、真实数据验证

- NCBI API key 已配置：限速 10 次/秒；真实检索 5 篇 1.34 秒
- 模型：deepseek-chat，真实抽取跑通
- 端到端样例：1 篇文献 → 14 条证据 → 14 条通过核查
- 产物：
  - 报告：reports/
  - CSV / 日志：data/exports/
  - 原始 XML/JSON：data/raw/
  - 处理后证据：data/processed/

## 五、评测结果

Gold set：12 篇，覆盖人体 RCT、人体原始研究、临床前、meta 分析、综述。

| 指标 | 结果 |
| --- | --- |
| 证据数 | 177 |
| 抽取失败 | 0 |
| 支持率（precision 近似） | 169/177（95%） |
| quote 逐字率 | 177/177（100%） |
| 召回（4 篇 18 条） | 18/18（100%） |
| 人工抽查 | v3 批次 10/10 一致 |

分层：human_rct 38/42、meta_analysis 57/59、review 30/32、human_primary 11/11、preclinical 33/33。

提示词 A/B（同一批 5 篇）：

| 版本 | 证据数 | 支持率 | RCT 覆盖 |
| --- | --- | --- | --- |
| v1 | 43 | 93% | 7 |
| v2 | 44 | 95% | 12 |
| v3（一条证据一个结果） | 59 | 97% | 14 |
| v4（作者解释/绝对风险） | 185（12 篇） | 97% | — |
| v5（比较性结论） | 177（12 篇） | 95% | — |

召回评测（4 篇 / 18 条关键结论）：**18/18（100%）**；v5 补上了比较性结论。

评测工具：eval/gold_set.yaml、eval/recall_gold.yaml、scripts/build_eval.py、scripts/score_eval.py、scripts/auto_label_eval.py、scripts/recall_eval.py。
最新结果：eval/runs/20261102T131013Z/score.md 与 recall.md。

## 六、过程中修掉的真实缺陷

1. **参考文献 ID 覆盖本篇 ID**：PMCID 被参考文献覆盖，抓错全文（已修复 + 回归测试）
2. **长全文 JSON 截断**：max_tokens 不足导致整篇抽取失败（默认 4000 + 8000 自动重试）
3. **数字字段导致整条证据被丢**：模型把段落号返回成数字，严格校验误杀（类型归一）
4. **response_format 兼容**：供应商不支持时自动退回普通 JSON
5. **限速只覆盖 PubMed**：PMC 全文抓取也接入同一限速器
6. **Windows 控制台中文乱码**：CLI 强制 UTF-8

## 七、边界与未完成

- **召回 100%**：4 篇 18 条关键结论全中；代价是精度降到 95%，8 条引句不完整/超额推断
- **冗余未量化**：v3 拆条会产生碎片化，135 条里可能有重复结论
- 评测只有 12 篇、135 条，且主要是 auto-strict 判定
- min_confidence 未用于过滤
- 抽取失败清单只进 JSON/CSV，未进报告正文
- 检索单页，未做翻页
- PMC 全文许可/署名未逐篇处理
- 没有配置 git 远端

## 八、关键提交

~~~text
14410cc docs: 扩展集人工抽查 10/10 一致
6016ba0 eval: 扩展 gold set 到 12 篇（99%，待人工抽查）
b37297e feat: v3 提示词设为默认并接入配置；评测 97%
dacb0c5 fix: 修复参考文献 ID 覆盖；提高抽取 token 上限；记录提示词 A/B
6d68baa feat: 导出 CSV（articles/evidence/verifications，UTF-8-SIG）
9c422db chore: 建立项目基线（第一至第三步）
~~~

## 九、怎么复查

~~~powershell
cd D:\Apps\大肥鱼\aspirin-research-agent
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check src tests scripts
.\.venv\Scripts\aspirin-agent.exe --question "阿司匹林如何抑制血小板聚集？" --query "aspirin platelet inhibition" --max-queries 1
~~~

更多细节见 README.md、PROGRESS.md、eval/README.md。
