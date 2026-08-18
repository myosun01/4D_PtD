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

## 2. Unity 프로젝트 폴더 확인

Unity Hub에서 기존 `4DBIM_Base` 프로젝트의 위치를 연다. 올바른 프로젝트 루트에는
다음 폴더가 함께 있어야 한다.

```text
4DBIM_Base/
├─ Assets/
├─ Packages/
└─ ProjectSettings/
```

기존 프로젝트를 찾지 못하면 Unity 6.3 LTS로 새 3D 프로젝트를 만든다. 기존 영상과
연속성을 유지하려면 새 씬 이름을 `PtdConsistency`로 둔다.

## 3. Unity 안의 권장 파일 배치

```text
4DBIM_Base/
└─ Assets/
   ├─ 4D_PtD/
   │  ├─ Model/
   │  │  └─ model.glb
   │  ├─ Scripts/              # 다음 단계에서 C# 로더 배치
   │  ├─ Prefabs/              # Worker/Hazard 프리팹
   │  └─ Materials/
   └─ StreamingAssets/
      └─ 4D_PtD/
         ├─ bundle_meta.json
         ├─ manifest.json
         ├─ timeline.json
         ├─ hazard_zones.json
         ├─ worker_trajectory.json
         ├─ ptd_library.json
         ├─ temp_structures.json
         └─ lambda_daily.csv
```

복사 원본은 GitHub 저장소의 `unity_bundle/`이다. `model.glb`만 `Assets/4D_PtD/Model/`로,
나머지 데이터 파일은 `Assets/StreamingAssets/4D_PtD/`로 복사한다.

Unity 런타임 로더는 데이터 경로를 절대경로로 하드코딩하지 않고 다음 기준으로 읽는다.

```csharp
var bundleRoot = Path.Combine(Application.streamingAssetsPath, "4D_PtD");
```

## 4. GLB 모델 임포트

1. Unity 메뉴 `Window > Package Manager`를 연다.
2. `+ > Add package by name`에서 `com.unity.cloud.gltfast`를 설치한다.
3. `model.glb`를 위의 `Assets/4D_PtD/Model/`에 복사한다.
4. 임포트가 끝나면 Project 창에서 생성된 glTF Scene/Prefab을 `PtdConsistency` 씬의
   Hierarchy로 드래그한다.
5. 루트 Transform은 Position `(0,0,0)`, Rotation `(0,0,0)`, Scale `(1,1,1)`로 둔다.

좌표는 Python 익스포터가 이미 IFC `(x,y,z)`를 glTF `(x,z,-y)`로 변환했다. Unity에서
별도의 축 반전·센터링·1000배 스케일 보정을 추가하면 궤적과 모델이 어긋난다.

## 5. 데이터는 복사만으로 재생되지 않음

현재 저장소에는 Unity C# 로더가 없으므로 JSON을 폴더에 넣는 것만으로 작업자가 움직이지
않는다. 다음 단계에서 최소 네 컴포넌트가 필요하다.

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
