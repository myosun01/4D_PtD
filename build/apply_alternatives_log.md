# variant 생성 (v4.0 Phase 0-1)

`build/alternative_classification.csv` 의 **class=S 10건**만 대상. 규칙을 새로 쓰거나 계수를 지어내지 않았다.

생성된 variant: **10개** (BASE 포함), 미생성 1건.

## variant 목록

| variant | 사고유형 | HoC | 규칙 | 기구 | 대상 | zone | 셀 | 공기 |
|---|---|---|---|---|---|---|---|---|
| `BASE` | — | — | — | none | — | 84 (+0) | 22,175 (+0) | 350 (+0) |
| `ALT_H001_01` | 떨어짐 | 제거 | SpatialChange | zone_removal | H001 | 45 (-39) | 21,063 (-1112) | 350 (+0) |
| `ALT_H001_05` | 떨어짐 | 공학적 | AgentParameter | controls_effect | H001 | 84 (+0) | 22,175 (+0) | 350 (+0) |
| `ALT_M_Fall_FormErection_02` | 떨어짐 | 공학적 | AgentParameter | controls_effect | H007 | 84 (+0) | 22,175 (+0) | 350 (+0) |
| `ALT_S_CP_04` | 무너짐 | 공학적 | AgentParameter | controls_effect | H008 | 84 (+0) | 22,175 (+0) | 350 (+0) |
| `ALT_S_CP_05` | 무너짐 | 제거 | Temporal | schedule_shift | — | 84 (+0) | 22,175 (+0) | 356 (+6) |
| `ALT_S_FE_08` | 떨어짐 | 대체 | SpatialChange | zone_removal | H008 | 77 (-7) | 15,368 (-6807) | 350 (+0) |
| `ALT_T_CP_01` | 무너짐 | 대체 | SpatialChange | zone_removal | H008 | 77 (-7) | 15,368 (-6807) | 350 (+0) |
| `ALT_T_CP_03` | 무너짐 | 관리적 | SpatialChange | controls_effect | H008 | 84 (+0) | 22,175 (+0) | 350 (+0) |
| `ALT_T_HS_02` | 물체에맞음 | 공학적 | AgentParameter | controls_effect | H009 | 84 (+0) | 22,175 (+0) | 350 (+0) |

## 존속기간 변화 (전 인스턴스 활성일 합)

| variant | 활성일 합 | BASE 대비 |
|---|---|---|
| `BASE` | 3,424 | +0 |
| `ALT_H001_01` | 1,864 | -1560 |
| `ALT_H001_05` | 3,424 | +0 |
| `ALT_M_Fall_FormErection_02` | 3,424 | +0 |
| `ALT_S_CP_04` | 3,424 | +0 |
| `ALT_S_CP_05` | 3,472 | +48 |
| `ALT_S_FE_08` | 2,912 | -512 |
| `ALT_T_CP_01` | 2,912 | -512 |
| `ALT_T_CP_03` | 3,424 | +0 |
| `ALT_T_HS_02` | 3,424 | +0 |

## controls 효과 상세 (mechanism=controls_effect)

| variant | kind | 채널배율 | 심각도배율 | 설치일 | effective_day |
|---|---|---|---|---|---|
| `ALT_H001_05` | scale | {'fall': 0.1} | — | 1 | 91~346 |
| `ALT_M_Fall_FormErection_02` | scale | {'edge': 0.1} | — | 1 | 22~346 |
| `ALT_S_CP_04` | scale | {'collapse_zone': 0.5} | — | 0 | 89~344 |
| `ALT_T_CP_03` | block | {} | — | 0 | 89~344 |
| `ALT_T_HS_02` | scale | {'drop_zone': 0.35} | — | 1 | 53~337 |

**설치 기간 중 무방호 노출**: `install_duration_days` 가 1 이상인 variant 는 `effective_day` 전까지 BASE 와 동일한 노출이 발생한다. `controls.py` 의 기존 의미론이며 새로 만들지 않았다.

## 미생성 — 적용 불가

| 대안 | entry | 사유 |
|---|---|---|
| `ALT_H001_04` | `KE_H001_04` | apply_temporal_shift 가 0건을 바꿨다 — 지시 'set FS_lag(slab_pour -> opening_closure) = 0 days' 이 가리키는 선후관계가 이 공정표에 없다. variant 미생성. |

**억지로 적용해 variant 를 만들지 않았다.**

## variant 간 중복

서로 다른 대안이 모델에서 **같은 변형**을 만든다. 오류는 아니지만 저감량이 동일하게 나오므로 사다리 비교 해석에 영향을 준다.

| 원본 | 중복 |
|---|---|
| `ALT_S_FE_08` | `ALT_T_CP_01` |

## 검증 — BASE 와 실제로 다른가

전 variant 가 BASE 와 구분된다 — zone 집합이 BASE 와 동일하면서 변형 기구가 zone/schedule 인 항목 0건, 배율이 1.0 뿐인 항목 0건.

