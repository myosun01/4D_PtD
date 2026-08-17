# appliesToCellType 유도 (v3.5 Part B)

마스터 CSV 44열 (v3.5 에서 `applies_to_cell_type`·`cell_type_basis` 추가).
TTL 에 직접 쓰지 않는다 — 마스터 CSV → `build_ttl.py` 정규 경로를 탄다.

## 전제 확인 — 지시서가 가정한 유도 경로는 존재하지 않았다

- KnowledgeEntry 에 `hasHazardType` **없음** (이 술어를 가진 subject 28개는 LifecycleRuleTemplate 7 + RiskScenario 21, KE 는 0개)
- `CoverageCell.targetKnowledgeEntries` 가 가리키는 KE 는 전체 **1개**뿐이고 대상 항목은 하나도 포함되지 않음
- 대상 항목의 `scenario_ids` 전부 공란

따라서 hazard_type 경유 유도는 불가능하다. accident_type 단독 유도는 추측이므로(떨어짐 → H001/H007 결정 불가) 하지 않았다.

## 사용한 유도 규칙

| 규칙 | 원천 | 조건 |
|---|---|---|
| R1 | `simulation_action` | 문자열이 대상 격자를 명시할 때 (키워드 매칭, 매칭어를 basis 에 기록) |
| R2 | `exposure_channel` | 이 프로젝트 zone 집합에서 1:1 일 때만 — `zone_occupancy`→H008 |
| B-2 | 오기 교정 | `KE_T_HS_04` (아래 별도 절) |

## 유도 성공 25건

| entry_id | rule_id | cellType | 근거 |
|---|---|---|---|
| `KE_H001_01` | `RULE_H001_ELIM` | `floor_opening` | v2.3 정본 값 (유도하지 않음 — 정본이 우선) |
| `KE_H001_05` | `RULE_H001_GUARD` | `opening_edge_cells` | v2.3 정본 값 (유도하지 않음 — 정본이 우선) |
| `KE_H001_07` | `RULE_ADM_H001` | `floor_opening` | v2.3 정본 값 (유도하지 않음 — 정본이 우선) |
| `KE_H001_08` | `RULE_PPE_H001` | `floor_opening` | v2.3 정본 값 (유도하지 않음 — 정본이 우선) |
| `KE_K_CP_07` | `RULE_K_CP_07` | `collapse_zone` | R1 simulation_action='substitute_shoring_system_reduce_defect_derived_collapse_instances' 에 'shoring_system' 명시 |
| `KE_K_FE_10` | `RULE_K_FE_10` | `scaffold` | R1 simulation_action='substitute_scaffold_system_reduce_assembly_defect_instances' 에 'scaffold_system' 명시 |
| `KE_K_FE_11` | `RULE_K_FE_11` | `collapse_zone` | R2 exposure_channel='zone_occupancy' — 이 프로젝트 zone 집합에서 1:1 (H008 뿐) |
| `KE_K_HS_05` | `RULE_K_HS_05` | `material_storage` | R1 simulation_action='cap_material_stack_height_limit_spawn_volume' 에 'material_stack' 명시 |
| `KE_K_HS_06` | `RULE_K_HS_06` | `drop_zone` | R1 simulation_action='block_agent_entry_to_drop_influence_zone' 에 'drop_influence_zone' 명시 |
| `KE_K_ST_03` | `RULE_K_ST_03` | `equipment_corridor` | R1 simulation_action='separate_worker_and_equipment_corridors' 에 'equipment_corridor' 명시 |
| `KE_M_Fall_FormErection_02` | `RULE_FE_GUARDRAIL` | `edge_cells` | v2.3 정본 값 (유도하지 않음 — 정본이 우선) |
| `KE_M_Fall_FormErection_03` | `RULE_FE_PLATFORM` | `elevated_work_zone` | v2.3 정본 값 (유도하지 않음 — 정본이 우선) |
| `KE_M_Fall_FormErection_04` | `RULE_FE_ADM` | `elevated_work_zone` | v2.3 정본 값 (유도하지 않음 — 정본이 우선) |
| `KE_M_HitByObj_Stripping_01` | `RULE_HS_ADM` | `material_storage` | v2.3 정본 값 (유도하지 않음 — 정본이 우선) |
| `KE_M_Trip_MatHandling_02` | `RULE_TRIP_LIGHT` | `route` | v2.3 정본 값 (유도하지 않음 — 정본이 우선) |
| `KE_M_Trip_MatHandling_05` | `RULE_TRIP_ROUTE` | `route` | v2.3 정본 값 (유도하지 않음 — 정본이 우선) |
| `KE_M_Trip_MatHandling_06` | `RULE_TRIP_STORAGE` | `material_storage` | v2.3 정본 값 (유도하지 않음 — 정본이 우선) |
| `KE_S_CP_04` | `RULE_CP_LIFT_LIMIT` | `collapse_zone` | v2.3 정본 값 (유도하지 않음 — 정본이 우선) |
| `KE_S_FE_08` | `RULE_FE_METALDECK` | `collapse_zone` | v2.3 정본 값 (유도하지 않음 — 정본이 우선) |
| `KE_S_H001_09` | `RULE_H001_RELOCATE` | `floor_opening` | v2.3 정본 값 (유도하지 않음 — 정본이 우선) |
| `KE_T_CP_01` | `RULE_CP_PC` | `collapse_zone` | v2.3 정본 값 (유도하지 않음 — 정본이 우선) |
| `KE_T_CP_03` | `RULE_CP_NOENTRY` | `collapse_zone` | v2.3 정본 값 (유도하지 않음 — 정본이 우선) |
| `KE_T_HS_01` | `RULE_HS_GROUNDASM` | `elevated_work_zone` | v2.3 정본 값 (유도하지 않음 — 정본이 우선) |
| `KE_T_HS_02` | `RULE_HS_DEBRISNET` | `drop_zone` | v2.3 정본 값 (유도하지 않음 — 정본이 우선) |
| `KE_T_HS_04` | `RULE_HS_INTFORM` | `drop_zone` | 오기교정: v2.3 이월값 material_storage 는 적재구역을 가리켜 이 항목과 무관하다. directive_ko('작업발판 일체형 거푸집 — 해체 시 개별 부재 탈락·낙하 기회를 축소') 와 accident_type(물체에맞음)이 모두 낙하물 노출을 가리키므로 drop_zone 으로 교정. 전거: 산업안전보건기준에 관한 규칙 제331조의3 (legal_basis 열에 기재됨). |

