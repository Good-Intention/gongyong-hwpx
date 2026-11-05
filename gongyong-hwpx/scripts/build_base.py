# -*- coding: utf-8 -*-
"""문서 만들기(build.py)의 상수·공통 함수·BuildError. 네 파일(build_fill·build_rules·build)이 함께 쓴다.

쓰는 법:
    python build.py --template 견본.hwpx --plan plan.json --out 결과.hwpx

계획 파일 모양(자세한 것은 references/plan-format.md):
    {"title": "문서 제목(파일 속성)",
     "blocks": [
        {"like": 0, "text": "○○ 추진 계획(안)"},                 # 견본 0번 문단 모양으로 글 넣기
        {"like": 5, "text": "추진 배경"},                        # 머리 기호(□ 등)는 견본 것을 그대로 붙임
        {"like": 6, "text": "**(현황)** 안내판 노후화 심화"},    # **…**는 견본 문단의 굵은 조각 모양
        {"like": 6, "runs": [["  ○ ", 0], ["(현황)", 1], [" 내용", 2]]},  # 조각 모양을 직접 고름
        {"like": 12, "table": [["구분", "현행"], ["대상", "100곳"]]},      # 표: 줄을 늘리거나 줄임
        {"like": 15, "cells": {"0,0": "참고1", "0,2": "세부 현황"}, "page_break": true},
        {"like": 2}                                              # 견본 문단 그대로(빈 줄 등)
     ]}
견본에 없는 서식은 만들지 않는다. 모양은 늘 견본 문단에서 온다.
"""
import argparse
import copy
import json
import math
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hwpx_lib import (HWPUNIT_PER_MM, UNIT_RE, T, HeaderEdit, Package, Styles, _base_head, blank_png,  # noqa: E402
                      etree,
                      cell_paras,
                      drop_linesegs, indexed_runs, is_blank, is_struct, label_colon, label_content, marker_level, new_id,
                      page_info, para_pics, para_runs, para_tables, para_text, run_objects, run_text, set_run_text, space_colons,
                      split_marker,
                      table_grid, TABLE_TITLE_MARK, is_table_title)
from check import check, print_report  # noqa: E402
from fit import ARROWS, Fitter, cover_end  # noqa: E402
from layout import FW_EM, Layout, Metrics  # noqa: E402

# **굵게**, ^^위 첨자^^ 표시(견본 문단의 굵은 조각·위 첨자 조각 모양을 빌려 씀).
# 위 첨자는 낱말 풀이 *와, 줄임말 바로 뒤에 붙이는 원래 이름(유가보조금^^유류세연동보조금^^)에 쓴다.
MARKUP_RE = re.compile(r"(\*\*.+?\*\*|\^\^.+?\^\^)", re.S)
FW = "⎵"  # 고정폭 빈칸(1/4 글자, 양쪽 정렬 때 늘어나지 않음)
# 항목 첫머리의 괄호 이름표: (현황), **(문제점)** …
LABEL_RE = re.compile(r"^(?P<b1>\*\*)?\((?P<core>[^()\n]{1,12})\)(?P<b2>\*\*)?(?P<gap>[ ⎵]*)")
# 작대기(-) 줄의 두 글자 항목명 + 쌍점('교체 : …') — 세 글자 폭으로 늘린다
DASH_HEAD_RE = re.compile(r"^(?P<b1>\*\*)?(?P<core>[가-힣]{2})(?P<b2>\*\*)?(?=[ ⎵]*:(?!\d))")
QUOTES = "’”‘“"  # 휴먼명조 등에서 한 글자 폭이라 벌어져 보이는 따옴표
OPEN_QUOTES = "‘“"
# 낫표·가운데점도 휴먼명조에서는 한 글자 폭이라 벌어져 보인다(한글 2024, 60pt 실측 2026-11-01): 「는 표시가 칸 오른쪽
# (왼쪽이 빔), 」는 왼쪽(오른쪽이 빔), ·ㆍ는 가운데(양쪽이 빔). 표시 자리를 잰 글꼴만 좁힌다.
TIGHT_FONTS = {"휴먼명조"}
NL = "\n"
IMAGE_MAX_PX = 1200       # 표 칸 배경 그림: 긴 변을 이 화소까지 줄임(인쇄 A4 칸에 충분, 용량 줄이기 — 사용자 원칙 2026-11-01)
IMAGE_JPEG_QUALITY = 82


