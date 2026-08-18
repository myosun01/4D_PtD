# PtD 대안 효과 정량화 반복실험 규약

## 현재 확정된 경로선택 실험 규약

- 연구 질문은 **작업자 조건을 고정했을 때 경로선택 불확실성이 노출·λ에 만드는
  분포**다. `variation_scope="route_only"`를 사용한다.
- 한 조건의 첫 정식 배치는 **고정 100회**다. 100회를 모두 실행한 뒤 수렴곡선과
  신뢰구간 반폭을 사후 점검한다. 결과를 보면서 임의로 일찍 멈추지 않는다.
- 일·층별 인원, 작업자 ID, 시작조건, 작업 목적지, ρ, 출발시각, 작업구역은 한 번만
  뽑아 100회에 재사용한다. 목적지 도착 뒤에는 그날 horizon 끝까지 같은 작업구역에
  머문다.
- 시행마다 다시 뽑는 값은 Theta*의 경로 비용 충격뿐이다. 서로 다른 시행에서 같은
  경로가 다시 나오는 것은 정상이며, 100개 경로가 모두 달라야 한다는 제약은 두지 않는다.
- 같은 seed와 replicate 번호는 같은 셀에 같은 경로 충격을 주는 공통난수(Common Random
  Numbers, CRN)다. BASE–대안은 작업자 조건 해시가 같을 때만 대응 비교한다.
- 보고값은 시행별 원자료, 평균, 표준편차, Student-t 95% 신뢰구간, 5/50/95 분위수,
  경로 digest 다양성이다.

## 이전 70회 결론과 해석 제한

이 시뮬레이션은 공기가 끝나는 유한기간(terminating) 모형이므로 서로 다른 시드의 독립
반복 결과를 분석 단위로 삼는다. 시뮬레이션 출력분석 문헌은 임의의 고정 반복수보다
신뢰구간 반폭이 목표 정밀도에 도달할 때까지 반복하는 절차를 권고하며, 상대정밀도
절차는 통상 최소 10회의 파일럿에서 시작한다.

2026-08-17 최종 설정(`max_steps=480`)에서 BASE와 대표 대안 `ALT_S_CP_05`를 각각
10회 실행했다. 채널별 평균 변동계수는 다음과 같았다.

| 출력 | 평균 CV | 1% 차이 검출에 필요한 조건당 반복 |
|---|---:|---:|
| dwell_time | 0.0210 | 35 |
| passage_count | 0.0132 | 14 |
| zone_occupancy | 0.0148 | 17 |
| 총 노출 | 0.0085 | 6 |

두 조건 평균 차이의 95% 신뢰구간 반폭을 평균의 1% 이하로 만드는 근사식
`n ≥ 2 × (1.96 / 0.01)² × CV²`을 적용하면 최악 채널에서 35회가 필요하다.
BASE와 9개 대안을 동시에 비교할 때 가족단위 오류율 5%를 유지하도록 Bonferroni
보정하면 임계값이 약 1.96에서 2.77로 증가하고 필요 반복은 약 두 배가 된다.
따라서 당시에는 `35 × (2.77/1.96)² ≈ 70`회를 운영 최소치로 정했다.

이 값은 효과가 1%보다 작은 대안까지 반드시 검출한다는 뜻은 아니다. 0.5% 차이를
주요 판정 대상으로 삼는 경우 파일럿 근사상 최대 137회가 필요하고, 다중비교까지
보정하면 약 274회가 필요하다.

그러나 그 파일럿의 각 시행은 경로뿐 아니라 시작점·목적지·ρ·출발·체류 변동까지 함께
다시 뽑았다. 현재 `route_only`의 분산과 다른 추정대상이다. 따라서 **70회를 새 모드에
그대로 전용하지 않고**, 100회 고정 배치를 새 기준자료로 만든 뒤 다음 배치의 표본수를
다시 산정한다. 이전 수치는 역사적 근거로만 보존한다.

## 확률 모형과 재현성

작업자 `i`, 시행 `r`, 셀 `c`의 경로 충격은 다음과 같다.

`ε(r,i,c) = PATH_NOISE × U(seed, r, i, c)`, `U ~ Uniform(0,1)`

`U`는 Python의 프로세스별 `hash()`가 아니라 SHA-256 키에서 직접 만든다. 호출 순서나
병렬 배치 구성이 달라져도 값이 같다. Theta*의 선분 비용은 다음 구조를 유지한다.

`C(a,b) = Σ(distance + risk_extra(c) × (1-ρ_i) + ε(r,i,c))`

