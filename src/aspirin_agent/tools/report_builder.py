"""生成可追溯的 Markdown 报告。"""

from __future__ import annotations

from datetime import datetime, timezone

from ..licensing import classify_license, license_label
from ..schemas import (
    Article,
    Evidence,
    EvidenceType,
    ExtractionFailure,
    FullTextStatus,
    PublicationType,
    Report,
    StatementType,
    Verification,
    VerificationStatus,
)

EVIDENCE_TYPE_LABELS = {
    EvidenceType.PRIMARY_RESULT: "原始结果",
    EvidenceType.SECONDARY_RESULT: "二次分析",
    EvidenceType.REVIEW_SUMMARY: "综述转述",
    EvidenceType.MECHANISM: "机制证据",
    EvidenceType.OTHER: "其他",
}

STATEMENT_TYPE_LABELS = {
    StatementType.FACT: "原文事实",
    StatementType.AUTHOR_INTERPRETATION: "作者解释",
    StatementType.MODEL_INFERENCE: "模型推断",
    StatementType.UNCLEAR: "未说明",
}

STUDY_MODEL_LABELS = {
    "human": "人体研究",
    "animal": "动物研究",
    "cell": "细胞实验",
    "biochemical": "生化实验",
    "computational": "计算研究",
    "mixed": "混合",
    "unclear": "未说明",
}

PUBLICATION_TYPE_LABELS = {
    PublicationType.SYSTEMATIC_REVIEW: "系统综述",
    PublicationType.META_ANALYSIS: "Meta 分析",
    PublicationType.REVIEW: "综述",
    PublicationType.RCT: "随机对照试验",
    PublicationType.COHORT: "队列研究",
    PublicationType.CASE_CONTROL: "病例对照",
    PublicationType.CASE_REPORT: "病例报告",
    PublicationType.PRECLINICAL: "临床前研究",
    PublicationType.OTHER: "其他",
}

FULLTEXT_LABELS = {
    FullTextStatus.NOT_FETCHED: "未抓取",
    FullTextStatus.ABSTRACT_ONLY: "仅摘要",
    FullTextStatus.FULLTEXT_AVAILABLE: "全文可用",
    FullTextStatus.FULLTEXT_UNAVAILABLE: "全文不可用",
}

STATUS_LABELS = {
    VerificationStatus.PENDING: "待核查",
    VerificationStatus.PARTIAL: "部分通过",
    VerificationStatus.PASSED: "通过",
    VerificationStatus.FAILED: "未通过",
    VerificationStatus.NOT_VERIFIABLE: "无法核查",
}

BOOL_LABELS = {True: "通过", False: "不通过", None: "未核查"}


def _text_or_missing(value: str | None, label: str = "未报告") -> str:
    return value if value else f"{label}（原文未提供）"


def _location_text(item: Evidence) -> str:
    location = item.source_location
    if not location.is_locatable:
        return "未定位（不得作为已核实结论）"
    parts = [location.locator]
    if location.section:
        parts.append(location.section)
    if location.paragraph:
        parts.append(f"第 {location.paragraph} 段")
    quote = location.quote or ""
    return f"{' · '.join(parts)}；引句：{quote}"


