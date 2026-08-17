# 4D 작업자 이동 알고리즘

## 목적과 경계

작업자는 공정표가 지정한 작업일·공종·인원으로 생성되고, BIM에서 유도된 작업 위치로
이동해 체류한다. 기존 `movement.py`의 2D 위험가중 A*와 한 셀 한 명 규칙은 그대로
유지한다. `worker_mobility.py`는 그 앞에 **현장 입구→작업층 통근**을 추가한다.

## 하루 상태 전이

`출발 전 → 층내 통근 → 계단 대기 → 계단 통과 → 작업층 이동 → 작업 체류 → 다음 POI`

1. 작업자 수·공종·작업층은 `schedule.json`의 활성 액티비티에서만 온다.
2. 작업 위치는 `element_task_mapping.json`과 `build/task_locations.json`에서 유도한다.
3. 명시적 entrance zone이 없으면 L1 주 연결공간의 외곽 walkable 셀을 결정론적으로
   파생한다. 임의 좌표를 하드코딩하지 않는다.
4. 같은 층은 기존 `soft_route`; 다른 층은 `SiteModel.plan_path`가 층내 A*와
   `VerticalLink`를 교대로 연결한다. 층간 순간이동은 허용하지 않는다.
5. 계단은 `capacity`와 `traversalSteps`를 갖는 자원이다. 용량이 차면 입구에서
   `stair_wait`, 진입하면 `stair` 상태로 정해진 시간 동안 점유한다.
6. 작업층 도착 이후 기존 워커 루프가 `travel/work`를 수행한다. 통근 지연은 당일
   작업 가능 시간을 실제로 줄인다.
7. 모든 무작위 선택은 주입된 시드에서만 나오며, 계단 예약 순서는 정렬돼 동일 시드
   결과가 재현된다.

## 선행연구에서 채택한 원칙

- 건설현장은 공정에 따라 공간·장애물·이동경로가 바뀌므로 BIM과 ABM을 함께 써야
  한다. 위험을 포함한 최저비용 경로가 단순 최단경로보다 적합하다는 건설현장 대피
  연구의 구조를 위험가중 A*에 반영했다.
- 실제 작업자 경로와 BIM 최적경로의 차이가 위험구역 탐지에 유용하다는 연구에 따라,
  궤적에는 계획 결과를 숨기지 않고 `commute/stair_wait/stair/travel/work` 상태를 남긴다.
- 계단 이동은 평면 보행보다 느리고 밀도·계단 형상에 영향을 받으며, 고밀도에서 위험이
  증가한다. 따라서 계단을 순간 링크가 아닌 시간과 용량을 가진 자원으로 모델링한다.
- 한국 고층건물 실험에서 평균 계단 속도는 상승 남/녀 0.66/0.48 m/s, 하강
  0.83/0.74 m/s로 보고됐다. 현재 프로젝트의 `traversalSteps=40`은 현장 입력값으로
  유지하며, 임의로 논문 평균을 하드코딩하지 않는다. 향후 계단 형상·방향별 입력을
  `site.json`에 추가해 보정해야 한다.

## 2026-08-17 실증

350일, `max_steps=480`, 시드 `unity-stairs-v1`로 재실행한 궤적은 106,425점이다.

| 상태 | 표본 수 |
|---|---:|
| commute | 38,756 |
| stair | 23,432 |
| stair_wait | 10,889 |
| travel | 5,757 |
| work | 27,591 |

L1~L8 모든 층이 궤적에 포함됐고 Unity 번들 좌표·액티비티 검증을 통과했다.

## 남은 모델 한계

- 통근 중 위험노출은 궤적에는 있지만 현재 λ 주 집계에는 아직 포함되지 않는다.
- 명시적 현장 출입구·휴게공간이 없어 L1 경계에서 입구를 파생한다.
- `traversalSteps=40`은 상승·하강, 계단 높이, 피로를 구분하지 않는다.
- 480스텝은 전체 8시간(28,800초)의 표본 창이다. 통근을 연결하면서 상층의 작업
  표본이 줄었으므로 기존 `max_steps` 하한 실험은 다시 평가해야 한다.

이 네 항목은 수치를 임의 보정하지 않고 데이터 또는 별도 검증 단계에서 해결한다.

## 참고문헌

- Marzouk & Al Daour, [Planning labor evacuation for construction sites using BIM and
  agent-based simulation](https://doi.org/10.1016/j.ssci.2018.04.023), Safety Science, 2018.
- Lee et al., [Automated hazardous area identification using laborers' actual and optimal
  routes](https://doi.org/10.1016/j.autcon.2016.01.006), Automation in Construction, 2016.
- Zhang et al., [Pedestrian single file movement on stairway](https://doi.org/10.1016/j.ssci.2021.105409),
  Safety Science, 2021.
- Choi, Galea & Hong, [Individual stair ascent and descent walk speeds measured in a
  Korean high-rise building](https://gala.gre.ac.uk/id/eprint/10826/), 2013.
