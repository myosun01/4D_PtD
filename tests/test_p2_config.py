"""P2-1 — config.py 확장 검증: EDGE(6) 셀타입, 채널별 per-step 확률(§2 분포),
기존 2D 상수 불변(Phase 5 2D 베이스라인 보호)."""
import config as C
from fourd import CHANNELS


def test_edge_celltype_registered():
    assert C.EDGE == 6
    assert C.VEHICLE_ROUTE == 7                      # 예약(미사용)
    assert C.CELL_NAME[C.EDGE] == "단부"
    assert C.EDGE in C.CELL_COLOR
    # 기존 셀타입 코드 불변
    assert (C.WALKABLE, C.WALL, C.FLOOR_OPENING, C.MATERIAL, C.NARROW) == (0, 1, 2, 4, 5)


def test_channel_per_step_all_positive():
    assert set(C.CHANNEL_PER_STEP) == set(CHANNELS)
    for ch, p in C.CHANNEL_PER_STEP.items():
        assert p > 0, ch
    # fall 은 2D P_FALL_PER_STEP 에 앵커 (Phase 5 동등성 전제)
    assert C.CHANNEL_PER_STEP["fall"] == C.P_FALL_PER_STEP
    assert C.CHANNEL_PER_STEP["edge"] == C.P_FALL_PER_STEP
    # 무너짐(붕괴) < 떨어짐 (사망가중 분포상 6.3% < 41.2%)
    assert C.CHANNEL_PER_STEP["collapse_zone"] < C.CHANNEL_PER_STEP["fall"]


def test_channel_distributions_present():
    # §2 두 분포가 통계 상수로 존재 (대책 효과 아님)
    assert abs(C.FATAL_WEIGHTED_SHARE["fall"] - 0.412) < 1e-9
    assert abs(C.RC_FREQ_SHARE["trip"] - 0.308) < 1e-9
    assert "collapse" in C.FATAL_WEIGHTED_SHARE and "collapse" in C.RC_FREQ_SHARE


def test_2d_constants_unchanged():
    # movement.py 2D 경로가 쓰는 절대 확률은 재보정에도 불변이어야 함
    assert C.P_FALL_PER_STEP == 1.1e-8
    assert C.P_STRUCK_MATERIAL == 2.6e-9
    assert C.P_STRUCK_NARROW == 2.6e-9
    assert C.GRID_ROWS == 30 and C.GRID_COLS == 44
