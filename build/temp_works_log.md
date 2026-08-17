# 가설물·위험구역 파생 로그 (Part 2)

IFC 는 완성된 건물만 기술한다. 거푸집·동바리·작업발판과 그것들이 만드는 위험 공간은 IFC 에 없으므로 영구 부재와 공정에서 파생했다.

## lifecycle.py 인터페이스

`lifecycle.py` 의 `LifecycleEngine` 은 **폴리곤을 받지 않는다.** `spawnLocation.cells` = 그리드 `(row, col)` 정수쌍, `level` = `"L1".."L8"`, `boundActivity` = `"T-<task_id>"` 형식이다. `hazard_type` 과 트리거는 TTL `LifecycleRuleTemplate` 에서 오고 바인딩은 '어느 액티비티·어느 셀'만 지정한다.

따라서 지시서의 `hazard_zones.json` 스키마(polygon/z/height)는 lifecycle 이 소비할 수 없다. 두 표현을 함께 냈다 — `zones[].geometry`(폴리곤, Unity·면적검증용)와 `zones[].cells`(그리드, lifecycle 소비용), 그리고 `build/lifecycle_bindings_v2.json`(lifecycle 이 그대로 읽는 형식).

`element_task_mapping.json` 의 `element_ids` 는 **IFC GlobalId GUID** (22자 base64)다. Name/Tag 가 아니다. 178 task 중 112개에 총 1,438 GUID.

### 템플릿이 없어 바인딩에서 제외된 zone

v2.4 TTL 의 `LifecycleRuleTemplate` 은 **4종뿐**이다 — `LCR_SLAB_OPENING` / `LCR_SLAB_EDGE` / `LCR_SHORING_COLLAPSE` / `LCR_MATERIAL_STORAGE` (`LCR_EXPOSED_REBAR` 는 찔림 계열로 범위 제외). 낙하영향구역·협소통로에 대응하는 템플릿은 존재하지 않는다.

`lifecycle.LifecycleEngine` 은 미정의 템플릿에 `ValueError` 를 던지므로 해당 zone 은 바인딩에서 제외했다. **템플릿은 지식이므로 코드에서 만들어내지 않았다** — 필요하면 `ptd_library_master` xlsx 에 항목을 추가하고 TTL 을 재생성하는 것이 정규 경로다(CLAUDE.md §1·§2).

zone 자체는 `hazard_zones.json` 에 그대로 남아 있어 유실이 없다.

| 위험유형 | 제외 zone 수 | 대응 템플릿 |
|---|---:|---|

바인딩 산출 84건 / 제외 0건 (합계 84 = 전체 zone).

## 규칙별 생성 zone 수

| 규칙 | 위험유형 | 채널 | zone 수 |
|---|---|---|---:|
| R1 슬래브 개구부 | H001_FloorOpening | dwell_time | 39 |
| R2 슬래브 단부 | H007_SlabEdge | dwell_time | 8 |
| R3 동바리 존치 | H008_ShoringCollapse | zone_occupancy | 7 |
| R4 낙하 영향구역 | H009_DropZone | passage_count | 6 |
| R5 협소통로·적재 | H002/H004 | passage_count | 16 |
| **합계** | | | **84** |

### 층별 분포

| 층 | H001 | H007 | H008 | H009 | H002 | H004 | 합계 |
|---|---|---|---|---|---|---|---|
| Basement | 0 | 1 | 1 | 1 | 1 | 1 | 6 |
| Level_01 | 6 | 1 | 2 | 1 | 1 | 1 | 13 |
| Level_02a_Parking | 0 | 1 | 0 | 0 | 1 | 1 | 4 |
| Level_02 | 8 | 1 | 1 | 1 | 1 | 1 | 14 |
| Level_03 | 9 | 1 | 1 | 1 | 1 | 1 | 15 |
| Level_04 | 9 | 1 | 1 | 1 | 1 | 1 | 15 |
| Level_05 | 3 | 1 | 1 | 1 | 1 | 1 | 9 |
| Roof | 4 | 1 | 0 | 0 | 1 | 1 | 8 |

## 자기 검증

### 개구부 zone 39개 및 층별 분포 (6/8/9/9/3/4) — OK

- 실측 39개, 분포 {'Level_01': 6, 'Level_02': 8, 'Level_03': 9, 'Level_04': 9, 'Level_05': 3, 'Roof': 4}

### 층별 위험구역 합집합 면적 ≤ 해당 층 바닥면적 — OK

- Basement: zone합집합 1279 / IFC슬래브 1292
- Level_01: zone합집합 1888 / IFC슬래브 1950 / 지시서 참조 1015
- Level_02a_Parking: zone합집합 241 / IFC슬래브 492
- Level_02: zone합집합 1207 / IFC슬래브 1207 / 지시서 참조 1201
- Level_03: zone합집합 1192 / IFC슬래브 1192 / 지시서 참조 1185
- Level_04: zone합집합 1192 / IFC슬래브 1192 / 지시서 참조 1185
- Level_05: zone합집합 936 / IFC슬래브 1177 / 지시서 참조 597
- Roof: zone합집합 550 / IFC슬래브 827

