# 워커 작업 위치 매핑 진단 (v3.2 Phase 0)

조사일 2026-08-09 · 대상 `project/schedule.json` 234 액티비티
**진단만 수행했다. 코드·데이터를 수정하지 않았다.**

---

## 0. 요약

| | 건수 |
|---|---|
| 전체 액티비티 | 234 |
| GUID 매핑 있음 | **112** (47.9%) |
| GUID 매핑 없음 | **122** (52.1%) |

워커-일 단위로는 유도 600 / 폴백 1,430 (폴백 70.4%).

**가장 중요한 발견: 폴백이 전체 위험셀 노출의 61.3% 를 만들고 있다.** 폴백 좌표가
위험구역을 피해 있는 것이 아니라 층 전체를 배회하기 때문이다. 자세한 것은 §3.

---

## 1. 미매핑 122건 분류

분류는 `build/construction_schedule_v2.csv` 의 `origin` 열을 그대로 썼다
(task_id 범위 추측이 아니다 — T-10001~10003 은 9000번대가 아니지만 `origin=original`
이고 실제로 매핑되어 있다).

| origin | 매핑 | 미매핑 |
|---|---|---|
| `original` | 112 | **66** |
| `augment:material` | 0 | **48** |
| `augment:strip` | 0 | **8** |

### 분류 1 — `augment:strip` 8건 (해체)

| 액티비티 | 이름 | level | ifc_class | 선행 |
|---|---|---|---|---|
| T-9001 | Basement 슬래브 거푸집·동바리 해체 | Basement | IfcSlab | 8 |
| T-9002 | Level 01 슬래브 거푸집·동바리 해체 | Level_01 | IfcSlab | 22 |
| T-9003 | Level 02a Parking 슬래브 거푸집·동바리 해체 | Level_02a_Parking | IfcSlab | 34 |
| T-9004 | Level 02 슬래브 거푸집·동바리 해체 | Level_02 | IfcSlab | 48 |
| T-9005 | Level 03 슬래브 거푸집·동바리 해체 | Level_03 | IfcSlab | 63 |
| T-9006 | Level 04 슬래브 거푸집·동바리 해체 | Level_04 | IfcSlab | 78 |
| T-9007 | Level 05 슬래브 거푸집·동바리 해체 | Level_05 | IfcSlab | 97 |
| T-9008 | Roof 슬래브 거푸집·동바리 해체 | Roof | IfcSlab | 108 |

**왜 없는가**: `scripts/augment_schedule.py` 가 나중에 신설한 태스크이고,
`element_task_mapping.json` 은 그 이전(원본 178 태스크) 산출물이라 항목 자체가 없다.

**무엇으로 매핑 가능한가**: 같은 층 슬래브의 GUID. 8건 전부 `(level, IfcSlab)` 에
형제 GUID 가 존재한다. 해체 대상은 그 슬래브를 받치던 거푸집·동바리이므로
슬래브 풋프린트가 곧 작업 영역이다. **매핑 가능.**

**미해결 쟁점 (Phase 1 에서 판단 필요)**: 해체는 슬래브 *하부*에서 이루어진다.
현재 이 8건의 `zone` 은 상부층(슬래브가 속한 층)으로 배정되어 있다. 셀 좌표는
같아도 어느 층 격자에 워커를 놓느냐가 달라지며, 이는 `LCR_SHORING_COLLAPSE`
(H008, 직하부 zone)와 겹치는 층이기도 하다. 확신 없이 층을 바꾸면 collapse 노출이
인위적으로 생긴다.

### 분류 2 — `augment:material` 48건 (자재 반입·소진)

T-9101 ~ T-9148. 층 8개 × 자재 3종(거푸집·철근·콘크리트) × 2단계(반입·소진) = 48.

| 예시 | 이름 | level | CSV ifc_class | workType |
|---|---|---|---|---|
| T-9101 | Basement 거푸집 반입 | Basement | IfcColumn | delivery |
| T-9102 | Basement 거푸집 소진·정리 | Basement | IfcWall | consume_or_remove |
| T-9103 | Basement 철근 반입 | Basement | IfcColumn | delivery |
| … | | | | |
| T-9148 | Roof 콘크리트 소진·정리 | Roof | IfcSlab | consume_or_remove |

