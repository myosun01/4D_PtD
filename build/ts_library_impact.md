# 가설물 계층이 라이브러리에 미치는 영향 (v3.3 Phase 4-4)

**이번에 재작성하지 않았다.** 가능 여부와 근거만 기록한다.

---

## 문제 진술

이 연구의 핵심 주장은 "상위 HoC 등급의 효과는 계수가 아니라 시뮬레이션의 창발로
산출된다"는 것이다. 그런데 대체급(Substitution) 대안 두 건이 가설물 형상이 없어
계수로 들어가 있었다. Phase 2 에서 가설물 파생 계층이 생겼으므로 그 전제가 바뀐다.

---

## KE_T_HS_04 — 작업발판 일체형 거푸집

| 항목 | 현재 값 |
|---|---|
| 대안 ID | `ALT_T_HS_04` |
| HoC | Substitution (rank 3) |
| 규칙 | `RULE_HS_INTFORM` — **AgentParameterRule** |
| appliesToCellType | `material_storage` |
| 계수 | `materialProbMultiplier = 0.50` |
| parameterSourceType | `heuristic` |
| sensitivityTarget | `true` |

### 판정: **SpatialChangeRule 로 재작성 가능** — 단 TS1 확장이 선행되어야 한다

근거:

- 이 대안의 실체는 "거푸집에 작업발판이 붙어 있어 별도 발판 설치·해체가 불필요하고
  작업면이 상시 확보된다"는 **형상 변화**다. 확률 계수가 아니다.
- Phase 2 의 `TS1 formwork_deck` 이 이미 층별 8개 생성되어 있고
  `walkable=True`, `z_offset_mm = -(슬래브 두께)` 로 보행면을 정의한다.
  일체형 거푸집은 이 데크에 **가장자리 발판 밴드를 추가**하는 것으로 표현된다.
- 현재 계수 `materialProbMultiplier=0.50` 은 `parameterSourceType=heuristic` 이고
  `sensitivityTarget=true` 다. 즉 **문헌 근거가 없다고 라이브러리 자신이 선언하고
  있다.** 형상으로 대체하면 이 임의 계수를 제거할 수 있다.

### 선행 조건 (아직 없는 것)

1. **TS1 에 가장자리 밴드 파생이 없다.** 현재 TS1 은 슬래브 발자국 전체를 덮는
   면 하나이고 발판 밴드 개념이 없다. TS4 `platform` 파생이 필요하다
   (Phase 2 에서 BASE 에는 없다고 기록한 항목이 바로 이것이다).
2. **appliesToCellType 이 `material_storage` 다.** 거푸집 대안인데 적재구역을
   가리키고 있어 의미가 맞지 않는다. 재작성 시 이 값도 함께 바로잡아야 한다.
   현재 값은 v2.3 정본에서 이월된 것이며 이번 작업에서 손대지 않았다.
3. `RULE_HS_INTFORM` 이 무엇을 remove/block/relocate 하는지 `simulationAction`
   문자열을 정해야 한다. 현재 SpatialChangeRule 이 아니라 비어 있다.

---

## KE_K_FE_10 — 시스템비계·동바리

| 항목 | 현재 값 |
|---|---|
| 대안 ID | `ALT_K_FE_10` |
| HoC | Substitution (rank 3) |
| 규칙 | `RULE_K_FE_10` — **이미 SpatialChangeRule** |
| appliesToCellType | *(비어 있음)* |
| simulationAction | `substitute_scaffold_system_reduce_assembly_defect_instances` |
| parameterSourceType | `design_change` |
| 계수 | 없음 |

### 판정: **재작성이 아니라 '연결'이 필요하다.** 규칙 유형은 이미 맞다

이 대안은 지시서의 전제(“AgentParameterRule + 휴리스틱 계수로 들어가 있다”)와
**다르다.** 실제로는 이미 `SpatialChangeRule` 이고 계수가 없다. 문제는 다른 데 있다:

- `appliesToCellType` 이 **비어 있어** `CELLTYPE_TO_HAZARD` 매칭에 실패하고,
  `controls.resolve_all()` 이 이 대안을 거부한다. v3.1 의
  `build/library_wiring_report.md` 에서 "도달 못 하는 대안 15건" 중 하나로 이미
  기록되어 있다. v2.3 정본에도 이 값이 없어 이월할 것이 없었다.
- `simulationAction` 이 가리키는 대상(`scaffold_system`)이 **Phase 2 이전에는
  시뮬레이터에 존재하지 않았다.** 이제 `TS3 scaffold` 가 층별 4개 생성되어 있으므로
  대상이 생겼다.

### 선행 조건

1. **TS 를 대책의 적용 대상으로 삼는 경로가 없다.** 현재 `controls.py` 의
   `CELLTYPE_TO_HAZARD` 는 위험유형(H001·H004·H007·H008·H009)만 다루고
   가설물(TS)을 모른다. `appliesToCellType = "scaffold"` 같은 값을 넣어도
   받아줄 곳이 없다.
2. TS3 가 현재 **8개 층 중 4개 층에만** 있다. L1/L3/L8 은 외피(창문 설치) 태스크가
   없어 despawn 원천이 없다고 Phase 2 에서 기록했다. 대안 효과를 층 전체에
   적용하려면 이 공백을 먼저 처리해야 한다.
