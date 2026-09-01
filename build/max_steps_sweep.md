# `max_steps` 하한 실측 (v3.8 Part A)

`scripts/sweep_max_steps.py` 산출. **알고리즘·구조를 바꾸지 않았다 — 측정만 했다.**
BASE 조건, stage=v37, 전체 공기 전(350)일, 조건마다 5회(시드 다름).

## 0. 실행·무결성 기록

`pwd`:

```text
/workspace/scratch/dab16aaba33d/repo_work
```

| 보호 파일 | 실행 전 SHA-256 | 실행 후 SHA-256 | 동일 |
|---|---|---|---|
| `movement.py` | `3fb0bd8d6b7636de155a44a85a1977cba01abf9d95d1df4edbd9ff998382131b` | `3fb0bd8d6b7636de155a44a85a1977cba01abf9d95d1df4edbd9ff998382131b` | 예 |
| `social.py` | `57c73ce71f6570ac2a6abea72721faaba2afefd2f9eb9e0bb6bc4c4d37e9e44c` | `57c73ce71f6570ac2a6abea72721faaba2afefd2f9eb9e0bb6bc4c4d37e9e44c` | 예 |
| `site_model.py` | `85c32c7e1ed2b22d96c33f794b8a9aebd0b6bdb4498d0b7f22adfd430d99bff8` | `85c32c7e1ed2b22d96c33f794b8a9aebd0b6bdb4498d0b7f22adfd430d99bff8` | 예 |
| `lifecycle.py` | `0abe77a37bcce587d722ffa8d5821b2d70ffe11b42c8b9af01285d36f25841f4` | `0abe77a37bcce587d722ffa8d5821b2d70ffe11b42c8b9af01285d36f25841f4` | 예 |

`ls -la scripts/ build/`:

```text
build/:
total 3376
drwxr-xr-x  2 root root    4096 Sep  1 17:18 .
drwx------ 11 root root    4096 Aug 18 22:26 ..
-rw-r--r--  1 root root   48699 Aug 18 16:01 construction_schedule_v2.csv
-rw-r--r--  1 root root 2110280 Aug 18 15:51 hazard_zones.json
-rw-r--r--  1 root root  770765 Aug 18 15:49 lifecycle_bindings_v2.json
-rw-r--r--  1 root root    8377 Sep  1 17:18 max_steps_sweep.md
-rw-r--r--  1 root root   13296 Sep  1 17:18 max_steps_sweep_raw.json
-rw-r--r--  1 root root  125720 Aug 18 15:49 ptd_library_v2.4.ttl
-rw-r--r--  1 root root    1575 Aug 18 15:56 route_mc_BASE_report.md
-rw-r--r--  1 root root     445 Aug 18 15:55 route_mc_comparison.md
-rw-r--r--  1 root root    1518 Aug 18 15:55 route_mc_report.md
-rw-r--r--  1 root root  185129 Aug 18 15:49 task_locations.json
-rw-r--r--  1 root root  142238 Aug 18 15:49 temp_structures.json
-rw-r--r--  1 root root   11160 Aug 18 15:55 variant_manifest.json

scripts/:
total 612
drwxr-xr-x  3 root root  4096 Aug 18 16:00 .
drwx------ 11 root root  4096 Aug 18 22:26 ..
drwxr-xr-x  2 root root  4096 Sep  1 16:38 __pycache__
-rw-r--r--  1 root root 22324 Aug 18 16:00 adjudicate.py
-rw-r--r--  1 root root 19126 Aug 18 16:00 apply_alternatives.py
-rw-r--r--  1 root root 26868 Aug 18 16:00 augment_schedule.py
-rw-r--r--  1 root root  4141 Aug 18 16:00 build_all.py
-rw-r--r--  1 root root 12022 Aug 18 16:00 build_docx.py
-rw-r--r--  1 root root 15295 Aug 18 16:00 build_task_locations.py
-rw-r--r--  1 root root 26039 Aug 18 16:00 build_ttl.py
-rw-r--r--  1 root root  9088 Aug 18 16:00 check_library_wiring.py
-rw-r--r--  1 root root 10587 Aug 18 16:00 check_retention.py
-rw-r--r--  1 root root 18448 Aug 18 16:00 classify_alternatives.py
-rw-r--r--  1 root root 12709 Aug 18 16:00 clean_directives.py
-rw-r--r--  1 root root  3173 Aug 18 15:54 compare_route_monte_carlo.py
-rw-r--r--  1 root root  7476 Aug 18 16:00 compare_stages.py
-rw-r--r--  1 root root  9098 Aug 18 16:00 compare_v35.py
-rw-r--r--  1 root root  8543 Aug 18 16:00 compare_v36.py
-rw-r--r--  1 root root  9317 Aug 18 15:40 compare_v37.py
-rw-r--r--  1 root root 12931 Aug 18 16:00 derive_cell_types.py
-rw-r--r--  1 root root 16511 Aug 18 16:00 diagnose_h001.py
-rw-r--r--  1 root root 20900 Aug 18 16:00 export_unity_bundle.py
-rw-r--r--  1 root root 12152 Aug 18 16:00 kalis_unadopted.py
-rw-r--r--  1 root root 14180 Aug 18 16:00 migrate.py
-rw-r--r--  1 root root  8610 Aug 18 16:00 phase3_adjudicate.py
-rw-r--r--  1 root root 19343 Aug 18 16:00 phase4_rewrite.py
-rw-r--r--  1 root root 17773 Aug 18 15:40 pilot_run.py
-rw-r--r--  1 root root  8034 Aug 18 16:00 poi_structure.py
-rw-r--r--  1 root root  8700 Aug 18 16:00 ptd_common.py
-rw-r--r--  1 root root 11209 Aug 18 15:40 rho_sweep.py
-rw-r--r--  1 root root 12554 Aug 18 15:40 run_4d_workers.py
-rw-r--r--  1 root root 12934 Aug 18 15:56 run_route_monte_carlo.py
-rw-r--r--  1 root root  6582 Aug 18 16:00 sweep_h001.py
-rw-r--r--  1 root root 34711 Sep  1 16:42 sweep_max_steps.py
-rw-r--r--  1 root root  7594 Aug 18 16:00 sync_schedule.py
-rw-r--r--  1 root root 20821 Aug 18 16:00 temp_structures.py
-rw-r--r--  1 root root 62483 Aug 18 16:00 temp_works.py
-rw-r--r--  1 root root  9420 Aug 18 16:00 validate.py

```

