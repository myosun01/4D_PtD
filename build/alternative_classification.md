# 대안 효과 전수 분류 (v3.6 Part B)

`promoted=TRUE` **60건** 전수. 판정 기준은 "계수가 있는가"가 아니라 **"BASE 와 ALT 가 모델 표현에서 다른가"**다.

| 분류 | 뜻 | 건수 |
|---|---|---|
| **[S]** | 시뮬레이션 가능 — variant 생성 대상 | **10** |
| **[P]** | 규칙 미작성 | **27** |
| **[C]** | 계수 미확보 (원천에 값이 없음) | **5** |
| **[X]** | 모델 표현 불가 (BASE≡ALT) | **14** |
| **[D]** | 배관 결함 (지시는 있는데 코드가 못 읽음) | **4** |
| | **합계** | **60** |

## HoC 등급 × 분류 교차표

| HoC 등급 | S | P | C | X | D | 계 |
|---|---|---|---|---|---|---|
| 위험회피 | 0 | 0 | 0 | 1 | 0 | 1 |
| 제거 | 3 | 6 | 0 | 3 | 1 | 13 |
| 대체 | 2 | 4 | 0 | 3 | 1 | 10 |
| 공학적 | 4 | 15 | 4 | 6 | 1 | 30 |
| 경고 | 0 | 2 | 1 | 1 | 0 | 4 |
| 관리적 | 1 | 0 | 0 | 0 | 1 | 2 |
| **계** | **10** | **27** | **5** | **14** | **4** | **60** |

## [S] 시뮬레이션 가능 — 10건

| entry_id | HoC | 사고유형 | 근거 | BASE↔ALT 차이 |
|---|---|---|---|---|
| `KE_H001_01` | 제거 | 떨어짐 | SpatialChangeRule `remove` — 격자에서 직접 구분된다 | zone 이 사라진다 |
| `KE_H001_04` | 제거 | 떨어짐 | TemporalRule 파싱 `set_fs_lag` | 공정·생멸 시점이 이동 (set_fs_lag) |
| `KE_H001_05` | 공학적 | 떨어짐 | 채널 배율 적용 {'fall': 0.1} | λ 배율 {'fall': 0.1} |
| `KE_M_Fall_FormErection_02` | 공학적 | 떨어짐 | 채널 배율 적용 {'edge': 0.1} | λ 배율 {'edge': 0.1} |
| `KE_S_CP_04` | 공학적 | 무너짐 | 채널 배율 적용 {'collapse_zone': 0.5} | λ 배율 {'collapse_zone': 0.5} |
| `KE_S_CP_05` | 제거 | 무너짐 | TemporalRule 파싱 `min_curing_lag` | 공정·생멸 시점이 이동 (min_curing_lag) |
| `KE_S_FE_08` | 대체 | 떨어짐 | SpatialChangeRule `remove` — 격자에서 직접 구분된다 | zone 이 사라진다 |
| `KE_T_CP_01` | 대체 | 무너짐 | SpatialChangeRule `remove` — 격자에서 직접 구분된다 | zone 이 사라진다 |
| `KE_T_CP_03` | 관리적 | 무너짐 | SpatialChangeRule `block` — 격자에서 직접 구분된다 | 진입이 차단된다 |
| `KE_T_HS_02` | 공학적 | 물체에맞음 | 채널 배율 적용 {'drop_zone': 0.35} | λ 배율 {'drop_zone': 0.35} |

## [D] 배관 결함 — 수정 내역 — 4건

| entry_id | HoC | 결함 | 조치 |
|---|---|---|---|
| `KE_K_FS_02` | 관리적 | scheduleShift 'formwork_stripping(Z) requires retention_period_elapsed(Z)' 를 parse_schedule_shift 가 인식하지 못했다. | 패턴 추가 (v3.6). v3.6 Part A 에서 KCS 3개 층 존치를 temp_works R3 에 구현해 대응이 명확해졌다. 실행은 zone 생성이 하며 스케줄은 건드리지 않는다. |
| `KE_K_HS_06` | 공학적 | simulation_action 이 'block_agent_entry_to_drop_influence_zone' 인데 controls 가 정확히 'block_agent_entry' 만 받아 통과하지 못했다. | 접두 일치로 변경 (v3.6). 대상은 appliesToCellType=drop_zone 이 이미 지정. |
| `KE_T_FS_01` | 제거 | scheduleShift 'opening_closure(Z) FS-before formwork_stripping(Z)' 는 parse 는 되지만 apply_temporal_shift 가 fs_before 를 실행하지 않는다 (Phase 3 에서 '기록만'으로 남긴 항목). | **수정하지 않았다.** 선후관계 삽입은 CPM 재계산을 유발해 공기가 바뀔 수 있고, 그 영향은 별도 검증이 필요하다. 미수정 사유를 남긴다. |
| `KE_T_HS_04` | 대체 | 계수 materialProbMultiplier=0.50 이 있는데 drop_zone 채널의 키가 hazard_weight_multiplier 로 고정되어 있어 읽히지 않았다. | drop_zone 이 두 키를 모두 받도록 변경 (v3.6). **기존 값의 의미는 바뀌지 않았다** — RULE_HS_DEBRISNET 의 hazardWeightMultiplier 해석은 그대로다. 다만 두 이름 중 어느 것이 옳은지는 원저자만 답할 수 있어 미해결. |

