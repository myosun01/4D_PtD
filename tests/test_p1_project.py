"""P1-2 — project/*.json 4종 스키마 정합 및 상호참조 무결성 (ROADMAP §3).

site/schedule/crews/lifecycle_bindings 간 층ID·셀·템플릿·공종 참조가 서로 맞고,
셀 타입이 §2 어휘 계약을 지키며, 위험 인스턴스 셀이 격자 범위 내인지 확인한다.
"""
import json
import pathlib

from schedule import Schedule, TRADES

ROOT = pathlib.Path(__file__).resolve().parent.parent
PROJECT = ROOT / "project"
VALID_CELL_TYPES = {0, 1, 2, 4, 5, 6, 7}       # §2 어휘 계약
LEVELS = {f"L{i}" for i in range(1, 9)}         # L1..L8


def _load(name):
    with open(PROJECT / name, encoding="utf-8") as fp:
        return json.load(fp)


def test_all_json_present():
    for f in ("site.json", "schedule.json", "crews.json", "lifecycle_bindings.json"):
        assert (PROJECT / f).exists(), f


def test_site_schema():
    site = _load("site.json")
    assert site["siteID"] and site["gridResolution_m"] == 1.0
    assert len(site["levels"]) == 8
    for lv in site["levels"]:
        assert lv["levelID"] in LEVELS
        g = lv["grid"]
        assert len(g["cells"]) == g["rows"]
        assert all(len(row) == g["cols"] for row in g["cells"])
        used = {c for row in g["cells"] for c in row}
        assert used <= VALID_CELL_TYPES, (lv["levelID"], used - VALID_CELL_TYPES)


def test_site_vertical_links_within_grid():
    site = _load("site.json")
    assert len(site["verticalLinks"]) == 16
    dims = {lv["levelID"]: (lv["grid"]["rows"], lv["grid"]["cols"]) for lv in site["levels"]}
    for link in site["verticalLinks"]:
        assert isinstance(link["linkType"], str) and link["linkType"]
        assert len(link["connects"]) >= 2
        for c in link["connects"]:
            assert c["level"] in LEVELS
            r, col = c["cell"]
            rows, cols = dims[c["level"]]
            assert 0 <= r < rows and 0 <= col < cols


def test_crews_schema():
    crews = _load("crews.json")
    assert [t["trade"] for t in crews["trades"]] == list(TRADES)
    # 공종별 rho 동일 분포 (ROADMAP §3: 문헌 근거 미확보 → 전 공종 동일).
    rhos = {(t["rho"]["min"], t["rho"]["max"]) for t in crews["trades"]}
    assert len(rhos) == 1
    soc = crews["social"]
    assert soc["witnessShock"]["sameLevelOnly"] is True
    assert "imitation" in soc


def test_site_levels_match_schedule(real_schedule):
    site = _load("site.json")
    site_levels = {lv["levelID"] for lv in site["levels"]}
    sched_levels = {a.level for a in real_schedule.activities.values()}
    assert site_levels == LEVELS
    assert sched_levels <= site_levels


def test_bindings_cells_within_grid(real_lifecycle):
    site = _load("site.json")
    dims = {lv["levelID"]: (lv["grid"]["rows"], lv["grid"]["cols"]) for lv in site["levels"]}
    for h in real_lifecycle.instances:
        assert h.level in dims, h.instance_id
        rows, cols = dims[h.level]
        for (r, c) in h.cells:
            assert 0 <= r < rows and 0 <= c < cols, (h.instance_id, r, c)


def test_bindings_templates_are_ttl_four(real_lifecycle, library):
    used = {h.template_id for h in real_lifecycle.instances}
    assert used <= set(library.lifecycle_templates)
