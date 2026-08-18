# ROADMAP.md — 4D PtD Simulation 전체 프레임

> 목표: 2D 정적 시뮬레이터를 **공정 스케줄 연동 4D 엔진**으로 확장하여,
> ① 공정 진행에 따라 위험요소가 생성·소멸하고 ② 매일 다른 공종 구성의 작업자가 투입되며
> ③ PtD 대안이 위험 **인스턴스 단위**로 적용·재시뮬레이션되는 폐루프를 완성한다.
> 산출 지표는 λ(cell, day)와 심각도 가중 위험(SWR)이며, 목적은 HoC 대안(제거~PPE)의
> 효과를 대안 적용 전후 비교로 정량화하는 것이다.
>
> 이 문서는 자급자족이다 — 외부 문서 없이 여기 정의된 계약만으로 구현 가능해야 한다.
> 진행 상태는 §7 체크리스트에 기록한다.

---

## §1. 아키텍처 핵심 결정 (변경 불가)

1. **시간 해상도 = 일(day).** 액티비티 상태 전이(not_started→in_progress→completed)는
   일 경계에서만 판정. 하루 동안 격자·크루·effects 불변 → 기존 `_CTX` 정적 캐시가
   하루 단위로 유효. **4D = "날마다 다른 격자·다른 크루로 2D 하루를 N번 도는 것".**
