# Theta* 결과를 Unity에서 확인하는 절차

## 현재 경계

이 저장소에는 Python 시뮬레이터와 `unity_bundle/` 데이터는 있지만 Unity 프로젝트
자체(`Assets/`, `Packages/`, `ProjectSettings/`)와 C# 로더는 없다. 과거 화면녹화에서
프로젝트명 `4DBIM_Base`, 씬명 `PtdConsistency`, Unity 6.3 LTS가 확인되지만 해당
프로젝트 폴더는 GitHub에 포함되어 있지 않다.

따라서 아래 절차는 ① Python에서 Theta* 궤적을 다시 생성하고 ② 사용자의 Unity
프로젝트로 번들을 옮긴 뒤 ③ 다음 단계에서 C# 로더를 연결하는 방식이다.

## 1. Theta* 궤적과 Unity 번들 재생성

코드만 바꾸어도 기존 `unity_bundle/worker_trajectory.json`은 자동으로 갱신되지 않는다.
저장소 루트에서 반드시 다시 실행한다.

빠른 점검용:

```bash
python scripts/run_4d_workers.py --days 30 --max-steps 480 --every 5 --seed unity-theta-smoke
python scripts/export_unity_bundle.py --bundle unity_bundle
python check_unity_bundle.py --bundle unity_bundle --site project/site.json
```

전체 공기용:

```bash
python scripts/run_4d_workers.py --max-steps 480 --every 10 --seed unity-theta-v1
python scripts/export_unity_bundle.py --bundle unity_bundle
python check_unity_bundle.py --bundle unity_bundle --site project/site.json
```

`check_unity_bundle.py`가 실패하면 Unity로 복사하지 않는다. IFC 모델 자체가 바뀐 경우에만
먼저 다음을 다시 실행한다.

```bash
python build_unity_bundle.py ARK_NordicLCA_Office_Concrete_BuildingPermit_Revit.ifc --out unity_bundle --site project/site.json
```

## 2. 확인된 Unity 프로젝트

사용자 화면에서 기존 `PtdConsistency` 씬과 `PtdRoot`가 확인됐다. `PtdRoot`에는
`PtdBootstrap`이 연결돼 있고 Inspector의 `Bundle Sub Dir` 값은 정확히
`unity_bundle`이다. 따라서 로더의 입력 경로는 다음으로 확정한다.

```text
Assets/StreamingAssets/unity_bundle/
```

`Assets/StreamingAssets/ifc/`와 `Assets/Models/`는 이번 Theta* 데이터 교체에서
건드리지 않는다. Unity glTFast 패키지도 이미 설치되어 있다.

## 3. 최종 파일 배치

```text
Assets/StreamingAssets/unity_bundle/
├─ bundle_meta.json
├─ lambda_daily.csv
├─ manifest.json
├─ model.glb
├─ site.json
├─ timeline.json
├─ worker_trajectory.json     # Theta* 실행 후 추가/교체
├─ hazard_zones.json          # 새 번들에서 추가
├─ ptd_library.json           # 새 번들에서 추가
└─ temp_structures.json       # 새 번들에서 추가
```

복사 원본은 Python 저장소의 `unity_bundle/`이다. 새 `4D_PtD` 폴더를 만들지 않고,
기존 `Assets/StreamingAssets/unity_bundle/`에 같은 이름으로 덮어쓰거나 추가한다.
이번 변경에서는 IFC 형상이 바뀌지 않았으므로 기존 `model.glb`, `manifest.json`,
`site.json`은 그대로 유지해도 된다. 기존 `.meta` 파일은 삭제하지 않는다.

Unity 런타임 로더는 데이터 경로를 절대경로로 하드코딩하지 않고 다음 기준으로 읽는다.

```csharp
var bundleRoot = Path.Combine(Application.streamingAssetsPath, "unity_bundle");
```

## 4. 이번 단계에서 교체할 파일

1. `worker_trajectory.json` — Theta* 경로 확인의 핵심. 반드시 추가/교체
2. `timeline.json` — 새 익스포터가 다시 만들었으면 교체
3. `hazard_zones.json`, `ptd_library.json`, `temp_structures.json` — 새로 추가
4. `bundle_meta.json` — 새 익스포터에서 바뀌었을 때만 교체
5. `model.glb`, `manifest.json`, `site.json` — 이번에는 유지
6. `lambda_daily.csv` — 별도 λ 재실행 전까지 기존 파일 유지

복사 후 Unity의 임포트·컴파일이 끝날 때까지 기다리고 Console에 빨간 오류가 없을 때
`PtdConsistency` 씬에서 Play한다. `PtdRoot`의 `Bundle Sub Dir`는 `unity_bundle`로
그대로 둔다.

## 5. 데이터는 복사만으로 재생되지 않음

현재 Unity 프로젝트에는 `PtdBootstrap`이 있지만, 화면만으로는 새
`worker_trajectory.json`을 소비하는 코드까지 구현됐는지 확인할 수 없다. Play 후 모델과
타임라인만 나오고 작업자가 나오지 않으면 파일 위치 문제가 아니라 기존 C# 로더가 새
궤적 파일을 읽지 않는 것이다. 그때 Unity 프로젝트의 `Assets/Scripts`를 GitHub에 올려
다음 컴포넌트를 연결한다.

| C# 컴포넌트 | 입력 | 역할 |
|---|---|---|
| `BundleLoader` | bundle_meta, manifest | 경로·요소 메타 로드 |
| `TimelineController` | timeline | 현재 day/step, 부재 표시 제어 |
| `WorkerTrajectoryPlayer` | worker_trajectory | 워커 생성, 프레임 보간, 상태 갱신 |
| `HazardZoneRenderer` | hazard_zones | 위험구역 생성 및 날짜별 on/off |

씬에는 빈 GameObject `4D_PtD_System`을 만들고 위 컴포넌트를 붙이는 구성이 적합하다.
워커 프리팹과 위험구역 머티리얼도 이 GameObject의 Inspector 필드에 연결한다.
워커 상태는 `commute`, `stair_wait`, `stair`, `travel`, `work` 다섯 값을 처리해야 한다.

## 6. Theta* Unity 검증 항목

1. 동일 시드 Python 재실행 시 `worker_trajectory.json`이 동일한지 확인
2. 모델과 워커 좌표가 같은 층·통로에 놓이는지 확인
3. 워커가 벽·개구부를 통과하지 않는지 확인
4. 45도 격자 방향에만 고정되지 않은 LOS 단축 경로가 보이는지 확인
5. 계단에서 `stair_wait` 후 `stair` 상태로 층이 바뀌는지 확인
6. 두 JSON 샘플 스텝 사이를 Unity가 선형 보간해 자연스럽게 움직이는지 확인
7. 위험구역의 `spawnDay <= day < despawnDay`가 맞는지 확인

Python과 Unity를 대조할 때는 먼저 작업자 1~3명, 하루 1개, 배속 1배로 확인한 다음 전체
공기와 전체 크루로 확장한다.
