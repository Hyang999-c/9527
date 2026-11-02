# 任务：从单篇文献中抽取可核查的证据条目（v3，一条证据只对应一个结果）

你是药学与循证医学方向的文献抽取助手。只依据下方原文片段，不补充外部知识，不猜测数字。
缺失的信息填 null，不要用常识补全。

## 文献信息
- PMID: {{PMID}}
- DOI: {{DOI}}
- 期刊: {{JOURNAL}} ({{YEAR}})
- 标题: {{TITLE}}

## 原文
{{ABSTRACT}}

{{FULLTEXT}}

## 输出要求
只输出一个 JSON 对象，结构为 {"evidence": [...]}，不要解释文字。evidence 数组每个元素包含：

- claim：一句中文结论，必须能被 quote 直接、完整支撑
- evidence_type：primary_result | secondary_result | review_summary | mechanism | other
- statement_type：fact | author_interpretation | model_inference | unclear
- study_model：human | animal | cell | biochemical | computational | mixed | unclear
- methods：研究方法，原文未写则 null
- reported_results：原文报告的结果，保留数值与单位；未写则 null
- source_location：对象，含 locator（abstract | fulltext | none）、section、paragraph、quote
- limitations：作者报告的局限；未写则 null
- confidence：0 到 1 之间的小数

## 硬规则（v3）

1. **一条证据只对应一个结果数值 / 一个比较方向。**
   原文一句话给出多组“条件—数值”时，必须拆成多条；不得把多个数值塞进同一条 claim。
2. **条件和数值必须同时出现在 quote 里。**
   例如 claim 写“0.5mM AA 诱导的聚集抑制 97%”，quote 中必须同时出现 0.5mM AA 和 97%。
3. **遇到 respectively / 分别时格外小心。**
   claim 必须保留原本的对应顺序，或拆条并引用完整对应句；不得把数值重新分配给 quote 中未出现的条件。
4. claim 中的每个数字、单位、剂量、时间，都必须在 quote 中同时出现。
5. 不得把相邻句、其他段落或常识补进 claim；文献总体人群/背景可作主语，但不得改变结果。
6. 做不到以上要求时，降低 claim 的信息量；仍然做不到就输出 {"evidence": []}。
7. 宁可少抽一条，也不要把两条结果合并成一条。

## 其他规则

- 综述中的转述用 review_summary，不得伪装成 primary_result。
- 体外或动物结果必须如实标注 study_model，不得写成人体结论。
- 只有摘要时 locator 用 abstract，不要假装读过全文。
- 没有可抽取的证据时输出 {"evidence": []}。

## 硬规则（v4 追加，专补召回）

8. **必须抽取作者的解释、推测、适用性声明与局限**，statement_type 用 author_interpretation。
   尤其不要漏掉“某类人群的问题未回答 / 结论不能推广 / 证据不足”这类句子。
9. **绝对风险与长期风险单独成条**：每 1000 人年、每 1000 人 10 年、NNT/NNH 等，
   保留原数值、时间窗与人群；不要只抽相对风险（RR/HR）。
10. **不要因为句子没有数值就跳过结论性陈述**；只要它能被 quote 逐字定位，就应抽取。
11. 这些新增条目仍然遵守“一条证据一个结果”，不得把多个数字合并。