2. **하이브리드 직렬화**: 지식(대안·규칙·근거) = ptd_library.ttl / 프로젝트 사실
   (공간·공정·크루·바인딩) = project/*.json 4개 파일.
3. **시간축의 원천은 schedule.json 하나.** 위험 생멸, 대책 설치, 크루 투입 전부
   Activity.state 전이가 트리거.
4. **동결 스코프**: 크레인·차량·이동형 위험(H003/H006), 온열, 절단·베임은 구현하지
   않는다. 코드 자리(셀 타입 7 등)는 예약만.
5. **몬테카를로**: 사고를 표집하지 않고 기대위험 λ = 노출스텝 × 채널별 per-step 확률을
   누적 (기존 run_one_day 방식 승계, day 축 추가).

## §2. 어휘 계약 (이름 고정 — 임의 변경 금지)

**Trade (5)**: `rebar / formwork_erection / concrete_pour / formwork_stripping / material_handling`

**셀 타입**: `0 walkable / 1 wall / 2 floor_opening / 4 material / 5 narrow / 6 edge(신설) / 7 vehicle_route(예약·미사용)`

**위험 채널과 노출 정의**:
| 채널 | 노출 정의 | 신설 여부 |
|---|---|---|
| fall (opening/edge) | 개구부·단부 셀 및 인접 체류 | edge를 1급 셀로 승격 |
| material | 적재물 셀 인접 체류 (넘어짐·물체에맞음의 혼잡 노출 포함) | 해석 확장 |
| narrow | 협소 셀 통행 | 승계 |
| **collapse_zone** | 타설 시작~해체 완료 사이 동바리 존치 구간의 **직하부 층** 체류 | 신설 (다층 4D 고유) |
| **drop_zone** | 상층 해체·자재취급 구역의 직하부 셀 체류 | 신설 (다층 4D 고유) |

**HazardType**: H001 개구부, H002 협소, H004 적재, H005 고소, H007 단부, H008 동바리붕괴(collapse_zone), H009 낙하물구역(drop_zone). H003/H006 동결.

**채널별 확률 보정 기준** (기존 단일 재해율 비례 분배 폐지):
사망 가중 — 떨어짐 41.2% / 물체에맞음 11.9% / 부딪힘 10.2% / 끼임 8.3% / 무너짐 6.3%
(고용노동부 2025 재해조사, 전 업종). RC 빈도 가중 — 넘어짐 30.8% / 물체에맞음 17.5% /
떨어짐 11.6% / 끼임 9.8% / 부딪힘 8.4% / 무너짐 0.1% (CSI RC 1,368건, 2025).
채널별 per-step 확률은 위 분포로 분배 후 기존 자기보정 루프(노출량 역산)를 채널별로 적용.

**요소 식별 키 (고정)**: `element_key = { "ifc_guid": <IfcRoot.GlobalId>, "revit_uid": null }`
— `revit_uid`는 추후 Revit 애드인 모드용 예약 필드, 현재는 항상 null.

**좌표 정본 (고정)**: IFC 월드좌표(m, Z-up). 모든 교환 파일(site.json, manifest.json)의
좌표는 이 프레임. 소비자(Unity 등)는 단일 변환 함수로만 자기 좌표계로 변환한다.

## §3. 데이터 계약 — project/*.json (Phase 1에서 이 스키마대로 생성)

```jsonc
// project/site.json
{ "siteID": "PRJ001", "schemaVersion": "1.1", "gridResolution_m": 1.0,
  "gridFrame": {
    "origin_xy_m": [-11.0, 19.0],          // 셀 (0,0)의 최소 코너, IFC 월드좌표(m)
    "resolution_m": 1.0,
    "axisMapping": { "row": "+Y", "col": "+X" },   // r=floor((y-oy)/res), c=floor((x-ox)/res)
    "worldCRS": "IFC world coordinates, meters, Z-up",
    "cellCenter": "world_xy = origin + (index + 0.5) * resolution" },
  "levels": [ { "levelID": "L1", "elevation_m": 0.0, "sourceIfcStorey": null,
      "sourceIfcStoreyGuid": null,         // IfcBuildingStorey GlobalId — 이름은 중복 가능, GUID가 정본 키
      "grid": { "rows": 30, "cols": 44, "cells": [[...]] },     // 셀 타입 코드 2차원 배열
      "zones": [ { "zoneID": "Z-A", "zoneType": "work", "cells": [[r,c], ...] } ] } ],
  "verticalLinks": [ { "linkID": "ST1", "linkType": "stair",
      "connects": [ {"level":"L1","cell":[2,40]}, {"level":"L2","cell":[2,40]} ],
      "capacity": 2, "traversalSteps": 40, "availableFromActivity": null } ] }
// zoneType 어휘: work / storage / route / restricted / welfare

// project/schedule.json  ★시작·종료일 입력 금지 — 엔진이 CPM 전진계산으로 산출
{ "scheduleID": "PRJ001-S1",
  "calendar": { "workdays": "MON-SAT", "holidays": [] },
  "activities": [ { "activityID": "A-1030", "name": "3층 슬래브 타설",
      "trade": "concrete_pour", "zone": "L3:Z-A", "duration_days": 2,
      "predecessors": [ {"activity":"A-1020","relation":"FS","lag_days":0} ],
      "crewSize": 8, "dailyPattern": {"dwellMinutes":360,"tasksPerWorker":4},
      "workType": "slab" } ] }
// relation: FS/SS/FF. workType은 생멸규칙 트리거 매칭용 (slab/opening_closure/
// perimeter_protection/delivery/consume_or_remove/permanent_stair 등)

// project/crews.json
{ "trades": [ { "trade": "rebar",
      "rho": {"dist":"truncnorm","mean":null,"sd":null,"min":0.15,"max":0.90} } ],
  "foremanRho": 0.20,
  "social": { "witnessShock": {"deltaRho":-0.15,"radiusCells":3,"sameLevelOnly":true},
              "imitation": {"periodSteps":30,"wIntraCrew":null,"wInterCrew":null} } }
// 공종별 rho 분화 금지(문헌 근거 미확보) — 전 공종 동일 분포로 시작. null=전역 기본값.

// project/lifecycle_bindings.json
{ "bindings": [ { "template": "LCR_SLAB_OPENING", "boundActivity": "A-1030",
      "spawnLocation": {"level":"L3","cells":[[19,4]]}, "despawnActivity": "A-1180" } ] }
// template ID는 TTL의 LifecycleRuleTemplate 4종:
//   LCR_SLAB_OPENING (타설완료→개구부 spawn / 마감완료→despawn)
//   LCR_SLAB_EDGE (타설완료→단부 spawn / 단부방호완료→despawn)
//   LCR_SHORING_COLLAPSE (타설시작→직하부 collapse_zone spawn / 해체완료→despawn)
//   LCR_MATERIAL_STORAGE (반입중→적재 spawn / 소진·반출완료→despawn)
```

## §4. TTL 계약 — ptd_library.ttl에서 로더가 읽어야 하는 것 (Phase 1)

네임스페이스: `http://construction-safety.org/ptd-hoc-ontology#`

| 클래스 | 수량 | 로더가 추출할 것 |
|---|---|---|
| ExecutableAlternative | 25 | alternativeID, fromEntry, hasHoCLevel, hasSimulationRule, installCostLevel, installDurationDays |
| SpatialChangeRule | 8 | simulationAction, appliesToCellType, applicabilityCondition, riskCoefficientMultiplier |
| AgentParameterRule | 12 | appliesToCellType, applicabilityCondition, *Multiplier 계수들(fallProb/hazardWeight/fatality/injury/collapseProb/materialProb/tripProb), sensitivityTarget |
| TemporalRule | 5 | scheduleShift (자유 텍스트 — Phase 3에서 파싱 규약 정의), 조건부 1개 포함 |
| LifecycleRuleTemplate | 4 | spawnTrigger, despawnTrigger, locationSelector, hasHazardType |
| KnowledgeEntry | 75 | (엔진 비소비 — SPARQL 질의 API만 제공) |
| CoverageCell / RiskScenario / Reference | 28/19/29 | (질의 API용) |

로더 v2 요구사항: ① 2층 구조 인식(EA만 엔진 소비), ② 규칙 3유형 각각을 파이썬
dataclass로, ③ TemporalRule의 scheduleShift 원문 보존, ④ rdflib 부재 시 v1과 동일한
Base 폴백, ⑤ `load_library()` 시그니처 하위호환(기존 viewer.py가 깨지지 않게).

## §5. Phase 정의 (순서 고정)

### Phase 1 — 데이터 계층 [완료 조건: tests/test_p1_*.py 전부 통과]
- [x] P1-1 `ptd_ttl.py` v2 로더 개조 (§4 계약). 검증: EA 25개 로드, 규칙 유형별 8/12/5,
      TemporalRule의 scheduleShift 텍스트 보존 확인. — (2026-07-07, tests/test_p1_loader.py)
- [x] P1-2 `project/` 샘플 데이터 생성. ROADMAP 예시(3층·30×44·25~30개) 대신 실제 IFC
      (ARK_NordicLCA…BuildingPermit_Revit.ifc)로 확장: 8층(L1~L8)·69×93 격자·
      계단 VerticalLink 16개·164 액티비티(공기 409일). §2/§3 계약 준수
      (셀타입 0/1/2/6, trade 5종, 위험 21인스턴스). — (2026-07-07, tests/test_p1_project.py)
- [x] P1-3 `schedule.py` 신규 — JSON 파서 + CPM 전진계산(FS/SS/FF+lag, 달력 반영) +
      `activeSet(d)`, `crewsOnSite(d)` API. 검증: 손계산 임계경로와 일치. — (2026-07-07, tests/test_p1_schedule.py)
- [x] P1-4 `lifecycle.py` 신규 — 템플릿(TTL)×바인딩(JSON) 조인 → 일자별
      HazardInstance 집합 `hazards(d)`. 검증: 타설 완료 익일 개구부 spawn,
      마감 완료 익일 despawn, collapse_zone이 직하부 층에 생성. — (2026-07-07, tests/test_p1_lifecycle.py)

### Phase 2 — 4D 코어 [완료 조건: 8층 실제 프로젝트로 N일 MC가 돌아가고 λ(cell,d) CSV 산출]
- [x] P2-1 config.py 확장 — EDGE(6)·VEHICLE_ROUTE(7) 셀타입 추가, §2 두 분포
      (사망가중·RC빈도) 상수화, 채널별 `CHANNEL_PER_STEP`(fall 앵커로 분해). 기존 2D
      상수·λ 불변(md5 회귀 고정). — (2026-07-07, tests/test_p2_config.py)
- [x] P2-2 다층 격자 + VerticalLink — `site_model.py`(SiteModel): 8층 격자·zone·계단
      링크 16, 층 인접 그래프, 다층 경로계획(층별 soft_route + 링크 Dijkstra, 엔드포인트
      walkable 스냅), `availableFromActivity` 게이팅, `LinkOccupancy` capacity, 층
      메인 컴포넌트. — (2026-07-07, tests/test_p2_site.py)
      ※ 링크 기반 층간 통근을 실제 워커 일 루프·Unity 궤적에 연결. L1 파생 입구에서
        작업층까지 계단 capacity·대기·통과시간을 적용하고 L1→L8 연속 통과 및 동일
        시드 재현성 검증 (2026-08-17, `worker_mobility.py`,
        `tests/test_worker_mobility.py`, `WORKER_ALGORITHM.md`).
- [x] P2-3 일 루프 — `fourd.py run_project(...)`: 매일 activeSet→층별 크루 생성(trade별
      crewSize, rho는 crews.json 표집)→hazards(d) 오버레이 격자→하루 커널 mc_runs회 MC
      →λ(level,cell,day,channel) 누적. 재현성(str 시드) 테스트 포함. — (2026-07-07,
      tests/test_p2_run.py)
      ※ 하루 커널은 movement.soft_route(층 2D A*)+λ 공식을 재사용하되 4D 크루·다층·6채널용
        경량 워커 루프로 감쌌다(step_world는 미변경). 2D 완전 동등(P5-1)은 Phase 5에서 확정.
- [x] P2-4 신규 채널 — collapse_zone(직하부)·drop_zone(예약)·edge(단부 분리) 채널화.
      검증: 위험 활성일+직하부 크루 → collapse λ>0, 비활성일 → 0. — (2026-07-07,
      tests/test_p2_run.py::test_collapse_channel_only_when_active)
      ※ 실제 데이터는 직렬 공정이라 하부층에 동시 크루가 없어 collapse 실노출=0(데이터
        이슈 #1). 메커니즘은 extra_crews 강제투입으로 검증.
- [x] P2-5 산출 — `output/lambda_daily.csv`(level,row,col,day,channel,lambda),
      `exposure_by_trade.csv`(day,trade,crew,exposure_steps). 공종 투입곡선이
      schedule.crewsOnSite와 정합(mismatch 0). — (2026-07-07, tests/test_p2_run.py,
      check_p2.py)

### Phase 3 — 대책 적용 계층 [완료 조건: 대안 1개 적용 전후 λ 차이가 산출]
- [x] P3-1 ControlApplication — `controls.py`: `{alternative(TTL AltID), target_instance,
      install_activity}`. 위험 인스턴스 단위. 적용가능 대안 질의(cell-type 매칭, HoC순,
      조건/무조건 필터, TTL SPARQL). — (2026-07-08, tests/test_p3_controls.py)
      ※ HOC_SCENARIOS(전역 시나리오)는 삭제하지 않고 config/ptd_ttl에 보존(2D 뷰어용).
        비교실험용 래퍼 정식화는 Phase 4/5에서.
- [x] P3-2 설치 무방호 창 — effective_day = install_activity.ef 또는
      spawn_day + installDurationDays. 그 전엔 base(무방호), 이후 대책 적용. — (2026-07-08,
      tests/test_p3_executors.py::test_install_window_unprotected_then_protected)
      ※ 설치 액티비티의 정식 CPM 삽입(후행 재계산)은 effective_day로 대체 모델링. 완전
        삽입은 후속 정련.
- [x] P3-3 SpatialChangeRule 실행기 — remove(위험 제거)/block_agent_entry(셀 WALL화)/
      relocate(riskCoeff·fall 배율). 인스턴스 셀 단위 적용. — (2026-07-08,
      tests/test_p3_executors.py)
      ※ 위치 의미론(opening_edge/perimeter/full_zone)은 인스턴스 셀 집합 전체에 적용(세부
        하위선택 단순화).
- [x] P3-4 AgentParameterRule 실행기 — 채널별 prob multiplier(fall/collapse/material 등)를
      해당 인스턴스 셀에만 λ에 적용. fatality/injury는 λ 불변·SWR용(Phase 4)으로 분리. —
      (2026-07-08, tests/test_p3_executors.py)
- [x] P3-5 TemporalRule 실행기 — scheduleShift 파싱 규약: set_fs_lag / min_curing_lag
      (strength_verified 양생 최소치 강제) 지원 + 재-CPM. — (2026-07-08,
      tests/test_p3_temporal.py)
      ※ fs_before(재정렬)/기타는 파싱만(미적용). TemporalRule 대책은 run_project 전에
        스케줄에 선적용(controls.apply_temporal_shift).
- [x] P3-6 폐루프 데모 — `fourd.closed_loop_demo`: base→λ상위 인스턴스(rank)→TTL 적용가능
      대안(HoC순)→최상위 적용→재실행→전후 비교. `check_p3.py`(단부 난간 적용 시 전체
      λ 24%↓). — (2026-07-08, tests/test_p3_closedloop.py)

### Phase 4 — 지표·사회 모듈 [완료 조건: SWR로 PPE 시나리오가 base와 구분됨]
- [ ] P4-1 SWR = Σ λ×심각도 가중(사망환산; fatalityMultiplier 반영 — PPE 비교의 전제)
- [ ] P4-2 DetourCost(대책 전후 총 이동시간 차), CE-ratio(ΔSWR/비용 — 비용 확보 전 costLevel 서수)
- [ ] P4-3 social.py 크루 구조화 — witness shock에 sameLevelOnly, imitation을
      크루 내/외 2계층(w_in>w_out). ρ 단일 스칼라 유지. ON/OFF 스위치 필수
- [ ] P4-4 viewer.py 연동 — 일 선택 히트맵, 공정-위험 곡선(Λ(d) 시계열)

### Phase 5 — 검증 인프라 [완료 조건: 검증 리포트 자동 생성]
- [ ] P5-1 **2D 동등성**: 단층·정적(생멸 없음)·단일 trade 설정에서 4D 결과 ≡ 기존
      2D run_one_day 결과 (동일 시드, λ 상대오차 <1e-9)
- [ ] P5-2 MC 수렴 곡선 (런 수 vs λ 분산), 시드 재현성 테스트
- [ ] P5-3 민감도 스윕 러너 — TTL에서 sensitivityTarget=true 규칙 자동 추출(현재 6개;
      RULE_CP_DESIGNCHECK/CP_LIFT_LIMIT/FE_PLATFORM/HS_INTFORM/TRIP_LIGHT/TRIP_STORAGE)
      + 사회 파라미터, ±50% 스윕, 시나리오 순위 안정성 리포트
- [ ] P5-4 패턴 검증 — 시뮬레이션 공종별 노출 분포 vs §2 통계 분포 비교 리포트

## §6. Phase 이후 (엔진 외 — 참고만)
실제 공정표·도면 확보(critical path), IFC→site.json 추출기, 실험 6종(HoC 위계 재현 /
사회 ON·OFF / 창발 부작용 / 시간 타겟팅 / TemporalRule / 레이아웃 복수화),
ODD 프로토콜 문서화, 마스터표→docx Appendix 변환기,
U-트랙: IFC→Unity 시각화 번들 (build_unity_bundle.py / export_timeline.py / Unity 로더).

## §7. 진행 체크리스트
위 Phase별 체크박스를 작업 완료 시 [x]로 갱신하고, 완료 일자와 테스트 파일명을 옆에 기록.
예: `- [x] P1-1 ... (2026-07-05, tests/test_p1_loader.py)`

- [x] v3.8 Part A `max_steps` 80/150/300/480/720 × 5회 하한 실측 —
      하한 150, 체류 근접 300, 채널 구성 안정 480. 기본값은 미변경
      (2026-08-17, `scripts/sweep_max_steps.py`, `tests/test_v38_max_steps.py`)
- [x] v3.8 Part D v3.3 공정 증강(178 + 해체 8 + 자재 48) 이후 낡은
      schedule/timeline 테스트 6건을 산출 근거 기준으로 교정 (2026-08-17,
      `tests/test_p1_schedule.py`, `tests/test_v2_convert.py`, `tests/test_v2_timeline.py`)
- [x] v3.8 Part E Anaconda Python 3.13 의존성 고정 및 build_all 사전 점검
      (2026-08-17, `requirements.txt`, `tests/test_build_all.py`)
- [ ] v3.8 Part B·C — Part A 보고 후 별도 지시 대기 (미착수)
- [x] Unity 이전 반복실험 수 사전 확정 — 최종 `max_steps=480`에서 BASE/대표
      대안 각 10회 파일럿, 단일 비교 하한 35회, 10조건 동시비교 운영 최소 70회
      확정. Phase 5 정식 완료 표시는 Phase 4 종료 후 수행
      (2026-08-17, `scripts/pilot_run.py`, `build/pilot_run.md`,
      `SIMULATION_PROTOCOL.md`)
- [x] 작업자 통근 병목 개선 — 작업구역 접근 셀, OD·ρ구간별 확률적 경로대안 3개 캐시,
      interval-lane 계단 예약, 반복실험 `--jobs` 병렬화, BASE–대안 공통난수 시드 교정.
      8층 동일 OD 60회 경로계획 마이크로벤치마크 3.48배 개선
      (2026-08-17, `worker_mobility.py`, `fourd_workers.py`,
      `tests/test_worker_mobility.py`, `WORKER_ALGORITHM.md`)
- [x] 4D 층내 이동을 위험가중 Theta*로 전환 — LOS any-angle 부모 단축,
      Euclidean heuristic, 벽·개구부 관통 및 코너컷 금지, 연속 셀 궤적 복원.
      작업자 행동 파라미터는 변경하지 않음. 기존 2D A*는 회귀 베이스라인으로 보존
      (2026-08-18, `movement.py`, `site_model.py`, `fourd.py`, `fourd_workers.py`,
      `tests/test_theta_route.py`)
