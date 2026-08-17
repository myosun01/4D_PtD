# Part C 로그 — Unity 번들 익스포터 확장

## C-1 타임라인 재생성

| | 공기(일) | 액티비티 |
|---|---|---|
| 이전(번들에 있던 것) | 350 | 234 |
| 재생성 | 350 | 234 |

`export_timeline.py` 종료코드 0. hazardSpans 23건.

## C-2 위험구역 익스포트

`unity_bundle/hazard_zones.json` — zone 84, 유형 7종, 1.5 MB

| 위험유형 | zone | 노출채널 | λ채널 |
|---|---|---|---|
| H001_FloorOpening | 39 | dwell_time | fall |
| H002_NarrowPassage | 8 | passage_count | narrow |
| H004_MaterialStorage | 8 | passage_count | material |
| H007_SlabEdge | 8 | dwell_time | edge |
| H008_ShoringCollapse | 7 | zone_occupancy | collapse_zone |
| H009_DropZone | 6 | passage_count | drop_zone |
| H011_EquipmentCorridor | 8 | passage_count | narrow |

생멸 일 인덱스는 `LifecycleEngine` 산출을 그대로 실었다 (날짜 문자열을 재해석하지 않는다). 일 인덱스를 얻지 못한 zone: 0건

**개구부 본체/버퍼 구분 (v3.5 D-3)**: H001 zone 의 `cells`·`geometry` 는 개구부 **주변 버퍼**(통행 가능한 위험대)이고, 개구부 본체는 폴리곤의 안쪽 링이다. Unity 가 다르게 렌더링할 수 있도록 `buffer_outline_gltf`(위험대)와 `opening_body_outline_gltf`(구멍)를 나눠 실었다. 본체 링을 가진 zone 38 / 39 — 나머지는 개구부가 1셀 미만이거나 슬래브 경계에서 잘려 본체 링이 없다.

## C-3 워커 궤적 익스포트

`unity_bundle/worker_trajectory.json` — 106,425행, 일자 262개, 스텝 103종, 16.4 MB

state 분포: commute=38,756, work=27,591, stair=23,432, stair_wait=10,889, travel=5,757

## C-4 라이브러리 메타 익스포트

`unity_bundle/ptd_library.json` — 대안 35, variant 1 (BASE), 0.0 MB

이 프로젝트의 zone 에 실제로 걸리는 대안 18 / 35.

| HoC | 대안 수 |
|---|---|
| RiskAvoidance | 1 |
| Elimination | 7 |
| Substitution | 6 |
| EngineeringControls | 15 |
| WarningSystems | 2 |
| AdministrativeControls | 3 |
| PPE | 1 |

## C-6 가설물 익스포트

`unity_bundle/temp_structures.json` — 19개, 0.4 MB

| 유형 | 개수 | walkable | 셀 합 |
|---|---|---|---|
| `formwork_deck` | 8 | 예 | 9,172 |
| `scaffold` | 4 | 예 | 2,019 |
| `shoring` | 7 | 아니오 | 1,582 |

> shoring_spacing_m 과 scaffold_band_m 은 **근거 없는 임의값**이며 문헌값이 아니다. 통행·시각 목적의 배치 파라미터일 뿐 구조 계산의 산물이 아니다. 전부 민감도 분석 대상이다. deck_offset 만 IFC 슬래브 두께에서 유도된 값이다.

## 번들 파일 목록

| 파일 | 크기 |
|---|---|
| `bundle_meta.json` | 0.0 MB |
| `hazard_zones.json` | 1.5 MB |
| `lambda_daily.csv` | 0.3 MB |
| `manifest.json` | 11.4 MB |
| `model.glb` | 59.1 MB |
| `ptd_library.json` | 0.0 MB |
| `temp_structures.json` | 0.4 MB |
| `timeline.json` | 0.5 MB |
| `worker_trajectory.json` | 16.4 MB |