위험가중은 TTL `hazardWeightMultiplier`와 기존 셀 위험계수를 사용한다. `PATH_NOISE`,
ρ 분포, 계단 통과시간 등 행동 파라미터는 아직 실측 보정값이 아니므로 이번 수정에서
새 값을 만들지 않았다.

## 실행·판정 규칙

1. 같은 조건을 같은 seed로 다시 실행했을 때 시행별 JSON이 같아야 한다.
2. 직렬 실행과 병렬 배치 실행의 같은 replicate가 같아야 한다.
3. 모든 병렬 배치의 작업자 조건 해시가 같고 replicate 번호가 정확히 `0..99`여야 한다.
4. 경로 digest가 모두 하나면 경로 변동이 작동하지 않은 것으로 보고 본실험에 쓰지 않는다.
5. 100회를 전부 실행한 뒤 주요 지표의 95% CI 반폭/평균과 수렴표를 확인한다.
6. BASE–대안 대응 비교는 seed, 반복수, horizon, 작업자 조건 해시가 모두 같을 때만 한다.
7. 효과의 신뢰구간이 0을 포함하면 “효과 없음”이 아니라 “현재 정밀도에서 방향을
   확정하지 못함”으로 기록한다.

작업자 조건 해시가 달라지는 공간제거·공정변경 대안은 이 엄격한 경로-only 대응비교와
추정대상이 다르다. 이를 억지로 짝짓지 않고 별도 실험 설계를 사용한다.

## 실행 명령과 산출물

```bash
python scripts/run_route_monte_carlo.py --variant BASE --runs 100 --max-steps 480 --jobs 4 --seed route-mc-v1
```

산출물은 `route_mc_BASE_replicates.csv`, `route_mc_BASE_summary.json`,
`route_mc_BASE_report.md`다. 대안도 같은 seed로 실행한 뒤 조건이 일치하면 다음처럼 비교한다.

```bash
python scripts/compare_route_monte_carlo.py output/route_mc_BASE_summary.json output/route_mc_ALT_ID_summary.json
```

## 한 사이클이 오래 걸렸던 이유와 이번 절감

기존 전체 실행은 `공정일 × 활성층 × 작업자 × 480 스텝 × 반복`의 점유·노출 갱신에 더해,
층별 Theta*와 계단 예약을 수행한다. 여기에 모든 작업자 궤적 CSV를 기록하면 I/O가 크게
늘고, 100회 결과를 평균 지도만 남기면 재실행 없이 통계를 고칠 수도 없었다.

새 MC 실행기는 궤적을 쓰지 않고 셀별 평균지도도 기본적으로 만들지 않는다. 시행별 작은
요약만 남기며, 절대 replicate 번호에 결합된 시드로 2~4개 프로세스의 독립 배치를 병렬
실행한다. 작업자 조건은 day/level마다 한 번만 생성해 모든 시행에 복제한다. 시각화용
궤적은 통계가 확정된 뒤 대표 시행만 별도로 생성한다.

## 근거 자료

- A. M. Law, [“Output Data Analysis for Simulations”](https://informs-sim.org/wsc02papers/012.pdf),
  Winter Simulation Conference, 2002. 독립 반복, 상대정밀도 신뢰구간, 최소 10회에서
  시작하는 순차 절차를 설명한다.
- K. A. Hoad, S. Robinson, R. Davies,
  [“Automating DES Output Analysis: How Many Replications to Run”](https://informs-sim.org/wsc07papers/060.pdf),
  Winter Simulation Conference, 2007. 신뢰구간 반폭을 사용한 반복수 자동 결정 절차를
  제시한다.
- 본 저장소 `build/pilot_run.md`, `build/pilot_raw.json`: 480스텝, 10회 실측 근거.
- A. Nash, K. Daniel, S. Koenig & A. Felner,
  [“Theta*: Any-Angle Path Planning on Grids”](https://doi.org/10.1613/jair.2994),
  JAIR, 2010. any-angle Theta*의 원 알고리즘 근거.
- M. Fosgerau, E. Frejinger & A. Karlström,
  [“A link based network route choice model with unrestricted choice set”](https://doi.org/10.1016/j.trb.2013.07.012),
  Transportation Research Part B, 2013. 경로선택을 확률분포로 다루는 근거.
- A. Kivimäki et al.,
  [“Developments in the theory of randomized shortest paths”](https://doi.org/10.1016/j.physa.2013.09.016),
  Physica A, 2014. 비용과 경로 무작위성의 균형을 갖는 randomized shortest-path 계열 근거.
- W. G. Kennedy,
  [“The role of multiple replications in agent-based modeling”](https://doi.org/10.1016/j.ecolmodel.2018.12.022),
  Ecological Modelling, 2019. ABM 시행별 분포와 반복 필요성의 근거.
