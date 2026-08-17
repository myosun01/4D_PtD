# Unity 4D 환경 현황 조사

조사 일자: 2026-08-08 · 저장소 루트: `C:\Users\pc\Downloads\4D_Simulation` (상대경로로 기술)
**조사·보고만 수행했다. 코드·Unity 파일을 작성하거나 수정하지 않았다.**

---

## 1. Unity 번들에 무엇이 들어가는가 — **부분적으로 있음**

### 1-1. 데이터 종류별 포함 여부

| 데이터 | 상태 | 근거 |
|---|---|---|
| 지오메트리 | **있음** | `unity_bundle/model.glb` 59.1 MB. 노드/메쉬 이름 = `IfcRoot.GlobalId` (build_unity_bundle.py:141-143) |
| 요소 메타 | **있음** | `unity_bundle/manifest.json` 11.4 MB, 12,712 요소 (bundle_meta.json `elementCount`) |
| 좌표계 선언 | **있음** | `unity_bundle/bundle_meta.json` |
| 타임라인(공정) | **있음** | `unity_bundle/timeline.json` 449 KB, `schemaVersion 2.0`, `projectDays 409` |
| **에이전트 궤적** | **없음** | 번들 4개 파일 어디에도 워커 위치 시계열이 없다. `timeline.json`의 `crewByDay`는 `{day, trade, level, count}` — **인원수만**이고 좌표가 없다 (export_timeline.py:122-132) |
| **위험구역** | **부분적으로 있음** | `timeline.json.hazardSpans` 22건. 아래 §3 참조 |
| λ(기대위험) 히트맵 | **부분적으로 있음** | `unity_bundle/lambda_daily.csv` 존재. **그러나 이 파일을 번들로 복사하는 코드가 저장소에 없다** — `fourd.write_outputs()`는 `output/`에만 쓴다 (fourd.py:442-461). `output/lambda_daily.csv`와 SHA256 완전 동일(`001FF31F…6F81`) → 수동 복사로 보인다. 복사 주체는 **확인 불가** |

`build_unity_bundle.py` 가 자기 산출물로 선언한 것은 **3종뿐**이다 (build_unity_bundle.py:4-9): `model.glb` / `manifest.json` / `bundle_meta.json`. `timeline.json` 은 별도 스크립트(`export_timeline.py`) 산출물이고, `lambda_daily.csv` 는 어느 스크립트의 산출물도 아니다.

### 1-2. 출력 경로와 형식

| 스크립트 | 출력 | 형식 |
|---|---|---|
| `build_site_json.py` | `site.json` (인자로 경로 지정, 관례상 `project/site.json`) | JSON — 격자·gridFrame 정본 (build_site_json.py:199-202) |
| `build_unity_bundle.py` | `unity_bundle/` (기본값, `--out`) | GLB(binary glTF 2.0) + JSON (build_unity_bundle.py:314) |
| `check_unity_bundle.py` | 표준출력만 (파일 산출 없음) | 검증 4종, 종료코드 0/1 (check_unity_bundle.py:274-278) |
| `export_timeline.py` | `unity_bundle/timeline.json` (기본값, `--out`) | JSON (export_timeline.py:299) |
| `fourd.write_outputs()` | `output/lambda_daily.csv`, `output/exposure_by_trade.csv` | CSV (fourd.py:445-446) |

### 1-3. 좌표계·단위 — IFC mm ↔ m 변환은 **있음**, Unity 좌표 변환은 **부분적으로 있음**