3. 시스템비계와 재래식 비계의 차이를 무엇으로 표현할지 정해야 한다 —
   밴드 폭? 접근 지점 수? 조립 기간? **현재 `scaffold_band_m = 1.5` 는 근거 없는
   임의값이고 시스템/재래식 구분이 없다.** 구분 근거가 없으면 형상으로 옮겨도
   숫자를 지어내는 것이 된다.

---

## 정리

| 대안 | 현재 규칙유형 | 재작성 가능? | 막고 있는 것 |
|---|---|---|---|
| `ALT_T_HS_04` | AgentParameterRule | **가능** | TS4 platform 파생 부재, appliesToCellType 이 `material_storage` 로 잘못됨 |
| `ALT_K_FE_10` | SpatialChangeRule (이미 맞음) | **재작성 불필요 — 연결 필요** | appliesToCellType 공란, controls 가 TS 를 대상으로 받지 못함, TS3 가 4/8 층 |

**공통으로 필요한 것**: `controls.py` 의 대상 어휘를 위험유형(H0xx)에서
가설물(TS)까지 넓히는 것. 이는 `controls.py` 수정을 요구하므로 이번 범위 밖이다
(v3.3 은 controls.py 미수정이 완료 기준이다).

---

## v3.5 갱신 — Part C 로 두 걸림돌이 해소되었다

### 해소된 것

1. **`controls.py` 가 가설물을 대상으로 받는다.** `CELLTYPE_TO_TS`
   (formwork_deck / shoring / scaffold / platform)와 `TS_CHANNEL` 을 추가하고,
   `resolve_all(..., temp_structures=...)` 로 가설물 dict 를 대상으로 받는다.
   `temp_structures` 를 주지 않으면 예전과 동일하게 동작한다(후방호환).
2. **`ALT_K_FE_10` 이 실제로 해석된다.** `appliesToCellType='scaffold'` 가
   `scripts/derive_cell_types.py` 의 R1 규칙
   (`simulation_action` 에 `scaffold_system` 명시)으로 채워졌고,
   `TS_L2_SCAF_001` 에 적용해 `kind=scale, effective_day=58` 로 해석된다.
3. **`ALT_T_HS_04` 의 `appliesToCellType` 오기가 교정되었다.**
   `material_storage` → `drop_zone`. 근거는 `directive_ko`
   ("해체 시 개별 부재 탈락·낙하 기회를 축소")와 `accident_type`(물체에맞음)이
   모두 낙하물 노출을 가리킨다는 것이다. `build/cell_type_derivation.md` 에 기록.

### 갱신된 판정

| 대안 | 현재 규칙유형 | 도달 여부 | 남은 것 |
|---|---|---|---|
| `ALT_T_HS_04` | AgentParameterRule | **도달** (H009 ×6) | 아래 계수 불일치 |
| `ALT_K_FE_10` | SpatialChangeRule | **도달** (scaffold ×4) | 아래 정량 근거 부재 |

### 그래도 남는 두 문제 — 지어내지 않고 남긴다

**(가) `ALT_T_HS_04` 의 계수가 채널에 닿지 않는다.**
규칙의 계수는 `materialProbMultiplier=0.50` 인데 `drop_zone` 채널의 계수 키는
`controls._CHANNEL_PROB_KEY['drop_zone'] = 'hazard_weight_multiplier'` 다.
따라서 해석은 되지만 `channel_mult` 가 비어 효과가 0 이다.
**계수 키를 바꾸면 값의 의미가 달라지므로 하지 않았다.** 형상(SpatialChangeRule)
으로 재작성할 때 함께 정리할 항목이다.

**(나) `ALT_K_FE_10` 의 효과 크기를 정할 근거가 없다.**
시스템비계와 재래식 비계의 정량적 차이가 원천(§2 통계·TTL·문헌)에 없다.
현재 `channel_mult={'fall': 1.0}` 으로 해석되어 **효과가 없다.**
`scaffold_band_m=1.5` 도 근거 없는 임의값이고 시스템/재래식 구분이 없다.

### SpatialChangeRule 재작성 가능 여부 (이번에도 재작성하지 않음)

| 대안 | 재작성 가능? | 선행 조건 |
|---|---|---|
| `ALT_T_HS_04` | **가능** | TS4 `platform` 파생이 필요하다. Phase 2 에서 BASE 에는 없다고 기록한 항목이며, 일체형 거푸집은 데크에 발판 밴드를 더하는 것으로 표현된다 |
| `ALT_K_FE_10` | 재작성 불필요 (이미 SpatialChangeRule) | TS3 가 8개 층 중 4개뿐(L1·L3·L8 은 외피 태스크 부재). 그리고 (나)의 정량 근거 |

**지어내지 않은 것**: 시스템비계 vs 재래식 비계의 정량적 차이. 원천(§2 통계·TTL·
문헌)에 없어 비워 두었다. 이것을 채우지 않으면 `ALT_K_FE_10` 을 형상으로 옮겨도
효과는 여전히 임의값에서 나온다.
