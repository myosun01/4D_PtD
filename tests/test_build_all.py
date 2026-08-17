"""v3.8 Part E — build_all 의존성 사전 점검."""
from scripts import build_all


def test_build_all_dependencies_present():
    assert build_all.missing_dependencies() == []


def test_missing_dependency_is_reported_by_package_name(monkeypatch):
    real = build_all.importlib.util.find_spec

    def fake_find_spec(module):
        return None if module == "rdflib" else real(module)

    monkeypatch.setattr(build_all.importlib.util, "find_spec", fake_find_spec)
    assert build_all.missing_dependencies() == ["rdflib"]
