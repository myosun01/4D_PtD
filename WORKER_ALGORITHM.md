# 4D 작업자 이동 알고리즘

## 목적과 경계

작업자는 공정표가 지정한 작업일·공종·인원으로 생성되고, BIM에서 유도된 작업 위치로
이동해 체류한다. 기존 `movement.py`의 2D A*는 검증 베이스라인으로 보존하고,
4D 실제 워커는 위험가중 Theta*와 한 셀 한 명 규칙을 사용한다.
`worker_mobility.py`는 그 앞에 **현장 입구→작업층 통근**을 추가한다.

## 하루 상태 전이

`출발 전 → 층내 통근 → 계단 대기 → 계단 통과 → 작업층 이동 → 작업 체류 → 다음 POI`

1. 작업자 수·공종·작업층은 `schedule.json`의 활성 액티비티에서만 온다.
2. 작업 위치는 `element_task_mapping.json`과 `build/task_locations.json`에서 유도한다.
3. 명시적 entrance zone이 없으면 L1 주 연결공간의 외곽 walkable 셀을 결정론적으로
   파생한다. 임의 좌표를 하드코딩하지 않는다.
4. 같은 층은 `theta_route`; 다른 층은 `SiteModel.plan_path`가 층내 Theta*와
   `VerticalLink`를 교대로 연결한다. 층간 순간이동은 허용하지 않는다.
5. 계단은 `capacity`와 `traversalSteps`를 갖는 자원이다. 용량이 차면 입구에서
   `stair_wait`, 진입하면 `stair` 상태로 정해진 시간 동안 점유한다.
6. 작업층 도착 이후 기존 워커 루프가 `travel/work`를 수행한다. 통근 지연은 당일
   작업 가능 시간을 실제로 줄인다.
7. 모든 무작위 선택은 주입된 시드에서만 나오며, 계단 예약 순서는 정렬돼 동일 시드
   결과가 재현된다.
8. 통근 목표는 작업구역 내부의 임의 셀이 아니라 마지막 계단 출구에서 가장 가까운
   **구역 접근 셀**로 정한다. 구역 도착 후 작업 POI는 기존처럼 개별 표집한다.
9. 동일 OD·계단 가용상태·ρ 0.1 구간마다 확률적 경로 대안 3개를 만들어 재사용한다.
   하나의 최단경로로 고정하지 않아 개인차를 남기면서 반복 Theta* 계산을 줄인다.

## 선행연구에서 채택한 원칙

- 건설현장은 공정에 따라 공간·장애물·이동경로가 바뀌므로 BIM과 ABM을 함께 써야
  한다. 위험을 포함한 최저비용 경로가 단순 최단경로보다 적합하다는 건설현장 대피
  연구의 구조를 위험가중 Theta* 비용함수에 반영했다.

## Theta* 경로계획

- A*와 동일하게 8방향 이웃을 확장하되, `parent(current)`에서 후보 이웃까지 벽·개구부
  없는 line-of-sight가 있으면 현재 노드를 건너뛰어 부모를 직접 연결한다.
- any-angle 연결의 휴리스틱은 Euclidean distance를 사용한다. 반환 궤적은 LOS 선분을
  연속 격자 셀로 다시 펼쳐 기존 점유·노출 집계와 호환한다.
- LOS는 벽·개구부 관통과 막힌 두 직교 셀 사이의 대각선 코너컷을 금지한다.
- 기존 위험비용, ρ 회피강도, 경로 노이즈, TTL `hazardWeightMultiplier`는 유지한다.
- 2D `soft_route()`는 Phase 5 회귀검증용으로 삭제하지 않는다.
- 실제 작업자 경로와 BIM 최적경로의 차이가 위험구역 탐지에 유용하다는 연구에 따라,
  궤적에는 계획 결과를 숨기지 않고 `commute/stair_wait/stair/travel/work` 상태를 남긴다.
- 계단 이동은 평면 보행보다 느리고 밀도·계단 형상에 영향을 받으며, 고밀도에서 위험이
  증가한다. 따라서 계단을 순간 링크가 아닌 시간과 용량을 가진 자원으로 모델링한다.
- 한국 고층건물 실험에서 평균 계단 속도는 상승 남/녀 0.66/0.48 m/s, 하강
  0.83/0.74 m/s로 보고됐다. 현재 프로젝트의 `traversalSteps=40`은 현장 입력값으로
  유지하며, 임의로 논문 평균을 하드코딩하지 않는다. 향후 계단 형상·방향별 입력을
  `site.json`에 추가해 보정해야 한다.