## [X] 모델 표현 불가 — 사유와 가능 조건 — 14건

| entry_id | HoC | 왜 BASE 와 ALT 가 구분되지 않는가 | 무엇이 있으면 구분되는가 |
|---|---|---|---|
| `KE_K_CP_07` | 대체 | 결함 유래 collapse 인스턴스만 축소하는 지시인데, 모델의 H008 zone 에 '결함 유래' 구분이 없다. 시스템동바리로 바꿔도 zone 형상·기간이 같다. | H008 zone 을 결함원인별로 나눌 수 있는 데이터(동바리 종류·조립 품질) |
| `KE_K_CP_09` | 제거 | '조립/해체 선후 강제'라는 지시인데 **어떤 작업 쌍인지 특정되지 않는다.** 무엇을 바꿔야 할지 알 수 없어 BASE 와 ALT 가 같아진다. | 대상 작업 쌍을 명시한 scheduleShift 문구 |
| `KE_K_FE_10` | 대체 | TS3 비계가 슬래브 외곽선을 1.5 m 밴드로 오프셋한 하나뿐이며, 시스템비계와 재래식의 형상 차이(경간·작업발판 일체 여부·통로 폭)가 모델에 없다. 두 상태가 동일한 밴드로 파생된다. | KCS 21 60 10 등에서 규격 차이를 확보해 TS3 를 두 종류로 파생 |
| `KE_K_HS_05` | 공학적 | 적재 높이 제한으로 spawn 부피를 줄이는 지시인데, 모델의 H004 zone 은 면적만 갖고 높이·적치 단수 개념이 없다. | 적재물 높이/단수를 zone 속성으로 파생 (현재 적치 단수 3 은 임의값) |
| `KE_K_RB_02` | 공학적 | 전용 이동통로를 추가해 우회시키는 지시인데, 모델에 통로(route) zone 이 없고 appliesToCellType 도 v2.3 정본에 없다. 통로를 어디에 놓을지 정보가 없다. | 배근면과 분리된 통로 위치를 IFC 또는 가설물 파생으로 확보 |
| `KE_K_ST_03` | 공학적 | 작업자 동선과 장비 동선을 분리하는 지시인데, 모델에 작업자 전용 동선 개념이 없다. H011 zone 은 그대로 두고 사람만 피하게 할 수단이 없다. | 작업자 전용 통로를 별도 TS 로 파생하고 A* 가 그것을 선호하도록 |
| `KE_M_Fall_FormErection_03` | 공학적 | 계수 0.30 은 있으나 cellType 이 elevated_work_zone 이라 대상 인스턴스가 없다. **계수 문제가 아니라 대상 부재다.** | 고소작업 zone(H005) 파생 |
| `KE_M_Trip_MatHandling_02` | 경고 | 계수 0.80 은 있으나 cellType 이 route 라 대상이 없다. **계수 문제가 아니라 대상 부재다.** | 통로 zone 파생 |
| `KE_M_Trip_MatHandling_05` | 공학적 | 통로 회랑을 보호해 적재물 spawn 을 배제하는 지시인데 cellType 이 route 이고 이 프로젝트에 route zone 이 없다. | 통로 zone 파생 (R5 의 보행가능영역에서 축을 추출) |
| `KE_M_Trip_MatHandling_06` | 공학적 | 적재구역을 통로와 겹치지 않게 이전하는 지시인데, **어디로 옮길지**가 모델에 없다. 현재 해석은 배율 1.0 으로 떨어져 BASE 와 동일하다. | 이전 목적지를 정하는 규칙(빈 면적 탐색) 또는 대안 zone 세트 |
| `KE_S_H001_09` | 대체 | 개구부를 동선에서 이격하는 지시인데, **이격 목적지**가 모델에 없다. 개구부를 어디로 옮길지 정하는 규칙이 없어 BASE 와 동일하다. 떨어짐 사다리의 대체급이 여기서 막힌다. | 동선 zone 과 이전 가능 위치를 파생해 개구부 재배치 규칙을 정의 |
| `KE_T_FE_04` | 제거 | 영구계단 조기 설치 지시인데 **얼마나 앞당길지**가 없다('earlier'). 정량이 없어 스케줄을 바꿀 수 없다. | 앞당기는 양 또는 목표 선후관계를 명시한 문구 |
| `KE_T_HS_01` | 위험회피 | 지상 조립으로 고소작업 자체를 없애는 지시인데 cellType 이 elevated_work_zone 이고 이 프로젝트에 대응 위험유형이 없다. | 고소작업 zone(H005) 파생 |
| `KE_T_HS_03` | 제거 | '중첩=0 이 되도록 이동'인데 대상 작업 쌍이 특정되지 않는다. | 대상 작업 쌍을 명시한 문구 |

