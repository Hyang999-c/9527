# 使用指南（USAGE）

> 面向日常使用：怎么跑、看什么、改哪里、卡住怎么办。

## 0. 前提

- 项目目录：D:\Apps\大肥鱼\aspirin-research-agent
- 虚拟环境：.venv（已装好运行依赖与 pytest）
- .env 已配置：NCBI_EMAIL、NCBI_API_KEY、LLM_API_KEY、LLM_BASE_URL、LLM_MODEL
- 密钥不要提交；.gitignore 已排除 .env

## 1. 最快跑一次

~~~powershell
cd D:\Apps\大肥鱼\aspirin-research-agent

.\.venv\Scripts\aspirin-agent.exe --question "阿司匹林如何抑制血小板聚集？" --query "aspirin platelet inhibition" --max-queries 1
~~~

默认行为：

- 每个检索式最多 20 篇
- 自动做 2 轮扩展（相关文献 + 参考文献/被引），带相关性过滤
- 有 PMCID 的抓 PMC 全文
- 用 v6 提示词抽证据
- 生成 Markdown 报告 + 3 张 CSV + JSON

## 2. 常用参数

| 参数 | 作用 |
| --- | --- |
| --question | 研究问题，写进报告标题 |
| --query | 自定义检索式，可重复 |
| --max-queries | 使用 search_queries.yaml 的前 N 条 |
| --no-llm | 只检索，不调模型（报告无证据） |
| --no-expand | 关闭多轮扩展 |
| --log-level | DEBUG / INFO / WARNING |

## 3. 改配置

config/settings.yaml：

- search.max_results_per_query：每个检索式取几篇（省钱先改小）
- search.expand：rounds、max_total、min_relevance、citations
- extraction.prompt：提示词版本（当前 v6）
- extraction.min_confidence：低置信度过滤阈值
- verification.online_check / semantic_judge：默认关，开了会联网/多调模型

config/search_queries.yaml：按主题分组的检索式。

## 4. 看输出

- 报告：reports/report_<时间>.md
- CSV：data/exports/articles_*.csv、evidence_*.csv、verifications_*.csv
- 原始响应：data/raw/pubmed_*、pmc_*
- 处理后数据：data/processed/evidence_*.json（含 failures 与 filtered_low_confidence）

报告里每条证据都带：

- evidence_id（如 35768902-E01）
- 证据类型 / 陈述类型 / 研究模型
- 来源位置与逐字引句
- 核查状态：passed / partial / failed / not_verifiable

partial 常见原因是“只有摘要，没拿到全文”；failed 通常是引句定位不到或标题不一致。

## 5. 在 Python 里调用

~~~python
import yaml
from dotenv import load_dotenv
from aspirin_agent.llm_client import LLMClient
from aspirin_agent.orchestrator import Orchestrator

load_dotenv()
settings = yaml.safe_load(open("config/settings.yaml", encoding="utf-8"))
llm = LLMClient.from_settings(settings)

result = Orchestrator(settings, llm=llm).run(
    "阿司匹林如何抑制血小板聚集？",
    ["aspirin platelet inhibition"],
)
print(result.stats)
print(result.report.markdown)
llm.close()
~~~

## 6. 评测

~~~powershell
# 生成评测批次（会调模型）
.\.venv\Scripts\python.exe scripts\build_eval.py

# 标注后算 precision
.\.venv\Scripts\python.exe scripts\score_eval.py eval\runs\<run_id>

# 召回
.\.venv\Scripts\python.exe scripts\recall_eval.py eval\runs\<run_id>

# 冗余
.\.venv\Scripts\python.exe scripts\redundancy_eval.py eval\runs\<run_id>
~~~

## 7. 测试

~~~powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\ruff.exe check src tests scripts

# 真实网络冒烟
$env:RUN_LIVE_TESTS='1'; .\.venv\Scripts\python.exe -m pytest tests\test_live_pubmed.py
~~~

## 8. 常见问题

- 报告 0 条证据：没有 LLM_API_KEY，或模型调用失败；看日志里的抽取失败
- 检索很慢：无 NCBI key 时限速 3 次/秒；配 key 后 10 次/秒
- 全是 partial：文献没有 PMCID，只能基于摘要核查
- 推送 GitHub 失败：DNS 污染时用
  git -c http.curloptResolve=github.com:443:140.82.112.4 push origin main
  IP 会变，先 curl 探测
- 成本：每篇文献一次抽取调用；扩展越多，篇数越多。先调小 max_results_per_query

## 9. 质量边界

- 评测基于 12 篇 / 161 条，precision 98%、recall 100%，仍属小样本
- 被引/参考文献追溯依赖 PMC 链接，覆盖不全
- 相关性过滤是词面覆盖，不是语义判断
- 许可分类是规则判断，不构成法律意见