- **IFC 원본은 mm이다.** `bundle_meta.json.unitScaleToMeter = 0.001`. 변환은 `ifcopenshell.util.unit.calculate_unit_scale()` 로 읽고, 지오메트리는 `iterator(use-world-coords)` 가 m로 내놓는다 (build_unity_bundle.py:61-62, 265). **하드코딩된 1000 나눗셈은 없다.**
- **좌표 정본**: IFC 월드좌표, **m, Z-up**. `manifest.json` 의 모든 `bbox_ifc_m` 이 이 프레임 (build_unity_bundle.py:13, 189).
- **glTF 축 변환**: `(x,y,z)_ifc → (x,z,-y)_gltf`, up = `+Y` (build_unity_bundle.py:112, 119, 294). 회전 행렬식 +1(우수계 유지)이라고 주석에 명시.
- **모델 센터링 금지가 계약이다** — `--center-model` 류 옵션을 절대 전달하지 않는다 (build_unity_bundle.py:14, 86, 90-91). 원점을 옮기면 `site.json` gridFrame 정합이 깨진다.
- **격자 ↔ 월드**: `gridFrame` = `{origin_xy_m: [-11.0, 19.0], resolution_m: 1.0, axisMapping: {row:"+Y", col:"+X"}, cellCenter: "world_xy = origin + (index+0.5)*resolution"}`. `bundle_meta.json` 은 `site.json` 의 사본을 싣고(정본은 site.json), `tests/test_unity_bundle.py:34` 가 동일성을 검사한다. 구현 참조: check_unity_bundle.py:48-52.
- **timeline.json 좌표는 변환하지 않는다.** 격자 인덱스 `[row, col]` 그대로 내보내고, **Unity 쪽이 gridFrame 매퍼로 변환하라**는 설계다 (export_timeline.py:5-6). 즉 그 매퍼는 Unity 측 미구현 부분이다.
- **glTF → Unity 좌표(왼손좌표계) 변환은 저장소에 없다.** glTF는 오른손·+Y-up, Unity는 왼손·+Y-up이라 추가 반전이 필요하지만, 이를 처리하는 코드가 존재하지 않는다(=Unity 임포터 소관). **확인 불가.**

### 1-4. Unity 프로젝트 경로가 코드에 있는가 — **없음**

전 파이썬 파일 grep 결과, 출력 경로는 상대경로 `unity_bundle` 뿐이다 (build_unity_bundle.py:314, check_unity_bundle.py:275, export_timeline.py:298-299). Unity 프로젝트 절대경로·`Assets/` 경로·프로젝트명 문자열은 **어디에도 없다.**

---

## 2. 작업자 에이전트가 이미 있는가 — **있음 (단, 두 개의 서로 다른 구현)**

### 2-1. 구현 현황

| | 2D 엔진 | 4D 엔진 |
|---|---|---|
| 클래스 | `movement.Worker` (movement.py:197-211) | `fourd._Crew4D` (fourd.py:51-60) |
| 인원 | `config.N_WORKERS = 20`, 그중 `N_FOREMEN = 2` (config.py:29-30) | 공정표의 `crew_size` 합 — 고정값 없음 (fourd.py:254-260, 204-213) |
| 속성 | `id, is_foreman, pos, home, queue, cur, state, route, timer, rho, base_rho, ppe, injured, accident_type, depart, _stuck, _move_accum` (17개) | `trade, rho, pos, route, dwell` (5개) |
| 상태기계 | `wait → travel → work → travel …`, `injured` 흡수상태 | `route 소진 → dwell` 반복만 |
| 사회효과 | 있음 — `social.apply_witness_shock`, `apply_imitation` 호출 (movement.py:290, 344) | **없음** — ρ를 A* 회피강도로만 쓰고 갱신하지 않는다 |
| 사고 표집 | 있음 (movement.py:278-291) | 없음 — λ(기대건수)만 산출 |
| 격자 | `config.build_grid()` 합성 30×44 (movement.py:25-38) | `site.json` 층별 69×93 × 8층 |

**주의**: 2D와 4D는 서로 다른 세계를 돈다. 2D는 IFC와 무관한 합성 격자다.

### 2-2. 경로 탐색 — **Python 쪽. Unity 쪽에는 존재 자체가 없다**

- 알고리즘: **소프트 위험가중 A\*** — `movement.soft_route()` (movement.py:149-191).
  - 8방향, 대각선 비용 √2, **대각선 코너컷 금지** (movement.py:116)
  - 휴리스틱: octile (movement.py:180-183)
  - 비용 = `base + HAZARD_WEIGHT[cell]×RISK_K×weight_mult×(1−ρ) + uniform(0, PATH_NOISE)`, 개구부 인접 셀에 `OPEN_EDGE_PEN` 가산 (movement.py:118-122, 177)
  - 탐색 상한 `max_expand=4000`
- 그래프: 격자 셀 인접표를 `_build_context()` 가 격자당 1회 선계산해 캐시 (movement.py:80-143). 4D도 이 함수를 그대로 재사용 (fourd.py:31, 241).
- **Unity 측 NavMesh·경로탐색 코드는 없다.** 저장소에 `.cs` 파일이 0개다(§5).

### 2-3. 궤적 파일 출력 — **부분적으로 있음 (2D만)**

