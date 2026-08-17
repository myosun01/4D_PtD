# 라이브러리 → 코드 도달 점검 (Part A)

생성: `python scripts/check_library_wiring.py`  ·  라이브러리: `build\ptd_library_v2.4.ttl`

## 1. TTL 로드

| 항목 | 수 |
|---|---|
| ExecutableAlternative | 35 |
| SpatialChangeRule | 14 |
| AgentParameterRule | 14 |
| TemporalRule | 7 |
| LifecycleRuleTemplate | 7 |

`parameterValue` 파싱 경고: 0건

## 2. `resolve_all()` 통과 여부

대안마다 그 위험유형의 실제 인스턴스 1건을 붙여 해석을 시도한다 (바인딩 84건, 위험유형 7종).

**통과 18 / 실패 10**

| 대안 | 규칙 | cellType | 위험 | kind | 채널배율 |
|---|---|---|---|---|---|
| `ALT_H001_01` | `RULE_H001_ELIM` | floor_opening | H001 | remove | — |
| `ALT_H001_05` | `RULE_H001_GUARD` | opening_edge_cells | H001 | scale | fall=0.1 |
| `ALT_H001_07` | `RULE_ADM_H001` | floor_opening | H001 | scale | fall=0.59 |
| `ALT_H001_08` | `RULE_PPE_H001` | floor_opening | H001 | scale | — |
| `ALT_K_CP_07` | `RULE_K_CP_07` | collapse_zone | H008 | scale | collapse_zone=1 |
| `ALT_K_FE_11` | `RULE_K_FE_11` | collapse_zone | H008 | scale | — |
| `ALT_K_HS_05` | `RULE_K_HS_05` | material_storage | H004 | scale | material=1 |
| `ALT_K_HS_06` | `RULE_K_HS_06` | drop_zone | H009 | block | — |
| `ALT_K_ST_03` | `RULE_K_ST_03` | equipment_corridor | H011 | scale | narrow=1 |
| `ALT_M_Fall_FormErection_02` | `RULE_FE_GUARDRAIL` | edge_cells | H007 | scale | edge=0.1 |
| `ALT_M_Trip_MatHandling_06` | `RULE_TRIP_STORAGE` | material_storage | H004 | scale | material=1 |
| `ALT_S_CP_04` | `RULE_CP_LIFT_LIMIT` | collapse_zone | H008 | scale | collapse_zone=0.5 |
| `ALT_S_FE_08` | `RULE_FE_METALDECK` | collapse_zone | H008 | remove | — |
| `ALT_S_H001_09` | `RULE_H001_RELOCATE` | floor_opening | H001 | scale | fall=1 |
| `ALT_T_CP_01` | `RULE_CP_PC` | collapse_zone | H008 | remove | — |
| `ALT_T_CP_03` | `RULE_CP_NOENTRY` | collapse_zone | H008 | block | — |
| `ALT_T_HS_02` | `RULE_HS_DEBRISNET` | drop_zone | H009 | scale | drop_zone=0.35 |
| `ALT_T_HS_04` | `RULE_HS_INTFORM` | drop_zone | H009 | scale | drop_zone=0.5 |

## 3. AgentParameterRule 계수 도달

| 규칙 | cellType | 읽힌 계수 | 출처 |
|---|---|---|---|
| `RULE_ADM_H001` | floor_opening | fall_prob_multiplier=0.59 | — |
| `RULE_CP_LIFT_LIMIT` | collapse_zone | collapse_prob_multiplier=0.5 | heuristic |
| `RULE_FE_GUARDRAIL` | edge_cells | fall_prob_multiplier=0.1 | — |
| `RULE_FE_PLATFORM` | elevated_work_zone | fall_prob_multiplier=0.3 | — |
| `RULE_H001_GUARD` | opening_edge_cells | fall_prob_multiplier=0.1 | literature |
| `RULE_HS_DEBRISNET` | drop_zone | hazard_weight_multiplier=0.35 | — |
| `RULE_HS_INTFORM` | drop_zone | material_prob_multiplier=0.5 | heuristic |
| `RULE_K_CA_02` | — | **계수 미확보** | heuristic |
| `RULE_K_CA_03` | — | **계수 미확보** | heuristic |
| `RULE_K_FE_11` | collapse_zone | **계수 미확보** | heuristic |
| `RULE_K_RB_03` | — | **계수 미확보** | heuristic |
| `RULE_K_TR_08` | — | **계수 미확보** | heuristic |
| `RULE_PPE_H001` | floor_opening | fatality_multiplier=0.27, injury_multiplier=1 | — |
| `RULE_TRIP_LIGHT` | route | trip_prob_multiplier=0.8 | heuristic |