## 유도 불가 6건 — 비워 둔다

| entry_id | rule_id | accident_type | exposure_channel | 사유 |
|---|---|---|---|---|
| `KE_K_CA_02` | `RULE_K_CA_02` | 끼임 | proximity | 적용 불가: proximity(끼임) 채널은 현재 zone 집합에 대응 유형이 없다 |
| `KE_K_CA_03` | `RULE_K_CA_03` | 끼임 | proximity | 적용 불가: proximity(끼임) 채널은 현재 zone 집합에 대응 유형이 없다 |
| `KE_K_PI_01` | `RULE_K_PI_01` |  |  | 유도 원천 없음 (simulation_action·exposure_channel 모두 비었거나 미인식) |
| `KE_K_RB_02` | `RULE_K_RB_02` | 떨어짐 | passage_count | R1 미결: simulation_action 의 'walkway' 는 대상 격자를 특정하지 않는다 |
| `KE_K_RB_03` | `RULE_K_RB_03` | 물체에맞음 | passage_count | R2 미결: exposure_channel='passage_count' 는 복수 위험유형에 대응해 모호 (accident_type='물체에맞음' 만으로는 결정 불가) |
| `KE_K_TR_08` | `RULE_K_TR_08` | 넘어짐 | passage_count | R2 미결: exposure_channel='passage_count' 는 복수 위험유형에 대응해 모호 (accident_type='넘어짐' 만으로는 결정 불가) |

**추측으로 채우지 않았다.** 이 항목들은 `resolve_all()` 에서 '적용 불가'로 남는 것이 정상이다.

## B-2 오기 교정

- `KE_T_HS_04` → `drop_zone`
  - 오기교정: v2.3 이월값 material_storage 는 적재구역을 가리켜 이 항목과 무관하다. directive_ko('작업발판 일체형 거푸집 — 해체 시 개별 부재 탈락·낙하 기회를 축소') 와 accident_type(물체에맞음)이 모두 낙하물 노출을 가리키므로 drop_zone 으로 교정. 전거: 산업안전보건기준에 관한 규칙 제331조의3 (legal_basis 열에 기재됨).

## TemporalRule 7건

격자 대상이 아니므로 비운다 (`controls.applicable_alternatives` 가 별도 경로로 처리).

## 규제 전거 기재 (v3.5)

확인한 조항을 `legal_basis` 열에 남긴다. 기존 값은 덮어쓰지 않고 병기한다. 전문은 `build/limitations.md` §1 참조.

| entry_id | 처리 | 전거 |
|---|---|---|
| `KE_M_Fall_FormErection_01` | 신규 | 산업안전보건기준에 관한 규칙 제43조 (개구부 등의 방호 조치) — 덮개는 뒤집히거나 떨어지지 않도록 설치  |
| `KE_C_WARN_01` | 신규 | 산업안전보건기준에 관한 규칙 제43조 (개구부 등의 방호 조치) — 어두운 장소에서도 알아볼 수 있도록 개구 |
| `KE_H001_05` | 추가(병기) | 29 CFR 1926.502(i) — 개구부 안전난간은 방호되지 않은 모든 측면에 설치, 덮개는 예상 하중의 |