def _png_jpeg_size(data):
    """PNG·JPEG 바이트에서 (가로, 세로) 화소. 모르면 (0, 0)."""
    import struct
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return struct.unpack(">II", data[16:24])
    if data[:2] == b"\xff\xd8":
        i = 2
        while i + 9 < len(data):
            marker, size = data[i + 1], struct.unpack(">H", data[i + 2:i + 4])[0]
            if marker in (0xC0, 0xC1, 0xC2):
                h, w = struct.unpack(">HH", data[i + 5:i + 9])
                return w, h
            i += 2 + size
    return 0, 0
BASIS_TITLE_RE = re.compile(r"근\s*거|관계\s*법|관련\s*법")  # 근거법령 장·□ 제목
# 부연설명 검사(basis_notes)는 제목이 근거법령 그 자체일 때만('산출근거'·'추진근거 및 경과'는 아님)
BASIS_LAW_TITLE_RE = re.compile(r"^(근\s*거\s*(법\s*령|법\s*규|규\s*정)?|관\s*[계련]\s*법\s*[령규]|법\s*적\s*근\s*거)\s*$")
BASIS_RE = re.compile(r"근\s*거|법\s*령|법\s*적|관계\s*법|관련\s*법")  # 근거법령 ○의 괄호 이름표
# 출력 두 등급: 계획을 고쳐야 하는 알림(고쳐야 함)과 도구가 한 일의 기록(알림) — 중요한 것이 묻히지 않게(검수 2026-11-01)
SUMMARY_END_RE = re.compile(r"(고자\s*함|보고임)\s*\.?$")  # 요약 상자 끝맺음 ~하고자 함·~줄이고자 함·~에 대한 보고임(사용자 원칙 2026-11-01)
FIX_RE = re.compile(r"근거법령이 없|‘~으로’로 끝나는|한 열에 세 가지 정보|요약 상자에는|요약 상자 끝맺음|끝 줄에 한두 낱말만|한 줄 줄이기 후보|항목 수 —|두 쪽에 걸친|칸보다 긴 낱말|줄여도 다음 줄로 넘어가는|빈칸이 크게 벌어지는 줄이 남은|"
                    r"견본 문단은 '|굵은 조각이 없어|위 첨자 조각이 없어|넣지 못했습니다|다 들어가지 않을 수 있습니다|"
                    r"날짜·부서 줄이 없습니다|근거법령에는 부연설명|표 제목이 없습니다|표 제목이 한 줄을 넘")
# 날짜·부서 줄: ’26. 10. 30.(금) / 2026. 10. 30. / ’26. ○. ○.(○)로 시작하는 문단
DATE_NEXT = 1 * 100  # 날짜·부서 줄 아래(요약 상자 위) 간격 1pt(사용자 2026-11-05 '부서 이름 행의 아래에 공간을 조금 1pt 정도')
DATE_LINE_RE = re.compile(r"^[ \t⎵]*(?:[’']\s*[\d○]{2}|(?:19|20)\d{2})\.\s*[\d○]{1,2}\.\s*[\d○]{1,2}\.")
MID_DOTS = "·ㆍ"
NOTE_STAR_PT = 2        # * 풀이는 설명하는 글보다 이만큼(pt) 작게(사용자 원칙 2026-11-02)
SQUARE_DOWN = 2         # □ 큰 항목 기호만 뒤 글자보다 이만큼(pt) 작게(사용자 2026-11-04 '□도 줄이기')
NOTE_REF_PT = 2         # 본문 ※ 참고도 2pt 작게(사용자 원칙 2026-11-02 v1.1 — 표 밑 ※는 표 글자보다 1pt, fit)
NOTE_STAR_GAP = 300     # 본문 *·※ 설명 문단 아래 간격 하한(HWPUNIT, 3pt)
FLOW_PT = 11  # 투명 선 도표(flow) 상자 글 크기(pt)
FLOW_ARROW_PT = 16  # 도표 화살표: 굵게, 이 크기(사용자 의견 2026-11-01)
FLOW_TITLE_PT = 12  # 도표 위 제목(예: ○○○ 신청절차): 굵게
# 도표 상자 모양(디자인 검토 권고 2026-11-01 — 정사각형 대신 가로로 긴 상자, 쪽의 가로 띠 리듬에 맞춤)
FLOW_BOX_H_MM = 14  # 상자 높이: 글 1~2줄(제목 상자 높이와 같음), 한 줄 늘 때마다 5mm
FLOW_BOX_MAX_MM = 42  # 상자 너비 상한(2~3칸 도표가 늘어져 보이지 않게, 이때는 가운데)
FLOW_BOX_MIN_MM = 26  # 한 줄 상자 너비 하한 — 이보다 좁으면 두 줄로
FLOW_GAP_MM = 10  # 상자 사이 화살표 칸 폭
FLOW_ROW_GAP_MM = 5  # 두 줄 도표의 줄 사이(둘째 줄도 왼쪽 → 오른쪽, 아래 화살표 없음)
FLOW_PAD_MM = 2  # 상자 안 좌우 여백
FLOW_LINE = 140  # 상자 안 줄 간격(%)
FLOW_ROW_MAX = 5  # 상자가 이보다 많으면 두 줄로(둘 다 왼쪽 → 오른쪽)
# '~로'로 끝나도 조사가 아닌 낱말(도로·경로·그대로·서로 …) — '~으로' 끝맺음 검사에서 뺀다
LO_WORDS = ("도로", "경로", "진로", "통로", "회로", "항로", "선로", "철로", "수로", "미로", "기로", "공로", "과로", "활주로",
            "대로", "따로", "별로", "새로", "서로", "날로", "절로", "홀로", "스스로", "실로", "주로", "비로")
