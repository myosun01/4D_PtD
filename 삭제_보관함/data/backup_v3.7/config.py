"""
config.py — 시뮬레이션의 모든 '값(설정)'을 관리
"""
import os

# 작업자 이동 셀 종류 (§2 어휘 계약)
WALKABLE      = 0
WALL          = 1
FLOOR_OPENING = 2   # 개구부
MATERIAL      = 4   # 적재물
NARROW        = 5   # 협소공간
EDGE          = 6   # 단부 (신설, P2-1) — 슬래브 가장자리. walkable이지만 추락 노출
VEHICLE_ROUTE = 7   # 차량동선 (예약·미사용, §2 동결 스코프)

CELL_NAME  = {WALKABLE: "통로", WALL: "벽", FLOOR_OPENING: "개구부",
              MATERIAL: "적재물", NARROW: "협소공간", EDGE: "단부"}
CELL_COLOR = {WALL: "#334155", FLOOR_OPENING: "#ef4444",
              MATERIAL: "#b45309", NARROW: "#6366f1", EDGE: "#f59e0b"}

# 1) 시공간 단위 (1셀=1m, 작업자 0.5 m/s → 이동 시 2스텝당 1칸)
CELL_SIZE_M      = 1.0
WORKER_SPEED_MPS = 0.5
STEP_SECONDS     = 1
WORK_START_HOUR  = 10
WORK_END_HOUR    = 18
WORKDAY_STEPS    = (WORK_END_HOUR - WORK_START_HOUR) * 3600 // STEP_SECONDS   # 28800

# 2) 작업자 agent 구성
N_WORKERS        = 20
N_FOREMEN        = 2
DWELL_MINUTES    = 360                                   # PoI 1회 작업량 = 1인 기준 6시간(=360분)
DWELL_STEPS      = DWELL_MINUTES * 60 // STEP_SECONDS    # = 21600 (6h). 하루 8h 중 대부분 작업 체류
DWELL_JITTER_FRAC = 0.20                                 # 개인별 체류시간 ±편차(평균 DWELL은 유지)
TASKS_PER_WORKER = 4
START_STAGGER_S  = 120                                   # 출발 분산(0~120초) — 초반부터 곧 이동 시작

# 3) 위험허용도 ρ (avoider↔aggressive) 
RHO_MIN, RHO_MAX = 0.15, 0.90
RHO_FOREMAN      = 0.20

# 4) 이동(소프트 위험회피) 비용 파라미터
HAZARD_WEIGHT    = {MATERIAL: 3.0, NARROW: 2.0}
RISK_K           = 0.8        # 회피 강도
OPEN_EDGE_PEN    = 1.2        # 개구부 인접 회피
PATH_NOISE       = 0.25       # 경로 다양성(작을수록 동선이 곧고 차분)
MILL_MOVE_PROB   = 0.15       # 작업 중 미세이동 확률(작을수록 차분)

# 5) 사고 확률(per-step=per-second, 노출 중) — 한국 고용노동부 2024 건설업 실측 재보정
#    산출식: 연 재해율 1.65% × 유형비중 ÷ 연근무일 250 ÷ 하루 노출초(가정)
P_FALL_PER_STEP    = 1.1e-8   # 추락: 0.0165×0.25÷250 ≈ 1.65e-5/인·일 ÷ ~1,500 노출초
P_STRUCK_MATERIAL  = 2.6e-9   # 부딪힘·맞음(적재물): 0.0165×0.15÷250 ≈ 9.9e-6/인·일 ÷ 노출초(적재+협소 합산)
P_STRUCK_NARROW    = 2.6e-9   # 부딪힘·맞음(협소): 상동(협소 채널; 적재물과 동일 per-step)
FATAL_FRACTION     = 0.05     # 사망만인율 2.38‱ 반영 → 재해 중 사망 약 5%
# ── 관전/빠른확인 전용 배율 ──
# 이 배율은 히트맵(연구)에는 절대 곱하지 않는다(run_one_day 는 scale=1.0 고정).
# 오직 실시간 관전(viewer)에서 드문 사고를 눈으로 보고 싶을 때만 키운다(예: 4~8). 기본 1.0.
ACCIDENT_PROB_SCALE = 1.0