도달성 지표는 `TrajectoryLogger` 자리에 메모리 집계 프로브를 끼워 얻었다
(`fourd_workers.py` 미수정). 각 조건의 동일한 5개 시드를 프로브로도
반복해 도달 분포를 합쳤다. 프로브에는 관측 비용이 있어 **실행 시간은
프로브 없는 실행에서만 쟀다.**

## 1. 도달성

| max_steps | POI/워커·일 | 미도달 워커 | 첫 도달 스텝 중앙값 | 90%tile | work 스텝 비율 | travel |
|---|---|---|---|---|---|---|
| **80** | **0.13** | 87.4% | 46.0 | 72 | **5.1%** | 11.6% |
| **150** | **0.27** | 75.0% | 79 | 130 | **11.6%** | 10.1% |
| **300** | **0.47** | 59.0% | 119.0 | 240 | **22.3%** | 8.2% |
| **480** | **0.81** | 32.5% | 214.5 | 436 | **33.3%** | 8.1% |
| **720** | **1.16** | 5.7% | 358 | 612 | **49.2%** | 7.2% |

`dwell_ratio` 는 0.75 로 설정돼 있다. **work 스텝 비율이 75%에 못 미치면
체류가 설정대로 일어나지 않은 것이다** — 도달을 못 하면 체류도 없다.

반대로 75%를 넘는 값도 가능하다. 현행 `dwell_steps`는 하루 work 비율의
상한이 아니라 **POI 방문 1회당 체류시간**이며, 이를 끝낸 뒤 다음 POI에서
다시 work 상태에 들어갈 수 있기 때문이다.

## 2. 노출 — 채널 구성

