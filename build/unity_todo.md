# 복귀 후 Unity 에서 할 일

Python 측에서 할 수 있는 것은 v3.1 에서 끝냈다. 아래는 **Unity 프로젝트가 있어야만
할 수 있는 것들**이다. 이 저장소에는 `.cs` 0개, `.unity` 0개이며 Unity 프로젝트
`4DBIM_Base`(씬 `PtdConsistency`, Unity 6.3 LTS 6000.3.2f1)는 이 머신에 없다.

---

## 0. 번들에 이미 준비된 것 (임포트만 하면 됨)

| 파일 | 내용 | 크기 |
|---|---|---|
| `model.glb` | 요소별 노드 분리 지오메트리. 노드/메쉬 이름 = IFC GlobalId | 59.1 MB |
| `manifest.json` | 요소 12,712개 — 클래스·층·bbox(IFC 월드 m)·pset·재료 | 11.4 MB |
| `bundle_meta.json` | 스키마·좌표계 선언·gridFrame 사본 | 1 KB |
| `timeline.json` | 공기 350일 / 액티비티 234 / elementAppear / ghostPhase / hazardSpans / crewByDay | 0.6 MB |
| `hazard_zones.json` | **위험구역 84 zone, 7유형 전부.** 셀 + glTF 좌표 폴리곤 + spawnDay/despawnDay | 3.4 MB |
| `worker_trajectory.json` | **워커 궤적.** `frames[day][step] → [{worker_id, pos_gltf, state, activity_id, trade}]` | 3.6 MB |
| `ptd_library.json` | 대안 35건 — HoC 등급·규칙유형·계수·적용 가능 zone / variant 목록(BASE) | 24 KB |
| `lambda_daily.csv` | 셀·일·채널별 기대위험 λ | 0.3 MB |

좌표 계약은 세 파일(`bundle_meta` / `hazard_zones` / `worker_trajectory`)이
동일하게 선언한다:

```
IFC 원본 mm → m        (unitScaleToMeter 0.001)
격자 → 월드            world_xy = gridFrame.origin + (index + 0.5) * resolution
                       row=+Y, col=+X, z = level.elevation_m
월드 → glTF            (x, y, z)_ifc → (x, z, -y)_gltf,  up = +Y
센터링                 금지 (원점 이동 시 gridFrame 정합이 깨진다)
```

`check_unity_bundle.py` 가 궤적 좌표가 `model.glb` 바운딩박스 안에 있는지 이미
검증한다. **Unity 쪽에서 좌표를 다시 손보지 말 것** — glTF 임포트 시 Unity 가
오른손→왼손 변환을 자동으로 하므로, 그 위에 추가 변환을 얹으면 어긋난다.

---

## 1. 프로젝트 연결 — 결정 필요

- [ ] Unity 프로젝트를 이 저장소 안에 둘지, 밖에 두고 `unity_bundle/` 만 복사할지 결정
- [ ] 저장소 루트의 `.meta` 5개(`construction_schedule.csv.meta` 등)를 어떻게 할지 결정
      — 이 파일들은 한때 어떤 Unity 프로젝트의 `Assets/` 아래 있었다는 흔적이다
- [ ] `model.glb` 59 MB — Git LFS 를 쓸지, 번들을 버전관리에서 뺄지

## 2. 임포트·로더 (C#)

- [ ] `BundleMeta` 로더 — `gridFrame` 을 읽어 (row,col) ↔ 월드(x,y) 변환하는 **단일 매퍼**
      (ROADMAP §2: "소비자는 단일 변환 함수로만 자기 좌표계로 변환한다")
- [ ] `manifest.json` 로더 — GLB 노드 GlobalId ↔ 요소 메타 조인. 12,712개라 딕셔너리 필수
- [ ] `timeline.json` 로더 — 일자 슬라이더(0~349), `elementAppear` 로 부재 점진 출현,
      `ghostPhase` 로 시공중 고스트 머티리얼 전환
