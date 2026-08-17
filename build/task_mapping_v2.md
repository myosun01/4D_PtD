# 작업 위치 매핑 보강 (v3.3 Phase 1)

원본 `element_task_mapping.json` 은 **수정하지 않았다**. 백업 `data/element_task_mapping.backup.json`, 파생 위치표 `build/task_locations.json`.

## 보강 전후 매핑률 (액티비티 단위)

| | 매핑 | 미매핑 | 매핑률 |
|---|---|---|---|
| 보강 전 | 112 | 122 | 47.9% |
| **보강 후** | **234** | **0** | **100.0%** |

## 위치 원천별 내역

| source | 건수 |
|---|---|
| `inherited:pour` | 67 |
| `inherited:shoring` | 7 |
| `original` | 112 |
| `zone:material` | 48 |

## 분류별 보강 결과

| origin | 전체 | 보강 전 | 보강 후 |
|---|---|---|---|
| `original` | 178 | 112 | 178 |
| `augment:strip` | 8 | 0 | 8 |
| `augment:material` | 48 | 0 | 48 |

## 상속 규칙과 적용 내역

| 액티비티 | 규칙 | 상속 원천 | 층 | 셀/GUID 수 |
|---|---|---|---|---|
| `T-1` | `inherited:pour` | Basement/기둥 | Basement | 32 |
| `T-9101` | `zone:material` | HZ_L1_MAT_001 | Basement | 237 |
| `T-9103` | `zone:material` | HZ_L1_MAT_001 | Basement | 237 |
| `T-2` | `inherited:pour` | Basement/기둥 | Basement | 32 |
| `T-9105` | `zone:material` | HZ_L1_MAT_001 | Basement | 237 |
| `T-4` | `inherited:pour` | Basement/기둥 | Basement | 32 |
| `T-5` | `inherited:pour` | Basement/슬래브 | Basement | 9 |
| `T-6` | `inherited:pour` | Basement/슬래브 | Basement | 9 |
| `T-8` | `inherited:pour` | Basement/슬래브 | Basement | 9 |
| `T-9` | `inherited:pour` | Basement/벽체 | Basement | 124 |
| `T-9001` | `inherited:pour(최하층)` | Basement/슬래브 | Basement(유지) | 9 |
| `T-10` | `inherited:pour` | Basement/벽체 | Basement | 124 |
| `T-9104` | `zone:material` | HZ_L1_MAT_001 | Basement | 237 |
| `T-9102` | `zone:material` | HZ_L1_MAT_001 | Basement | 237 |
| `T-12` | `inherited:pour` | Basement/벽체 | Basement | 124 |
| `T-9106` | `zone:material` | HZ_L1_MAT_001 | Basement | 237 |
| `T-9109` | `zone:material` | HZ_L2_MAT_001 | Level_01 | 271 |
| `T-15` | `inherited:pour` | Level_01/기둥 | Level_01 | 90 |
| `T-9107` | `zone:material` | HZ_L2_MAT_001 | Level_01 | 271 |
| `T-16` | `inherited:pour` | Level_01/기둥 | Level_01 | 90 |
| `T-9111` | `zone:material` | HZ_L2_MAT_001 | Level_01 | 271 |
| `T-18` | `inherited:pour` | Level_01/기둥 | Level_01 | 90 |
| `T-19` | `inherited:pour` | Level_01/슬래브 | Level_01 | 16 |
| `T-20` | `inherited:pour` | Level_01/슬래브 | Level_01 | 16 |
| `T-22` | `inherited:pour` | Level_01/슬래브 | Level_01 | 16 |
| `T-23` | `inherited:pour` | Level_01/벽체 | Level_01 | 126 |
| `T-9002` | `inherited:shoring` | HZ_L1_SHORE_001 | Level_01→L1 | 1173 |
| `T-24` | `inherited:pour` | Level_01/벽체 | Level_01 | 126 |
| `T-9110` | `zone:material` | HZ_L2_MAT_001 | Level_01 | 271 |
| `T-9108` | `zone:material` | HZ_L2_MAT_001 | Level_01 | 271 |
| `T-26` | `inherited:pour` | Level_01/벽체 | Level_01 | 126 |
| `T-9112` | `zone:material` | HZ_L2_MAT_001 | Level_01 | 271 |
| `T-9113` | `zone:material` | HZ_L3_MAT_001 | Level_02a_Parking | 42 |
| `T-31` | `inherited:pour` | Level_02a_Parking/슬래브 | Level_02a_Parking | 1 |
| `T-9115` | `zone:material` | HZ_L3_MAT_001 | Level_02a_Parking | 42 |
| `T-32` | `inherited:pour` | Level_02a_Parking/슬래브 | Level_02a_Parking | 1 |
| `T-9117` | `zone:material` | HZ_L3_MAT_001 | Level_02a_Parking | 42 |
| `T-34` | `inherited:pour` | Level_02a_Parking/슬래브 | Level_02a_Parking | 1 |
| `T-35` | `inherited:pour` | Level_02a_Parking/벽체 | Level_02a_Parking | 4 |
| `T-9003` | `inherited:shoring` | HZ_L2_SHORE_001 | Level_02a_Parking→L2 | 489 |
| `T-36` | `inherited:pour` | Level_02a_Parking/벽체 | Level_02a_Parking | 4 |
| `T-9116` | `zone:material` | HZ_L3_MAT_001 | Level_02a_Parking | 42 |
| `T-9114` | `zone:material` | HZ_L3_MAT_001 | Level_02a_Parking | 42 |
| `T-38` | `inherited:pour` | Level_02a_Parking/벽체 | Level_02a_Parking | 4 |
| `T-9118` | `zone:material` | HZ_L3_MAT_001 | Level_02a_Parking | 42 |
| `T-9121` | `zone:material` | HZ_L4_MAT_001 | Level_02 | 256 |
| `T-41` | `inherited:pour` | Level_02/기둥 | Level_02 | 38 |
| `T-9119` | `zone:material` | HZ_L4_MAT_001 | Level_02 | 256 |
| `T-42` | `inherited:pour` | Level_02/기둥 | Level_02 | 38 |
| `T-9123` | `zone:material` | HZ_L4_MAT_001 | Level_02 | 256 |
| `T-44` | `inherited:pour` | Level_02/기둥 | Level_02 | 38 |
| `T-45` | `inherited:pour` | Level_02/슬래브 | Level_02 | 2 |
| `T-46` | `inherited:pour` | Level_02/슬래브 | Level_02 | 2 |
| `T-48` | `inherited:pour` | Level_02/슬래브 | Level_02 | 2 |
| `T-49` | `inherited:pour` | Level_02/벽체 | Level_02 | 100 |
| `T-9004` | `inherited:shoring` | HZ_L2_SHORE_002 | Level_02→L2 | 1011 |
| `T-50` | `inherited:pour` | Level_02/벽체 | Level_02 | 100 |
| `T-9122` | `zone:material` | HZ_L4_MAT_001 | Level_02 | 256 |
| `T-9120` | `zone:material` | HZ_L4_MAT_001 | Level_02 | 256 |
| `T-52` | `inherited:pour` | Level_02/벽체 | Level_02 | 100 |
| `T-9124` | `zone:material` | HZ_L4_MAT_001 | Level_02 | 256 |
| `T-9127` | `zone:material` | HZ_L5_MAT_001 | Level_03 | 216 |
| `T-56` | `inherited:pour` | Level_03/기둥 | Level_03 | 38 |
| `T-9125` | `zone:material` | HZ_L5_MAT_001 | Level_03 | 216 |
| `T-57` | `inherited:pour` | Level_03/기둥 | Level_03 | 38 |
| `T-9129` | `zone:material` | HZ_L5_MAT_001 | Level_03 | 216 |
| `T-59` | `inherited:pour` | Level_03/기둥 | Level_03 | 38 |
| `T-60` | `inherited:pour` | Level_03/슬래브 | Level_03 | 3 |
| `T-61` | `inherited:pour` | Level_03/슬래브 | Level_03 | 3 |
| `T-63` | `inherited:pour` | Level_03/슬래브 | Level_03 | 3 |
| `T-64` | `inherited:pour` | Level_03/벽체 | Level_03 | 100 |
| `T-9005` | `inherited:shoring` | HZ_L4_SHORE_001 | Level_03→L4 | 1190 |
| `T-65` | `inherited:pour` | Level_03/벽체 | Level_03 | 100 |
| `T-9128` | `zone:material` | HZ_L5_MAT_001 | Level_03 | 216 |
| `T-9126` | `zone:material` | HZ_L5_MAT_001 | Level_03 | 216 |
| `T-67` | `inherited:pour` | Level_03/벽체 | Level_03 | 100 |
| `T-9130` | `zone:material` | HZ_L5_MAT_001 | Level_03 | 216 |
| `T-9133` | `zone:material` | HZ_L6_MAT_001 | Level_04 | 195 |
| `T-71` | `inherited:pour` | Level_04/기둥 | Level_04 | 38 |
| `T-9131` | `zone:material` | HZ_L6_MAT_001 | Level_04 | 195 |
| `T-72` | `inherited:pour` | Level_04/기둥 | Level_04 | 38 |
| `T-9135` | `zone:material` | HZ_L6_MAT_001 | Level_04 | 195 |
| `T-74` | `inherited:pour` | Level_04/기둥 | Level_04 | 38 |
| `T-75` | `inherited:pour` | Level_04/슬래브 | Level_04 | 3 |
| `T-76` | `inherited:pour` | Level_04/슬래브 | Level_04 | 3 |
| `T-78` | `inherited:pour` | Level_04/슬래브 | Level_04 | 3 |
| `T-79` | `inherited:pour` | Level_04/벽체 | Level_04 | 102 |
| `T-9006` | `inherited:shoring` | HZ_L5_SHORE_001 | Level_04→L5 | 1182 |
| `T-80` | `inherited:pour` | Level_04/벽체 | Level_04 | 102 |
| `T-9134` | `zone:material` | HZ_L6_MAT_001 | Level_04 | 195 |
| `T-9132` | `zone:material` | HZ_L6_MAT_001 | Level_04 | 195 |
| `T-82` | `inherited:pour` | Level_04/벽체 | Level_04 | 102 |
| `T-9136` | `zone:material` | HZ_L6_MAT_001 | Level_04 | 195 |
| `T-9139` | `zone:material` | HZ_L7_MAT_001 | Level_05 | 238 |
| `T-86` | `inherited:pour` | Level_05/기둥 | Level_05 | 43 |
| `T-9137` | `zone:material` | HZ_L7_MAT_001 | Level_05 | 238 |
| `T-87` | `inherited:pour` | Level_05/기둥 | Level_05 | 43 |
| `T-9141` | `zone:material` | HZ_L7_MAT_001 | Level_05 | 238 |
| `T-89` | `inherited:pour` | Level_05/기둥 | Level_05 | 43 |
| `T-90` | `inherited:pour` | Level_05/보 | Level_05 | 8 |
| `T-91` | `inherited:pour` | Level_05/보 | Level_05 | 8 |
| `T-93` | `inherited:pour` | Level_05/보 | Level_05 | 8 |
| `T-94` | `inherited:pour` | Level_05/슬래브 | Level_05 | 4 |
| `T-95` | `inherited:pour` | Level_05/슬래브 | Level_05 | 4 |
| `T-97` | `inherited:pour` | Level_05/슬래브 | Level_05 | 4 |
| `T-98` | `inherited:pour` | Level_05/벽체 | Level_05 | 51 |
| `T-9007` | `inherited:shoring` | HZ_L6_SHORE_001 | Level_05→L6 | 1171 |
| `T-99` | `inherited:pour` | Level_05/벽체 | Level_05 | 51 |
| `T-9140` | `zone:material` | HZ_L7_MAT_001 | Level_05 | 238 |
| `T-9138` | `zone:material` | HZ_L7_MAT_001 | Level_05 | 238 |
| `T-101` | `inherited:pour` | Level_05/벽체 | Level_05 | 51 |
| `T-9142` | `zone:material` | HZ_L7_MAT_001 | Level_05 | 238 |
| `T-9143` | `zone:material` | HZ_L8_MAT_001 | Roof | 99 |
| `T-105` | `inherited:pour` | Roof/슬래브 | Roof | 3 |
| `T-9145` | `zone:material` | HZ_L8_MAT_001 | Roof | 99 |
| `T-106` | `inherited:pour` | Roof/슬래브 | Roof | 3 |
| `T-9144` | `zone:material` | HZ_L8_MAT_001 | Roof | 99 |
| `T-9147` | `zone:material` | HZ_L8_MAT_001 | Roof | 99 |
| `T-9146` | `zone:material` | HZ_L8_MAT_001 | Roof | 99 |
| `T-108` | `inherited:pour` | Roof/슬래브 | Roof | 3 |
| `T-9148` | `zone:material` | HZ_L8_MAT_001 | Roof | 99 |
| `T-9008` | `inherited:shoring` | HZ_L7_SHORE_001 | Roof→L7 | 591 |