- 보행자는 가능한 모든 미세 경로를 독립 대안으로 판단하지 않으며, 경로 선택은 제한된
  대안집합과 개인별 이질성을 갖는다는 보행자 경로선택 연구에 따라, 캐시는 OD별 단일
  경로가 아니라 소수의 확률적 대안집합으로 구성한다. ρ 구간폭과 대안 수 3은 아직
  실측 보정값이 아니므로 민감도 분석 대상으로 기록한다.

## 경로선택 몬테카를로(`route_only`)

기존 `mc_runs`는 한 시행마다 시작점·목적지·ρ·출발시각·체류 jitter·milling까지 함께
재표집했다. 이 결과의 분산은 “경로선택 불확실성”만 뜻하지 않는다. 새 모드는 다음처럼
추정대상을 분리한다.

| 시행 간 고정 | 시행마다 재표집 |
|---|---|
| 일·층별 인원, worker ID, 시작조건, 목적지, ρ, 출발시각, 작업구역 | Theta* 셀별 경로 충격 |
| 도착 뒤 horizon 끝까지 작업 | 그 충격으로 생긴 경로·도착시각·교착 결과 |

셀별 충격은 `ε(r,i,c)=PATH_NOISE×U(seed,r,i,c)`다. SHA-256 키 기반이므로 탐색 중 RNG
호출 순서가 달라져도 동일 셀에는 동일 공통난수가 배정된다. 프로세스별 내장 `hash()`를
사용하지 않아 Windows/Linux와 직렬/병렬 실행이 같다.

각 시행의 전체 실현 경로는 SHA-256 `route_digest`로 축약한다. 원 궤적을 100벌 쓰지
않고도 경로 확률변동이 실제로 작동했는지 확인할 수 있다. digest가 반복되는 것은 같은
경로가 확률적으로 재선택된 정상 결과이며, 강제 유일성은 분포를 왜곡하므로 금지한다.

노출과 λ는 평균지도에 바로 합쳐 버리지 않고 시행별로 보존한다. 평균·표준편차,
Student-t 95% 신뢰구간, 경험적 5/50/95 분위수와 사후 수렴표를 계산한다. BASE–대안은
같은 replicate 번호를 짝지은 대응차를 쓰며, 작업자 조건 해시가 다르면 비교를 중단한다.

## 실행시간 개선

- 기존 병목: 작업일×작업자마다 L1→작업층의 층별 A*를 전부 재계산하고, 계단 대기열은
  후보 시각마다 전체 통과시간 구간을 반복 탐색함.
- 수정: 작업구역 접근 셀 통일, OD·ρ구간별 3개 경로 템플릿 캐시, 계단 capacity별
  interval lane 예약, 반복실험 `--jobs N` 병렬화, BASE–대안 공통난수 시드 적용.
- 경로 MC에서는 궤적 CSV와 셀별 평균지도를 기본 비활성화하고 시행별 작은 요약만
  프로세스 사이에 전달한다. 작업자 조건 생성도 day/level당 한 번으로 줄였다.
- 8층 동일 OD 60회 마이크로벤치마크에서 통근 계획은 0.862초→0.248초(약 3.48배)로
  감소함. 이는 전체 350일 실험의 보장 속도향상이 아니라 경로계획 부분의 실측값임.
- `max_steps=480`은 노출 구성 안정성 때문에 유지한다. 실행시간을 줄이기 위해 시간창을
  다시 축소하면 절대 노출량과 상층 작업 체류가 왜곡될 수 있으므로 우선순위가 낮다.

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
- 경로 캐시의 ρ 구간폭 0.1과 OD당 대안 3개는 경험적 보정 전 휴리스틱이다.
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
- Filomena et al., [Empirical characterisation of agents' spatial behaviour in pedestrian
  movement](https://doi.org/10.1016/j.jenvp.2022.101809), Journal of Environmental
  Psychology, 2022.
- Vizzari et al., [Route choice in pedestrian simulation: Design and evaluation of a
  model based on empirical observations](https://doi.org/10.3233/IA-160102), 2017.
- Tong & Bode, [The principles governing the routes taken by pedestrians through cities](https://doi.org/10.1098/rsif.2022.0061),
  Journal of the Royal Society Interface, 2022.
- Fosgerau, Frejinger & Karlström,
  [A link based network route choice model with unrestricted choice set](https://doi.org/10.1016/j.trb.2013.07.012),
  Transportation Research Part B, 2013.
- Kivimäki et al., [Developments in the theory of randomized shortest paths](https://doi.org/10.1016/j.physa.2013.09.016),
  Physica A, 2014.
