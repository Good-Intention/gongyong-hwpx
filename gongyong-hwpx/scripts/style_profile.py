# -*- coding: utf-8 -*-
"""기준값 — 사용자 원칙의 숫자(본문 크기·표 글자 차이·간격·자간 범위 등)를 assets/profile.json 한 곳에서 읽는다.

다른 부서·기관은 이 파일만 고쳐 쓴다(평가 2026-11-08 '기준값이 코드 상수 — 공용이 되는 최소 조건'). 파일이 없거나 항목이
빠지면 아래 DEFAULTS(지금까지 쓰던 값)를 쓴다. 다른 파일을 쓰려면 환경 변수 GONGYONG_PROFILE에 그 경로를 준다.
항목은 {"값": 14, "뜻": "…"} 꼴(뜻은 사람이 읽는 설명) 또는 숫자 하나. 기관 항목(org_* — 표지 슬로건·마크 그림, 전화 앞자리,
공문 시스템 이름)은 글이다(아래 TEXT_DEFAULTS).
"""
import json
import os
import re
import sys

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
    "line_fill_pct": 3,             # 한 줄·끝 줄을 끝선까지 채울 때 자간을 늘리는 한도(%p), 0이면 끔
    "note_smaller_pt": 2,           # 본문 * 풀이·※ 참고 = 바로 위 문단보다 이만큼 작게
    "note_gap_pt": 3,               # 그 문단 아래 간격 하한
    "paren_smaller_pt": 2,          # 부연설명 괄호 = 이만큼 작게(계획 paren_small로 문서마다 바꿈)
    "square_smaller_pt": 2,         # □ 기호만 뒤 글자보다 이만큼 작게
    "date_gap_pt": 1,               # 날짜·부서 줄 아래(요약 상자 위) 간격
}


# 기관 항목(글) — 다른 기관도 같은 스킬을 쓰게(사용자 2026-11-11 '다른 기관 공용'). 기본값은 지금까지 쓰던 대구시 값이다.
#   그림 항목: "" = 기본 양식 그림 그대로(대구시), "없음" = 빼기(슬로건만), 파일 경로 = 그 그림으로 바꾸기(이 파일 폴더 기준 또는 전체 경로)
TEXT_DEFAULTS = {
    "org_slogan_image": "",         # 표지 맨 위 슬로건 그림(기본 양식 19번)
    "org_mark_image": "",           # 표지 아래 기관 마크 그림(기본 양식 22번) — "없음"은 받지 않음(표지 자리 잡기의 기준)
    "org_header_image": "",         # 머리말 오른쪽 위 슬로건 띠 그림(표지 뺀 모든 쪽)
    "org_phone_prefix": "053-803",  # 날짜·부서 줄 사무실 전화 앞자리(예시·자리표시)
    "org_paste_system": "온나라",    # 여백 안내에서 붙여 넣을 공문 시스템 이름 — ""이면 그 안내 문장을 뺌
    "doc_note": "",                 # 만든 문서의 문서 정보 '기타' 칸에 판 표시 한 줄 — "" = 남김, "없음" = 남기지 않음
}
NO_IMAGE = "없음"

# 값의 범위 — 벗어나면 알리고 기본값(자간 하한 12처럼 틀린 값이 말없이 자간 줄이기를 끄던 것, 평가 2026-11-09)
RANGES = {"spacing_min_pct": (-50, 0), "spacing_max_pct": (0, 20), "line_fill_pct": (0, 20), "line_min_pct": (50, 400), "line_max_pct": (50, 400),
          "table_title_line_pct": (50, 400), "body_pt": (6, 40), "table_min_pt": (6, 40)}


# 정수만 받는 항목 — 도구가 이 값부터 한 칸(1%·1pt)씩 올리내리며 맞는 값을 찾는다
WHOLE = {"spacing_min_pct", "spacing_max_pct", "line_fill_pct", "line_min_pct", "line_max_pct", "table_title_line_pct",
         "table_min_pt"}


def _warn(msg):
    try:
        print("기준값 알림: " + msg, file=sys.stderr)
    except (OSError, UnicodeError):
        pass


def _load():
    d = dict(DEFAULTS, **TEXT_DEFAULTS)
    try:
        with open(PATH, encoding="utf-8-sig") as f:  # 메모장 저장본(BOM 붙음)도 읽게
            raw = json.load(f)
    except FileNotFoundError:
        return d
    except ValueError as e:
        raise SystemExit(f"기준값 파일({PATH})이 JSON 모양이 아닙니다: {e}")
    if not isinstance(raw, dict):
        _warn(f"기준값 파일({PATH})은 {{ \"항목\": 값 }} 꼴이어야 합니다 — 기본값으로 진행합니다.")
        return d
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        if k not in DEFAULTS and k not in TEXT_DEFAULTS:
            raise SystemExit(f"기준값 파일에 모르는 항목 ‘{k}’ — 쓸 수 있는 것: {', '.join(list(DEFAULTS) + list(TEXT_DEFAULTS))}")
        if isinstance(v, dict):
            v = v.get("값")
        if k in TEXT_DEFAULTS:
            if not isinstance(v, str):
                raise SystemExit(f"기준값 ‘{k}’는 글(따옴표 안)이어야 합니다(받은 값: {v!r}).")
            v = v.strip()
            if k == "org_mark_image" and v == NO_IMAGE:
                _warn("‘org_mark_image’는 ‘없음’을 받지 않습니다(표지 자리 잡기의 기준) — 기관 마크 그림 파일을 주거나 표지를 쓰지 마세요. 기본 그림을 씁니다.")
                continue
            if k == "org_phone_prefix" and v and not re.fullmatch(r"0\d{1,2}-\d{3,4}", v):
                _warn(f"‘org_phone_prefix’ 값 ‘{v}’은 ‘053-803’ 꼴(지역 번호-국번)이 아니라 기본값을 씁니다.")
                continue
            if k == "doc_note" and v not in ("", NO_IMAGE):
                _warn(f"‘doc_note’ 값 ‘{v}’은 쓸 수 없습니다 — 비우면 남기고 ‘없음’이면 남기지 않습니다. 기본값(남김)을 씁니다.")
                continue
            d[k] = v
            continue
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            raise SystemExit(f"기준값 ‘{k}’는 숫자여야 합니다(받은 값: {v!r}).")
        lo, hi = RANGES.get(k, (0, 1000))
        if not lo <= v <= hi:  # 범위 먼저 — 끝없이 큰 값(1e309)·숫자 아님(NaN)도 여기서 걸러진다
            _warn(f"‘{k}’ 값 {v:g}은 쓸 수 있는 범위({lo:g}~{hi:g}) 밖이라 기본값 {DEFAULTS[k]:g}을 씁니다.")
            continue
        if k in WHOLE:  # 한 칸씩 올리내리며 찾는 값 — 소수면 파이썬 오류로 멈췄음(검토 2026-11-12: 140.5 → TypeError)
            if v != round(v):
                _warn(f"‘{k}’ 값 {v:g}은 소수라 가까운 정수 {round(v)}로 씁니다(이 항목은 정수만).")
            v = int(round(v))
        d[k] = v
    return d


P = _load()


def org_image(key):
    """기관 그림 항목의 뜻: None = 기본 양식 그림 그대로, NO_IMAGE = 빼기, 그 밖 = 그림 파일 전체 경로(기준값 파일 폴더 기준)."""
    v = P.get(key) or ""
    if not v:
        return None
    if v == NO_IMAGE:
        return NO_IMAGE
    return v if os.path.isabs(v) else os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(PATH)), v))
