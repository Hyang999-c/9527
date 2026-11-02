from __future__ import annotations

from aspirin_agent.licensing import LicenseClass, classify_license, license_label


def test_cc_by_allows_commercial_and_derivatives() -> None:
    info = classify_license(
        "This is an open-access article",
        "https://creativecommons.org/licenses/by/4.0/",
    )

    assert info.license_class is LicenseClass.CC_BY
    assert info.commercial_ok is True
    assert info.derivatives_ok is True
    assert info.attribution_required is True


def test_cc_by_nc_blocks_commercial() -> None:
    info = classify_license("CC BY-NC 4.0", "https://creativecommons.org/licenses/by-nc/4.0/")

    assert info.license_class is LicenseClass.CC_BY_NC
    assert info.commercial_ok is False
    assert info.derivatives_ok is True


def test_cc_by_nc_nd_blocks_derivatives() -> None:
    info = classify_license("CC BY-NC-ND", "https://creativecommons.org/licenses/by-nc-nd/4.0/")

    assert info.license_class is LicenseClass.CC_BY_NC_ND
    assert info.commercial_ok is False
    assert info.derivatives_ok is False


def test_cc_by_sa_requires_share_alike() -> None:
    info = classify_license("CC BY-SA 4.0")

    assert info.license_class is LicenseClass.CC_BY_SA
    assert info.commercial_ok is True
    assert info.derivatives_ok is True


def test_cc0_is_public_domain() -> None:
    info = classify_license("CC0 1.0 Universal")

    assert info.license_class is LicenseClass.CC0
    assert info.attribution_required is False


def test_unknown_license_is_flagged() -> None:
    info = classify_license(None, None)

    assert info.license_class is LicenseClass.UNKNOWN
    assert "人工核对" in info.note
    assert "UNKNOWN" in license_label(info)
