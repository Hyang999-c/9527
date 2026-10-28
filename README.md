# 阿司匹林研究 Agent

从 PubMed 检索阿司匹林相关文献 → 去重 → 补全全文 → 抽取结构化证据 → 核查引用 → 生成中文证据简报。

> 仅用于研究辅助，不构成医学建议。
>
> 当前进度、已知问题与接续方式见 [PROGRESS.md](PROGRESS.md)。

## 流水线

1. **检索**：NCBI E-utilities（ESearch + EFetch），检索式见 `config/search_queries.yaml`
2. **去重**：PMID / DOI / 标题相似度（阈值 0.92）
3. **全文补全**：有 PMCID 的文献抓取 PMC OA XML，失败则保留摘要
4. **证据抽取**：LLM 按 `prompts/extract_evidence.md` 输出 JSON 证据条目（claim + 原文引句）
5. **引用核查**：标识符是否存在、引句是否逐字出现在原文中
6. **成稿**：Markdown 简报写入 `reports/`，中间产物写入 `data/raw`、`data/processed`

## 快速开始

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
pip install -e ".[dev]"

copy .env.example .env           # Windows；Linux/macOS 用 cp
# 填入 NCBI_EMAIL、NCBI_API_KEY（可选）、LLM_API_KEY

aspirin-agent --question "阿司匹林在二级预防中的获益与出血风险如何权衡？"
```

不配置 `LLM_API_KEY` 时只跑检索、去重与落盘；加 `--no-llm` 可强制跳过模型调用。

## 目录

```text
aspirin-research-agent/
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── config/               # settings.yaml 运行参数、search_queries.yaml 检索式
├── src/aspirin_agent/    # main / orchestrator / schemas / llm_client
│   ├── tools/            # 检索、抓取、去重、抽取、核查、成稿
│   ├── parsers/          # PubMed XML、PMC/HTML 全文解析
│   └── utils/            # 日志、重试
├── data/                 # raw / processed / exports
├── prompts/              # 抽取、核查、机制归纳提示词
├── tests/                # 离线单测 + 端到端
└── reports/              # 生成的简报
```

## 数据模型

- `Article`：PMID、DOI、标题、作者、年份、期刊、出版类型、摘要、来源、检索时间、全文状态
- `Evidence`：evidence_id、PMID、研究问题、主张、证据类型、研究模型、方法、原文结果、来源位置、局限、置信度、核查状态
- `Verification`：标识符、标题、来源可访问性、主张支持四项核查，加问题清单与最终状态

缺失信息不补全：`Article.missing_fields` 与 `Evidence.missing_fields` 显式列出空字段。

## 模型输出契约

模型返回 `{"evidence": [...]}`；每条先过 Pydantic 校验，再执行科学规则：

- 综述 / 系统综述中的 `primary_result` 降为 `review_summary`
- 标注全文但只取到摘要时，按实际文本改标 `abstract` 或 `none`，并写校验提示
- 非法条目丢弃并记日志；单篇失败进 `failures`，不伪装成功
没有可定位原文位置时，`Evidence` 不能标记 `passed`；四项核查未全部通过时，`Verification` 也不能。

## 配置

- `config/settings.yaml`：检索条数、超时、重试、限速、EFetch 批大小、抽取批次、模型参数、报告标题
- `config/search_queries.yaml`：按主题分组的检索式，`--max-queries` 控制本轮使用前 N 条
- 密钥只放 `.env`，不进入版本库

## NCBI 使用规则

- 每次请求都带 `tool` 与 `email`；配置 `NCBI_API_KEY` 后自动按 10 次/秒限速，否则 3 次/秒
- `rate_limit_per_second` 可显式覆盖；相邻请求由 `RateLimiter` 保证最小间隔
- EFetch 按 `efetch_batch_size`（默认 200）分批，避免单次请求过大
- 429/5xx 与传输错误会按 `retry_attempts` 指数退避重试，4xx 直接报错
- 原始 ESearch JSON 与 EFetch XML 落在 `data/raw/pubmed_*`，处理后的记录另存，二者不混用

## 测试

```bash
pytest                      # 离线测试，默认跳过真实网络
RUN_LIVE_TESTS=1 pytest tests/test_live_pubmed.py   # 真打 PubMed，需要网络
```

测试默认走 `httpx.MockTransport` 与假 LLM，不依赖网络；真实接口另有一条冒烟测试，需显式开启。

## 进度

- [x] 第一步：目录、依赖、Article / Evidence / Verification 模型与单元测试
- [x] 第二步：PubMed 检索（限速/重试/超时/分批）、XML 解析、原始响应落盘、全文抓取、去重，均有离线测试与真实接口冒烟
- [x] 第三步：LLM 客户端（超时/重试/JSON 模式回退）与结构化抽取、科学规则校验；已用真实 deepseek-chat 跑通 2 篇
- [x] 第四步（部分）：引文定位、标识符/标题/可访问性核查与状态回写已实现；在线校验与语义 judge 待接线
- [x] 第五步（部分）：调度与 Markdown 报告已实现；CSV 导出待补
- [ ] 真实 API 联调、CSV 导出、语义核查 judge、多轮检索
