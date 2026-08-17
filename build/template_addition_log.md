# LifecycleRuleTemplate 2종 추가 로그

## 결과

| 항목 | 전 | 후 |
|---|---:|---:|
| TTL LifecycleRuleTemplate | 4 | **6** |
| lifecycle 바인딩 | 62 | **77** |
| 템플릿 부재 제외 | 15 | **0** |
| TTL 트리플 | 2,352 | 2,369 |

`build/lifecycle_bindings_v2.json` 템플릿 분포:

| 템플릿 | 바인딩 수 |
|---|---:|
| LCR_SLAB_OPENING | 39 |
| LCR_SLAB_EDGE | 8 |
| LCR_SHORING_COLLAPSE | 7 |
| LCR_MATERIAL_STORAGE | 8 |
| **LCR_DROP_ZONE** | **7** |
| **LCR_NARROW_PASSAGE** | **8** |
| 합계 | **77** |

---

## 1. 경로 선택 — (a) 별도 소스 + 이월 단계 병합

지시서의 두 선택지 중 **(a)** 를 택했다.

### 근거

**(b) 마스터 CSV 에 템플릿 행/시트 신설은 구조상 맞지 않는다.**
`build/ptd_library_master_v2.4.csv` 는 `1행 = 1 KnowledgeEntry` 42열 불변식 위에
서 있고, 이 전제를 `scripts/adjudicate.py`(결정 트리), `scripts/validate.py`
(entry_id 중복·promoted/reason_code 정합), `scripts/build_docx.py`
(재해유형별 그룹핑) 가 모두 공유한다. 템플릿 행을 섞으면 세 소비자를 전부
고쳐야 하고, `entry_id`·`hoc_level`·`promoted` 같은 열이 템플릿에는 의미가 없어
빈칸 행이 대량 생긴다.

**(a) 는 이미 있는 구조에 얹힌다.** `build_ttl.py` 는 결함 A 수정 때
**비-KE 온톨로지 이월 단계**를 갖추었다 (Reference / CoverageCell /
RiskScenario / AccidentType / Trade / HazardType / LifecycleRuleTemplate /
ConflictResolution 을 v2.3 에서 그대로 옮김). LifecycleRuleTemplate 은 정확히
이 범주이므로, 같은 단계에서 신규 선언을 병합하는 것이 자연스럽다.

참고로 구 마스터 `ptd_library_master.xlsx` 는 11시트 구조였고 그중
`I_LifecycleRules` 시트가 있었다. 즉 템플릿을 KE 와 분리해 두는 것은 이 프로젝트의
원래 설계이기도 하다. v2.4 파이프라인이 단일 CSV 로 좁아지면서 그 자리가 사라진 것을
(a) 로 복원한 셈이다.

### 원천 파일 위치

`lifecycle_templates.csv` (저장소 루트).

`data/` 는 직전 작업에서 "입력 사본이 두 벌이면 사고가 난다"는 이유로 삭제했다.
이 파일은 사본이 아니라 **신규 원천**이므로, `construction_schedule.csv` ·
`ptd_library_v2.3.ttl` 등 다른 원천과 같은 위치인 루트에 두었다.

### 재생성 경로

```
lifecycle_templates.csv
      │
      ▼  scripts/build_ttl.py  add_lifecycle_templates()  ← 이월 단계
      ▼
build/ptd_library_v2.4.ttl   (LifecycleRuleTemplate 6종)
      │
      ▼  scripts/temp_works.py  write_bindings()
      ▼
build/lifecycle_bindings_v2.json  (77건)
```

**TTL 에 손으로 덧붙이지 않았다.** `build_all.py` 재실행으로 재생성되며 사라지지
않는다. `write_bindings()` 에 `ttl_templates()` 검증을 추가해, `TEMPLATE_OF` 가
TTL 에 없는 템플릿을 가리키면 경고와 함께 해당 zone 을 제외하도록 했다 —
매핑과 TTL 이 다시 어긋나면 즉시 드러난다.

---

## 2. 템플릿 정의와 temp_works.py 대조

지시서 요구대로 `scripts/temp_works.py` 의 R4·R5 실제 파생 로직을 읽고 맞췄다.

### LCR_DROP_ZONE

| 속성 | 값 |
|---|---|
| hasHazardType | `H009_DropZone` |
| spawnTrigger | `activity[zone=UPPER].started` |
| despawnTrigger | `activity[zone=UPPER].completed` |
| locationSelector | `zone.below` |
| exposureChannel | `passage_count` |
| derivedBy | `scripts/temp_works.py R4` |

코드 대조: R4 의 spawn 은 `trig(t["first"], "task_start")` — 상부층 **최초 작업
착수**. despawn 은 `trig(t["last"])` — 상부층 **최종 작업 완료**. 템플릿과 일치한다.

`locationSelector = zone.below` 는 **필수**다. `lifecycle.py` 는
`expected = self._below_level(act.level) if tpl.location_selector == "zone.below"
else act.level` 로 검증하는데, DropZone 의 `boundActivity` 는 상부층 작업이고
`spawnLocation.level` 은 하부층이므로 `zone.below` 가 아니면 검증에서 탈락한다.
생성된 7건이 전부 `projection_depth=1` 이므로 `_below_level`(N−1) 로 충분하다.

