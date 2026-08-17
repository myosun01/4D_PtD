# AGENTS.md — 4D PtD Simulation 프로젝트 규약

이 저장소는 RC 골조 공사의 4D(공정 연동) PtD 시뮬레이션 엔진 개발 프로젝트다.
**작업 시작 전 반드시 `ROADMAP.md`를 읽고, 현재 Phase의 작업만 수행한다.**
Phase를 건너뛰거나 병합하지 않는다. 각 작업 완료 시 ROADMAP.md의 체크박스를 갱신한다.

## 절대 원칙 (위반 금지)

1. **`ptd_library.ttl` 직접 수정 금지.** 이 파일은 `ptd_library_master.xlsx`에서
   `build_ttl_from_master.py`로 생성되는 산출물이다. 라이브러리 항목의 추가·수정이
   필요하면 xlsx를 수정하고 재생성한다.
2. **대책(HoC 대안)의 효과 수치를 코드에 하드코딩 금지.** 모든 효과 계수·규칙은
   TTL에서만 온다. 시뮬레이션 파라미터가 필요한데 TTL에 없으면, 코드에 박지 말고
   xlsx에 항목을 추가(evidenceLevel="heuristic", sensitivityTarget=true)한 뒤 재생성.
3. **프로젝트 데이터(현장·공정·크루)는 JSON, 지식(대안·규칙·근거)은 TTL.**
   이 경계를 흐리지 않는다. JSON에 대책 효과를, TTL에 특정 현장 좌표를 넣지 않는다.
4. **기존 2D 엔진(movement.py의 핵심 로직)은 삭제하지 않는다.** 4D는 2D 하루 커널을
   재사용하며, 2D 결과는 검증 베이스라인이다 (ROADMAP Phase 5 참조).
5. **재현성**: 모든 확률 사용처는 시드 주입 가능해야 하고, 동일 시드 → 비트 동일 결과.

## 파일 맵

| 파일 | 역할 | 수정 |
|---|---|---|
| config.py | 2D 상수 (셀 타입, 속도, 확률) | Phase 2에서 확장 |
| movement.py | 2D 엔진 (격자·A*·Worker·step_world·run_one_day·보정) | 하루 커널로 재사용 |
| social.py | 사회 전염 (witness shock, imitation) | Phase 4에서 크루 구조화 |
| ptd_ttl.py | TTL 로더 v1 | **Phase 1에서 v2로 개조 (첫 작업)** |
| viewer.py | 실행 진입점 (배치 MC + 관전 모드) | Phase 2·4에서 일 루프 연동 |
| ptd_library.ttl | 지식 라이브러리 v2 (KE 75 / EA 25 / 규칙 3유형) | **읽기 전용** |
| ptd_library_master.xlsx | 라이브러리 단일 원천 (11시트) | 항목 변경 시에만 |
| build_ttl_from_master.py | xlsx → ttl 생성기 | 스키마 확장 시에만 |
| project/ (신규 생성) | site.json, schedule.json, crews.json, lifecycle_bindings.json | Phase 1 |
| tests/ (신규 생성) | pytest 테스트 | 각 Phase마다 추가 |

## 작업 규약

- 각 Phase 완료 조건(DoD)은 ROADMAP.md에 정의됨. DoD의 테스트가 전부 통과해야 다음 Phase.
- 새 기능마다 tests/에 pytest 추가. 실행: `python -m pytest tests/ -q`
- TTL 로딩 검증: `python -c "import ptd_ttl; ptd_ttl.load_library()"` 가 항상 성공해야 함.
- rdflib 미설치 환경 폴백(기존 v1 로더의 Base 폴백 동작)은 유지한다.
- 커밋은 작업 단위로 작게. 메시지에 Phase 번호 명시 (예: "P1: schedule.json CPM 파서").
- 모호하면 ROADMAP.md의 어휘 계약(§2)과 데이터 계약(§3)이 정답이다. 임의로 이름을
  바꾸지 않는다 (예: trade는 rebar/formwork_erection/concrete_pour/formwork_stripping/
  material_handling 5개 고정).
