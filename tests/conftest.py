"""pytest 공용 설정 — 프로젝트 루트를 import 경로에 넣고, 공용 픽스처 제공.

실행: 프로젝트 루트에서 `python -m pytest tests/ -q`
"""
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pytest                       # noqa: E402
import ptd_ttl                      # noqa: E402
from schedule import Schedule       # noqa: E402
from lifecycle import LifecycleEngine  # noqa: E402

PROJECT = ROOT / "project"


@pytest.fixture(scope="session")
def library():
    """로드된 TTL 라이브러리(v2). rdflib/ttl 미가용 시 해당 테스트는 skip."""
    if ptd_ttl.LIBRARY is None:
        pytest.skip("rdflib/ptd_library.ttl 미가용 (폴백 모드)")
    return ptd_ttl.LIBRARY


@pytest.fixture(scope="session")
def real_schedule():
    """실제 프로젝트 공정표 (project/schedule.json)."""
    return Schedule.load(str(PROJECT / "schedule.json"))


@pytest.fixture(scope="session")
def real_lifecycle(library, real_schedule):
    """실제 바인딩으로 조립한 생멸 엔진 (project/lifecycle_bindings.json)."""
    return LifecycleEngine(library.lifecycle_templates,
                           str(PROJECT / "lifecycle_bindings.json"),
                           real_schedule)


@pytest.fixture(scope="session")
def site_model():
    """실제 다층 현장 모델 (project/site.json). Phase 2."""
    from site_model import SiteModel
    return SiteModel.load(str(PROJECT / "site.json"))


@pytest.fixture(scope="session")
def project4d(library):
    """4D 실행에 필요한 (schedule, site, lifecycle, crews_cfg) 일괄 로드. Phase 2."""
    import fourd
    return fourd.load_project(str(PROJECT), library=library)