# 5b) 자기보정(Self-calibration) — '노출초 가정' 없이 실제 배치에 자동으로 맞춤
#     per_step = (연재해율 × 유형비중 ÷ 연근무일) ÷ (시뮬 측정 1인당 하루 평균 노출스텝)
SELF_CALIBRATE     = False    # True: 예비 실행으로 per-step 확률 역산 후 사용 / False: 위 고정 절대값 사용
ANNUAL_INJURY_RATE = 0.0165   # 2024 건설업 연 재해율 1.65%
SHARE_FALL         = 0.25     # 유형비중 — 추락(떨어짐)
SHARE_STRUCK       = 0.15     # 유형비중 — 부딪힘+물체에맞음(적재물+협소 합산)
WORK_DAYS_PER_YEAR = 250      # 연 2,000시간 = 250일(하루 8h)
CALIB_DAYS         = 5        # 예비 실행 일수(많을수록 노출 추정 안정)
CALIB_SEED         = 20240    # 예비 실행 시드 기준

# 6) 사회(모방·목격충격)
SOCIAL_ENABLED   = True
SOCIAL_RADIUS    = 3
SOCIAL_EVERY     = 30
IMITATION_RATE   = 0.05
WITNESS_SHOCK    = 0.15

# 7) HoC/PtD 연결
# 라이브러리 정본은 v2.4 (scripts/build_ttl.py 산출물). 루트의 ptd_library_v2.3.ttl 은
# build_ttl.py 가 온톨로지를 이월해 오는 원천이지 엔진이 읽는 파일이 아니다.
TTL_PATH = os.path.join(os.path.dirname(__file__), "build", "ptd_library_v2.4.ttl")
# 시나리오 = 모든 활성 위험에 같은 HoC 단계 적용 (level 0=Base)
HOC_SCENARIOS = {
    "base":           dict(label="Base (기본)",            level=0),
    "elimination":    dict(label="Elimination (제거)",      level=1),
    "substitution":   dict(label="Substitution (대체)",     level=2),
    "engineering":    dict(label="Engineering (공학적)",    level=3),
    "administrative": dict(label="Administrative (관리적)", level=4),
    "ppe":            dict(label="PPE (보호구)",            level=5),
}
CELL_NAME_TO_INT = {
    "floor_opening": FLOOR_OPENING,
    "narrow_hazard_zone": NARROW, "narrow_passage": NARROW,
    "material_storage": MATERIAL, "walkable": WALKABLE,
}
# 현재 2D 격자에 존재하는 위험만 활성화 (TTL 6종 중 3종)
HAZARD_TO_CELL = {"H001": FLOOR_OPENING, "H002": NARROW, "H004": MATERIAL}
ACTIVE_HAZARDS = ["H001", "H002", "H004"]

# 8) 현장 레이아웃 
GRID_ROWS, GRID_COLS = 30, 44
HOME_CELL = (28, 8)
# 작업구역(PoI): 일부는 위험요소 위/인접(현실: 작업이 위험 근처에서 이뤄짐)
WORK_ZONES = {
    "wz_mat_L":   dict(cell=(5, 5),   note="적재물"),
    "wz_mat_R":   dict(cell=(6, 36),  note="적재물"),
    "wz_narrow1": dict(cell=(10, 22), note="협소공간"),
    "wz_narrow2": dict(cell=(23, 19), note="협소공간"),
    "wz_open":    dict(cell=(23, 12), note="개구부 인접"),
    "wz_safe1":   dict(cell=(11, 37), note="일반"),
    "wz_safe2":   dict(cell=(4, 12),  note="일반"),
}