## 매핑 불가로 남은 것

없음 — 234건 전부 위치 원천이 확정되었다.

## 위치 원천은 확정되었으나 좌표가 나오지 않는 것

`element_task_mapping.json` 이 **manifest 에 없는 GUID** 를 참조하는 기존 데이터 결손이다 (참조 1438개 중 160개 부재, 11.1%). 위치를 지어내지 않고 그대로 두었으며, 해당 액티비티는 실행 시 폴백(층 배회)으로 처리되고 노출 주 집계에서 제외된다.

| 액티비티 | 이름 | source | 참조 GUID |
|---|---|---|---|
| `T-56` | Level 03 기둥 철근배근 | `inherited:pour` | 38 |
| `T-57` | Level 03 기둥 거푸집 | `inherited:pour` | 38 |
| `T-59` | Level 03 기둥 양생 | `inherited:pour` | 38 |
| `T-71` | Level 04 기둥 철근배근 | `inherited:pour` | 38 |
| `T-72` | Level 04 기둥 거푸집 | `inherited:pour` | 38 |
| `T-74` | Level 04 기둥 양생 | `inherited:pour` | 38 |
| `T-302` | Basement 기둥 콘크리트 타설 (Day 2/2) | `original` | 2 |
| `T-2506` | Level 01 벽체 콘크리트 타설 (Day 6/6) | `original` | 1 |
| `T-5801` | Level 03 기둥 콘크리트 타설 (Day 1/2) | `original` | 30 |
| `T-5802` | Level 03 기둥 콘크리트 타설 (Day 2/2) | `original` | 8 |
| `T-7301` | Level 04 기둥 콘크리트 타설 (Day 1/2) | `original` | 30 |
| `T-7302` | Level 04 기둥 콘크리트 타설 (Day 2/2) | `original` | 8 |
| `T-8802` | Level 05 기둥 콘크리트 타설 (Day 2/2) | `original` | 13 |

## 양생 22건 — crewSize 확인

`crewSize` 분포: {0: 22}. **이미 전부 0이므로 변경하지 않았다** (공기 변화 없음). 워커가 생성되지 않으므로 노출에 기여하지 않는다. 위치는 나중에 점검·살수 작업을 넣을 때를 위해 매핑해 두었다.