def build_markdown(
    articles: list[Article],
    evidence: list[Evidence],
    verifications: list[Verification],
    question: str = "",
    title: str = "阿司匹林研究证据简报",
    extraction_failures: list[ExtractionFailure] | None = None,
    low_confidence_filtered: int = 0,
) -> str:
    status_by_evidence = {item.evidence_id: item for item in verifications}
    counts = {status: 0 for status in VerificationStatus}
    for check in verifications:
        counts[check.final_status] += 1

    lines: list[str] = [
        f"# {title}",
        "",
        f"> 研究问题：{question or '未填写'}",
        f"> 生成时间：{datetime.now(timezone.utc).astimezone().strftime('%Y-%m-%d %H:%M')}",
        "",
        "## 摘要",
        "",
        (
            f"纳入 {len(articles)} 篇文献，抽取 {len(evidence)} 条证据；"
            f"核查结果：通过 {counts[VerificationStatus.PASSED]} 条、"
            f"部分通过 {counts[VerificationStatus.PARTIAL]} 条、"
            f"未通过 {counts[VerificationStatus.FAILED]} 条、"
            f"无法核查 {counts[VerificationStatus.NOT_VERIFIABLE]} 条。"
        ),
        "",
        "缺失信息一律标注为“未报告”，不做推测补全。",
        "",
    ]
    if low_confidence_filtered:
        lines += [f"低置信度未纳入 {low_confidence_filtered} 条（阈值见 config/settings.yaml）。", ""]
    lines += ["## 证据条目", ""]

    if not evidence:
        lines += ["（本轮未抽取到证据）", ""]
    for index, item in enumerate(evidence, start=1):
        check = status_by_evidence.get(item.evidence_id)
        status = check.final_status if check else item.verification_status
        lines += [
            f"### {index}. {item.claim}",
            "",
            f"- 证据 ID：{item.evidence_id}（PMID {item.pmid}）",
            (
                f"- 证据类型：{EVIDENCE_TYPE_LABELS.get(item.evidence_type, '其他')}；"
                f"陈述类型：{STATEMENT_TYPE_LABELS.get(item.statement_type, '未说明')}；"
                f"研究模型：{STUDY_MODEL_LABELS.get(item.study_model.value, '未说明')}"
            ),
            f"- 方法：{_text_or_missing(item.methods)}",
            f"- 原文报告结果：{_text_or_missing(item.reported_results)}",
            f"- 来源位置：{_location_text(item)}",
            f"- 局限：{_text_or_missing(item.limitations)}",
            *(
                [f"- 校验提示：{'；'.join(item.validation_notes)}"]
                if item.validation_notes
                else []
            ),
            f"- 置信度：{item.confidence:.2f}；核查状态：{STATUS_LABELS[status]}",
            "",
        ]

    if extraction_failures:
        lines += ["## 抽取失败", ""]
        for failure in extraction_failures:
            lines.append(f"- PMID {failure.pmid}：{failure.error}")
        lines.append("")

    lines += [
        "## 核查",
        "",
        "| 证据 | 标识符 | 标题 | 来源可访问 | 主张支持 | 状态 | 问题 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    if not verifications:
        lines.append("| - | 未核查 | 未核查 | 未核查 | 未核查 | - | 无证据条目 |")
    for check in verifications:
        issues = "；".join(check.issues) if check.issues else "无"
        lines.append(
            f"| {check.evidence_id} | {BOOL_LABELS[check.identifier_check]} | "
            f"{BOOL_LABELS[check.title_check]} | {BOOL_LABELS[check.source_accessible]} | "
            f"{BOOL_LABELS[check.claim_supported]} | "
            f"{STATUS_LABELS[check.final_status]} | {issues} |"
        )
    lines.append("")

    lines += ["## 文献清单", ""]
    if not articles:
        lines.append("（无）")
    for article in articles:
        year = article.year or "n.d."
        journal = article.journal or "未知期刊"
        link = article.url or (
            f"https://pubmed.ncbi.nlm.nih.gov/{article.pmid}/" if article.pmid else "#"
        )
        missing = "、".join(article.missing_fields) or "无"
        permission = classify_license(article.license, article.license_url)
        lines.append(
            f"- {year} · {journal} · {PUBLICATION_TYPE_LABELS.get(article.publication_type, '其他')} · "
            f"[{article.title}]({link}) · 全文：{FULLTEXT_LABELS[article.fulltext_status]} · "
            f"许可：{license_label(permission)} · 缺失字段：{missing}"
        )
    lines += [
        "",
        "---",
        "",
        "本报告由程序生成，仅供研究参考，不构成医学建议。",
        "全文来自 PMC 开放获取子集，仅用于本地研究；对外转载需逐篇核对许可与署名。",
        "",
    ]
    return "\n".join(lines)


def build_report(
    articles: list[Article],
    evidence: list[Evidence],
    verification_results: list[Verification],
    question: str | None = None,
    title: str = "阿司匹林研究证据简报",
    extraction_failures: list[ExtractionFailure] | None = None,
    low_confidence_filtered: int = 0,
) -> Report:
    if question is None and evidence:
        question = evidence[0].research_question
    question = question or ""

    passed = sum(
        1
        for check in verification_results
        if check.final_status is VerificationStatus.PASSED
    )
    return Report(
        title=title,
        question=question,
        summary=(
            f"纳入 {len(articles)} 篇文献，抽取 {len(evidence)} 条证据，"
            f"{passed} 条核查通过。"
        ),
        evidence=evidence,
        verifications=verification_results,
        extraction_failures=extraction_failures or [],
        low_confidence_filtered=low_confidence_filtered,
        markdown=build_markdown(
            articles,
            evidence,
            verification_results,
            question,
            title,
            extraction_failures=extraction_failures,
            low_confidence_filtered=low_confidence_filtered,
        ),
    )