- **2D**: `movement.MovementLogger` (movement.py:409-443) → CSV
  헤더 `frame, clock, worker_id, row, col, state, is_foreman, injured, accident_type`
  경로 기본값 `movement_log_<YYYYmmdd_HHMMSS>.csv` (저장소 루트). `MOVEMENT_LOG_EVERY` 로 기록 주기 조절.
  **현재 저장소에 `movement_log_*.csv` 파일은 0개다.** 또한 주석에 "몬테카를로(대량 반복)에는 성능상 붙이지 않는다"고 명시.
- **4D**: **없음.** `run_level_day()` 는 매 스텝 워커 위치를 채널 셀집합과 대조해 노출스텝만 누적하고 **위치를 버린다** (fourd.py:229-248). 궤적을 남기는 인자·훅이 없다.
- 따라서 **Unity에서 작업자를 움직이려면 궤적 출력 경로를 새로 만들어야 한다.**

### 2-4. 시간 단위

| 단위 | 값 | 근거 |
|---|---|---|
| 1 스텝 | **1초** (`STEP_SECONDS = 1`) | config.py:23 |
| 1 셀 | 1 m (`CELL_SIZE_M = 1.0`), 보행 0.5 m/s → 2스텝당 1칸 | config.py:21-22, movement.py:262 |
| 하루 | `WORKDAY_STEPS = 28800` 스텝 = 8시간 (10:00~18:00) | config.py:24-26 |
| 4D 바깥 루프 | **1일** | fourd.py:290 |

단, 실사용에서는 `run_project(max_steps=…)` 로 하루 스텝수를 크게 줄여 쓴다 — `gen_lambda_v2.py:11` 은 `max_steps=80`(=80초). 즉 **현재 산출된 `lambda_daily.csv` 의 하루는 실제 8시간이 아니라 80스텝이다.**

---

## 3. 위험구역이 렌더링되는가 — **없음 (데이터 일부만 번들에 있음)**

### 3-1. `hazard_zones.json` / `lifecycle_bindings_v2.json` 소비 코드

전 저장소 grep 결과:

| 파일 | 소비처 | 용도 |
|---|---|---|
| `build/hazard_zones.json` | `scripts/temp_works.py` (생성자), `scripts/sync_schedule.py` | 생성·참조 무결성 검증만 |
| `build/lifecycle_bindings_v2.json` | `scripts/sync_schedule.py:33,140` | 액티비티 참조·레벨 정합 검증만 |

**Unity 경로(build_unity_bundle / check_unity_bundle / export_timeline)에서는 두 파일을 전혀 읽지 않는다.** 시뮬레이션(`fourd.load_project`)도 `project/lifecycle_bindings.json`(21건)을 읽으므로 84 zone 은 현재 어느 실행 경로에도 들어가지 않는다.

### 3-2. Unity 씬 시각 표현 경로 — **없음**

- 번들에 실린 위험 정보는 `timeline.json.hazardSpans` **22건**뿐이다:
  `{level, kind ∈ {edge, opening, collapse}, hazardType ∈ {H007, H001, H008}, spawnDay, despawnDay, cells:[[r,c],…]}` (export_timeline.py:189-244)
- 이 22건은 **layer 단위 집계**다. 셀 목록은 `site.json` 격자에서 타입별로 긁어온 것(`_cells_by_type`, export_timeline.py:87-102)이고, `hazard_zones.json` 의 개별 zone(84개)과 **1:1 대응하지 않는다.**
- `hazard_zones.json` 이 가진 **폴리곤 지오메트리**(`zones[].geometry.coords`, 월드 m 좌표 — Unity 렌더링용으로 명시적으로 만들어진 것, build/temp_works_log.md:9)는 **번들에 들어가지 않는다.**
- `hazardSpans` 를 읽어 씬에 그리는 **C# 로더가 저장소에 없다**(§5). 따라서 렌더링 경로는 끝까지 이어지지 않는다.
- 누락 유형: `hazardSpans` 는 H001/H007/H008 3종만 다룬다. `hazard_zones.json` 의 H002(협소) 8 / H004(적재) 8 / H009(낙하) 6 / H011(장비동선) 8 = **30 zone 은 번들에 어떤 형태로도 없다.**

---

## 4. 기존 MP4 두 개 — **생성 스크립트는 저장소에 없음 (외부 화면 녹화)**

