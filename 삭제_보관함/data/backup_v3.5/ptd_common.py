# -*- coding: utf-8 -*-
"""PtD v2.4 파이프라인 공용 모듈 — 42열 스키마, 경로, 어휘 매핑.

경로는 전부 작업 디렉터리(저장소 루트) 기준 상대경로다.
스크립트는 루트에서 실행한다:  python scripts/build_all.py
"""
import io
import os

# ── 경로 (상대경로만 사용)
SRC_TTL = "ptd_library_v2.3.ttl"
SRC_KALIS_CAND = "PtD_Library_KALIS_Candidates.csv"
SRC_KALIS_PROFILE = "국토안전관리원_위험요소프로파일_20250923.csv"
SRC_DOCX_REF = "Appendix_PtD_Library_v2.3.docx"

BUILD = "build"
SCRIPTS = "scripts"

MASTER_CSV = "build/ptd_library_master_v2.4.csv"
OUT_TTL = "build/ptd_library_v2.4.ttl"
OUT_DOCX = "build/Appendix_PtD_Library_v2.4.docx"
ADJ_REPORT = "build/adjudication_report.md"
KALIS_UNADOPTED = "build/kalis_unadopted_summary.csv"
VALIDATE_REPORT = "build/validate_report.txt"
MIGRATE_LOG = "build/migrate_log.txt"

PROFILE_ENCODING = "cp949"      # 원본 (검증: 0xc2dc='시')
OUTPUT_ENCODING = "utf-8-sig"

PTD_NS = "http://construction-safety.org/ptd-hoc-ontology#"


def ensure_cwd():
    """루트에서 실행되지 않으면 즉시 실패시킨다 (경로 사고 방지)."""
    if not os.path.exists(SRC_TTL):
        raise SystemExit(
            "[중단] '%s' 를 찾을 수 없습니다. 저장소 루트에서 실행하세요.\n"
            "        예: python scripts/build_all.py" % SRC_TTL)


def ensure_build():
    if not os.path.isdir(BUILD):
        os.makedirs(BUILD)


# --------------------------------------------------------------------------
# 42열 스키마
# --------------------------------------------------------------------------
COLUMNS = [
    # 식별 (5)
    "entry_id", "status", "accident_type", "trade", "scenario_ids",
    # 내용 (4)
    "directive_ko", "hoc_level", "spec", "action_by",
    # 판정 (6)
    "design_decidable", "promoted", "reason_code", "exposure_channel",
    "adjudication_note", "hoc_rule_exception",
    # 전거 (6)
    "source_id", "source_type", "source_edition", "legal_basis",
    "legal_verified_date", "evidence_level",
    # 시뮬레이션 (6)
    "rule_type", "rule_id", "simulation_action", "parameter_value",
    "parameter_source", "sensitivity_target",
    # 관계 (4)
    "supersedes", "redundant_with", "requires", "residual_risk",
    # IFC (4)
    "ifc_class", "ifc_predefined_type", "target_pset", "geometry_operation",
    # 비용·공기 (3)
    "install_cost_level", "install_duration_days", "cost_note",
    # 실험·이력 (4)
    "in_experiment_set", "kalis_frequency", "needs_review", "note",
]
assert len(COLUMNS) == 42, len(COLUMNS)

# --------------------------------------------------------------------------
# 어휘
# --------------------------------------------------------------------------
ACCIDENT_TYPES = ["떨어짐", "무너짐", "물체에맞음", "넘어짐", "끼임", "부딪힘"]
TRADES = ["거푸집설치", "거푸집해체", "타설", "철근", "자재운반"]
HOC_LEVELS = ["위험회피", "제거", "대체", "공학적", "경고", "관리적", "보호구"]
RULE_TYPES = ["SpatialChangeRule", "TemporalRule", "AgentParameterRule"]
EXPOSURE_CHANNELS = ["dwell_time", "passage_count", "zone_occupancy",
                     "proximity", "none"]
REASON_CODES = ["NOT_DESIGN", "NO_EXPOSURE", "NO_CHANNEL"]
SOURCE_TYPES = ["지침", "기술기준", "법령", "공공데이터", "학술", "사고데이터"]
EVIDENCE_LEVELS = ["official_data", "guideline", "standard",
                   "systematic_review", "heuristic"]
PARAM_SOURCES = ["literature", "official_data", "heuristic",
                 "design_change", "schedule_logic"]

# HoC × rule_type 대응은 '검증 대상 가설'이지 제약이 아니다 (지시서 §5).
# 아래는 예상 대응일 뿐이며, 어긋나도 ERROR 가 아니라 INFO 로 기록만 한다.
HOC_EXPECT_STRUCTURAL = {"위험회피", "제거", "대체"}   # Spatial/Temporal 예상
HOC_EXPECT_PARAMETRIC = {"경고", "관리적", "보호구"}   # AgentParameter 예상
HOC_EXPECT_EITHER = {"공학적"}