trade/workType 필터를 넣지 않았다. `lifecycle.py` 의 `_CHECKED_FILTERS` 는
`("trade", "workType")` 만 검사하는데, 상부층 최초 작업의 trade 가 층마다 다르다 —
`T-15/41/56/71/86`(rebar) 와 `T-31/105`(formwork_erection) 가 섞인다. 특정 trade 로
고정하면 실제 파생 결과와 어긋난다. 규칙 자체가 "상부층 작업이 시작되면"이지
"특정 공종이 시작되면"이 아니므로 zone 범위 필터만 둔 것이 정확하다.

**트리거 문법으로 표현하지 못한 조건 1건**: R4 는 상하부 **동시작업(중첩)이 실제로
존재하는 층쌍에만** zone 을 만든다(`ov = (hi-lo).days + 1; if ov <= 0: continue`).
`lifecycle.py` 의 `_TRIGGER_RE` 는 `activity[filters].state` 단일 형식만 파싱하므로
AND 조건을 넣을 수 없다. 이 판정은 파생기가 수행하고 템플릿 `rdfs:comment` 에
명시했다.

### LCR_NARROW_PASSAGE

| 속성 | 값 |
|---|---|
| hasHazardType | `H002_NarrowPassage` |
| spawnTrigger | `activity[zone=SAME, workType=curing].completed` |
| despawnTrigger | `activity[zone=SAME].completed` |
| locationSelector | `zone.walkable` |
| exposureChannel | `passage_count` |
| derivedBy | `scripts/temp_works.py R5` |

코드 대조: R5 의 spawn 은
`trig(t.get("slab_curing")) or trig(t.get("first"), "task_start")` 이며, 8개 층
전부 슬래브 양생 작업이 있어 **기본 경로(슬래브 양생 완료)** 만 실제로 쓰인다
(`T-8/22/34/48/63/78/97/108`, 전부 `workType=curing`). 따라서
`workType=curing` 필터가 검증을 통과하고 파생 로직과도 일치한다.

`locationSelector` 는 `zone.below` 가 **아니어야** 한다. NarrowPassage 는
`boundActivity` 와 `spawnLocation.level` 이 같은 층이므로, `zone.below` 를 쓰면
lifecycle 이 하부층을 기대해 탈락한다.

**지시서 문구와 코드가 다른 점 1건**: 지시서는 spawnTrigger 를 "해당 층 작업 착수"
로 적었으나, `temp_works.py` 의 실제 기본 경로는 **슬래브 양생 완료**다.
"불일치하면 zone 과 템플릿이 서로 다른 것을 기술하게 된다"는 지시에 따라
**코드를 기준**으로 삼았다. 착수 시점이 맞다면 R5 의 spawn 을 바꾸고 템플릿도 함께
고쳐야 한다.

---

## 3. 부수 변경

**`ptd:exposureChannel` 의 `rdfs:domain` 을 제거했다.** 기존에는
`rdfs:domain ptd:KnowledgeEntry` 였는데 이제 LifecycleRuleTemplate 도 이 속성을
쓴다. 도메인을 KnowledgeEntry 로 고정해 두면 OWL 추론에서 템플릿이 KnowledgeEntry
로 분류된다. `build_ttl.py` 의 `NO_DOMAIN` 집합으로 처리했다.

**`ptd:derivedBy` 를 신설했다** (도메인 없음). 개체가 어느 파생 규칙에서 나왔는지
기록한다.

---

## 4. 남는 문제 — 별도 판단 필요

**`project/schedule.json` 이 Part 1 이전 상태다.** 이 파일은 원본
`construction_schedule.csv` 178건에서 만들어진 것이라 Part 1 에서 신설한
해체 작업 `T-9001`~`T-9008` 이 없다.

현재 바인딩 77건 중 **7건이 `T-9002`~`T-9008` 을 `despawnActivity` 로 참조**한다
(LCR_SHORING_COLLAPSE 의 despawn = 거푸집·동바리 해체 완료). 이 상태로
`LifecycleEngine` 을 돌리면
`ValueError: 바인딩 N: despawnActivity 'T-9002' 미정의` 가 난다.

즉 **바인딩 파일 자체는 77건으로 완성되었으나, lifecycle 이 이를 로드하려면
`project/schedule.json` 을 `build/construction_schedule_v2.csv` 기준으로
재생성해야 한다.** 저장소에 `convert_schedule_csv.py` 가 있어 그 경로로 가능하지만,
`project/` 아래 파일 수정은 이번 지시 범위에 없어 하지 않았다.

추가로, 재생성 시 `trade`/`workType` 부여 규칙도 확인이 필요하다. 해체 작업의
trade 를 `formwork_stripping` 으로 매기면 `lifecycle.py` 46~63행의
"양생을 formwork_stripping 으로 간주"하는 예외 처리가 더는 필요 없어진다.