| 파일 | 크기 | mtime |
|---|---|---|
| `4DBIM_Base - PtdConsistency - Windows, Mac, Linux - Unity 6.3 LTS (6000.3.2f1) _DX12_ 2026-07-20 14-30-14.mp4` | 6.1 MB | 2026-08-07 23:21 |
| `4DBIM_Base - PtdConsistency - Windows, Mac, Linux - Unity 6.3 LTS (6000.3.2f1) _DX12_ 2026-07-28 12-14-35.mp4` | 27.1 MB | 2026-08-07 23:21 |

**파일명에서 확정되는 것** — 파일명이 Unity 에디터 창 제목 형식(`<프로젝트명> - <씬명> - <빌드타깃> - Unity <버전> <그래픽API>`)과 정확히 일치한다:

- Unity 프로젝트명: **`4DBIM_Base`**
- 씬 이름: **`PtdConsistency`**
- 빌드 타깃: Windows, Mac, Linux (Standalone)
- Unity 버전: **6.3 LTS (6000.3.2f1)**, 그래픽 API **DX12**
- 뒤에 붙은 `YYYY-MM-DD HH-MM-SS` 는 녹화 시각(2026-07-20, 2026-07-28)

**컨테이너 메타에서 확정되는 것** — 두 파일 모두 헤더가 `ftyp mp42 / mp41 / isom` 이고, `mdat` 직전 `uuid` 박스에 Windows 빌드 문자열 **`10.0.19045.0`** 이 박혀 있다. 이는 **Windows 게임 바(Game DVR) 화면 녹화**의 서명이다. 녹화 당시 OS는 Windows 10 22H2(빌드 19045)로, 현재 이 머신(Windows 11, 빌드 26200)과 다르다.

**결론**: 이 저장소의 어떤 스크립트도 영상을 생성하지 않는다(영상 생성 코드 0건). 두 파일은 **Unity 에디터에서 `PtdConsistency` 씬을 재생하는 화면을 OS 화면녹화 기능으로 찍은 것**이다.

**영상 내용은 확인 불가.** 프레임을 열어보지 않았고, 대응하는 씬·스크립트가 저장소에 없어 무엇을 보여주는지 코드로 역추적할 수 없다. 파일명으로 알 수 있는 범위를 넘는 서술은 하지 않는다.

---

## 5. Unity 프로젝트 자체 — **저장소 안에 없음 / 밖에서도 찾지 못함**

### 5-1. 저장소 내부 — **없음**

| 대상 | 결과 |
|---|---|
| `**/*.cs` | **0개** |
| `**/*.unity` (씬 파일) | **0개** |
| `Assets/`, `ProjectSettings/`, `Packages/`, `Library/` | **없음** |
| `*.asmdef`, `*.prefab`, `*.asset` | **0개** |

**커스텀 C# 스크립트는 하나도 없다. 씬 파일도 0개다.** 씬 이름 `PtdConsistency` 는 §4 의 영상 제목에서만 확인되는 이름이다.

### 5-2. 저장소 외부 — **찾지 못함 (완전 확인 불가)**

`$env:USERPROFILE` 하위 depth 3 검색(`4DBIM|Ptd|Unity` 패턴)에서 매치된 디렉터리:

```
C:\Users\pc\Desktop\묘선\4D_Simulation\unity_bundle
C:\Users\pc\Downloads\4D_Simulation\unity_bundle
C:\Users\pc\Downloads\4D_Simulation\4D_PtD_라이브러리_CSI
```

Unity 프로젝트 디렉터리는 없다. **다만 depth 3·사용자 폴더 한정 검색이므로, 더 깊은 경로나 다른 드라이브에 있을 가능성은 배제하지 못한다 — 확인 불가.**

### 5-3. Unity 잔재 증거 — `.meta` 파일 5개 **있음**

저장소 루트에 Unity 에셋 임포터 메타 파일이 5개 남아 있다:

```
construction_schedule.csv.meta
element_task_mapping.json.meta
ifc_elements.json.meta
ifc_manifest.json.meta
productivity_rates.json.meta
```

내용 예 (`construction_schedule.csv.meta`):
```yaml
fileFormatVersion: 2
guid: 82805304a706dd54c8aa2718a57c4b2a
TextScriptImporter: {...}
```

`TextScriptImporter` = Unity가 텍스트 에셋을 임포트할 때 생성하는 메타다. 즉 **이 5개 파일은 한때 어떤 Unity 프로젝트의 `Assets/` 아래에 있었다.** 어느 프로젝트인지는 guid만으로는 **확인 불가**. `.meta` 가 있는 5개는 전부 **공정·요소 데이터**이고, `hazard_zones.json` 이나 `timeline.json` 에는 `.meta` 가 없다 — 즉 위험구역·타임라인은 Unity로 넘어간 적이 없어 보인다(정황 근거).

