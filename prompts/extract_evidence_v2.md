# 任务：从单篇文献中抽取可核查的证据条目（v2，claim 不得超出引句）

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
  - fact：原文直接报告的事实、数据或结果
  - author_interpretation：作者的解释、推测、观点（claim 含“作者认为/提示/可能”时必须用这个）
  - model_inference：你基于原文做的推断，不得冒充原文
- study_model：human | animal | cell | biochemical | computational | mixed | unclear
- methods：研究方法，原文未写则 null
- reported_results：原文报告的结果，保留数值与单位；未写则 null
- source_location：对象，含 locator（abstract | fulltext | none）、section、paragraph、quote
- limitations：作者报告的局限；未写则 null
- confidence：0 到 1 之间的小数

## 硬规则（v2 新增）

1. claim 只能包含 quote 中明确出现的事实要素：剂量、人群、研究模型、机制、因果词都必须在 quote 里出现。
2. 不得把相邻句、摘要其他段落、全文其他章节或常识补进 claim。
3. 一条证据只对应一个连续引句；宁可拆成两条，也不要把两处内容合并。
4. 若完整意思需要更多上下文，把 quote 扩成能独立支撑 claim 的连续片段（最多 80 词），不得用省略号拼接。
5. 做不到以上要求时，降低 claim 的信息量；仍然做不到就输出 {"evidence": []}。

## 其他规则

- 综述中的转述用 review_summary，不得伪装成 primary_result。
- 体外或动物结果必须如实标注 study_model，不得写成人体结论。
- 只有摘要时 locator 用 abstract，不要假装读过全文。
- 没有可抽取的证据时输出 {"evidence": []}。