| max_steps | dwell_time | passage_count | zone_occupancy | 총 노출 | 회차간 sd |
|---|---|---|---|---|---|
| **80** | 6,995 | 12,990 | 2,748 | 22,733 | 219 |
| **150** | 15,553 | 33,761 | 5,463 | 54,777 | 621 |
| **300** | 44,847 | 91,864 | 12,448 | 149,159 | 1,866 |
| **480** | 104,905 | 214,047 | 22,668 | 341,621 | 3,238 |
| **720** | 222,015 | 471,614 | 41,211 | 734,840 | 3,687 |

### 채널 구성비 (%)

| max_steps | dwell_time | passage_count | zone_occupancy |
|---|---|---|---|
| **80** | 30.8% | 57.1% | 12.1% |
| **150** | 28.4% | 61.6% | 10.0% |
| **300** | 30.1% | 61.6% | 8.3% |
| **480** | 30.7% | 62.7% | 6.6% |
| **720** | 30.2% | 64.2% | 5.6% |

직전 조건 대비 구성비 최대 변동(%p): 150: 4.5 · 300: 1.7 · 480: 1.7 · 720: 1.5

**체류형→통과형 이동이 관측됐다.** dwell_time 구성비는 30.8%→30.2%, passage_count는 57.1%→64.2%였다. 예상과 반대여도 수치를 조정하지 않았다.

## 3. 위험유형별 노출

| 위험유형 | 채널 | 80 | 150 | 300 | 480 | 720 |
|---|---|---|---|---|---|---|
| H001 | dwell_time | 0 | 762 | 4,519 | 18,124 | 52,538 |
| H002 | passage_count | 4,759 | 13,463 | 42,447 | 100,278 | 212,634 |
| H004 | passage_count | 4,008 | 10,658 | 26,596 | 59,037 | 135,838 |
| H007 | dwell_time | 2,277 | 4,726 | 12,962 | 32,124 | 69,383 |
| H008 | zone_occupancy | 2,748 | 5,463 | 12,448 | 22,668 | 41,211 |
| H009 | passage_count | 3,957 | 8,715 | 20,387 | 49,856 | 114,543 |
| H011 | passage_count | 266 | 925 | 2,434 | 4,876 | 8,599 |

## 4. 비용

| max_steps | 초/회 (평균) | sd | 회차 | 80 대비 배수 | 스텝 배수 | 선형인가 | 프로브 초/회 |
|---|---|---|---|---|---|---|---|
| **80** | **34.4** | 1.0 | 5 | 1.00× | 1.00× | 선형 | 35.5s |
| **150** | **36.5** | 0.8 | 5 | 1.06× | 1.88× | **sublinear** | 36.7s |
| **300** | **40.1** | 0.7 | 5 | 1.17× | 3.75× | **sublinear** | 40.8s |
| **480** | **47.5** | 0.7 | 5 | 1.38× | 6.00× | **sublinear** | 47.9s |
| **720** | **53.5** | 1.0 | 5 | 1.56× | 9.00× | **sublinear** | 54.4s |

스텝 수는 80→720로 9.0배지만 실행시간은 34.4→53.5초로 1.56배다. 실측 분류는 **sublinear**다.

## 5. 판정

**하한 = max_steps 720** (POI/워커·일 1.16 ≥ 1.0 을 만족하는 최소 조건)

| 기준 | 그 지점의 값 | 판단 |
|---|---|---|
| 체류 비율이 `dwell_ratio`(75%)에 근접하는가 | 49.2% (차이 -25.8%p) | **근접하지 않음 — 도달은 하되 체류는 부족** |
| 채널 구성이 안정되는가 | 직전 대비 1.5%p | **아직 이동 중** |

- **POI 기준 하한:** 720 스텝.
- **75% 체류 근접점:** 측정 범위 내 없음. 최대 조건 720에서도 work 비율 49.2%다. 외삽하지 않는다.
- **채널 구성 안정 구간:** 측정 범위 내 없음. 마지막 조건의 직전 대비 최대 변동은 1.5%p다. 외삽하지 않는다.

따라서 정의상 POI 하한은 720지만, 체류 재현과 채널 안정 기준은 측정 범위 안에서 충족되지 않았다. 기본값 채택이나 추가 범위 측정은 Part B 지시 전까지 하지 않는다.