**왜 없는가**: 분류 1과 같은 이유(신설 태스크). 더 근본적으로, **자재 반입·소진은
특정 부재에 귀속되는 작업이 아니다.** CSV 의 `ifc_class` 는 후속 소비 공정을
가리키려고 붙은 값이지 작업 위치가 아니다.

**무엇으로 매핑 가능한가**: `build/hazard_zones.json` 의 H004_MaterialStorage
zone 이 층마다 정확히 1개씩 있다 — 이것이 적재구역이다.

| zone | level | storey | 셀 |
|---|---|---|---|
| HZ_L1_MAT_001 | L1 | Basement | 237 |
| HZ_L2_MAT_001 | L2 | Level_01 | 271 |
| HZ_L3_MAT_001 | L3 | Level_02a_Parking | 42 |
| HZ_L4_MAT_001 | L4 | Level_02 | 256 |
| HZ_L5_MAT_001 | L5 | Level_03 | 216 |
| HZ_L6_MAT_001 | L6 | Level_04 | 195 |
| HZ_L7_MAT_001 | L7 | Level_05 | 238 |
| HZ_L8_MAT_001 | L8 | Roof | 99 |

**GUID 가 아니라 zone 셀로 매핑해야 한다.** 형제 GUID 경로를 쓰면(48건 전부
`(level, ifc_class)` 형제가 존재하긴 한다) 자재 작업자를 기둥·벽체 위치에 놓게 되어
**틀린 매핑**이다. 위치 유도 로직이 GUID 경로와 zone 경로를 모두 받도록 확장해야 한다.

### 분류 3 — `original` 66건 (원본 공정표)

**전부 구조부재의 철근배근·거푸집·양생이다.** 타설(pour)만 매핑되어 있고
같은 부재의 나머지 3공정이 비어 있다.

| element_type | ifc_class | trade | workType | 건수 |
|---|---|---|---|---|
| 슬래브 | IfcSlab | formwork_erection | formwork | 8 |
| 슬래브 | IfcSlab | rebar | rebar | 8 |
| 양생 | IfcSlab | concrete_pour | curing | 8 |
| 벽체 | IfcWall | rebar | rebar | 7 |
| 벽체 | IfcWall | formwork_erection | formwork | 7 |
| 양생 | IfcWall | concrete_pour | curing | 7 |
| 기둥 | IfcColumn | rebar | rebar | 6 |
| 기둥 | IfcColumn | formwork_erection | formwork | 6 |
| 양생 | IfcColumn | concrete_pour | curing | 6 |
| 보 | IfcBeam | formwork_erection | formwork | 1 |
| 보 | IfcBeam | rebar | rebar | 1 |
| 양생 | IfcBeam | concrete_pour | curing | 1 |
| **계** | | | | **66** |

(슬래브 8 + 벽체 7 + 기둥 6 + 보 1) × 3공정 = 66. 정확히 맞는다.

대조군 — **매핑되어 있는 112건**:

| element_type | trade | workType | 건수 |
|---|---|---|---|
| 창문 | material_handling | opening_closure | 29 |
| 벽체 | concrete_pour | pour | 25 (+ T-10001~3 3건) |
| 문 | material_handling | opening_closure | 17 |
| 기둥 | concrete_pour | pour | 13 |
| 슬래브 | concrete_pour | slab | 10 |
| 계단 | material_handling | perimeter_protection | 10 |
| 난간 | material_handling | perimeter_protection | 4 |
| 보 | concrete_pour | pour | 1 |

**왜 없는가**: `element_task_mapping.json` 이 **부재를 '생성'하는 공정(타설·설치)에만
GUID 를 붙였고, 같은 부재를 만들기 위한 선행 공정(철근·거푸집)과 후속 대기
공정(양생)에는 붙이지 않았다.** 누락이지 원리적 불가가 아니다.