### 모든 zone 의 spawn 시점 < despawn 시점 — OK

- 위반 0건

### derived_from GUID 가 IFC 에 실재 — OK

- 미확인 0건

### 채널별 zone 수 집계 — OK

- dwell_time: 47
- passage_count: 30
- zone_occupancy: 7

## R4 낙하 영향구역

Part 1 의 층간 중첩으로 상하부 동시작업이 실제로 발생해 6건이 생성되었다. 중첩이 없었다면 0건이 정상이다.

| zone | 상부층 | 투영 대상 | 깊이 | 여유폭(m) | 중첩(일) |
|---|---|---|---:|---:|---:|
| HZ_L1_DROP_001 | Level_01 | Basement | 1 | 1.02 | 13 |
| HZ_L2_DROP_001 | Level_02a_Parking | Level_01 | 1 | 0.91 | 15 |
| HZ_L4_DROP_001 | Level_03 | Level_02 | 1 | 1.06 | 18 |
| HZ_L5_DROP_001 | Level_04 | Level_03 | 1 | 1.06 | 19 |
| HZ_L6_DROP_001 | Level_05 | Level_04 | 1 | 1.16 | 19 |
| HZ_L7_DROP_001 | Roof | Level_05 | 1 | 1.60 | 9 |

## R5 적재구역 면적 배정 규칙

층의 `element_count` 최대 작업을 골라, `productivity_rates.json` 의 `assumptions[ifc_class].area_m2` 를 곱해 소요 면적을 구하고 **3단 적치 가정으로 ÷3** 했다. 적치 단수 3 은 근거 없는 값이며 민감도 대상이다.

| 층 | 기준 작업 | 개수 | 단위면적(m²) | 소요(m²) | 배정(m²) | 자유영역(m²) |
|---|---|---:|---:|---:|---:|---:|
| Basement | 1101 Basement 벽체 콘크리트 타설 (D | 25 | 35.0 | 875.0 | 291.7 | 1127.8 |
| Level_01 | 2501 Level 01 벽체 콘크리트 타설 (D | 25 | 35.0 | 875.0 | 291.7 | 1877.6 |
| Level_02a_Parking | 37 Level 02a Parking 벽체 콘 | 4 | 35.0 | 140.0 | 46.7 | 485.3 |
| Level_02 | 5101 Level 02 벽체 콘크리트 타설 (D | 25 | 35.0 | 875.0 | 291.7 | 1130.2 |
| Level_03 | 6601 Level 03 벽체 콘크리트 타설 (D | 25 | 35.0 | 875.0 | 291.7 | 1105.4 |
| Level_04 | 8101 Level 04 벽체 콘크리트 타설 (D | 25 | 35.0 | 875.0 | 291.7 | 1105.4 |
| Level_05 | 10001 Level 05 벽체 콘크리트 타설 (D | 25 | 35.0 | 875.0 | 291.7 | 1100.3 |
| Roof | 9147 Roof 콘크리트 반입 | 3 | 100.0 | 300.0 | 100.0 | 827.0 |

## 파라미터 — 전부 민감도 분석 대상

| 파라미터 | 값 | 근거 |
|---|---:|---|
| `opening_buffer_m` | 2.0 | **없음.** 개구부 주변 노출 버퍼. 문헌값 아님 |
| `edge_band_m` | 2.0 | **없음.** 단부 노출 밴드 폭. 문헌값 아님 |
| `drop_angle_deg` | 15.0 | **없음.** 낙하 확산각. 문헌값 아님 |
| `wall_proximity_m` | 0.5 | **없음.** 벽 인접 판정 임계. 문헌값 아님 |
| `retention_days` | 0 | Part 1 파라미터. 기본 0 = 현행 유지 |
| `overlap_days` | 0 | Part 1 파라미터. 기본 0 = 벽체 양생 익일 착수 |
| 적치 단수 | 3 | **없음.** R5 면적 배정용 |

> 이 값들에 문헌 근거가 있는 것처럼 쓰지 않았다. 전부 민감도 분석에서 변화시켜야 하는 임의값이다.

## 파생 중 경고

- - R3 Basement: 교집합 0.0 m² 가 기준(10%) 미만 → 직하부 없음
- 
- R3 동바리 존치 (KCS 14 20 12 3.3.2(2) — 3개 층):
- Level_01             동바리층 Basement 적용 3개 층 → 해체 Level_02 (T-9004, 이전 T-9002)
- Level_02a_Parking    동바리층 Level_01 적용 3개 층 → 해체 Level_03 (T-9005, 이전 T-9003)
- Level_02             동바리층 Level_01 적용 3개 층 → 해체 Level_04 (T-9006, 이전 T-9004)
- Level_03             동바리층 Level_02 적용 3개 층 → 해체 Level_05 (T-9007, 이전 T-9005)
- Level_04             동바리층 Level_03 적용 3개 층 → 해체 Roof (T-9008, 이전 T-9006)
- Level_05             동바리층 Level_04 적용 2개 층 → 해체 Roof (T-9008, 이전 T-9007)
- Roof                 동바리층 Level_05 적용 1개 층 → 해체 Roof (T-9008, 이전 T-9008)