---

## 6. 실행 방법 — **부분적으로 있음 (문서화는 없음)**

### 6-1. 문서 상황

- **프로젝트 README가 존재하지 않는다.** (`README*` 검색 결과 유일한 매치는 pytest가 자동 생성한 `.pytest_cache/README.md` 이며 프로젝트 문서가 아니다.)
- `CLAUDE.md` 에 Unity 관련 기술 **없음**. 파일 맵(§파일 맵)에도 Unity 항목이 없다.
- `ROADMAP.md` 에서 Unity는 **§6 "Phase 이후 (엔진 외 — 참고만)"** 에만 한 줄 등장한다:

  > `U-트랙: IFC→Unity 시각화 번들 (build_unity_bundle.py / export_timeline.py / Unity 로더).`
  > — ROADMAP.md:213

  즉 **"Unity 로더"는 로드맵상 아직 만들지 않은 항목으로 명시되어 있다.**
- 좌표 계약만 §2에 있다:
  > `좌표 정본 (고정): IFC 월드좌표(m, Z-up). … 소비자(Unity 등)는 단일 변환 함수로만 자기 좌표계로 변환한다.` — ROADMAP.md:54-55
- `Makefile` 은 PtD 라이브러리 파이프라인 전용이며 Unity 타깃이 없다.

### 6-2. 코드에서 읽어낸 실행 순서 (문서가 아니라 각 스크립트의 docstring·argparse에서 재구성)

```bash
python build_site_json.py ARK_NordicLCA_Office_Concrete_BuildingPermit_Revit.ifc project/site.json
```
```bash
python build_unity_bundle.py ARK_NordicLCA_Office_Concrete_BuildingPermit_Revit.ifc --out unity_bundle --site project/site.json
```
```bash
python check_unity_bundle.py --bundle unity_bundle --site project/site.json
```
```bash
python export_timeline.py --schedule project/schedule.json --site project/site.json --manifest unity_bundle/manifest.json --out unity_bundle/timeline.json
```
```bash
python gen_lambda_v2.py
```

- 1→2 순서는 강제된다: `site.json` 이 없거나 `gridFrame` 이 없으면 `build_unity_bundle.py` 가 즉시 종료한다 (build_unity_bundle.py:256-262).
- 2→4 순서도 강제된다: `export_timeline.py` 가 `manifest.json` 을 읽는다 (export_timeline.py:306-307).
- 5는 `output/lambda_daily.csv` 를 만들 뿐 **번들로 복사하지 않는다**(§1-1).

### 6-3. "4D 재생을 보려면" — **저장소만으로는 불가능**

번들 4개 파일을 읽어 씬을 구성/재생하는 **Unity 측 코드가 저장소에 없다**(§5). 따라서 위 명령을 다 실행해도 재생 화면은 나오지 않는다. 재생을 본 기록은 §4의 MP4 두 개뿐이며, 그때 사용한 Unity 프로젝트 `4DBIM_Base` 는 **이 저장소 밖에 있고 위치를 찾지 못했다 — 확인 불가.**

참고: `viewer.py` 에는 실시간 관전 GUI가 있으나(`python viewer.py --watch`) 이는 **matplotlib 기반 2D 합성 격자** 화면이며 Unity·IFC와 무관하다.

---

## 종합 — 라이브러리 + 위험구역 + 작업자를 Unity 4D 씬에서 함께 보려면

### 이미 되어 있는 것

1. **건물 지오메트리 파이프라인 완결** — IFC(mm) → `model.glb`(m, +Y-up), 노드명 = GlobalId. 개구부 보이드가 메쉬에 실제 구멍으로 반영됨.
2. **좌표 계약이 문서·코드·테스트로 고정** — IFC 월드 m Z-up 정본, `(x,y,z)→(x,z,-y)` 변환, `gridFrame` 으로 격자↔월드 왕복. 센터링 금지가 강제되고 `tests/test_unity_bundle.py` 가 검사한다.
3. **번들 무결성 검증기 4종** — 키 정합 / 개구부 관통 레이캐스트 / 계단 좌표 정합 / 규모 리포트.
4. **공정 타임라인 직렬화** — 409일치 `elementAppear`(부재 점진 출현) / `ghostPhase` / `levelAppear` / `crewByDay` / `activities` 178건.
5. **위험구역 데이터 자체** — `build/hazard_zones.json` 84 zone이 **폴리곤(월드 m)과 격자셀 두 표현을 모두** 갖고 있고, spawn/despawn 액티비티·날짜까지 붙어 있다. Unity 렌더링용으로 만들어졌다고 로그에 명시됨.
6. **작업자 경로탐색 엔진** — 층별 위험가중 A*, 시드 주입 가능·결정론적.
7. **PtD 라이브러리** — `build/ptd_library_v2.4.ttl` (대안 35건, HoC 등급·규칙 연결).

