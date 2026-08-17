# Phase 3 — UNSURE 판정 확정 로그

사람의 판단 결과를 직접 적용했다. 결정 트리를 다시 돌리지 않았다.

| promoted | 건수 |
|---|---:|
| TRUE | 59 |
| FALSE | 30 |
| UNSURE | 0 |
| (빈칸 — excluded) | 1 |

## 재해유형 → 노출 채널 매핑

`exposure_channel` 은 대안 문구가 아니라 재해유형이 결정한다.

| 재해유형 | 채널 |
|---|---|
| 떨어짐 | `dwell_time` |
| 무너짐 | `zone_occupancy` |
| 넘어짐 | `passage_count` |
| 물체에맞음 | `passage_count` |
| 부딪힘 | `passage_count` |
| 끼임 | `proximity` |

## 항목별 적용 내역

| entry_id | 그룹 | 전 | 채널 | 사유 |
|---|---|---|---|---|
| `KE_K_CP_09` | a | UNSURE | zone_occupancy | H008_ShoringCollapse zone 이 생성되어 NO_CHANNEL 논거 |
| `KE_S_CP_05` | a | UNSURE | zone_occupancy | H008_ShoringCollapse zone 이 생성되어 NO_CHANNEL 논거 |
| `KE_K_CP_07` | a | UNSURE | zone_occupancy | H008_ShoringCollapse zone 이 생성되어 NO_CHANNEL 논거 |
| `KE_T_CP_01` | a | UNSURE | zone_occupancy | H008_ShoringCollapse zone 이 생성되어 NO_CHANNEL 논거 |
| `KE_K_FE_11` | a | UNSURE | zone_occupancy | H008_ShoringCollapse zone 이 생성되어 NO_CHANNEL 논거 |
| `KE_S_CP_04` | a | UNSURE | zone_occupancy | H008_ShoringCollapse zone 이 생성되어 NO_CHANNEL 논거 |
| `KE_T_CP_03` | a | UNSURE | zone_occupancy | H008_ShoringCollapse zone 이 생성되어 NO_CHANNEL 논거 |
| `KE_T_HS_04` | b | UNSURE | passage_count | LCR_DROP_ZONE 템플릿 추가로 NO_CHANNEL 논거 소멸 |
| `KE_K_HS_06` | b | UNSURE | passage_count | LCR_DROP_ZONE 템플릿 추가로 NO_CHANNEL 논거 소멸 |
| `KE_T_HS_02` | b | UNSURE | passage_count | LCR_DROP_ZONE 템플릿 추가로 NO_CHANNEL 논거 소멸 |
| `KE_K_HS_05` | b | UNSURE | passage_count | LCR_DROP_ZONE 템플릿 추가로 NO_CHANNEL 논거 소멸 |
| `KE_T_HS_01` | c | UNSURE | passage_count | 채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정 |
| `KE_S_FE_09` | c | UNSURE | dwell_time | 채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정 |
| `KE_T_HS_03` | c | UNSURE | passage_count | 채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정 |
| `KE_M_Struck_Rebar_01` | c | UNSURE | passage_count | 채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정 |
| `KE_K_FE_10` | c | UNSURE | dwell_time | 채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정 |
| `KE_S_FE_07` | c | UNSURE | dwell_time | 채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정 |
| `KE_S_FE_08` | c | UNSURE | dwell_time | 채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정 |
| `KE_M_Struck_FormErection_01` | c | UNSURE | passage_count | 채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정 |
| `KE_K_CA_02` | c | UNSURE | proximity | 채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정 |
| `KE_K_CA_03` | c | UNSURE | proximity | 채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정 |
| `KE_M_Trip_FormErection_01` | c | UNSURE | passage_count | 채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정 |
| `KE_M_Trip_MatHandling_03` | c | UNSURE | passage_count | 채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정 |
| `KE_M_Trip_MatHandling_04` | c | UNSURE | passage_count | 채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정 |
| `KE_M_Trip_Rebar_01` | c | UNSURE | passage_count | 채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정 |
| `KE_M_Fall_FormErection_03` | c | UNSURE | dwell_time | 채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정 |
| `KE_M_Trip_MatHandling_02` | c | UNSURE | passage_count | 채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정 |
| `KE_H001_06` | c | UNSURE | dwell_time | 채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정 |
| `KE_K_RB_03` | c+ | UNSURE | passage_count | 채널 특정 불가 논거 해소 — 노출 채널은 재해유형이 결정. 지시서 3-1 목록에  |
| `KE_K_ST_03` | 3-3 | UNSURE | passage_count | H011_EquipmentCorridor 채널을 R6 로 신규 구현 (장비 에이전트 |
| `KE_T_CP_02` | 3-2 | UNSURE | none | FALSE/NO_EXPOSURE + 규칙 4개 필드 제거 |
| `KE_K_PI_01` | 3-4 | UNSURE | (빈칸) | excluded — 판정 대상 제외 |

## 지시서와 다른 점 1건

실측 UNSURE 는 **32건**이나 지시서 3-1 이 열거한 것은 **31건**이다. `KE_K_RB_03`(수직 철근 전도방지 버팀대 / 물체에맞음 / 공학적)이 목록에 없다. 그룹 (c)의 '채널 특정 불가' 항목들과 성격이 같아 동일 처리했고 (→ `passage_count`), 표에서 그룹 `c+` 로 구분했다. 다른 판정을 원하시면 알려주시기 바란다.

## KE_T_CP_02 — 규칙 제거

승격하지 않는 항목에 실행 규칙이 붙어 있는 모순을 해소했다. 제거된 필드는 `note` 에 원문을 보존했다.

| 필드 | 제거된 값 |
|---|---|
| `rule_type` | AgentParameterRule |
| `rule_id` | RULE_CP_DESIGNCHECK |
| `parameter_value` | collapseProbMultiplier=0.30 |
| `parameter_source` | heuristic |

이 판정으로 `kalis_unadopted.py` 의 `U_STRUCT_REVIEW`(NO_EXPOSURE) 및 부록 C 본문 서술과 정합해진다.

## status=excluded 처리

`KE_K_PI_01` 은 판정 대상이 아니므로 `promoted`/`reason_code`/`exposure_channel` 을 빈칸으로 두었다. `adjudicate.py` 도 `status=excluded` 행을 건너뛰도록 수정해 재실행 시 다시 UNSURE 가 붙지 않는다.

