# -*- coding: utf-8 -*-
"""기준값 — 사용자 원칙의 숫자(본문 크기·표 글자 차이·간격·자간 범위 등)를 assets/profile.json 한 곳에서 읽는다.

다른 부서·기관은 이 파일만 고쳐 쓴다(평가 2026-11-08 '기준값이 코드 상수 — 공용이 되는 최소 조건'). 파일이 없거나 항목이
빠지면 아래 DEFAULTS(지금까지 쓰던 값)를 쓴다. 다른 파일을 쓰려면 환경 변수 GONGYONG_PROFILE에 그 경로를 준다.
항목은 {"값": 14, "뜻": "…"} 꼴(뜻은 사람이 읽는 설명) 또는 숫자 하나.
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
PATH = os.environ.get("GONGYONG_PROFILE") or os.path.join(HERE, "..", "assets", "profile.json")

DEFAULTS = {
    "body_pt": 14,                  # 표 글자의 기준인 본문 글자 크기(pt)
    "table_gap_pt": 3,              # 표 글자 = 본문보다 이만큼 작게
    "table_min_pt": 10,             # 표를 한 장에 넣으려고 줄일 때 하한
    "table_title_up_pt": 1,         # ■ 표 제목 = 표 글자보다 이만큼 크게
    "table_title_mark_down_pt": 2,  # ■ 기호만 제목 글자보다 이만큼 작게
    "table_title_prev_pt": 6,       # ■ 표 제목 위 간격
    "table_title_prev_text_pt": 11,  # ■ 표 제목 바로 위가 글 줄이면 위 간격
    "table_title_next_pt": 3,       # 단위 줄이 없을 때 ■ 제목 아래 간격
    "table_title_line_pct": 75,     # ■ 표 제목 줄 간격(%)
    "table_after_mm": 2,            # 표 뒤가 □ 사이 빈 줄이면 표 아래 여백
    "table_note_gap_mm": 2,         # 표와 바로 밑 ※ 사이
    "table_note_smaller_pt": 1,     # 표 밑 ※·* 설명 = 표 글자보다 이만큼 작게
    "table_unit_smaller_pt": 2,     # 표 위 기준·단위 줄 = 표 글자보다 이만큼 작게
    "money_pad_mm": 1.5,            # 금액·수량 칸 오른쪽 띄움
    "line_min_pct": 140,            # 쪽 맞춤이 줄 간격을 낮출 때 하한(%)
    "line_max_pct": 190,            # 쪽 맞춤이 줄 간격을 넓힐 때 상한(%)
    "spacing_min_pct": -18,         # 자간 하한(%) — 줄 맞춤에서 줄일 때
    "spacing_max_pct": 5,           # 자간 상한(%) — 줄 맞춤에서 늘릴 때
    "note_smaller_pt": 2,           # 본문 * 풀이·※ 참고 = 바로 위 문단보다 이만큼 작게
    "note_gap_pt": 3,               # 그 문단 아래 간격 하한
    "paren_smaller_pt": 2,          # 부연설명 괄호 = 이만큼 작게(계획 paren_small로 문서마다 바꿈)
    "square_smaller_pt": 2,         # □ 기호만 뒤 글자보다 이만큼 작게
    "date_gap_pt": 1,               # 날짜·부서 줄 아래(요약 상자 위) 간격
}


def _load():
    d = dict(DEFAULTS)
    try:
        with open(PATH, encoding="utf-8-sig") as f:  # 메모장 저장본(BOM 붙음)도 읽게
            raw = json.load(f)
    except FileNotFoundError:
        return d
    except ValueError as e:
        raise SystemExit(f"기준값 파일({PATH})이 JSON 모양이 아닙니다: {e}")
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        if k not in DEFAULTS:
            raise SystemExit(f"기준값 파일에 모르는 항목 ‘{k}’ — 쓸 수 있는 것: {', '.join(DEFAULTS)}")
        if isinstance(v, dict):
            v = v.get("값")
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise SystemExit(f"기준값 ‘{k}’는 숫자여야 합니다(받은 값: {v!r}).")
        d[k] = v
    return d


P = _load()
