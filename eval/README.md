# 评测说明

当前最佳提示词：prompts/extract_evidence_v3.md（一条证据只对应一个结果；5 篇 gold set 上 57/59，auto-strict）。

目的：用一批人工可核对的真实文献，衡量“抽取出的 claim 是否被 quote 支持”，而不是只看程序是否跑通。

## 流程

1. 编辑 eval/gold_set.yaml，选 5–10 篇文献，标明 stratum（human_rct / human_primary / preclinical / review）。
2. 生成评测批次（会调用模型）：

   ~~~powershell
   .\.venv\Scripts\python.exe scripts\build_eval.py
   ~~~

3. 打开 eval/runs/<run_id>/items.csv，逐行填写：
   - supported：1 = quote 支持 claim；0 = 不支持；留空 = 未标注
   - quote_verbatim：1 = quote 逐字出现在原文；0 = 有改动或找不到
   - reviewer_note：可选备注
4. 计算指标：

   ~~~powershell
   .\.venv\Scripts\python.exe scripts\score_eval.py eval\runs\<run_id>
   ~~~

输出 score.md：precision（按 stratum / statement_type 分组）、false positive 清单、quote 逐字率。

## 注意

- 评测批次写到 eval/runs/，已被 .gitignore 排除；gold_set.yaml 与脚本进版本库。
- 标注时只看 claim 与 quote，不看程序给的 auto_status，避免被自动结果带偏。
- 判据：quote 必须支持 claim 的核心结果，以及 claim 中出现的剂量、数值、机制、因果；文献总体人群、队列名称（如 Duke/NYU）可作背景，但新增的剂量/数值/机制算“不支持”。
- 样本量 5–10 篇只能看方向，不要当成统计显著性结论。