**무엇으로 매핑 가능한가**: 66건 **전부** `(level, ifc_class)` 에 형제 GUID 가 있다.
철근배근·거푸집은 그 부재가 세워질 자리에서 이루어지므로 타설 태스크와 같은
GUID 집합을 쓰는 것이 기하적으로 타당하다. **매핑 가능.**

**양생 22건은 별도 판단이 필요하다.** 양생은 작업자가 그 자리에 상주하는 공정이
아니다(`crewSize` 확인 필요). 위치를 부재에 묶는 것이 타당한지 Phase 1 에서 판단한다.

---

## 2. 유도된 600건의 작업 위치는 어떻게 계산되는가

`fourd_workers.WorkLocations` (v3.1 신규):

```
activityID  →  element_task_mapping.json[task_id].element_ids   (IFC GlobalId)
            →  unity_bundle/manifest.json[guid].bbox_ifc_m       (IFC 월드 m, Z-up)
            →  bbox XY 발자국이 덮는 격자 셀 (gridFrame 역함수)
            →  그날 격자에서 walkable 인 셀만 남김 (WALL·FLOOR_OPENING 제외)
```

셀 계산은 `_bbox_cells()` 로, bbox 의 min/max XY 를 `origin + (index+0.5)*res`
규약의 역으로 바꿔 **사각 발자국 전체**를 채운다. 폴리곤이 아니라 bbox 라
비스듬한 벽체는 실제보다 넓게 잡힌다 (Phase 1 에서 정밀화 여부 판단).

**GUID 해석률**: 참조 1,438개 중 manifest 에서 **1,278개 해석 (88.9%)**.
나머지 160개는 manifest 에 bbox 가 없는 요소다 (집계 호스트 등).

---

## 3. 폴백이 쓰는 좌표 — 가장 중요한 발견

`fourd_workers.make_workers`: 유도 실패 시

```python
targets = comp          # site.level(lv).main_component() 중 그날 walkable 인 셀 전체
```

즉 **층 전체를 배회한다.** 원점도 층 중심도 아니다.

| 층 | main_component 셀 |
|---|---|
| L1 | 1,152 |
| L2 | 1,899 |
| L3 | 519 |
| L4 | 1,134 |
| L5 | 1,111 |
| L6 | 1,110 |
| L7 | 1,115 |
| L8 | 855 |

### 폴백이 만드는 노출 측정 (전체 공기 350일, every=1 궤적 162,400행 대조)

| | 워커-스텝 | 위험셀 위 워커-스텝 |
|---|---|---|
| derived (매핑됨) | 52,480 | 29,116 |
| fallback (미매핑) | 109,920 | **46,178** |
| 합 | 162,400 | 75,294 |

**→ 전체 위험셀 노출의 61.3% 가 폴백 워커에서 나온다.**

위험유형별:

| hazard_type | derived | fallback | 폴백 비중 |
|---|---|---|---|
| H001 개구부 | 1,617 | 3,542 | **68.7%** |
| H002 협소통로 | 3,974 | 10,707 | **72.9%** |
| H004 적재물 | 3,608 | 12,020 | **76.9%** |
| H007 단부 | 4,881 | 17,618 | **78.3%** |
| H008 동바리붕괴 | 355 | 0 | 0.0% |
| H009 낙하물 | 14,270 | 974 | 6.4% |
| H011 장비동선 | 411 | 1,317 | **76.2%** |

### 이것이 뜻하는 것

- 폴백은 위험구역을 **피하지 않는다.** 층 전체를 배회하므로 위험셀을 확률적으로
  밟는다. 즉 노출 과소가 아니라 **기하와 무관한 가짜 노출**이 생긴다.
- 지시서가 우려한 바로 그 상황이다. 특히 **H001(개구부) 노출의 68.7%, H007(단부)
  노출의 78.3% 가 폴백에서 나온다.** 개구부·단부는 `ALT_S_H001_09`(개구부를
  동선에서 이격) 같은 variant 가 겨냥하는 채널이다. 지금 상태로 저감량을 뽑으면
  그 3분의 2 이상이 기하와 무관한 배회에서 나온 값이 된다.