## [C] 계수 미확보 — 5건

| entry_id | HoC | 사고유형 | 근거 | BASE↔ALT 차이 |
|---|---|---|---|---|
| `KE_K_CA_02` | 공학적 | 끼임 | AgentParameterRule 인데 parameter_value 가 비어 있다. 원천에 계수가 존재하지 않는다 (지어내지 않음). | 없음 — 배율이 없어 BASE 와 동일 |
| `KE_K_CA_03` | 공학적 | 끼임 | AgentParameterRule 인데 parameter_value 가 비어 있다. 원천에 계수가 존재하지 않는다 (지어내지 않음). | 없음 — 배율이 없어 BASE 와 동일 |
| `KE_K_FE_11` | 공학적 | 무너짐 | AgentParameterRule 인데 parameter_value 가 비어 있다. 원천에 계수가 존재하지 않는다 (지어내지 않음). | 없음 — 배율이 없어 BASE 와 동일 |
| `KE_K_RB_03` | 공학적 | 물체에맞음 | AgentParameterRule 인데 parameter_value 가 비어 있다. 원천에 계수가 존재하지 않는다 (지어내지 않음). | 없음 — 배율이 없어 BASE 와 동일 |
| `KE_K_TR_08` | 경고 | 넘어짐 | AgentParameterRule 인데 parameter_value 가 비어 있다. 원천에 계수가 존재하지 않는다 (지어내지 않음). | 없음 — 배율이 없어 BASE 와 동일 |

## [P] 규칙 미작성 — 27건

이번 범위가 아니다 (규칙을 쓰지 않았다).

`KE_C_WARN_01`, `KE_H001_02`, `KE_H001_03`, `KE_H001_06`, `KE_M_Fall_FormErection_01`, `KE_M_Fall_MatHandling_01`, `KE_M_Fall_Pour_01`, `KE_M_HitByObj_FormErection_01`, `KE_M_HitByObj_MatHandling_01`, `KE_M_Struck_FormErection_01`, `KE_M_Struck_Rebar_01`, `KE_M_Trip_FormErection_01`, `KE_M_Trip_FormErection_02`, `KE_M_Trip_MatHandling_01`, `KE_M_Trip_MatHandling_03`, `KE_M_Trip_MatHandling_04`, `KE_M_Trip_Rebar_01`, `KE_S_FE_06`, `KE_S_FE_07`, `KE_S_FE_09`, `KE_S_H001_10`, `KE_T_FE_01`, `KE_T_FE_02`, `KE_T_FE_03`, `KE_T_FE_05`, `KE_T_PO_01`, `KE_T_PO_02`

## variant 후보 — 사다리별

### 떨어짐 — [S] 5건 / 등급 3개

| HoC 등급 | entry_id |
|---|---|
| 제거 | `KE_H001_01`, `KE_H001_04` |
| 대체 | `KE_S_FE_08` |
| 공학적 | `KE_H001_05`, `KE_M_Fall_FormErection_02` |

### 무너짐 — [S] 4건 / 등급 4개

| HoC 등급 | entry_id |
|---|---|
| 제거 | `KE_S_CP_05` |
| 대체 | `KE_T_CP_01` |
| 공학적 | `KE_S_CP_04` |
| 관리적 | `KE_T_CP_03` |

### 물체에맞음 — [S] 1건 / 등급 1개

| HoC 등급 | entry_id |
|---|---|
| 공학적 | `KE_T_HS_02` |

> **등급이 1개뿐이라 축 1(HoC 위계) 실험 대상에서 제외한다.**

## 이 분류가 결과다

상위 등급은 형상·시점 변화라 계수가 필요 없어 [S]가 되기 쉽고, 하위 등급은 계수가 필요해 [C]가 되기 쉽다는 가설을 위 교차표가 검증한다. **억지로 [S]를 늘리지 않았다.** 분류가 어느 등급에 몰리는지가 정보다.