## 6. 실험 규모 산정

variant 10개 × 반복 n × 1회 실행 시간. 반복수 근거는 `build/pilot_run.md`
의 MDD 측정값이다 (n = 2·(1.96/δ)²·CV̄², 가장 분산이 큰 zone_occupancy 기준).

| max_steps | 초/회 | n=43 | n=169 | n=500 | n=1000 |
|---|---|---|---|---|---|
| **80** | 34.4 | 🟩 4.1 시간 | 🟨 16.1 시간 | 🟧 47.8 시간 | 🟥 95.6 시간 |
| **150** | 36.5 | 🟩 4.4 시간 | 🟨 17.1 시간 | 🟧 50.6 시간 | 🟥 101.3 시간 |
| **300** | 40.1 | 🟩 4.8 시간 | 🟨 18.8 시간 | 🟧 55.8 시간 | 🟥 111.5 시간 |
| **480** | 47.5 | 🟩 5.7 시간 | 🟨 22.3 시간 | 🟧 66.0 시간 | 🟥 132.0 시간 |
| **720** | 53.5 | 🟩 6.4 시간 | 🟧 25.1 시간 | 🟥 74.4 시간 | 🟥 148.7 시간 |

🟩 8시간 이내 · 🟨 8~24시간 · 🟧 24~72시간 · 🟥 72시간 초과

- **n=43** — δ=1% (pilot_run.md 측정)
- **n=169** — δ=0.5% (pilot_run.md 측정)
- **n=500** — 참고값 — 특정 δ 산출 아님
- **n=1000** — 참고값 — δ=0.2% 는 n≈1,050

하한(720)에서 경계 판정:

- n=43: **8시간 이내** (6.4 시간)
- n=169: **24~72시간** (25.1 시간)
- n=500: **72시간 초과** (74.4 시간)
- n=1000: **72시간 초과** (148.7 시간)

## 7. 계산비용 절충안 — 제시만, 미채택

하한에서 일부 실험 규모가 24시간을 넘으므로 절충안을 병기한다. **이번 작업에서는 어느 안도 실행하거나 채택하지 않았다.**

| 안 | 비용 영향 | 노출 정밀도 영향 |
|---|---|---|
| (a) 셀 1m→2m | 셀 수 약 1/4, 경로탐색 감소 | 2m 버퍼가 1셀로 축약되어 경계 위치 오차가 커진다. 동일 원점·셀 중심 방식으로 39개 개구부 위험구역을 재투영한 실측: **소멸 0개, 1셀 이하 0개, 셀수 최소/중앙/최대 4/6/11**. 이번 데이터에서는 소멸은 없지만 위험 띠의 공간 해상도는 절반이다. 1m 재계산은 저장 cells와 전건 일치했다. |
| (b) 스텝 1초→5초 | 같은 시간 범위를 약 1/5 스텝으로 계산 | 한 스텝 이동량 2.5m가 되어 좁은 통로·한 셀 점유·혼잡 상호작용을 건너뛸 수 있고 노출 시간이 5초 단위로 양자화된다. |
| (c) 8층→기준층 5개 | Basement·Level_02a_Parking·Roof 계산 제거 | 최하·최상층 경계와 주차층 이질성이 표본에서 사라지고, 직하부 3개층 동바리 존치의 경계 노출을 같은 모집단으로 추정할 수 없다. |
| (d) 반복 감축 | 실행시간이 반복수에 비례해 감소 | 파일럿 MDD 기준 n=43은 δ=1%, n=169는 δ=0.5%. n=500은 같은 식으로 약 δ=0.29%, n=1000은 약 δ=0.20%(정확한 0.2% 목표는 n≈1,050)까지만 검출한다. 감축할수록 더 작은 효과를 구분하지 못한다. |
| (e) 시드 독립 병렬 실행 | 워커 수에 따라 벽시계 시간 감소 | 노출 정밀도 영향 없음. 단, 시드 목록·결과 정렬·실패 재시도 기록을 고정해야 비트 재현성을 관리할 수 있다. |

2m 재투영은 **절충안을 채택한 실행이 아니라 기존 폴리곤에 대한 읽기 전용 해상도 진단**이다.
