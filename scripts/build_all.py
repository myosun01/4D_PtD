# -*- coding: utf-8 -*-
"""전체 파이프라인 순차 실행 (Makefile 의 all 타깃과 동일 순서).

  migrate → adjudicate → kalis → ttl → validate → docx

이 환경에는 make 와 Node.js 가 없으므로 이 스크립트가 실행기다.
저장소 루트에서 실행한다:  python scripts/build_all.py
"""
import os
import importlib.util
import subprocess
import sys
import time

sys.path.insert(0, "scripts")
import ptd_common as C


# build_all의 10개 단계가 직접 import하는 외부 패키지. 여기서 먼저 확인해
# migrate.py 등의 내부 Traceback보다 설치 방법이 분명한 오류를 보여 준다.
REQUIRED_PACKAGES = (
    ("rdflib", "rdflib"),
    ("docx", "python-docx"),
)


def missing_dependencies():
    return [package for module, package in REQUIRED_PACKAGES
            if importlib.util.find_spec(module) is None]

# migrate.py 가 CSV 를 v2.3 TTL 에서 매번 재생성하므로, 사람 판정(Phase 3)과
# directive 재작성(Phase 4)도 파이프라인 단계로 두어야 재실행에도 재현된다.
# 순서: 정제 → 트리 판정 → 사람 판정(트리 결과를 덮어씀) → 재작성/통합
STEPS = [
    ("migrate.py",          "Phase 0    v2.3 TTL(정본) → v2.4 마스터 CSV"),
    ("clean_directives.py", "결함 C     directive_ko 에서 CSI 사례 원문 제거"),
    ("adjudicate.py",       "Phase 1    결정 트리 판정 + adjudication_report.md"),
    ("phase3_adjudicate.py", "Phase 3    UNSURE 확정 (사람 판정 — 트리 결과 갱신)"),
    ("phase4_rewrite.py",   "Phase 4    CSI 기반 directive 재작성 + TBM 통합"),
    ("derive_cell_types.py", "v3.5       appliesToCellType 유도 (CSV 자체 필드에서)"),
    ("kalis_unadopted.py",  "Phase 1-3  KALIS 미채택 원형 집계"),
    ("build_ttl.py",        "결함 A     v2.3 온톨로지 이월 + CSV → TTL"),
    ("validate.py",         "Phase 0-3  정합성 검사"),
    ("build_docx.py",       "Phase 0-3  CSV → 부록 docx (A4 가로)"),
]

ARTIFACTS = [
    C.MASTER_CSV, C.OUT_TTL, C.OUT_DOCX,
    C.ADJ_REPORT, C.KALIS_UNADOPTED, C.VALIDATE_REPORT, C.MIGRATE_LOG,
    "build/directive_cleanup_log.md",
    "build/phase3_adjudication_log.md",
    "build/directive_rewrite_log.md",
    "build/cell_type_derivation.md",
]


def human(n):
    return "{:,}".format(n)


def main():
    C.ensure_cwd()
    missing = missing_dependencies()
    if missing:
        print("ERROR: build_all.py 실행에 필요한 Python 패키지가 없습니다: %s"
              % ", ".join(missing))
        print("현재 Python: %s" % sys.executable)
        print("설치 명령: %s -m pip install -r requirements.txt" % sys.executable)
        print("권장 Python: C:\\Users\\USER\\anaconda3\\python.exe")
        return 2
    C.ensure_build()
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    failed = []

    for script, desc in STEPS:
        path = os.path.join("scripts", script)
        print("")
        print("=" * 70)
        print("▶ %-20s %s" % (script, desc))
        print("=" * 70)
        sys.stdout.flush()
        t0 = time.time()
        rc = subprocess.call([sys.executable, path], env=env)
        dt = time.time() - t0
        sys.stdout.flush()
        if rc != 0:
            failed.append((script, rc))
            print("  ⚠ %s 종료코드 %d (%.1fs) — 계속 진행" % (script, rc, dt))
        else:
            print("  ✓ %s 완료 (%.1fs)" % (script, dt))

    print("")
    print("=" * 70)
    print("파이프라인 완료 — 산출물")
    print("=" * 70)
    missing = []
    for p in ARTIFACTS:
        if os.path.exists(p):
            print("  ✓ %-44s %10s bytes" % (p, human(os.path.getsize(p))))
        else:
            print("  ✗ %-44s %10s" % (p, "없음"))
            missing.append(p)

    print("")
    if failed:
        print("실패 단계 : %s" % ", ".join(s for s, _ in failed))
        return 1
    if missing:
        print("누락 산출물 : %s" % ", ".join(missing))
        return 1
    print("전 단계 통과 — 오류 없음")
    return 0


if __name__ == "__main__":
    sys.exit(main())