# '약 900대'처럼 숫자를 꾸미는 말과 숫자 사이는 묶음 빈칸(⍽)으로: 줄이 바뀌어도 둘이 떨어지지 않는다
NUMWORD_RE = re.compile(r"(?<![가-힣])(약|총|최대|최소|각|매|연|월|일|제) (?=[0-9’])")
# 부연설명이 아닌 괄호: 이름의 일부 (안)·(가칭), 날짜 뒤 요일 (금)
SKIP_PAREN_RE = re.compile(r"\((안|가칭|[월화수목금토일])\)")


ROMAN = "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ"
HANGUL_NUM = "가나다라마바사아자차카타파하"
CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳"
# 번호 갈래(위 갈래가 나오면 아래 갈래 번호는 1부터 다시)
FAMILIES = ["roman", "num.", "han.", "num)", "han)", "(num)", "(han)", "circled"]


def number_family(mark):
    """번호 머리 기호의 갈래: Ⅰ. → roman, 1. → num., 가. → han., 1) → num), (1) → (num), ① → circled."""
    if not mark:
        return None
    if mark[0] in ROMAN:
        return "roman"
    if mark[0] in CIRCLED:
        return "circled"
    m = re.fullmatch(r"(\()?(\d{1,2}|[가-하])([.)])", mark)
    if not m:
        return None
    kind = "num" if m.group(2).isdigit() else "han"
    if m.group(1):
        return f"({kind})"
    return f"{kind}{m.group(3)}"


def number_mark(family, n, sample):
    """갈래의 n번째 번호를 견본 기호 모양대로 만든다."""
    if family == "roman":
        return ROMAN[(n - 1) % len(ROMAN)] + "."
    if family == "circled":
        return CIRCLED[(n - 1) % len(CIRCLED)]
    val = str(n) if family.startswith(("num", "(num")) else HANGUL_NUM[(n - 1) % len(HANGUL_NUM)]
    return re.sub(r"\d{1,2}|[가-하]", val, sample, count=1)


def spread(core, n):
    """이름표 글자 사이에 고정폭 빈칸 n개를 고르게 더한다(이미 있는 빈칸은 그 자리에 둔다).
    현황 + 4 → 현⎵⎵⎵⎵황, 문제점 + 4 → 문⎵⎵제⎵⎵점.
    이어진 영문·숫자(AI·CCTV·3D)는 한 덩어리로 두고 벌리지 않는다(A I 한 계 → AI⎵⎵한⎵⎵계)."""
    if n <= 0:
        return core
    letters, gaps_now = [], []
    for ch in core:
        if ch == FW and letters:
            gaps_now[-1] += 1
        elif ch != FW:
            if (letters and gaps_now[-1] == 0 and ch.isascii() and ch.isalnum()
                    and letters[-1][-1].isascii() and letters[-1][-1].isalnum()):
                letters[-1] += ch
                continue
            letters.append(ch)
            gaps_now.append(0)
    if len(letters) == 1:
        return FW * (n // 2) + letters[0] + FW * (n - n // 2)
    gaps = len(letters) - 1
    out = ""
    for k in range(gaps):
        share = n // gaps + (1 if k < n % gaps else 0)
        out += letters[k] + FW * (gaps_now[k] + share)
    return out + letters[-1]


class BuildError(Exception):
    pass
