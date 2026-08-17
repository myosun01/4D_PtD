# 공정표 보강 로그 (Part 1)

- 원본: `construction_schedule.csv` (178행, **수정하지 않음**)
- 산출: `build/construction_schedule_v2.csv` (234행)
- 파라미터: `retention_days=0`, `overlap_days=0`

> 두 파라미터는 **실험 변수**다. 기본값은 현행 유지(추가 지연 0일, 벽체 양생 완료 익일 착수)이며, '현실적인' 값으로 임의 조정하지 않았다.
> `retention_days` 는 KE_K_FS_02(존치기간 도면 명기)의 TemporalRule 입력이다.

## 1-1. 추가된 해체 작업 (층별)

| task_id | 작업명 | 층 | 기간(일) | 선행 | 시작 | 종료 |
|---|---|---|---:|---|---|---|
| 9001 | Basement 슬래브 거푸집·동바리 해체 | Basement | 3 | 8 | 2024-01-26 | 2024-01-28 |
| 9002 | Level 01 슬래브 거푸집·동바리 해체 | Level_01 | 6 | 22 | 2024-04-04 | 2024-04-09 |
| 9003 | Level 02a Parking 슬래브 거푸집·동바리 해체 | Level_02a_Parking | 1 | 34 | 2024-05-15 | 2024-05-15 |
| 9004 | Level 02 슬래브 거푸집·동바리 해체 | Level_02 | 1 | 48 | 2024-06-13 | 2024-06-13 |
| 9005 | Level 03 슬래브 거푸집·동바리 해체 | Level_03 | 1 | 63 | 2024-07-31 | 2024-07-31 |
| 9006 | Level 04 슬래브 거푸집·동바리 해체 | Level_04 | 1 | 78 | 2024-09-17 | 2024-09-17 |
| 9007 | Level 05 슬래브 거푸집·동바리 해체 | Level_05 | 2 | 97 | 2024-11-19 | 2024-11-20 |
| 9008 | Roof 슬래브 거푸집·동바리 해체 | Roof | 1 | 108 | 2024-12-15 | 2024-12-15 |

기간은 지시대로 해당 층 **설치 작업(슬래브 거푸집+동바리) 기간과 동일**하게 두었다. 착수는 슬래브 양생 완료 익일 + `retention_days`(기본 0).

## 1-2. 층간 중첩 — 선행 재배선

현행은 층 N+1 첫 작업의 선행이 층 N 마지막 창문이라 완전 순차였다. 이를 **층 N 벽체 양생**으로 옮겨 층 N 계단·문·창문이 층 N+1 골조와 병행하도록 했다.

| 층 | 첫 작업 | 기존 선행 | 변경 선행 |
|---|---|---|---|
| Level_01 | 15 | 1404 (Basement 문 설치 (Day 4/4)) | 12 (Basement 벽체 양생) |
| Level_02a_Parking | 31 | 3002 (Level 01 창문 설치 (Day 2/2)) | 26 (Level 01 벽체 양생) |
| Level_02 | 41 | 40 (Level 02a Parking 난간 설치) | 38 (Level 02a Parking 벽체 양생) |
| Level_03 | 56 | 5509 (Level 02 창문 설치 (Day 9/9)) | 52 (Level 02 벽체 양생) |
| Level_04 | 71 | 7009 (Level 03 창문 설치 (Day 9/9)) | 67 (Level 03 벽체 양생) |
| Level_05 | 86 | 8509 (Level 04 창문 설치 (Day 9/9)) | 82 (Level 04 벽체 양생) |
| Roof | 105 | 104 (Level 05 문 설치) | 101 (Level 05 벽체 양생) |

### 층별 시작·종료·중첩 전후 대조

| 층 | 전: 시작~종료 | 후: 시작~종료 | 직전 층과 중첩(일) |
|---|---|---|---:|
| Basement | 2024-01-01 ~ 2024-03-05 | 2024-01-01 ~ 2024-03-05 | 0 |
| Level_01 | 2024-03-06 ~ 2024-05-23 | 2024-02-22 ~ 2024-05-16 | 13 |
| Level_02a_Parking | 2024-05-24 ~ 2024-06-10 | 2024-05-02 ~ 2024-05-25 | 15 |
| Level_02 | 2024-06-11 ~ 2024-08-09 | 2024-05-18 ~ 2024-07-22 | 8 |
| Level_03 | 2024-08-10 ~ 2024-10-09 | 2024-07-05 ~ 2024-09-09 | 18 |
| Level_04 | 2024-10-10 ~ 2024-12-11 | 2024-08-22 ~ 2024-10-29 | 19 |
| Level_05 | 2024-12-12 ~ 2025-02-04 | 2024-10-11 ~ 2024-12-10 | 19 |
| Roof | 2025-02-05 ~ 2025-02-12 | 2024-12-02 ~ 2024-12-15 | 9 |

