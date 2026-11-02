"""PMC 许可分类与基本使用权限判断（非法律意见）。"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel


class LicenseClass(str, Enum):
    CC0 = "cc0"
    CC_BY = "cc_by"
    CC_BY_SA = "cc_by_sa"
    CC_BY_NC = "cc_by_nc"
    CC_BY_NC_SA = "cc_by_nc_sa"
    CC_BY_NC_ND = "cc_by_nc_nd"
    OTHER = "other"
    UNKNOWN = "unknown"


class LicenseInfo(BaseModel):
    license_class: LicenseClass
    commercial_ok: bool | None = None
    derivatives_ok: bool | None = None
    attribution_required: bool | None = None
    note: str = ""


def classify_license(text: str | None, url: str | None = None) -> LicenseInfo:
    haystack = f"{text or ''} {url or ''}".lower()

    if "cc0" in haystack or "publicdomain/zero" in haystack:
        return LicenseInfo(
            license_class=LicenseClass.CC0,
            commercial_ok=True,
            derivatives_ok=True,
            attribution_required=False,
            note="公共领域，可商用/可改作",
        )
    if "by-nc-nd" in haystack or "by_nc_nd" in haystack:
        return LicenseInfo(
            license_class=LicenseClass.CC_BY_NC_ND,
            commercial_ok=False,
            derivatives_ok=False,
            attribution_required=True,
            note="非商用、不可改作，需署名",
        )
    if "by-nc-sa" in haystack or "by_nc_sa" in haystack:
        return LicenseInfo(
            license_class=LicenseClass.CC_BY_NC_SA,
            commercial_ok=False,
            derivatives_ok=True,
            attribution_required=True,
            note="非商用、可改作需同许可，需署名",
        )
    if "by-nc" in haystack or "by_nc" in haystack:
        return LicenseInfo(
            license_class=LicenseClass.CC_BY_NC,
            commercial_ok=False,
            derivatives_ok=True,
            attribution_required=True,
            note="非商用、可改作，需署名",
        )
    if "by-sa" in haystack or "by_sa" in haystack:
        return LicenseInfo(
            license_class=LicenseClass.CC_BY_SA,
            commercial_ok=True,
            derivatives_ok=True,
            attribution_required=True,
            note="可商用、可改作需同许可，需署名",
        )
    if "creativecommons.org/licenses/by/" in haystack or "by/4.0" in haystack or "by/3.0" in haystack:
        return LicenseInfo(
            license_class=LicenseClass.CC_BY,
            commercial_ok=True,
            derivatives_ok=True,
            attribution_required=True,
            note="可商用、可改作，需署名",
        )
    if "public domain" in haystack:
        return LicenseInfo(
            license_class=LicenseClass.CC0,
            commercial_ok=True,
            derivatives_ok=True,
            attribution_required=False,
            note="公共领域，可商用/可改作",
        )
    if haystack.strip():
        return LicenseInfo(
            license_class=LicenseClass.OTHER,
            note="非标准许可，需人工核对",
        )
    return LicenseInfo(license_class=LicenseClass.UNKNOWN, note="未提供许可，需人工核对")


def license_label(info: LicenseInfo) -> str:
    label = info.license_class.value.upper().replace("_", " ")
    return f"{label}（{info.note}）"
