"""
social.py — 작업자 간 사회적 상호작용 (위험행동 전염 / 안전 경각심)
====================================================================
모든 사회 효과는 위험허용도 ρ(risk tolerance, 0~1) 하나로 표현된다.
  ρ 높음 → 위험을 덜 피함(이동 비용식의 (1−ρ) 통해 movement에 직결)
  ρ 낮음 → 조심
이 파일은 config 값만 쓰고, movement의 Worker 객체(.pos/.rho/.base_rho/
.is_foreman/.injured)를 받아 ρ를 갱신한다. (movement → social 단방향 의존)

[근거] Choi & Lee (2018) 사회인지 안전행동 ABM; 안전문화 전염 연구.
[Unity 이식] 순수 수치 로직이라 C# 포팅이 가장 쉽다.
"""
import config as C


def init_rho(index: int, is_foreman: bool, rng) -> float:
    """작업자 초기 ρ. foreman은 보수적(낮은 ρ) 고정."""
    if is_foreman:
        return C.RHO_FOREMAN
    return rng.uniform(C.RHO_MIN, C.RHO_MAX)


def apply_witness_shock(workers, r: int, c: int):
    """사고 발생 즉시: 반경 내 작업자 ρ 하락(경각심↑)."""
    if not C.SOCIAL_ENABLED:
        return
    for w in workers:
        if w.injured:
            continue
        if abs(w.pos[0] - r) <= C.SOCIAL_RADIUS and abs(w.pos[1] - c) <= C.SOCIAL_RADIUS:
            w.rho = max(0.05, w.rho - C.WITNESS_SHOCK)


def apply_imitation(workers, frame: int):
    """주기적: 주변 평균 ρ 쪽으로 서서히 모방(동조). foreman은 영향받지 않음."""
    if not C.SOCIAL_ENABLED or frame == 0 or frame % C.SOCIAL_EVERY != 0:
        return
    snapshot = [(w.pos, w.rho) for w in workers if not w.injured]
    for w in workers:
        if w.injured or w.is_foreman:
            continue
        near = [rho for (p, rho) in snapshot
                if abs(p[0] - w.pos[0]) <= C.SOCIAL_RADIUS
                and abs(p[1] - w.pos[1]) <= C.SOCIAL_RADIUS]
        if len(near) >= 2:                       # 자기 외 최소 1명
            avg = sum(near) / len(near)
            w.rho = max(0.05, min(0.95, w.rho + C.IMITATION_RATE * (avg - w.rho)))