# 9) 화면/실행 기본값
MC_RUNS_DEFAULT  = 100        # 히트맵 반복 기본 횟수(사용자 변경 가능)
PLAYBACK_DEFAULT = 3          # 관전 기본 배속(스텝/프레임). 낮을수록 부드러움
PLAYBACK_MAX     = 10         # 배속 상한(프레임당 스텝수 폭증 방지)
MAX_STEPS_PER_FRAME = 10      # 한 프레임에 실행할 스텝 하드 상한(렉 방지)
ANIM_INTERVAL_MS = 50         # ≈20fps (blit로 변경분만 그리므로 더 부드럽게)
GUI_MC_RUNS_CAP  = 100        # 화면 버튼 히트맵 최대 반복(별도 프로세스라 안 멈춤; 그 이상은 --mc 권장)

# 10) 동선 로그 — 각 작업자 스텝별 위치/상태를 CSV로 기록(관전/헤드리스 추적용)
MOVEMENT_LOG_EVERY = 1        # N스텝마다 1줄 기록(1=매 스텝). 몬테카를로엔 사용하지 않음.

# ══════════════════════════════════════════════
# 11) 4D 채널별 per-step 확률 (P2-1) — §2 위험 채널·분포 계약
# ══════════════════════════════════════════════
# 채널: fall(개구부 인접) / edge(단부) / material(적재물) / narrow(협소) /
#       collapse_zone(동바리 직하부) / drop_zone(상층작업 직하부)
# 대책(HoC) 효과 계수는 여기 절대 넣지 않는다 — TTL 전용. 여기엔 통계 상수만.
#
# §2 사망 가중(고용노동부 2025, 전 업종): 떨어짐 41.2 / 물체에맞음 11.9 /
#   부딪힘 10.2 / 끼임 8.3 / 무너짐 6.3 (%)
FATAL_WEIGHTED_SHARE = {
    "fall": 0.412, "material": 0.119, "struck": 0.102, "caught": 0.083, "collapse": 0.063,
}
# §2 RC 빈도 가중(CSI RC 1,368건, 2025): 넘어짐 30.8 / 물체에맞음 17.5 /
#   떨어짐 11.6 / 끼임 9.8 / 부딪힘 8.4 / 무너짐 0.1 (%)
RC_FREQ_SHARE = {
    "trip": 0.308, "material": 0.175, "fall": 0.116, "caught": 0.098, "struck": 0.084, "collapse": 0.001,
}
# 채널별 per-step 확률 = 기존 fall 확률을 앵커로 §2 사망가중 분포 비율로 분해.
# (기존 2D P_FALL_PER_STEP/P_STRUCK_* 는 2D 경로가 계속 사용 — 불변. fall 채널을
#  P_FALL_PER_STEP에 앵커로 두면 Phase 5 2D 동등성 검증이 가능하다.)
# 자기보정(SELF_CALIBRATE)은 Phase 2에선 채널 분해 전이므로 고정 절대값을 쓴다.
_FALL_ANCHOR = P_FALL_PER_STEP        # 1.1e-8 (떨어짐)
_S = FATAL_WEIGHTED_SHARE
CHANNEL_PER_STEP = {
    "fall":          _FALL_ANCHOR,
    "edge":          _FALL_ANCHOR,                              # 단부=추락형, 동일 앵커
    "material":      _FALL_ANCHOR * (_S["material"] / _S["fall"]),
    "narrow":        _FALL_ANCHOR * (_S["struck"]   / _S["fall"]),
    "collapse_zone": _FALL_ANCHOR * (_S["collapse"] / _S["fall"]),
    "drop_zone":     _FALL_ANCHOR * (_S["material"] / _S["fall"]),  # 낙하물=물체에맞음
}
# 채널 → 치명도 비중(SWR 심각도 가중의 통계 근거; Phase 4에서 TTL fatalityMultiplier와 결합)
CHANNEL_FATAL_SHARE = {
    "fall": _S["fall"], "edge": _S["fall"], "material": _S["material"],
    "narrow": _S["struck"], "collapse_zone": _S["collapse"], "drop_zone": _S["material"],
}

# 4D 산출물 폴더
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "output")

# 4D 크루 rho 분포 기본값(crews.json의 mean/sd=null일 때 = 전역 기본).
# 2D init_rho(uniform)와 동일 표집으로 Phase 5 동등성 유지.
CREW_RHO_DIST_DEFAULT = "uniform"