### 새로 만들어야 하는 것 (목록만 — 이번 작업에서 구현하지 않음)

**Unity 측 (C#) — 전부 미존재**

1. Unity 프로젝트를 이 저장소와 연결하는 방법 결정 (저장소 안에 둘지, 밖에 두고 번들만 복사할지)
2. `bundle_meta.json` 로더 — `gridFrame` 을 읽어 (row,col) ↔ 월드(x,y) 변환하는 단일 매퍼
3. glTF 오른손 → Unity 왼손 좌표계 반전 처리 (임포터 설정으로 될지 코드가 필요한지 미검증)
4. `manifest.json` 로더 — GLB 노드 GlobalId ↔ 요소 메타 조인, 층·클래스별 조회
5. `timeline.json` 재생기 — 일자 슬라이더, `elementAppear`/`ghostPhase` 에 따른 부재 표시·고스트 전환
6. 위험구역 렌더러 — zone별 메쉬/데칼 생성, spawn/despawn 일자에 따른 on/off
7. 작업자 렌더러 — 궤적을 받아 보간 이동, 공종별 구분
8. λ 히트맵 오버레이 (선택) — `lambda_daily.csv` 를 층·일자별 셀 색으로

**Python 측 (내보내기) — 미존재**

9. **작업자 궤적 익스포터** — `fourd.run_level_day()` 가 위치를 버리므로(fourd.py:229-248) 궤적을 남기는 경로가 필요하다. `fourd.py` 미수정 원칙을 지키려면 바깥에 별도 일 루프를 두거나, `movement.MovementLogger` 형식(frame,worker_id,row,col,state)을 4D용으로 확장한 별도 익스포터를 두어야 한다. **어느 쪽이든 신규 파일이다.**
10. **위험구역 익스포터** — `hazard_zones.json`(84 zone, 폴리곤 + 셀 + spawn/despawn) → 번들 형식. 현재 `timeline.json.hazardSpans` 는 22건 layer 집계라 zone 단위 표현이 불가능하고, H002/H004/H009/H011 30 zone 은 아예 빠져 있다.
11. **PtD 라이브러리 익스포터** — TTL의 대안·HoC 등급·규칙을 Unity가 읽을 JSON으로. 현재 번들에 라이브러리 정보가 **전혀** 없다.
12. **λ CSV 번들 복사 단계** — 현재 수동. 스크립트화 필요.
13. **번들 스키마 버전 정리** — `bundle_meta.schemaVersion 1.0` 은 3종(glb/manifest/meta)만 선언하므로, timeline·hazard·trajectory·library를 추가하면 갱신 대상.

**정합성 문제 (Unity 이전에 해결해야 함 — 앞선 Phase 0 조사와 중복)**

14. `unity_bundle/timeline.json` 은 `projectDays 409` / 액티비티 178건인데, 현재 `project/schedule.json` 은 **350일 / 234건**이다. 번들이 옛 공정표로 만들어진 상태 → `export_timeline.py` 재실행 필요.
15. `project/lifecycle_bindings.json`(21건)과 `build/lifecycle_bindings_v2.json`(84건)이 갈라져 있어, "어느 것이 BASE 세계인가"가 확정되지 않으면 위험구역 렌더링 대상도 확정되지 않는다.

---

### 확인 불가 항목 정리

- MP4 두 영상의 **실제 내용**
- Unity 프로젝트 `4DBIM_Base` 의 **위치** (사용자 폴더 depth 3 검색 범위 밖은 미탐색)
- `.meta` 파일 5개가 속했던 **Unity 프로젝트의 정체**
- `unity_bundle/lambda_daily.csv` 를 **누가/언제 복사했는지**
- glTF → Unity 좌표 반전을 임포터 설정만으로 해결할 수 있는지