- [ ] `hazard_zones.json` 로더 — `spawnDay <= d < despawnDay` 로 on/off
- [ ] `worker_trajectory.json` 로더 — `frames[day][step]`. **스텝이 듬성하다**
      (샘플링 간격 10) → 프레임 사이를 보간해야 부드럽다

## 3. 프리팹

- [ ] **위험구역 프리팹** — 7유형별로 색·머티리얼 구분
      (H001 개구부 / H002 협소통로 / H004 적재물 / H007 단부 / H008 동바리붕괴 /
       H009 낙하물 / H011 장비동선). `outline_gltf` 폴리곤으로 메쉬를 만들거나
      `cellCenters_gltf` 로 셀 데칼을 깐다
- [ ] **워커 프리팹** — 공종(trade) 5종 구분: rebar / formwork_erection /
      concrete_pour / formwork_stripping / material_handling
- [ ] **워커 애니메이터** — `state` 필드가 `travel` / `work` 두 값이다.
      이 두 상태에 걸을 때·작업할 때 애니메이션을 매핑한다
- [ ] **λ 히트맵 데칼** — `lambda_daily.csv` 를 층·일자별 셀 색으로 (선택)

## 4. 씬 구성

- [ ] 층 토글 (L1~L8) — 층별 표고는 `hazard_zones.json` 의 `elevation_m` 에 있다
- [ ] 일자 타임라인 UI — 재생/일시정지/배속, 현재 일자 표시
- [ ] 위험구역 범례 + 유형별 on/off 필터
- [ ] 대안 비교 UI — `ptd_library.json` 의 `variants` 배열을 읽는다.
      **지금은 BASE 하나뿐**이며 대안 적용 세계(variant)가 생기면 항목만 늘어난다
- [ ] 카메라 프리셋 (전경 / 층별 평면 / 워커 추적)

## 5. 성능

- [ ] `model.glb` 12,477 메쉬 노드 — GPU Instancing 또는 메쉬 병합 검토
      (IfcMember 만 10,031개다)
- [ ] `worker_trajectory.json` 3.6 MB 를 한 번에 파싱할지 일자별로 스트리밍할지
- [ ] 위험구역 H008 은 zone 하나가 셀 1,000개를 넘는다 — 셀 단위 데칼은 무거울 수 있다

---

## 알아둘 것 (Unity 에서 헷갈릴 지점)

1. **하루가 8시간이 아니다.** `worker_trajectory` 의 `step` 은 `max_steps=80`
   으로 돌린 결과이고 1스텝 = 1초다. `config.WORKDAY_STEPS` 는 28,800(8시간)이지만
   전체 공기를 그 해상도로 돌리면 실행 시간이 감당되지 않아 80스텝으로 돌렸다.
   즉 **하루치 궤적은 80초분이다.** 재생 속도를 여기에 맞추거나, 더 긴 하루가
   필요하면 `python scripts/run_4d_workers.py --max-steps N` 으로 다시 뽑는다.

2. **워커 위치의 70%는 요소에서 유도된 것이 아니다.** 234개 액티비티 중 요소 GUID
   매핑이 있는 것은 112개뿐이고(양생·자재·해체 계열에 없다), 나머지는 층 메인
   컴포넌트를 배회한다. 실측 비율은 유도 600 / 폴백 1,430 이다.
   `build/run_4d_workers_log.md` 에 남아 있다.

3. **H002·H011 은 λ 채널을 `narrow` 로 공유한다.** 장비동선 접촉을 협소통로와
   분리할 계수가 원천(§2 통계·TTL)에 없어 채널을 나누지 않았다. zone 구분은
   `hazard_type` 으로 그대로 남아 있으므로 **시각화는 7유형으로 나눠도 된다.**

4. **사회 효과(목격 충격·모방)는 4D 에 없다.** ρ 는 크루 생성 시 1회 정해지고
   하루 동안 고정이다. 워커가 서로에게 반응하는 연출을 넣으면 시뮬레이션에 없는
   것을 보여주게 된다.

5. **대안 적용 세계(variant)가 아직 없다.** `ptd_library.json` 의 `variants` 는
   BASE 하나이고, 대안별 저감량 비교 화면은 variant 생성기가 나온 뒤에야 채워진다.