# 알려진 예외 3건 — 분류를 바꾸지 않고 사유만 기록한다 (지시서 §5).
KNOWN_HOC_EXCEPTIONS = {
    "KE_T_CP_03": "출입통제는 관리적이나 작용 기제는 우회 동선 생성(공간적). "
                  "둘 다 옳음 — 분류 유지.",
    "KE_K_FS_02": "도면 명기는 관리적이나 작용 기제는 해체 가능 시점 이동(시간적). "
                  "둘 다 옳음 — 분류 유지.",
    "KE_T_HS_04": "작업발판 일체형 거푸집은 분명한 대체급이므로 HoC 유지. 다만 "
                  "계수(휴리스틱)로 대신 작성된 것이므로 규칙 쪽이 잠정적 — "
                  "가설물 형상 확보 시 SpatialChangeRule 로 재작성.",
}

ACC_URI_TO_KO = {
    "ACC_Fall": "떨어짐", "ACC_Collapse": "무너짐", "ACC_HitByObj": "물체에맞음",
    "ACC_Trip": "넘어짐", "ACC_Caught": "끼임", "ACC_Struck": "부딪힘",
    "ACC_Pierce": "찔림",
}
TRADE_URI_TO_KO = {
    "TRD_FormworkErection": "거푸집설치", "TRD_FormworkStripping": "거푸집해체",
    "TRD_ConcretePour": "타설", "TRD_Rebar": "철근",
    "TRD_MaterialHandling": "자재운반",
}
HOC_URI_TO_KO = {
    "RiskAvoidance": "위험회피", "Elimination": "제거", "Substitution": "대체",
    "EngineeringControls": "공학적", "WarningSystems": "경고",
    "AdministrativeControls": "관리적", "PPE": "보호구",
}
HOC_KO_TO_URI = {v: k for k, v in HOC_URI_TO_KO.items()}

KALIS_TRADE_TO_KO = {
    "거푸집 설치": "거푸집설치", "거푸집 해체": "거푸집해체", "타설": "타설",
    "철근": "철근", "자재 운반": "자재운반", "자재운반": "자재운반",
    "자재 운반·야적": "자재운반",
}

PARAM_SOURCE_MAP = {
    "heuristic": "heuristic",
    "design_change": "design_change",
    "schedule_logic": "schedule_logic",
    "literature": "literature",
    "official_data": "official_data",
}

# Reference.evidenceLevel → (source_type, evidence_level)
# 목표 열거형에 명확히 대응할 때만 evidence_level 을 채운다.
REF_LEVEL_MAP = {
    "law":                 ("법령", ""),
    "official_data":       ("공공데이터", "official_data"),
    "official_statistics": ("사고데이터", "official_data"),
    "guideline":           ("지침", "guideline"),
    "systematic_review":   ("학술", "systematic_review"),
    "literature":          ("학술", ""),
}

CITATION_TYPE_PATTERNS = [
    ("기술기준", ["ANSI", "ASSP", "Z590", "ISO ", "KS ", "BS ", "EN 1", "기술기준"]),
    ("지침",     ["Sourcebook", "Guide", "Guidance", "Handbook", "NIOSH", "OSHA",
                  "CPWR", "지침", "매뉴얼", "안전보건공단", "KOSHA"]),
    ("사고데이터", ["FACE", "재해조사", "사고사례", "중대재해"]),
    ("공공데이터", ["공공데이터", "국토안전관리원", "통계"]),
]

# v2.4 범위 제외 (찔림 계열)
PIERCE_EXCLUDE_ENTRIES = {"KE_K_PI_01"}          # CSV 행으로 존재하는 유일 항목
PIERCE_EXCLUDE_ENTITIES = {                       # 온톨로지 개체 (행 없음)
    "ACC_Pierce", "H010_ExposedRebar", "LCR_EXPOSED_REBAR",
    "SCN_20", "CELL_Pierce_Rebar",
}
EXCLUDE_NOTE = "v2.4 범위 제외"

# 미구현 위험 채널 (implementationStatus=planned)
UNIMPLEMENTED_HAZARDS = {
    "H008_ShoringCollapse": "동바리 붕괴",
    "H009_DropZone": "낙하 영향구역",
    "H011_EquipmentCorridor": "장비 동선",
}


def blank_row():
    return dict((c, "") for c in COLUMNS)


def uri_frag(node):
    s = str(node)
    return s.split("#")[-1] if "#" in s else s


def join_ids(ids):
    seen, out = set(), []
    for x in ids:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return ";".join(out)


def read_master():
    import csv
    with io.open(MASTER_CSV, encoding=OUTPUT_ENCODING, newline="") as f:
        return list(csv.DictReader(f))


def write_master(rows):
    import csv
    ensure_build()
    with io.open(MASTER_CSV, "w", encoding=OUTPUT_ENCODING, newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="raise")
        w.writeheader()
        w.writerows(rows)
