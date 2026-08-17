# Phase 0 — 존치기간 트리거 조기 발화 검증

## 판정

**조기 발화 아님.** H008(동바리 존치구간) 인스턴스 7건 전부 despawn 이 해체 작업(`origin=augment:strip`, T-9001~T-9008)에 걸려 있으며, 양생 종료일이 아니라 **해체 종료일**에 소멸한다.

따라서 `lifecycle.py` 46~63행의 예외 처리를 제거하지 않았다. 지시서 '하지 말 것' 의 "Phase 0 검증 없이 예외 처리를 먼저 제거하는 것" 및 "조기 발화가 아닌데 제거하면 다른 채널이 깨질 수 있다" 에 따른다.

### 예외가 발화하지 않는 이유

`lifecycle.Trigger.matches()` 의 예외는 바인딩된 액티비티의 `trade` 가 `formwork_stripping` **이 아닐 때만** 도달한다(`if got != want:` 안쪽). v2.5 Phase 2 에서 `project/schedule.json` 을 보강 공정표 기준으로 재생성하면서 해체 작업 8건이 실제로 `trade=formwork_stripping` 을 갖게 되었고, `temp_works.py` R3 가 그 작업을 `despawnActivity` 로 바인딩한다. 그래서 첫 비교에서 이미 매칭되어 예외 분기에 도달하지 않는다 — 주석이 예고한 "무영향" 조건이 실제로 성립한다.

또한 `despawn_day` 는 `despawn_tr.event_day(dact)` 로 **바인딩된 그 액티비티**에서 계산되므로, 필터가 통과하는 한 어느 작업에 걸렸는지가 곧 소멸 시점이다. 양생 작업은 바인딩되지 않으므로 소멸 시점에 관여하지 않는다.

## H008 인스턴스별 대조표

기준일(day 0) = 2024-01-01

| zone | 층 | spawn 작업 | spawn 일자 | despawn 작업 | despawn 일자 | 존치일 | despawn origin |
|---|---|---|---|---|---|---:|---|
| `HZ-047-LCR_SHORING_COLLAPSE-T-2102` | L1 | Level 01 슬래브 콘크리트 타설 (Day 2/2) | 2024-03-30 | Level 01 슬래브 거푸집·동바리 해체 | 2024-04-10 | 11 | `augment:strip` |
| `HZ-048-LCR_SHORING_COLLAPSE-T-33` | L2 | Level 02a Parking 슬래브 콘크리트 타설 | 2024-05-10 | Level 02a Parking 슬래브 거푸집·동바리 해체 | 2024-05-16 | 6 | `augment:strip` |
| `HZ-049-LCR_SHORING_COLLAPSE-T-47` | L2 | Level 02 슬래브 콘크리트 타설 | 2024-06-08 | Level 02 슬래브 거푸집·동바리 해체 | 2024-06-14 | 6 | `augment:strip` |
| `HZ-050-LCR_SHORING_COLLAPSE-T-62` | L4 | Level 03 슬래브 콘크리트 타설 | 2024-07-26 | Level 03 슬래브 거푸집·동바리 해체 | 2024-08-01 | 6 | `augment:strip` |
| `HZ-051-LCR_SHORING_COLLAPSE-T-77` | L5 | Level 04 슬래브 콘크리트 타설 | 2024-09-12 | Level 04 슬래브 거푸집·동바리 해체 | 2024-09-18 | 6 | `augment:strip` |
| `HZ-052-LCR_SHORING_COLLAPSE-T-96` | L6 | Level 05 슬래브 콘크리트 타설 | 2024-11-14 | Level 05 슬래브 거푸집·동바리 해체 | 2024-11-21 | 7 | `augment:strip` |
| `HZ-053-LCR_SHORING_COLLAPSE-T-107` | L7 | Roof 슬래브 콘크리트 타설 | 2024-12-10 | Roof 슬래브 거푸집·동바리 해체 | 2024-12-16 | 6 | `augment:strip` |

## 공정표 대조 — 양생 종료일 vs 해체 종료일

despawn 이 어느 쪽에 걸렸는지가 판정의 핵심이다.

| zone | despawn 층 | 양생 작업 | 양생 종료 | 해체 작업 | 해체 종료 | despawn 이 걸린 날 | 판정 |
|---|---|---|---|---|---|---|---|
| `HZ-047-LCR_SHORING_COLLAPSE-T-2102` | Level_01 | T-22 | 2024-04-03 | T-9002 | 2024-04-09 | **2024-04-09** | 정상(해체 종료) |
| `HZ-048-LCR_SHORING_COLLAPSE-T-33` | Level_02a_Parking | T-34 | 2024-05-14 | T-9003 | 2024-05-15 | **2024-05-15** | 정상(해체 종료) |
| `HZ-049-LCR_SHORING_COLLAPSE-T-47` | Level_02 | T-48 | 2024-06-12 | T-9004 | 2024-06-13 | **2024-06-13** | 정상(해체 종료) |
| `HZ-050-LCR_SHORING_COLLAPSE-T-62` | Level_03 | T-63 | 2024-07-30 | T-9005 | 2024-07-31 | **2024-07-31** | 정상(해체 종료) |
| `HZ-051-LCR_SHORING_COLLAPSE-T-77` | Level_04 | T-78 | 2024-09-16 | T-9006 | 2024-09-17 | **2024-09-17** | 정상(해체 종료) |
| `HZ-052-LCR_SHORING_COLLAPSE-T-96` | Level_05 | T-97 | 2024-11-18 | T-9007 | 2024-11-20 | **2024-11-20** | 정상(해체 종료) |
| `HZ-053-LCR_SHORING_COLLAPSE-T-107` | Roof | T-108 | 2024-12-14 | T-9008 | 2024-12-15 | **2024-12-15** | 정상(해체 종료) |

## retention_days 파라미터 유효성

`retention_days` 는 `augment_schedule.py` 에서 양생 종료 → 해체 착수 사이의 추가 지연으로 들어가며, 해체 작업의 날짜를 밀어낸다. despawn 이 해체 작업에 걸려 있으므로 이 파라미터를 키우면 존치 일수가 그만큼 늘어난다 — **무력화되지 않았다.** 따라서 KE_K_FS_02(존치기간 도면 명기)의 TemporalRule 효과가 0 으로 산출되지 않는다.

현재 기본값은 `retention_days=0`(현행 유지)이므로 존치 일수는 '타설 착수 → 해체 완료 익일' 구간이다.

### 실증

`augment_schedule.py --retention-days 3` 으로 재생성하니 해체 작업 착수일이 정확히 3일 밀렸다.

| 해체 task | retention_days=0 | retention_days=3 |
|---|---|---|
| T-9001 | 2024-01-26 | 2024-01-29 |
| T-9002 | 2024-04-04 | 2024-04-07 |
| T-9003 | 2024-05-15 | 2024-05-18 |

despawn 이 이 작업에 걸려 있으므로 존치 일수도 같이 늘어난다. (부수 효과: 전체 공기가 350 → 353 일로 늘어난다. 존치기간 연장이 크리티컬 패스에 실리기 때문이며, 이는 실험에서 관측해야 할 트레이드오프다.) 검증 후 기본값 0 으로 되돌려 두었다.