- H008 이 0%, H009 가 6.4% 인 것은 두 유형이 **직하부(zone.below)** 라 그 층에서
  일하는 크루가 대부분 매핑된 타설 공정이기 때문으로 보인다 (Phase 1 확인 대상).

**폴백을 노출 집계에 포함할지 제외할지는 Phase 1 에서 근거와 함께 판단한다.**
지금 시점의 사실은 "포함되어 있고 61.3% 를 차지한다"는 것이다.

---

## 4. IFC 원천에 부재가 실재하는가

미매핑 122건 **전부** `(level, ifc_class)` 에 형제 GUID 가 존재한다.
**형제 GUID 가 아예 없는 미매핑은 0건이다.** 즉 분류 3은 (a) "IFC 에 실재하는데
매핑만 없음" 이고, (b) "IFC 에 없음" 은 하나도 없다.

다만 **Level_02a_Parking(L3)은 예외적으로 빈약하다**:

| 원천 | L3 / Level_02a_Parking 구성 |
|---|---|
| `unity_bundle/manifest.json` | 총 14 — IfcWall 4, IfcRailing 4, IfcWasteTerminal 2, IfcBuildingElementProxy 1, IfcSlab 1, IfcStairFlight 1, IfcStair 1 |
| `ifc_elements.json` | IfcWall 4, IfcRailing 2, IfcSlab 1, IfcStair 1 |

공정표는 이 층에 슬래브 3공정 + 벽체 3공정 = 6 태스크를 잡고 있는데
**슬래브가 IFC 에 1개뿐이다.** 매핑은 되지만 작업 영역이 실제 주차데크 면적을
대표하지 못한다. Phase 1 에서 이 층은 별도 취급이 필요하다.

층 이름 대조 (혼동 주의 — 표고 순서와 이름 순서가 어긋난다):

| storey (CSV·IFC) | levelID (site.json) | manifest 요소 |
|---|---|---|
| Basement | L1 | 270 |
| Level_01 | L2 | 5,292 |
| **Level_02a_Parking** | **L3** | **14** |
| Level_02 | L4 | 1,388 |
| Level_03 | L5 | 1,423 |
| Level_04 | L6 | 1,401 |
| Level_05 | L7 | 2,466 |
| Roof | L8 | 17 |
| Sea Level | (없음) | 1 |

---

## 5. 백업 상태

`element_task_mapping.json` (72,556 bytes) 의 **백업이 없다.**
`.bak`, `build/` 사본 어느 것도 존재하지 않는다. Phase 1 에서 이 파일을 보강한다면
**먼저 백업을 만들어야 한다.**

---

## 6. Phase 1 진입 전 정리 — 매핑 가능성 판정

| 분류 | 건수 | 판정 | 근거 |
|---|---|---|---|
| `augment:strip` 해체 | 8 | **가능** (GUID 경로) | 같은 층 슬래브 GUID 존재. 단 **층 배정(상부/하부) 판단 필요** |
| `augment:material` 자재 | 48 | **가능** (zone 경로 — 신규) | 층마다 H004 적재구역 zone 1개. **GUID 경로로 하면 틀린 매핑** |
| `original` 철근·거푸집 | 44 | **가능** (GUID 경로) | 타설 형제 GUID 를 그대로 상속 |
| `original` 양생 | 22 | **판단 필요** | 위치는 유도 가능하나 양생 중 작업자 상주 여부를 먼저 확인해야 함 |
| **계** | **122** | | |

원리적으로 매핑 불가한 건은 현재 **0건**이다. 다만 위 두 개의 "판단 필요"
(해체의 층 배정, 양생의 상주 여부)를 추측으로 넘기면 노출 수치가 왜곡되므로,
Phase 1 에서 근거를 확인한 뒤 처리한다.

---

**여기서 멈춘다.** 수정 착수 전 이 진단의 확인을 요청한다.
