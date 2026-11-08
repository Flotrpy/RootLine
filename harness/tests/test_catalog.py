import re
from pathlib import Path

from rootline_harness import catalog

GO_CATALOG = Path(__file__).parents[2] / "controller" / "internal" / "catalog" / "catalog.go"


def test_faults_match_go_catalog() -> None:
    src = GO_CATALOG.read_text()
    go_faults = re.findall(r'\{Name: "([A-Za-z]+)"', src)
    assert tuple(go_faults) == catalog.FAULTS + catalog.HW_FAULTS


def test_hardware_counterparts_match_go_catalog() -> None:
    src = GO_CATALOG.read_text()
    pairs = dict(re.findall(r'\{Name: "(hw[A-Za-z]+)".*?Emulates: "([A-Za-z]+)"', src, re.S))
    assert pairs == catalog.HW_EMULATES


def test_flags_match_go_catalog() -> None:
    src = GO_CATALOG.read_text()
    go_flags = re.findall(r'Flag: "([A-Za-z]+)"', src)
    assert tuple(go_flags) == catalog.FLAGS


def test_categories_match_go_catalog() -> None:
    src = GO_CATALOG.read_text()
    go_cats = set(re.findall(r'Cat\w+\s+= "([a-z_]+)"', src))
    assert go_cats == set(catalog.CATEGORIES)


def test_every_label_service_is_known() -> None:
    src = GO_CATALOG.read_text()
    for svc in set(re.findall(r'Service: "([a-z-]+)"', src)) - {"none"}:
        assert svc in catalog.SERVICES


def test_forbidden_strings_cover_flags() -> None:
    forbidden = catalog.forbidden_strings()
    assert "paymentFailure" in forbidden
    assert "toxiReset" in forbidden
    assert "healthy" not in forbidden