계수 미확보 5건: `RULE_K_CA_02`, `RULE_K_CA_03`, `RULE_K_FE_11`, `RULE_K_RB_03`, `RULE_K_TR_08`

계수 미확보는 TTL 원천에 값이 없다는 뜻이며 0 이나 1.0 으로 채우지 않았다. 해당 대안은 적용해도 효과가 없다.

**수용 기준** `ALT_H001_05` → `RULE_H001_GUARD` fallProbMultiplier = **0.1** (기대 0.1) — OK

## 4. TemporalRule 파싱

| 규칙 | 원문 | 파싱 결과 |
|---|---|---|
| `RULE_CP_STRENGTH_VERIFY` | add precedence condition: formwork_stripping(Z) requires strength_verified(Z) [min curing lag enforced] | `min_curing_lag`  |
| `RULE_FE_STAIR_EARLY` | advance activity[workType=permanent_stair]; VerticalLink.availableFromActivity := earlier | **미인식** |
| `RULE_FS_CLOSURE_FIRST` | set precedence: opening_closure(Z) FS-before formwork_stripping(Z) | `fs_before` {'first': 'opening_closure', 'second': 'formwork_stripping'} |
| `RULE_H001_TEMPORAL` | set FS_lag(slab_pour -> opening_closure) = 0 days | `set_fs_lag` {'from_work': 'slab_pour', 'to_work': 'opening_closure', 'lag_days': 0} |
| `RULE_HS_PHASED` | deconflict: shift co-located activities so overlap(stripping, other)=0 | **미인식** |
| `RULE_K_CP_09` | deconflict: enforce assembly/dismantling precedence order | **미인식** |
| `RULE_K_FS_02` | set precedence: formwork_stripping(Z) requires retention_period_elapsed(Z) | `retention_period` {'work': 'formwork_stripping', 'executed_by': 'temp_works.py R3 — KCS 14 20 12 3.3.2(2) 3개 층 존치', 'schedule_mutation': False} |

파싱 성공 4 / 미인식 3

## 5. 여전히 코드에 도달하지 못하는 대안

| 대안 | 규칙 | 사유 |
|---|---|---|
| `ALT_K_CA_02` | `RULE_K_CA_02` | appliesToCellType 없음 (v2.3 정본에도 부재) |
| `ALT_K_CA_03` | `RULE_K_CA_03` | appliesToCellType 없음 (v2.3 정본에도 부재) |
| `ALT_K_FE_10` | `RULE_K_FE_10` | appliesToCellType='scaffold' → 매핑되는 위험유형 없음 |
| `ALT_K_RB_02` | `RULE_K_RB_02` | appliesToCellType 없음 (v2.3 정본에도 부재) |
| `ALT_K_RB_03` | `RULE_K_RB_03` | appliesToCellType 없음 (v2.3 정본에도 부재) |
| `ALT_K_TR_08` | `RULE_K_TR_08` | appliesToCellType 없음 (v2.3 정본에도 부재) |
| `ALT_M_Fall_FormErection_03` | `RULE_FE_PLATFORM` | appliesToCellType='elevated_work_zone' → 매핑되는 위험유형 없음 |
| `ALT_M_Trip_MatHandling_02` | `RULE_TRIP_LIGHT` | appliesToCellType='route' → 매핑되는 위험유형 없음 |
| `ALT_M_Trip_MatHandling_05` | `RULE_TRIP_ROUTE` | appliesToCellType='route' → 매핑되는 위험유형 없음 |
| `ALT_T_HS_01` | `RULE_HS_GROUNDASM` | appliesToCellType='elevated_work_zone' → 매핑되는 위험유형 없음 |

사유별 집계:

- appliesToCellType 없음 — 5건
- appliesToCellType='elevated_work_zone' → 매핑되는 위험유형 없음 — 2건
- appliesToCellType='route' → 매핑되는 위험유형 없음 — 2건
- appliesToCellType='scaffold' → 매핑되는 위험유형 없음 — 1건

미인식 TemporalRule 3건 (`RULE_FE_STAIR_EARLY`, `RULE_HS_PHASED`, `RULE_K_CP_09`) 은 `controls.parse_schedule_shift` 가 아는 세 패턴(set FS_lag / min curing lag enforced / FS-before) 중 어느 것도 아니다. 의미를 추측해 매핑하지 않았다.