## 1-3. hazard_state 재부여

슬래브 개구부는 **타설 이후**에 존재한다. 거푸집면 자체가 작업면인 단계에 `opening_open` 이 붙어 있어 상태 부여 시점이 어긋나 있었다.

| task_id | 작업명 | 기존 | 변경 |
|---|---|---|---|
| 5 | Basement 슬래브 거푸집+동바리 | opening_open | edge_open |
| 6 | Basement 슬래브 철근배근 | opening_open | edge_open |
| 701 | Basement 슬래브 콘크리트 타설 (Day 1/2) | opening_open | edge_open |
| 702 | Basement 슬래브 콘크리트 타설 (Day 2/2) | opening_open | edge_open |
| 8 | Basement 슬래브 양생 | (빈칸) | opening_open |
| 19 | Level 01 슬래브 거푸집+동바리 | opening_open | edge_open |
| 20 | Level 01 슬래브 철근배근 | opening_open | edge_open |
| 2101 | Level 01 슬래브 콘크리트 타설 (Day 1/2) | opening_open | edge_open |
| 2102 | Level 01 슬래브 콘크리트 타설 (Day 2/2) | opening_open | edge_open |
| 22 | Level 01 슬래브 양생 | (빈칸) | opening_open |
| 31 | Level 02a Parking 슬래브 거푸집+동바리 | opening_open | edge_open |
| 32 | Level 02a Parking 슬래브 철근배근 | opening_open | edge_open |
| 33 | Level 02a Parking 슬래브 콘크리트 타설 | opening_open | edge_open |
| 34 | Level 02a Parking 슬래브 양생 | (빈칸) | opening_open |
| 45 | Level 02 슬래브 거푸집+동바리 | opening_open | edge_open |
| 46 | Level 02 슬래브 철근배근 | opening_open | edge_open |
| 47 | Level 02 슬래브 콘크리트 타설 | opening_open | edge_open |
| 48 | Level 02 슬래브 양생 | (빈칸) | opening_open |
| 60 | Level 03 슬래브 거푸집+동바리 | opening_open | edge_open |
| 61 | Level 03 슬래브 철근배근 | opening_open | edge_open |
| 62 | Level 03 슬래브 콘크리트 타설 | opening_open | edge_open |
| 63 | Level 03 슬래브 양생 | (빈칸) | opening_open |
| 75 | Level 04 슬래브 거푸집+동바리 | opening_open | edge_open |
| 76 | Level 04 슬래브 철근배근 | opening_open | edge_open |
| 77 | Level 04 슬래브 콘크리트 타설 | opening_open | edge_open |
| 78 | Level 04 슬래브 양생 | (빈칸) | opening_open |
| 94 | Level 05 슬래브 거푸집+동바리 | opening_open | edge_open |
| 95 | Level 05 슬래브 철근배근 | opening_open | edge_open |
| 96 | Level 05 슬래브 콘크리트 타설 | opening_open | edge_open |
| 97 | Level 05 슬래브 양생 | (빈칸) | opening_open |
| 105 | Roof 슬래브 거푸집+동바리 | opening_open | edge_open |
| 106 | Roof 슬래브 철근배근 | opening_open | edge_open |
| 107 | Roof 슬래브 콘크리트 타설 | opening_open | edge_open |
| 108 | Roof 슬래브 양생 | (빈칸) | opening_open |

> 신설 해체 작업의 `hazard_state` 는 지시서 1-1 이 명시한 `edge_open` 을 따랐다. 다만 1-3 의 일반 규칙("타설 완료 이후 → opening_open")을 그대로 적용하면 `opening_open` 이 되어 두 지시가 어긋난다. 더 구체적인 1-1 을 따랐고, 개구부 채널이 필요하면 이 값을 바꾸면 된다.

## 1-4. 공기 변화

| 구분 | 일수 |
|---|---:|
| 현행 | 409 |
| 보강 후 | 350 |
| 변화 | -59 |

해체 작업 8건이 추가되었음에도 공기가 줄어든 것은 층간 중첩 때문이다. 해체는 후속 공정과 병행 가능하고, 층 N 계단·문·창문이 층 N+1 골조와 겹치면서 순차 사슬이 짧아졌다.

## 검증

| 검사 | 위반 |
|---|---:|
| 선후관계 (FS: 선행 종료 < 후행 시작) | **0** |
| 물리 제약 (층 N+1 동바리 > 층 N 슬래브 양생) | **0** |

물리 제약은 '층 N+1 슬래브 거푸집·동바리는 층 N 슬래브 양생 완료 후에만 착수 가능'(동바리가 하부 슬래브에 지지됨)을 검사한 것이다.

## 추가된 열

- `lag_days` — FS 관계의 지연일수. 해체 작업은 `retention_days`, 층 첫 작업은 `-overlap_days`.
- `origin` — `original` / `augment:strip`. 신설 행 추적용.

