# 가설물 파생 계층 (v3.3 Phase 2)

산출 `build/temp_structures.json` — 총 19개.

| 유형 | 개수 |
|---|---|
| `formwork_deck` | 8 |
| `scaffold` | 4 |
| `shoring` | 7 |

## 파라미터 — 근거 없음

| 파라미터 | 값 |
|---|---|
| `shoring_spacing_m` | 2.0 |
| `scaffold_band_m` | 1.5 |
| `deck_offset_source` | 슬래브 bbox z 범위의 층별 중앙값 (IFC 파생) |

> shoring_spacing_m 과 scaffold_band_m 은 **근거 없는 임의값**이며 문헌값이 아니다. 통행·시각 목적의 배치 파라미터일 뿐 구조 계산의 산물이 아니다. 전부 민감도 분석 대상이다. deck_offset 만 IFC 슬래브 두께에서 유도된 값이다.

층별 슬래브 두께(IFC bbox z 중앙값, m): {"L1": 0.32, "L2": 0.25, "L3": 0.5, "L4": 0.313, "L5": 0.313, "L6": 0.33, "L7": 0.72, "L8": 0.72}

## 파생 결과

| ts_id | 유형 | 층 | 셀 | walkable | z오프셋 | spawn일 | despawn일 |
|---|---|---|---|---|---|---|---|
| `TS_L1_DECK_001` | formwork_deck | L1 | 1198 | 예 | -320 mm | 13 | 28 |
| `TS_L1_SHORE_001` | shoring | L1 | 260 | 아니오 | 0 mm | None | None |
| `TS_L2_DECK_001` | formwork_deck | L2 | 1927 | 예 | -250 mm | 78 | 100 |
| `TS_L2_SCAF_001` | scaffold | L2 | 507 | 예 | 0 mm | 58 | 137 |
| `TS_L2_SHORE_001` | shoring | L2 | 118 | 아니오 | 0 mm | None | None |
| `TS_L2_SHORE_002` | shoring | L2 | 240 | 아니오 | 0 mm | None | None |
| `TS_L3_DECK_001` | formwork_deck | L3 | 519 | 예 | -500 mm | 128 | 136 |
| `TS_L4_DECK_001` | formwork_deck | L4 | 1187 | 예 | -313 mm | 157 | 165 |
| `TS_L4_SCAF_001` | scaffold | L4 | 504 | 예 | 0 mm | 144 | 204 |
| `TS_L4_SHORE_001` | shoring | L4 | 276 | 아니오 | 0 mm | None | None |
| `TS_L5_DECK_001` | formwork_deck | L5 | 1180 | 예 | -313 mm | 205 | 213 |
| `TS_L5_SCAF_001` | scaffold | L5 | 504 | 예 | 0 mm | 192 | 253 |
| `TS_L5_SHORE_001` | shoring | L5 | 275 | 아니오 | 0 mm | None | None |
| `TS_L6_DECK_001` | formwork_deck | L6 | 1179 | 예 | -330 mm | 253 | 261 |
| `TS_L6_SCAF_001` | scaffold | L6 | 504 | 예 | 0 mm | 240 | 303 |
| `TS_L6_SHORE_001` | shoring | L6 | 275 | 아니오 | 0 mm | None | None |
| `TS_L7_DECK_001` | formwork_deck | L7 | 1126 | 예 | -720 mm | 315 | 325 |
| `TS_L7_SHORE_001` | shoring | L7 | 138 | 아니오 | 0 mm | None | None |
| `TS_L8_DECK_001` | formwork_deck | L8 | 856 | 예 | -720 mm | 342 | 350 |

## TS2 동바리 — 바닥 없어 제외한 기둥

H008 zone 은 상부 슬래브를 하부 슬래브에 투영해 만든 것이라, 하부층 정적 격자에서 바닥이 없는(WALL·개구부) 셀이 섞인다. 기둥은 바닥 위에 서므로 그 셀은 제외했다.

| ts_id | 제외 기둥 수 |
|---|---|
| `TS_L1_SHORE_001` | 31 |
| `TS_L2_SHORE_001` | 4 |
| `TS_L2_SHORE_002` | 12 |
| `TS_L4_SHORE_001` | 19 |
| `TS_L5_SHORE_001` | 19 |
| `TS_L6_SHORE_001` | 17 |
| `TS_L7_SHORE_001` | 12 |

## 만들지 않은 것과 사유

| 규칙 | 대상 | 사유 |
|---|---|---|
| TS3 | L1 | 외피(커튼월/창문 설치) 태스크가 이 층에 없어 despawn 원천이 없다 — 억지로 만들지 않고 건너뛴다 |
| TS3 | L3 | 외피(커튼월/창문 설치) 태스크가 이 층에 없어 despawn 원천이 없다 — 억지로 만들지 않고 건너뛴다 |
| TS3 | L7 | 외피(커튼월/창문 설치) 태스크가 이 층에 없어 despawn 원천이 없다 — 억지로 만들지 않고 건너뛴다 |
| TS3 | L8 | 외피(커튼월/창문 설치) 태스크가 이 층에 없어 despawn 원천이 없다 — 억지로 만들지 않고 건너뛴다 |
| TS4 | - | BASE 에는 없다. H007 단부 zone 8 개가 파생 원천이며, KE_H001_05(개구부 난간) 등 대안이 적용될 때 형상이 추가된다. |

## 자기 검증

| 항목 | 결과 | 비고 |
|---|---|---|
| spawn < despawn | OK | 위반 0건 [] |
| derived_from GUID 가 IFC 에 실재 | OK | 부재 0건 [] |
| TS1 데크 셀 수가 슬래브 면적과 같은 자릿수 | OK | 이탈 0건 [] |
| TS2 동바리가 H008 zone 안에만 존재 | OK | 이탈 0건 [] |
| 층별 실내 TS 총면적 ≤ 층 바닥면적 (비계 제외) | OK | 초과 0건 [] |
| TS3 비계 밴드가 슬래브 발자국 밖에만 존재 | OK | 발자국 안 0건 [] |

전항목 통과.
