# -*- coding: utf-8 -*-
"""계획 파일(plan.json)대로 견본 문단을 복사해 새 한글 문서(.hwpx)를 만든다.

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
                      table_grid)
from check import check, print_report  # noqa: E402
from fit import Fitter, cover_end  # noqa: E402
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
BASIS_RE = re.compile(r"근\s*거|법\s*령|법\s*적|관계\s*법|관련\s*법")  # 근거법령 ○의 괄호 이름표
# 출력 두 등급: 계획을 고쳐야 하는 알림(고쳐야 함)과 도구가 한 일의 기록(알림) — 중요한 것이 묻히지 않게(검수 2026-11-01)
SUMMARY_END_RE = re.compile(r"(고자\s*함|보고임)\s*\.?$")  # 요약 상자 끝맺음 ~하고자 함·~줄이고자 함·~에 대한 보고임(사용자 원칙 2026-11-01)
FIX_RE = re.compile(r"근거법령이 없|‘~으로’로 끝나는|한 열에 세 가지 정보|요약 상자에는|요약 상자 끝맺음|끝 줄에 한두 낱말만|한 줄 줄이기 후보|항목 수 —|두 쪽에 걸친|칸보다 긴 낱말|줄여도 다음 줄로 넘어가는|빈칸이 크게 벌어지는 줄이 남은|"
                    r"견본 문단은 '|굵은 조각이 없어|위 첨자 조각이 없어|넣지 못했습니다|다 들어가지 않을 수 있습니다|"
                    r"날짜·부서 줄이 없습니다")
# 날짜·부서 줄: ’26. 10. 30.(금) / 2026. 10. 30. / ’26. ○. ○.(○)로 시작하는 문단
DATE_LINE_RE = re.compile(r"^[ \t⎵]*(?:[’']\s*[\d○]{2}|(?:19|20)\d{2})\.\s*[\d○]{1,2}\.\s*[\d○]{1,2}\.")
MID_DOTS = "·ㆍ"
NOTE_STAR_PT = 2        # * 풀이는 설명하는 글보다 이만큼(pt) 작게(사용자 원칙 2026-11-02)
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


class Builder:
    def __init__(self, pkg, base_dir=None):
        self.pkg = pkg
        self.base_dir = base_dir  # 계획 파일이 있는 폴더(그림 파일의 상대 경로 기준)
        self.image_seq = 0
        self.image_cells = set()  # 배경 그림을 넣은 칸(줄 높이를 늘리지 않음 — 비율 유지)
        self.flow_tables = set()  # 투명 선 도표 표(fit이 칸 너비를 다시 나누지 않음)
        self.flow_bottom = {}  # 도표 표 → 맨 아래 빈 줄 칸 크기(뒤가 글 문단이면 높임)
        self.image_aspect = {}  # 배경 그림 칸 → 그림 가로/세로(fit이 칸 너비·줄 높이를 비율에 맞춤)
        self.image_notes = []
        self.styles = Styles(pkg.xml("Contents/header.xml"))
        self.hedit = HeaderEdit(pkg.xml("Contents/header.xml"), self.styles)
        self.metrics = Metrics()
        self.keep_numbers = True
        self.colons = True
        self.sec_names = pkg.sections()
        self.sec = pkg.xml(self.sec_names[0])
        self.protos = [p for p in self.sec if p.tag == T("hp:p")]
        self.warnings = []
        tab = self.sec.find(".//" + T("hp:tab"))
        self.tab_proto = copy.deepcopy(tab) if tab is not None else None
        self.struct_runs = self._collect_struct()

    def warn(self, msg):
        if msg not in self.warnings:
            self.warnings.append(msg)

    # ------------------------------------------------------------ 준비
    def _collect_struct(self):
        """쪽 설정·머리말·꼬리말·쪽 번호가 든 run을 모아 둔다(결과 문서 첫 문단에 그대로 넣음)."""
        out = []
        for p in self.protos:
            for r in para_runs(p):
                if any(is_struct(ch) for ch in r):
                    nr = copy.deepcopy(r)
                    for ch in list(nr):
                        if not is_struct(ch):
                            nr.remove(ch)
                    out.append(nr)
        if not out:
            raise BuildError("견본에서 쪽 설정(secPr)을 찾지 못했습니다. 한글에서 저장한 hwpx가 맞는지 확인하세요.")
        return out

    def clone(self, idx, where):
        if not isinstance(idx, int) or not 0 <= idx < len(self.protos):
            raise BuildError(f"{where}: like {idx!r} — 견본에 그 번호의 문단이 없습니다(0~{len(self.protos) - 1}).")
        p = copy.deepcopy(self.protos[idx])
        first_char = None
        for r in para_runs(p):
            first_char = first_char or r.get("charPrIDRef")
            for ch in list(r):
                if is_struct(ch):
                    r.remove(ch)
            if len(r) == 0:
                p.remove(r)
        if not para_runs(p):
            r = copy.deepcopy(self.struct_runs[0])
            for ch in list(r):
                r.remove(ch)
            if first_char:
                r.set("charPrIDRef", first_char)
            set_run_text(r, "")
            p.insert(0, r)
        drop_linesegs(p)
        return p

    # ------------------------------------------------------------ 글 넣기
    def _mk(self, src_run, text):
        r = copy.deepcopy(src_run)
        for ch in list(r):
            r.remove(ch)
        return set_run_text(r, text, self.tab_proto)

    def fill_text(self, p, text, where, marker=True, cell=False):
        """견본 문단 p(복사본)의 글을 text로 바꾼다. 머리 기호와 조각 모양은 견본 것을 쓴다."""
        if not isinstance(text, str):
            raise BuildError(f"{where}: text는 글(문자열)이어야 합니다.")
        runs = indexed_runs(p)
        lost = sorted({o for r in runs for o in run_objects(r)} - {"tbl"})
        if lost:
            self.warn(f"{where}: 견본 문단의 글 아닌 것({', '.join(lost)})은 빼고 글만 넣었습니다.")
        segs = [(r, run_text(r)) for r in runs]
        full = "".join(t for _, t in segs)
        pre, mark, _ = split_marker(full)
        use_marker = marker and bool(pre)
        body = text
        upre, umark, ubody = split_marker(text)
        swap = None  # 번호(Ⅱ. 2. 나. ②)는 견본 번호 대신 글의 번호를 쓴다
        if use_marker and umark:
            if umark != mark and number_family(umark) and number_family(umark) == number_family(mark):
                swap = (mark, umark)
            elif umark != mark:
                self.warn(f"{where}: 견본 문단은 '{mark}'로 시작하는데 글이 '{umark}'로 시작합니다. "
                          f"견본 기호 '{mark}'를 쓰고 글의 '{umark}'는 뺐습니다. 다른 기호를 원하면 like를 바꾸세요.")
            body = ubody
        plen = len(pre) if use_marker else 0

        new_runs = []
        pos = 0
        body_count = {}
        # ○·- 같은 항목 기호 뒤 빈칸은 고정폭 빈칸으로: 양쪽 정렬 때 늘어나지 않아 괄호·내용이 위아래로 맞는다.
        # 고정폭 빈칸은 1/4 글자라, 보통 빈칸 하나를 그 글꼴의 빈칸 폭만큼의 고정폭 빈칸으로 바꾼다.
        # ※·*·· 뒤 빈칸도(두 줄 이상이면 첫 줄이 양쪽 정렬로 늘어나 ※ 뒤 첫 글자가 다른 ※ 줄과 어긋남 — 사용자 지적 2026-11-01)
        fix_gap = use_marker and (marker_level(pre) in (2, 3) or mark in ("※", "*", "＊", "·", "ㆍ"))
        for r, t in segs:
            start, end = pos, pos + len(t)
            if start < plen:
                take = t[: plen - start]
                if fix_gap and start + len(take) == plen:
                    stripped = take.rstrip(" ")
                    take = stripped + FW * (self._fw_per_space(r) * (len(take) - len(stripped)))
                if swap and swap[0] in take:
                    take = take.replace(swap[0], swap[1], 1)
                    swap = None
                if take:
                    new_runs.append(self._mk(r, take))
            if end > plen:
                body_count[id(r)] = (r, end - max(start, plen))
            pos = end
        cand = list(body_count.values())
        if not cand:  # 견본이 기호만 있거나 빈 문단
            cand = [(segs[-1][0], 0)] if segs else [(para_runs(p)[0], 0)]
        def kind(run):
            ch = self.styles.char.get(run.get("charPrIDRef"), {})
            return "sup" if ch.get("superscript") else ("bold" if ch.get("bold") else "plain")

        plain = [c for c in cand if kind(c[0]) == "plain"]
        normal = max(plain or cand, key=lambda c: c[1])[0]
        bold = next((c[0] for c in cand if kind(c[0]) == "bold"), None)
        sup = next((c[0] for c in cand if kind(c[0]) == "sup"), None)

        if self.keep_numbers:
            body = NUMWORD_RE.sub("\\1\u237d", body)
        if self.colons:
            body = space_colons(body)
        for part in MARKUP_RE.split(body):
            if not part:
                continue
            src = normal
            if part.startswith("**") and part.endswith("**") and len(part) > 4:
                part = part[2:-2]
                if bold is not None:
                    src = bold
                else:
                    self.warn(f"{where}: 견본 문단에 굵은 조각이 없어 **…** 부분을 보통 글씨로 넣었습니다.")
            elif part.startswith("^^") and part.endswith("^^") and len(part) > 4:
                part = part[2:-2]
                if sup is not None:
                    src = sup
                else:
                    self.warn(f"{where}: 견본 문단에 위 첨자 조각이 없어 ^^…^^ 부분을 보통 글씨로 넣었습니다.")
            new_runs.append(self._mk(src, part))
        if not new_runs:
            new_runs.append(self._mk(normal, ""))
        self._replace_runs(p, new_runs)

    def fill_runs(self, p, spec, proto_idx, where):
        src_runs = indexed_runs(self.protos[proto_idx])
        if not isinstance(spec, list) or not spec:
            raise BuildError(f"{where}: runs는 [[글, 조각 번호], …] 목록이어야 합니다.")
        new_runs = []
        for item in spec:
            if not (isinstance(item, list) and len(item) == 2 and isinstance(item[0], str) and isinstance(item[1], int)):
                raise BuildError(f"{where}: runs의 각 항목은 [글, 조각 번호] 모양이어야 합니다: {item!r}")
            text, k = item
            if not 0 <= k < len(src_runs):
                raise BuildError(f"{where}: 조각 번호 {k}가 없습니다(견본 문단 {proto_idx}의 조각은 0~{len(src_runs) - 1}).")
            new_runs.append(self._mk(src_runs[k], text))
        self._replace_runs(p, new_runs)

    def _replace_runs(self, p, new_runs):
        """p의 글 조각(run)을 new_runs로 바꾼다. 표가 든 run은 그대로 둔다."""
        old = indexed_runs(p)
        at = list(p).index(old[0]) if old else len([x for x in p if x.tag == T("hp:run")])
        for r in old:
            p.remove(r)
        for k, r in enumerate(new_runs):
            p.insert(at + k, r)

    # ------------------------------------------------------------ 표
    def fill_cell(self, tc, value, where):
        if value is None:  # 견본 글을 그대로 둠
            return
        if isinstance(value, dict):
            if "image" not in value:
                raise BuildError(f"{where}: 칸 값이 사전이면 {{\"image\": \"그림 파일\"}} 모양이어야 합니다.")
            return self.cell_image(tc, value, where)
        lines = value if isinstance(value, list) else str(value).split("\n")
        protos = cell_paras(tc)
        if not protos:
            raise BuildError(f"{where}: 표 칸 안에 문단이 없습니다.")
        sub = tc.find(T("hp:subList"))
        new_ps = []
        for line in lines:
            _, umark, _ = split_marker(line)
            chosen, marker = None, True
            for cp in protos:
                _, m, _ = split_marker(para_text(cp))
                if umark and m == umark:
                    chosen = cp
                    break
            if chosen is None and not umark:
                chosen = next((cp for cp in protos if not split_marker(para_text(cp))[1]), None)
            if chosen is None:
                chosen, marker = protos[0], bool(umark)
            np = copy.deepcopy(chosen)
            drop_linesegs(np)
            self.fill_text(np, line, where, marker=marker, cell=True)
            new_ps.append(np)
        for cp in protos:
            sub.remove(cp)
        for np in new_ps:
            sub.append(np)

    # ------------------------------------------------------------ 표 칸 배경 그림
    def _image_bytes(self, path, where):
        """그림 파일을 읽어 (바이트, 확장자, 화소 가로, 세로). Pillow가 있으면 긴 변 IMAGE_MAX_PX로 줄이고 용량을 줄인다(사용자
        원칙 2026-11-01): 투명 칸은 흰 바탕(종이색)에 합친 뒤 JPEG와 PNG를 둘 다 만들어 작은 쪽을 쓴다 — 사진은 JPEG,
        색이 단순한 로고·도표는 PNG가 대개 작다(투명 채널만 붙은 8MB 사진 PNG가 PNG로 남아 1.9MB가 되던 것, 실측). 없으면 원본 그대로 넣고 알린다."""
        if not os.path.isabs(path) and self.base_dir:
            path = os.path.join(self.base_dir, path)
        if not os.path.exists(path):
            raise BuildError(f"{where}: 그림 파일을 찾지 못했습니다: {path}")
        try:
            from PIL import Image
        except ImportError:
            Image = None
        if Image is None:
            with open(path, "rb") as f:
                data = f.read()
            w, h = _png_jpeg_size(data)
            self.warn(f"{where}: 그림 라이브러리(Pillow)가 없어 그림을 줄이지 못하고 원본({len(data) // 1024}KB) 그대로 넣었습니다.")
            return data, os.path.splitext(path)[1].lstrip(".").lower() or "png", w, h
        import io
        im = Image.open(path)
        im.load()
        if im.mode in ("RGBA", "LA", "P"):
            rgba = im.convert("RGBA")
            flat = Image.new("RGB", rgba.size, (255, 255, 255))
            flat.paste(rgba, mask=rgba.getchannel("A"))
            im = flat
        else:
            im = im.convert("RGB")
        if max(im.size) > IMAGE_MAX_PX:
            f = IMAGE_MAX_PX / max(im.size)
            im = im.resize((max(1, round(im.size[0] * f)), max(1, round(im.size[1] * f))), Image.LANCZOS)
        jpg, png = io.BytesIO(), io.BytesIO()
        im.save(jpg, "JPEG", quality=IMAGE_JPEG_QUALITY, optimize=True)
        im.save(png, "PNG", optimize=True)
        data, ext = (png.getvalue(), "png") if png.tell() < jpg.tell() else (jpg.getvalue(), "jpg")
        return data, ext, im.size[0], im.size[1]

    def cell_image(self, tc, value, where):
        """칸 바탕을 그림으로 채운다(글자처럼 넣는 그림이 아니라 '셀 배경' — 사용자 원칙 2026-11-01). 칸 높이를 칸 너비 × 그림
        비율로 맞춰 가로세로 비율을 지킨다(한글은 '크기에 맞추어' 채우므로 칸이 비율과 같아야 늘어나지 않음). 칸 글은 비운다."""
        data, ext, w, h = self._image_bytes(str(value["image"]), where)
        if not w or not h:
            raise BuildError(f"{where}: 그림 크기를 읽지 못했습니다(PNG·JPEG만 됩니다).")
        self.image_seq += 1
        item_id = f"cellimg{self.image_seq}"
        href = f"BinData/{item_id}.{ext}"
        self.pkg.data[href] = data
        hpf = self.pkg.xml("Contents/content.hpf")
        man = hpf.find(".//" + T("opf:manifest"))
        it = etree.SubElement(man, T("opf:item"))
        for k, v in (("id", item_id), ("href", href), ("media-type", "image/png" if ext == "png" else "image/jpg"),
                     ("isEmbeded", "1")):
            it.set(k, v)
        tc.set("borderFillIDRef", self.hedit.border_image(tc.get("borderFillIDRef"), item_id))
        sz = tc.find(T("hp:cellSz"))
        cw = int(sz.get("width", "0"))
        if cw:
            sz.set("height", str(int(round(cw * h / w))))
        protos = cell_paras(tc)
        sub_ = tc.find(T("hp:subList"))
        keep = copy.deepcopy(protos[0]) if protos else None
        for cp in protos:
            sub_.remove(cp)
        if keep is not None:
            drop_linesegs(keep)
            self.fill_text(keep, str(value.get("caption", "")), where, marker=False, cell=True)
            sub_.append(keep)
        self.image_cells.add(tc)
        self.image_aspect[tc] = w / h
        self.image_notes.append(f"{len(data) // 1024}KB")

    def fill_table(self, p, block, where):
        tables = para_tables(p)
        if len(tables) != 1:
            raise BuildError(f"{where}: like {block['like']} 문단에는 표가 {len(tables)}개라 표로 채울 수 없습니다.")
        tbl = tables[0]
        grid = table_grid(tbl)
        if "flow" in block:
            self.flow_table(tbl, block, where)
        elif "table" in block:
            self.rebuild_rows(tbl, block, where)
        elif "cells" in block:
            cells = block["cells"]
            if not isinstance(cells, dict):
                raise BuildError(f"{where}: cells는 {{\"줄,칸\": 글}} 모양이어야 합니다.")
            at = {(r, c): tc for r, c, rs, cs, tc in grid}
            for key, val in cells.items():
                try:
                    r, c = (int(x) for x in str(key).split(","))
                except ValueError:
                    raise BuildError(f"{where}: cells의 열쇠 '{key}'는 '줄,칸'(예: \"0,2\") 모양이어야 합니다.")
                if (r, c) not in at:
                    raise BuildError(f"{where}: 칸({r},{c})이 없습니다. 있는 칸: {sorted(at)}")
                self.fill_cell(at[(r, c)], val, f"{where} 칸({r},{c})")
        elif "text" in block:
            if len(grid) != 1:
                raise BuildError(f"{where}: 칸이 {len(grid)}개인 표입니다. \"table\"(줄 목록)이나 "
                                 "\"cells\"({\"줄,칸\": 글})로 채우세요.")
            self.fill_cell(grid[0][4], block["text"], where)

    def flow_table(self, tbl, block, where):
        """도표(단계·흐름)는 그림 도형 대신 표로: 표 선은 모두 투명, 상자 칸만 실선, 상자 사이 칸에 화살표
        (사용자 방식 2026-11-01 — 한글에서 바로 고칠 수 있음). 위·아래 빈 줄은 얇게 두어 앞뒤 글과 띄운다."""
        steps = block["flow"]
        if not isinstance(steps, list) or len(steps) < 2:
            raise BuildError(f"{where}: flow는 상자 글 목록(둘 이상)이어야 합니다: [\"1단계\", \"2단계\", …].")
        arrow = block.get("arrow", "→")
        title = str(block.get("title") or "").strip().strip("<>〈〉 ").strip()
        if title:  # 도표 제목은 '< ○○○ >'로 마감(사용자 의견 2026-11-01)
            title = f"< {title} >"
        n = len(steps)
        forced = block.get("rows")
        if forced not in (None, 1, 2) or (forced == 2 and n < 3):
            raise BuildError(f"{where}: flow의 rows는 1 또는 2(상자 셋 이상일 때)여야 합니다.")
        trs = [tr for tr in tbl if tr.tag == T("hp:tr")]
        total = sum(int(tc.find(T("hp:cellSz")).get("width", "0")) for tc in trs[0] if tc.tag == T("hp:tc"))
        # 상자 모양은 디자인 검토 권고(2026-11-01): 가로로 긴 상자(약 2.5:1) — 높이는 본문 두 줄(14mm) 공통,
        # 너비는 (본문 폭 − 화살표 칸) ÷ 상자 수를 42mm까지. 42mm에 걸리면 가운데, 아니면 본문 폭에 꽉 채움.
        gap, inner = FLOW_GAP_MM * HWPUNIT_PER_MM, 2 * FLOW_PAD_MM * HWPUNIT_PER_MM
        font = next((self.styles.char.get(r.get("charPrIDRef"), {}).get("font") for tc in trs[-1].iter(T("hp:tc"))
                     for cp in cell_paras(tc) for r in para_runs(cp)), None)

        def text_w(line):  # 상자 글 한 줄의 폭(HWPUNIT, FLOW_PT 어림)
            return sum(self.metrics.em(font, ch) for ch in line) * FLOW_PT * 100

        longest = max(text_w(line) for s in steps for line in str(s).split("\n"))

        def box_w(k, lead=0):
            return min((total - (k - 1 + lead) * gap) / k, FLOW_BOX_MAX_MM * HWPUNIT_PER_MM)

        lines = forced or (2 if n > FLOW_ROW_MAX else 1)
        if not forced and lines == 1 and n >= 4 and (
                box_w(n) < FLOW_BOX_MIN_MM * HWPUNIT_PER_MM or longest > box_w(n) - inner):
            lines = 2  # 한 줄이면 상자가 너무 좁거나 상자 글 한 줄이 넘침 → 두 줄
        k = (n + 1) // 2 if lines == 2 else n  # 첫 줄 상자 수
        if lines == 2 and block.get("widths"):
            raise BuildError(f"{where}: 두 줄 도표에는 widths를 쓸 수 없습니다(칸 너비는 도구가 맞춤).")
        # 두 줄이면 둘째 줄 첫 상자 앞에 →를 두고, 그 →의 왼쪽 끝을 윗줄 첫 상자의 왼쪽 선에 맞춘다(사용자 의견
        # 2026-11-01). 둘째 줄은 '→ 글자 폭 + 다른 화살표 옆 빈 폭'(ind)만큼 들어가, → 뒤 빈 폭이 다른 화살표와 같다.
        # 그래서 칸을 [ind | 상자 − ind | ind | 화살표 칸 − ind]씩 잘게 나누고 상자·화살표는 두 칸씩 합친다
        # (빈 칸은 줄마다 이어 합쳐 좁은 칸이 따로 남지 않게 — 한글은 좁은 칸을 저절로 넓힘).
        glyph = sum(self.metrics.em(font, ch) for ch in arrow) * FLOW_ARROW_PT * 100
        ind = min(gap - HWPUNIT_PER_MM, (gap + glyph) / 2)
        extra = ind if lines == 2 and n - k == k else 0  # 아랫줄 상자 수가 윗줄과 같으면 아랫줄이 ind만큼 더 김
        if block.get("widths"):
            widths, w, pad = list(block["widths"]), None, 0
        else:
            w = min((total - (k - 1) * gap - extra) / k, FLOW_BOX_MAX_MM * HWPUNIT_PER_MM)
            pad = (total - k * w - (k - 1) * gap - extra) / 2  # 남는 폭은 양옆 빈 칸으로(도표를 가운데에)
            if lines == 1:
                widths = [w if j % 2 == 0 else gap for j in range(2 * k - 1)]
            else:
                widths = ([ind, w - ind, ind, gap - ind] * k)[:4 * k - 2 + (1 if extra else 0)]
            if pad >= HWPUNIT_PER_MM:
                widths = [pad] + widths + [pad]
            else:
                widths[0] += 2 * pad
                pad = 0
        # 상자 높이: 글 1~2줄이면 14mm, 한 줄 늘 때마다 5mm(3줄 19mm). 한 도표의 상자는 모두 같은 높이.
        width_for_text = (w or total / max(1, 2 * k - 1)) - inner
        n_lines = max(sum(max(1, math.ceil(text_w(line) / width_for_text)) for line in str(s).split("\n"))
                      for s in steps)
        box_h = (FLOW_BOX_H_MM + 5 * max(0, n_lines - 2)) * HWPUNIT_PER_MM
        off = 1 if pad else 0  # 왼쪽 빈 칸이 있으면 도표 칸 번호가 하나씩 밀림
        width_n = len(widths)
        if lines == 1 and width_n != 2 * k - 1 + 2 * off:
            raise BuildError(f"{where}: flow의 widths는 칸 수({2 * k - 1} — 상자·화살표 칸)만큼이어야 합니다.")
        rows, boxes, arrows, spans = [], set(), set(), {}

        def put(r, c, s, is_box, span=1):
            rows[r][c + off] = s
            (boxes if is_box else arrows).add((r, c + off))
            if span > 1:
                spans[(r, c + off)] = span

        if title:
            rows.append([title] + [""] * (width_n - 1))
            spans[(0, 0)] = width_n  # 제목 줄은 한 칸으로 합침
        if not title:  # 위 빈 줄(얇게) — 제목이 있으면 제목 칸 아래 여백이 상자와의 사이(약 3mm)가 됨
            rows.append([""] * width_n)
        rows.append([""] * width_n)
        if lines == 1:
            for j in range(k):
                put(len(rows) - 1, 2 * j, steps[j], True)
                if j:
                    put(len(rows) - 1, 2 * j - 1, arrow, False)
            lead_arrow = None
        else:  # 둘째 줄도 왼쪽 → 오른쪽(아래로 가는 화살표는 쓰지 않음 — 사용자 의견 2026-11-01)
            for j in range(k):  # 윗줄: 상자 = 칸 4j·4j+1, 화살표 = 칸 4j+2·4j+3
                put(len(rows) - 1, 4 * j, steps[j], True, 2)
                if j:
                    put(len(rows) - 1, 4 * j - 2, arrow, False, 2)
            rows.append([""] * width_n)  # 줄 사이
            rows.append([""] * width_n)
            put(len(rows) - 1, 0, arrow, False)  # 첫 상자 앞 →: 왼쪽 끝 = 윗줄 첫 상자 왼쪽 선(칸 왼쪽에 붙임)
            for j, s in enumerate(steps[k:]):  # 아랫줄: 상자 = 칸 4j+1·4j+2, 그 앞 화살표 = 칸 4j−1·4j
                put(len(rows) - 1, 4 * j + 1, s, True, 2)
                if j:
                    put(len(rows) - 1, 4 * j - 1, arrow, False, 2)
            lead_arrow = (len(rows) - 1, off)
        rows.append([""] * width_n)  # 아래 빈 줄
        for r, row in enumerate(rows):  # 빈 칸은 줄마다 이어 합친다(좁은 칸이 따로 남지 않게)
            c = 0
            while c < width_n:
                if (r, c) in spans:
                    c += spans[(r, c)]
                    continue
                if row[c]:
                    c += 1
                    continue
                e = c
                while e < width_n and not row[e] and (r, e) not in spans:
                    e += 1
                if e - c > 1:
                    spans[(r, c)] = e - c
                c = e
        # 화살표·제목은 굵게: 견본 표 머리 줄의 굵은 글자 모양을 빌려(사용자 의견 2026-11-01)
        bold = next((r.get("charPrIDRef") for tc in trs[0].iter(T("hp:tc")) for cp in cell_paras(tc)
                     for r in para_runs(cp) if self.styles.char.get(r.get("charPrIDRef"), {}).get("bold")), None)
        self.rebuild_rows(tbl, {"table": rows, "header_rows": 0, "widths": widths,
                                "body_like": min(1, len(trs) - 1)}, where)
        none = self.hedit.border_lines(tbl.get("borderFillIDRef"), "NONE")
        box = self.hedit.border_lines(tbl.get("borderFillIDRef"), "SOLID")
        tbl.set("borderFillIDRef", none)
        tbl.set("pageBreak", "NONE")  # 제목·상자가 두 쪽으로 갈라지지 않게
        inm = tbl.find(T("hp:inMargin"))
        if inm is not None:  # 상자 안 글이 선에 붙지 않게 위아래 1.2mm
            for key in ("top", "bottom"):
                inm.set(key, str(max(int(inm.get(key, "0")), int(1.2 * HWPUNIT_PER_MM))))
        trs = [tr for tr in tbl if tr.tag == T("hp:tr")]
        for (r, c), span in spans.items():  # 제목 줄·두 줄 도표의 상자: 칸 합치기
            cells = {int(tc.find(T("hp:cellAddr")).get("colAddr")): tc for tc in trs[r] if tc.tag == T("hp:tc")}
            part = [cells[j] for j in range(c, c + span)]
            part[0].find(T("hp:cellSpan")).set("colSpan", str(span))
            part[0].find(T("hp:cellSz")).set("width", str(sum(int(tc.find(T("hp:cellSz")).get("width")) for tc in part)))
            for tc in part[1:]:
                trs[r].remove(tc)

        def size_runs(tc, want, cid_of=None):
            for cp in cell_paras(tc):
                for run in para_runs(cp):
                    cid = (cid_of or run.get("charPrIDRef"))
                    size = self.styles.char.get(cid, {}).get("size", want)
                    run.set("charPrIDRef", self.hedit.char_size(cid, want - size) if size != want else cid)

        first = None if title else 0
        box_rows = {r for r, _ in boxes}
        for r, c, rs, cs, tc in table_grid(tbl):
            tc.set("header", "0")
            tc.set("borderFillIDRef", box if (r, c) in boxes else none)
            sz = tc.find(T("hp:cellSz"))
            if r in box_rows:  # 상자 줄은 모든 칸을 상자 높이로
                sz.set("height", str(int(box_h)))
            if (r, c) in boxes:  # 상자 글은 FLOW_PT, 가운데, 줄 간격 140%, 좌우 안 여백 2mm·위아래 1mm
                size_runs(tc, FLOW_PT)
                for cp in cell_paras(tc):
                    cp.set("paraPrIDRef", self.hedit.para_line(cp.get("paraPrIDRef"), FLOW_LINE))
                sub = tc.find(T("hp:subList"))
                if sub is not None:
                    sub.set("vertAlign", "CENTER")
                cm = tc.find(T("hp:cellMargin"))
                if cm is not None:
                    tc.set("hasMargin", "1")
                    for key, mm in (("left", FLOW_PAD_MM), ("right", FLOW_PAD_MM), ("top", 1), ("bottom", 1)):
                        cm.set(key, str(int(mm * HWPUNIT_PER_MM)))
            elif (r, c) in arrows:
                size_runs(tc, FLOW_ARROW_PT, bold)
                if (r, c) == lead_arrow:
                    for cp in cell_paras(tc):
                        cp.set("paraPrIDRef", self.hedit.para_align(cp.get("paraPrIDRef"), "LEFT"))
                    cm = tc.find(T("hp:cellMargin"))
                    if cm is not None:
                        tc.set("hasMargin", "1")
                        cm.set("left", "0")
                        cm.set("right", "0")
            elif title and r == 0:
                size_runs(tc, FLOW_TITLE_PT, bold)
            elif r in (first, len(rows) - 1):  # 위·아래 빈 줄(글자 4pt, 1.5mm) — 아래 줄은 뒤가 글이면 flow_gaps가 6mm로
                sz.set("height", str(int(1.5 * HWPUNIT_PER_MM)))
                if r == len(rows) - 1:
                    self.flow_bottom.setdefault(tbl, []).append(sz)
                size_runs(tc, 4)
            elif r in box_rows:  # 상자 줄의 빈 칸
                size_runs(tc, FLOW_PT)
            else:  # 두 줄 도표의 줄 사이(얇게)
                size_runs(tc, 4)
                sz.set("height", str(int(FLOW_ROW_GAP_MM * HWPUNIT_PER_MM)))
        self.flow_tables.add(tbl)

    def flow_gaps(self, out):
        """도표 바로 뒤가 글 문단(○ 등)이면 도표 아래를 6mm 띄운다(디자인 검토 권고 2026-11-01).
        빈 줄·표가 뒤따르면 그대로 둔다(한글은 빈 줄 칸을 약 4mm보다 낮게 그리지 않음 — 실측)."""
        for p, nxt in zip(out, out[1:]):
            for tbl in para_tables(p):
                if self.flow_bottom.get(tbl) and not para_tables(nxt) and para_text(nxt).strip():
                    for sz in self.flow_bottom[tbl]:
                        sz.set("height", str(int(6 * HWPUNIT_PER_MM)))

    def rebuild_rows(self, tbl, block, where):
        data = block["table"]
        if not isinstance(data, list) or not all(isinstance(r, list) for r in data):
            raise BuildError(f"{where}: table은 [[칸, 칸, …], …] 줄 목록이어야 합니다.")
        tcols = int(tbl.get("colCnt", "0"))
        want = block.get("cols") or max((len(r) for r in data), default=tcols)
        if want != tcols or block.get("widths"):
            self.reshape_cols(tbl, want, block.get("widths"), where)
        trs = [tr for tr in tbl if tr.tag == T("hp:tr")]
        h = block.get("header_rows", 1 if len(trs) > 1 else 0)
        if not isinstance(h, int) or not 0 <= h <= len(trs):
            raise BuildError(f"{where}: header_rows는 0~{len(trs)} 사이 숫자여야 합니다.")
        body_like = block.get("body_like", min(h, len(trs) - 1))
        last_like = block.get("last_like")
        for name, v in (("body_like", body_like), ("last_like", last_like)):
            if v is not None and not (isinstance(v, int) and 0 <= v < len(trs)):
                raise BuildError(f"{where}: {name}는 견본 표의 줄 번호(0~{len(trs) - 1})여야 합니다.")
        keep_header = bool(block.get("keep_header"))
        rows_out = []
        if keep_header:
            rows_out = [(copy.deepcopy(trs[i]), None) for i in range(h)]
            body_rows = data
        else:
            body_rows = data[h:]
            for i in range(min(h, len(data))):
                rows_out.append((copy.deepcopy(trs[i]), data[i]))
            if len(data) < h:
                raise BuildError(f"{where}: 머리 줄이 {h}줄인데 table에 {len(data)}줄만 있습니다. "
                                 "머리 줄을 견본 그대로 두려면 \"keep_header\": true를 쓰세요.")
        for k, row in enumerate(body_rows):
            src = trs[last_like] if (last_like is not None and k == len(body_rows) - 1) else trs[body_like]
            rows_out.append((copy.deepcopy(src), row))

        for i, (tr, row) in enumerate(rows_out):
            cells = [tc for tc in tr if tc.tag == T("hp:tc")]
            if row is not None:
                is_header = i < h
                for tc in cells:
                    span = tc.find(T("hp:cellSpan"))
                    if not is_header and span is not None and span.get("rowSpan", "1") != "1":
                        raise BuildError(f"{where}: 견본 표의 본문 줄에 세로로 합친 칸이 있어 줄 수를 바꿀 수 없습니다. "
                                         "\"cells\"로 칸만 채우세요.")
                if len(row) > len(cells):
                    raise BuildError(f"{where}: {i + 1}번째 줄은 칸이 {len(cells)}개인데 글이 {len(row)}개입니다.")
                for k, tc in enumerate(cells):
                    self.fill_cell(tc, row[k] if k < len(row) else "", f"{where} {i + 1}번째 줄 {k + 1}번째 칸")
            for tc in cells:
                drop_linesegs(tc)
                tc.find(T("hp:cellAddr")).set("rowAddr", str(i))
        for tr in trs:
            tbl.remove(tr)
        for tr, _ in rows_out:
            tbl.append(tr)
        tbl.set("rowCnt", str(len(rows_out)))
        total = 0
        for tr, _ in rows_out:
            hs = [int(tc.find(T("hp:cellSz")).get("height", "0")) for tc in tr if tc.tag == T("hp:tc")
                  and (tc.find(T("hp:cellSpan")) is None or tc.find(T("hp:cellSpan")).get("rowSpan", "1") == "1")]
            total += max(hs) if hs else 0
        sz = tbl.find(T("hp:sz"))
        if sz is not None and total:
            sz.set("height", str(total))

    def reshape_cols(self, tbl, n, widths, where):
        """표의 칸 수를 n으로 바꾼다. 첫 칸·끝 칸은 견본의 첫 칸·끝 칸 모양을, 가운데 칸은 견본 가운데 칸 모양을 쓴다
        (그래서 '맨 왼쪽·오른쪽 선 없음' 같은 바깥 선 모양이 그대로 따라간다)."""
        if not isinstance(n, int) or n < 1:
            raise BuildError(f"{where}: cols는 1 이상의 숫자여야 합니다.")
        trs = [tr for tr in tbl if tr.tag == T("hp:tr")]
        if any(rs > 1 or cs > 1 for _, _, rs, cs, _ in table_grid(tbl)):
            raise BuildError(f"{where}: 합친 칸이 있는 표는 칸 수를 바꿀 수 없습니다(견본 {tbl.get('colCnt')}칸). "
                             "칸 수를 견본에 맞추거나 합친 칸이 없는 표를 고르세요.")
        tw = [int(tc.find(T("hp:cellSz")).get("width", "0")) for tc in trs[0] if tc.tag == T("hp:tc")]
        total = sum(tw)
        if widths:
            if (not isinstance(widths, list) or len(widths) != n
                    or any(not isinstance(w, (int, float)) or w <= 0 for w in widths)):
                raise BuildError(f"{where}: widths는 칸 수({n})만큼의 양수 목록이어야 합니다(비율, 예: [1, 2, 2]).")
            ws = [total * w / sum(widths) for w in widths]
        elif n == len(tw):
            ws = tw
        elif n == 1:
            ws = [total]
        else:
            w0 = tw[0] if len(tw) > 1 and tw[0] < total * 0.4 else total / n
            ws = [w0] + [(total - w0) / (n - 1)] * (n - 1)
        ws = [int(round(w)) for w in ws]
        ws[-1] += total - sum(ws)
        for tr in trs:
            cells = [tc for tc in tr if tc.tag == T("hp:tc")]
            m = len(cells)
            if m < 3 and n > 2:
                self.warn(f"{where}: 견본 표에 가운데 칸 모양이 없어 가운데 칸은 끝 칸 모양을 빌렸습니다.")

            def src(j):
                if j == 0:
                    return cells[0]
                if j == n - 1:
                    return cells[-1]
                return cells[1] if m >= 3 else cells[-1]

            new = []
            for j in range(n):
                tc = copy.deepcopy(src(j))
                tc.find(T("hp:cellAddr")).set("colAddr", str(j))
                tc.find(T("hp:cellSz")).set("width", str(ws[j]))
                new.append(tc)
            for tc in cells:
                tr.remove(tc)
            for tc in new:
                tr.append(tc)
        tbl.set("colCnt", str(n))

    # ------------------------------------------------------------ 사용자 원칙(줄 나눔·묶음)
    def keep_groups(self, out):
        """□는 바로 아래와 함께, ○와 그 아래 -·*·※·표는 한 쪽에 붙어 있게(다음 문단과 함께)."""
        def lv(p):
            tables = para_tables(p)
            if tables:
                return "T1" if tables[0].get("rowCnt") == "1" else "T"
            t = para_text(p)
            if UNIT_RE.match(t):
                return "U"  # 표 위 기준·단위 줄: 위 항목·아래 표와 한 쪽에
            return "blank" if not t.strip() else marker_level(t)

        lv_list = [lv(p) for p in out]
        member = (3, 4, "T", "T1", "U")
        for i in range(len(out) - 1):
            a, b = lv_list[i], lv_list[i + 1]
            c = lv_list[i + 2] if i + 2 < len(lv_list) else None
            if out[i + 1].get("pageBreak") == "1":
                continue
            keep = ((a == 1 and b not in ("blank", 0))
                    or (a in (2, 3, 4, "T", "T1", "U") and b in member)
                    or (a == "T1" and b in (1, 2))
                    # 표 앞에 둔 빈 줄은 묶음을 끊지 않는다: ○ → (빈 줄) → 표
                    or (a in (1, 2, 3, 4, "T", "T1") and b == "blank" and c in member)
                    or (a == "blank" and b in ("T", "T1") and i > 0 and lv_list[i - 1] in (1, 2, 3, 4, "T", "T1")))
            if keep:
                out[i].set("paraPrIDRef", self.hedit.para_keep_next(out[i].get("paraPrIDRef")))

    def word_wrap(self):
        """쓰는 문단 모양을 모두 어절(단어) 단위 줄 나눔으로 맞춘다."""
        changed = 0
        for pid in {el.get("paraPrIDRef") for el in self.sec.iter() if el.get("paraPrIDRef")}:
            changed += self.hedit.word_wrap(pid)
        if changed:
            self.warn(f"글자 단위로 줄을 나누던 문단 모양 {changed}개를 단어 단위로 바꿨습니다.")

    # ------------------------------------------------------------ 한 블록
    def make_block(self, n, block):
        where = f"블록 {block.get('_src', '(자동 빈 줄)')}" if isinstance(block, dict) else f"블록 {n + 1}"
        if not isinstance(block, dict) or "like" not in block:
            raise BuildError(f"{where}: 블록마다 \"like\"(견본 문단 번호)가 있어야 합니다: {block!r}")
        known = {"like", "text", "runs", "table", "cells", "page_break", "marker", "header_rows", "body_like",
                 "last_like", "keep_header", "cols", "widths", "note", "unit", "_src", "_align", "flow", "arrow",
                 "title", "rows"}
        if ("title" in block or "rows" in block) and "flow" not in block:
            raise BuildError(f"{where}: title·rows는 도표(flow) 블록에만 씁니다.")
        extra = set(block) - known
        if extra:
            raise BuildError(f"{where}: 모르는 항목 {sorted(extra)}. 쓸 수 있는 항목: {sorted(known)}")
        idx = block["like"]
        p = self.clone(idx, where)
        if para_tables(p):
            if "runs" in block:
                raise BuildError(f"{where}: 표 문단에는 runs를 쓸 수 없습니다. table·cells·text를 쓰세요.")
            self.fill_table(p, block, where)
        else:
            if "table" in block or "cells" in block or "flow" in block:
                raise BuildError(f"{where}: like {idx}는 표가 아닌 문단입니다. 표가 든 문단 번호를 고르세요.")
            if "runs" in block:
                self.fill_runs(p, block["runs"], idx, where)
            elif "text" in block:
                self.fill_text(p, block["text"], where, marker=block.get("marker", True))
        if "page_break" in block:
            p.set("pageBreak", "1" if block["page_break"] else "0")
        if block.get("_align"):
            p.set("paraPrIDRef", self.hedit.para_align(p.get("paraPrIDRef"), block["_align"]))
        return p

    # ------------------------------------------------------------ 괄호 이름표 맞추기
    def align_labels(self, blocks):
        """○(또는 -) 항목에 붙은 괄호 이름표 (현황)·(문제점)을 네 글자 폭에 맞춘다(네 글자가 기준).
        (현황)은 (현⎵⎵⎵⎵⎵⎵⎵⎵황)처럼 고정폭 빈칸을 넣어, 괄호 다음 내용이 위아래로 같은 자리에서 시작하게 한다.
        보통 빈칸은 양쪽 정렬 때 늘어나므로 이름표 안·뒤 빈칸은 모두 고정폭 빈칸(⎵, 반 글자)으로 쓴다."""
        groups, current = [], {}

        def close(levels):
            for lv in sorted(levels):
                if lv in current:
                    groups.append(current.pop(lv))

        for n, b in enumerate(blocks):
            if not isinstance(b, dict) or not isinstance(b.get("like"), int) or not 0 <= b["like"] < len(self.protos):
                continue
            proto = self.protos[b["like"]]
            if b.get("page_break"):
                close(list(current))
            if para_tables(proto) or "text" not in b:
                if para_tables(proto) or not para_text(proto).strip():
                    close(list(current))
                continue
            lv = marker_level(para_text(proto))
            if lv == 1:
                close(list(current))
                continue
            if lv not in (2, 3):
                continue
            close([x for x in current if x > lv])
            _, um, body = split_marker(b["text"])
            body = body if um else b["text"]
            current.setdefault(lv, []).append((n, LABEL_RE.match(body), body))
        close(list(current))

        for g in groups:
            labeled = [(n, m, body) for n, m, body in g if m]
            if not labeled:
                continue
            font = self._body_font(blocks[labeled[0][0]]["like"])
            k = max(1, round(self.metrics.em(font, " ") / FW_EM))  # 보통 빈칸 하나 = 고정폭 빈칸 k개
            cores = [m.group("core").strip().replace(" ", FW * k) for _, m, _ in labeled]
            widths = [self._label_em(c, font) for c in cores]
            # 네 글자 이름표가 기준: 두세 글자 이름표는 묶음과 상관없이 늘 네 글자 폭에 맞춘다(사용자 결정 2026-10-31).
            # 네 글자는 붙여 쓰고, 네 글자를 넘는 이름표는 그대로 둔다.
            target = self._label_em("가가가가", font)
            for (n, m, body), core, w in zip(labeled, cores, widths):
                core = spread(core, max(0, int(round((target - w) / FW_EM))))
                b1, b2 = m.group("b1") or "", m.group("b2") or ""
                rest = body[m.end():].lstrip(" " + FW)
                blocks[n] = dict(blocks[n], text=f"{b1}({core}){b2}{FW * k}{rest}")
        # 네 글자를 넘는 이름표는 맞춤에서 빠져도 된다(사용자: 네 글자가 기준, 넘는 것은 규칙에서 어긋나도 됨) — 알리지 않음

        # 작대기(-) 항목의 '항목명 : 내용'은 세 글자 폭이 기준(사용자 의견 2026-11-01): '- 교체 : …' → '- 교⎵⎵⎵⎵체 : …'
        # (세 글자·세 글자를 넘는 항목명은 그대로) → 쌍점과 내용이 위아래로 같은 자리
        for n, b in enumerate(blocks):
            if (not isinstance(b, dict) or "text" not in b or not isinstance(b.get("like"), int)
                    or not 0 <= b["like"] < len(self.protos)):
                continue
            proto = self.protos[b["like"]]
            if para_tables(proto) or marker_level(para_text(proto)) != 3:
                continue
            pre, um, body = split_marker(b["text"])
            m = DASH_HEAD_RE.match(body if um else b["text"])
            if not m:
                continue
            font = self._body_font(b["like"])
            k = int(round((self._label_em("가가가", font) - self._label_em(m.group("core"), font)) / FW_EM))
            if k > 0:
                head = f"{m.group('b1') or ''}{spread(m.group('core'), k)}{m.group('b2') or ''}"
                blocks[n] = dict(b, text=pre + head + (body if um else b["text"])[m.end():])

    def _body_font(self, idx):
        runs = indexed_runs(self.protos[idx])
        fonts = [self.styles.char.get(r.get("charPrIDRef"), {}).get("font") for r in runs]
        return next((f for f in reversed(fonts) if f), None)

    def _fw_per_space(self, run):
        font = self.styles.char.get(run.get("charPrIDRef"), {}).get("font")
        return max(1, round(self.metrics.em(font, " ") / FW_EM))

    def _label_em(self, core, font):
        return sum(FW_EM if ch == FW else self.metrics.em(font, ch) for ch in core)

    # ------------------------------------------------------------ 쌍점 뒤 맞추기
    def colon_hang(self, colons=True, labels=True):
        """두 줄 이상인 문단의 둘째 줄부터를 내용 첫 글자에 맞춰 내어쓴다.
        - 쌍점: '인센티브 : 밤 10시…' → 쌍점 뒤 첫 글자(사용자 원칙: 쌍점 뒤 처음 시작하는 글자의 끝선에 아랫줄을 맞춤)
        - 괄호 이름표: '○ (근  거) 「법」…' → 이름표 뒤 첫 글자(사용자 의견 2026-10-31: 근거·홍보 다음 첫 글자에 끝선 맞춤)
        내어쓰기가 본문 폭의 40%를 넘으면(이름표가 너무 김) 하지 않는다."""
        lay = Layout(self.styles, self.metrics)
        pg = page_info(self.sec)
        body_w = pg["body_width"] * HWPUNIT_PER_MM

        def content_at(text):
            k = label_colon(text) if colons else 0
            return k or (label_content(text) if labels else 0)

        n_colon = n_label = 0
        for p in [x for x in self.sec if x.tag == T("hp:p")]:
            if para_tables(p):
                continue
            text = para_text(p)
            k = content_at(text)
            if not k or marker_level(text) == 1:
                continue
            chs, lines = lay.para_lines(p, body_w)
            if len(lines) < 2 or sum(c[1] for c in chs[:k]) > body_w * 0.4:
                continue
            by_colon = bool(colons and label_colon(text))
            # 쌍점 뒤 첫 글자까지의 보통 빈칸은 고정폭 빈칸으로(첫 줄이 양쪽 정렬로 늘어나도 위치가 변하지 않게)
            pos = 0
            for r in indexed_runs(p):
                t = run_text(r)
                start, pos = pos, pos + len(t)
                if start >= k:
                    break
                cut = min(len(t), k - start)
                new = t[:cut].replace(" ", FW * self._fw_per_space(r)) + t[cut:]
                if new != t and len(r) == 1:
                    set_run_text(r, new, self.tab_proto)
            k = content_at(para_text(p))
            self._split_run_at(p, k)  # '항목명 : '·'(이름표) '와 내용을 다른 조각으로(내용만 자간 조정되게)
            chs, lines = lay.para_lines(p, body_w)
            hang = sum(c[1] for c in chs[:k])
            p.set("paraPrIDRef", self.hedit.para_hang(p.get("paraPrIDRef"), hang))
            if by_colon:
                n_colon += 1
            else:
                n_label += 1
        if n_colon:
            self.warn(f"쌍점(:) 뒤 내용이 두 줄 이상인 문단 {n_colon}개는 둘째 줄을 쌍점 뒤 첫 글자에 맞췄습니다.")
        if n_label:
            self.warn(f"괄호 이름표 뒤 내용이 두 줄 이상인 문단 {n_label}개는 둘째 줄을 이름표 뒤 첫 글자에 맞췄습니다.")

    def _split_run_at(self, p, k):
        """문단 글자 위치 k가 한 조각(run) 가운데에 있으면 그 조각을 둘로 나눈다(모양은 같게)."""
        pos = 0
        for r in indexed_runs(p):
            t = run_text(r)
            start, end = pos, pos + len(t)
            pos = end
            if start < k < end and len(r) == 1:
                tail = self._mk(r, t[k - start:])
                set_run_text(r, t[:k - start], self.tab_proto)
                r.addnext(tail)
                return

    def lone_dashes(self, out):
        """항목 수 알림(사용자 원칙 2026-11-01 — 사람은 셋으로 정리하는 것을 좋아함): □ 아래 ○, ○ 아래 -, - 아래 ·는
        셋쯤이 좋고 2~5개를 벗어나지 않게 한다. 하나뿐이거나 다섯을 넘으면 알린다. 참고 쪽(참고 머리표부터)은 세지 않는다.
        □ 아래 ○가 하나뿐이면 (추진방향) → (주요내용) → 표 꼴로 나누면 자연스럽다."""
        names = {1: "□", 2: "○", 3: "-"}
        child = {1: "○", 2: "-", 3: "·"}
        found = {1: [], 2: [], 3: []}
        open_ = {}  # 수준 → [이름, 아래 항목 수]

        def close(lv):
            for k in [x for x in open_ if x >= lv]:
                name, n = open_.pop(k)
                if n == 1 or n > 5:
                    found[k].append((name, n))

        for p in out:
            if para_tables(p):
                if self._is_ref_head(p):
                    break
                continue
            text = para_text(p)
            _, mark, _ = split_marker(text)
            if not mark:
                continue
            lv = marker_level(text)
            if lv == 4:
                continue  # * 설명·※ 참고는 세지 않고 지나감
            if lv == 1 and mark[0] in ROMAN:
                close(1)
                if BASIS_TITLE_RE.search(text):  # Ⅰ. 근거법령 아래 ○도 둘 이상(사용자 원칙 2026-11-03)
                    open_[1] = [text[_base_head(text):].lstrip(" " + FW)[:12], 0]
                continue
            if lv == 3:
                lv = 4 if mark in "•∙·ㆍ" else 3  # 작대기 다음은 가운데점
            name = text[_base_head(text):].lstrip(" " + FW).replace("**", "")[:12]
            close(lv)
            if lv - 1 in open_:
                open_[lv - 1][1] += 1
            if lv in names:
                open_[lv] = [name, 0]
        close(1)
        for lv, items in found.items():
            if not items:
                continue
            ones = [t for t, n in items if n == 1]
            many = [f"{t}({n}개)" for t, n in items if n > 5]
            msg = f"{child[lv]} 항목 수 — 셋쯤이 좋고 2~5개를 벗어나지 않게(사용자 원칙): "
            basis = [t for t in ones if lv == 1 and BASIS_TITLE_RE.search(t)]
            if basis:  # 근거법령도 ○ 둘 이상(사용자 원칙 2026-11-03) — 나누거나 합치지 말고 확인된 근거를 더함
                msg += (f"○ 하나뿐인 근거법령({', '.join('‘' + t + '’' for t in basis)}) → 확인된 다른 근거(시행령·시행규칙·"
                        "조례·훈령·지침·계획)를 ○로 더하세요(법령 검색 도구로 확인한 것만, 모르면 사용자에게 묻기)")
                ones = [t for t in ones if t not in basis]
                if ones or many:
                    msg += "; "
            if ones:
                msg += f"{child[lv]} 하나뿐인 {names[lv]} {len(ones)}개({', '.join('‘' + t + '’' for t in ones)})"
                msg += {1: " → (추진방향)·(주요내용)처럼 둘 이상으로 나누거나 다른 □와 합치세요",
                        2: " → -를 둘 이상으로 나누거나 ○ 글에 합치세요",
                        3: " → ·를 둘 이상으로 나누거나 - 글에 합치세요"}[lv]
            if many:
                msg += ("; " if ones else "") + f"{child[lv]}가 다섯을 넘는 {names[lv]} " + ", ".join(many) + " → 묶거나 나누세요"
            self.warn(msg + ".")

    def _is_ref_head(self, p):
        tables = para_tables(p)
        if not tables or tables[0].get("rowCnt") != "1" or tables[0].get("colCnt") == "1":
            return False
        grid = table_grid(tables[0])
        return bool(grid) and bool(re.match(r"^\s*(참\s*고|붙\s*임|별\s*첨|첨\s*부)",
                                            " ".join(para_text(cp) for cp in cell_paras(grid[0][4]))))

    def ref_bullets(self, out):
        """참고 머리표 바로 아래 ○ 한 줄 설명은 쓰지 않는 형식이다(사용자 의견 2026-10-31) — 설명은 표 아래 ※로."""
        hits = []
        for a, b in zip(out, out[1:]):
            tables = para_tables(a)
            if (tables and tables[0].get("rowCnt") == "1" and tables[0].get("colCnt") != "1"
                    and not para_tables(b) and marker_level(para_text(b)) == 2):
                hits.append(para_text(b).strip()[:16])
        if hits:
            self.warn(f"참고 머리표 바로 아래 ○ 줄 {len(hits)}개({', '.join(hits)}): 참고 쪽에는 ○ 한 줄 설명을 쓰지 않습니다 "
                      "— 표·내용을 바로 두고 설명은 표 아래 ※로 옮기세요.")

    # ------------------------------------------------------------ 부연설명 괄호 작게
    def small_notes(self):
        """설명 문단은 설명하는 글(바로 위 □·○·-·· 문단)보다 작게(사용자 원칙 2026-11-02): * 풀이·※ 참고 모두 **2pt**
        작게(v1.1). 설명 문단은 아래 간격을 3pt 이상 둬 작아진 글자 뒤 줄이 붙어 보이지 않게 한다. 표 바로 뒤 ※·*는 fit이
        표 글자 기준(1pt 작게)으로 맞추므로 건너뛴다. 조각마다 크기 차이(작게 한 괄호 등)는 그대로 두고 문단 전체를 같은
        만큼 옮긴다. 견본이 이미 그만큼 작으면 그대로."""
        def main_size(p):
            sizes = [round(self.styles.char.get(r.get("charPrIDRef"), {}).get("size", 0)) for r in indexed_runs(p)
                     if r.find(T("hp:t")) is not None and run_text(r).strip()
                     and not self.styles.char.get(r.get("charPrIDRef"), {}).get("superscript")]
            sizes = [s for s in sizes if s]
            return max(set(sizes), key=sizes.count) if sizes else 0

        changed, gapped, parent, after_table = 0, 0, 0, False
        for p in self.sec:
            if p.tag != T("hp:p"):
                continue
            if para_tables(p):
                after_table = True
                continue
            text = para_text(p)
            if not text.strip():
                continue
            lvl = marker_level(text)
            if lvl == 4:
                if after_table or not parent:
                    continue
                is_star = split_marker(text)[1] in "*＊"
                cur = main_size(p)
                delta = (parent - (NOTE_STAR_PT if is_star else NOTE_REF_PT)) - cur
                if cur and delta:
                    for r in indexed_runs(p):
                        if r.find(T("hp:t")) is None:
                            continue
                        r.set("charPrIDRef", self.hedit.char_size(r.get("charPrIDRef"), delta))
                    changed += 1
                if True:  # * 풀이·※ 참고 모두(v1.1)
                    pid = p.get("paraPrIDRef")
                    if self.styles.para.get(pid, {}).get("next", 0) < NOTE_STAR_GAP:
                        p.set("paraPrIDRef", self.hedit.para_margin(pid, "next", NOTE_STAR_GAP))
                        gapped += 1
                continue
            after_table = False
            if lvl in (1, 2, 3):
                parent = main_size(p) or parent
        if changed:
            self.warn(f"*·※ 설명 {changed}문단을 설명하는 글보다 작게(* {NOTE_STAR_PT}pt·※ {NOTE_REF_PT}pt) 했습니다(견본이 달랐음).")
        if gapped:
            self.warn(f"*·※ 설명 {gapped}문단 아래를 {NOTE_STAR_GAP // 100}pt 띄웠습니다(작은 글자 뒤 줄이 붙어 보이지 않게).")

    def small_parens(self, delta):
        """○·- 항목 글 속 부연설명 괄호(괄호와 그 안의 글)를 delta pt 작게 한다(사용자 원칙, 2026-10-31).
        첫머리 괄호 이름표 (현황)·이름의 일부 (안)·요일 (금)·「」 안의 괄호와 굵은·위 첨자 조각은 그대로 둔다."""
        changed = 0
        for p in self.sec:
            if p.tag != T("hp:p") or para_tables(p):
                continue
            text = para_text(p)
            if marker_level(text) not in (2, 3):
                continue
            spans, depth, quote, start = [], 0, 0, None
            for i in range(_base_head(text), len(text)):
                ch = text[i]
                if ch == "「":
                    quote += 1
                elif ch == "」":
                    quote = max(0, quote - 1)
                elif ch == "(" and not quote:
                    if depth == 0:
                        start = i
                    depth += 1
                elif ch == ")" and depth and not quote:
                    depth -= 1
                    if depth == 0 and not SKIP_PAREN_RE.fullmatch(text[start:i + 1]):
                        spans.append((start, i + 1))
            if not spans:
                continue
            pos = 0
            big = max((self.styles.char.get(r.get("charPrIDRef"), {}).get("size", 0) for r in indexed_runs(p)), default=0)
            for r in indexed_runs(p):
                t = run_text(r)
                a, b = pos, pos + len(t)
                pos = b
                c = self.styles.char.get(r.get("charPrIDRef"), {})
                if (c.get("bold") or c.get("superscript") or c.get("size", 0) < big
                        or r.find(T("hp:t")) is None or len(r) != 1):
                    continue  # 이름표·위 첨자·이미 작은 조각은 그대로
                cuts = sorted({x - a for s, e in spans for x in (s, e) if a < x < b} | {0, len(t)})
                pieces = [(t[x:y], any(s <= a + x and a + y <= e for s, e in spans)) for x, y in zip(cuts, cuts[1:])]
                if not any(small for _, small in pieces):
                    continue
                cid = self.hedit.char_size(r.get("charPrIDRef"), -delta)
                parent = r.getparent()
                at = list(parent).index(r)
                for k, (s, small) in enumerate(pieces):
                    nr = self._mk(r, s)
                    if small:
                        nr.set("charPrIDRef", cid)
                    parent.insert(at + 1 + k, nr)
                parent.remove(r)
                changed += 1
        if changed:
            self.warn(f"부연설명 괄호를 {delta}pt 작게 했습니다(○·- 항목 {changed}곳 — 첫머리 이름표·(안)·요일은 그대로).")

    # ------------------------------------------------------------ 따옴표 붙이기
    def _tight_deltas(self, text, font):
        """글자마다 줄일 자간(%): 한 글자 폭이라 벌어져 보이는 따옴표·낫표·가운데점을 붙인다(빈 쪽만큼, 표시는 겹치지 않게).
        - 닫는 ’ ”·」: 그 글자를 -50%(오른쪽 빈 곳을 줄임)
        - 여는 ‘ “·「: 표시가 칸 오른쪽이라 그 글자를 줄이면 다음 글자가 표시를 덮음 → 앞 글자를 줄임
          (「 앞이 낱말이면 -40%, 빈칸이면 빈칸 -50%·그 앞 글자 -20%. 고정폭 빈칸·여는 괄호 뒤는 그대로 — 머리 기호·이름표 뒤 줄 맞춤 유지)
        - 낱말 사이 ·ㆍ(홍보·안내): 앞 글자와 점을 -25%씩(양쪽 빈 곳을 같게 줄임). 머리 기호로 쓴 '· '는 그대로"""
        d = [0] * len(text)
        quotes = self.metrics.em(font, "’") >= 0.9
        tight = font in TIGHT_FONTS
        for i, ch in enumerate(text):
            prev = text[i - 1] if i > 0 else None
            nxt = text[i + 1] if i + 1 < len(text) else None
            if quotes and ch in QUOTES:
                if ch not in OPEN_QUOTES:
                    d[i] -= 50
                elif prev is not None and prev not in QUOTES:
                    d[i - 1] -= 50  # 조각 첫 글자인 여는 따옴표는 줄이지 않고 둔다
            elif tight and ch == "」":
                d[i] -= 50
            elif tight and ch == "「" and prev is not None and prev not in FW + "([{<〈《“‘「":
                d[i - 1] -= 50 if prev == " " else 40
                if prev == " " and i > 1 and text[i - 2] not in " " + FW:
                    d[i - 2] -= 20  # 빈칸은 -50%까지만 줄어 앞 글자도 조금(60pt 실측: 등 「 사이 0.84 → 0.6글자)
            elif tight and ch in MID_DOTS and prev not in (None, " ", FW) and nxt not in (None, " ", FW):
                d[i - 1] -= 25
                d[i] -= 25
        return d

    def tighten_quotes(self):
        """따옴표(’ ”)·낫표(「」)·가운데점(·)이 한 글자 폭인 글꼴(휴먼명조)에서는 ’26.이 ’ 26.처럼, 「법」 등이 「 법」  등처럼,
        홍보·안내가 홍보 · 안내처럼 벌어져 보인다. 빈 쪽 자간을 줄여 붙인다(사용자 원칙 1: 자간은 겹치지 않는 범위에서 조정,
        낫표·가운데점은 사용자 요청 2026-11-01). 줄인 자간은 -50%를 넘지 않는다."""
        for r in list(self.sec.iter(T("hp:run"))):
            text = run_text(r)
            if r.find(T("hp:t")) is None or len(r) != 1 or not any(q in text for q in QUOTES + "「」" + MID_DOTS):
                continue
            c = self.styles.char.get(r.get("charPrIDRef"), {})
            base = c.get("spacing", 0)
            deltas = self._tight_deltas(text, c.get("font"))
            if not any(deltas) or base <= -50:
                continue
            cids = [self.hedit.char_spacing(r.get("charPrIDRef"), max(-50, base + dl)) if dl else None for dl in deltas]
            pieces = []
            for ch, cid in zip(text, cids):
                if pieces and pieces[-1][1] == cid:
                    pieces[-1] = (pieces[-1][0] + ch, cid)
                else:
                    pieces.append((ch, cid))
            parent = r.getparent()
            at = list(parent).index(r)
            for k, (t, cid) in enumerate(pieces):
                nr = self._mk(r, t)
                if cid:
                    nr.set("charPrIDRef", cid)
                parent.insert(at + 1 + k, nr)
            parent.remove(r)

    # ------------------------------------------------------------ 번호·빈 줄
    def _proto_of(self, b):
        if isinstance(b, dict) and isinstance(b.get("like"), int) and 0 <= b["like"] < len(self.protos):
            return self.protos[b["like"]]
        return None

    def number_items(self, blocks):
        """번호 머리 기호(Ⅰ. 1. 가. ①)는 견본 번호를 그대로 쓰지 않고 차례로 매긴다. 글에 번호가 있으면 그것을 쓴다.
        위 갈래 번호가 나오면 아래 갈래 번호는 다시 1부터."""
        count = {}
        for n, b in enumerate(blocks):
            proto = self._proto_of(b)
            if proto is None or "text" not in b or para_tables(proto) or b.get("marker") is False:
                continue
            _, mark, _ = split_marker(para_text(proto))
            fam = number_family(mark)
            if not fam:
                continue
            for f in FAMILIES[FAMILIES.index(fam) + 1:]:
                count.pop(f, None)
            count[fam] = count.get(fam, 0) + 1
            _, um, _ = split_marker(b["text"])
            if number_family(um) != fam:
                blocks[n] = dict(b, text=f"{number_mark(fam, count[fam], mark)} {b['text']}")

    def join_titles(self, blocks):
        """네 글자 제목(두 글자 + 두 글자)은 띄어 쓰지 않는다: □ 추진 배경 → □ 추진배경, (추진 방향) → (추진방향).
        □·Ⅰ. 제목 글 전체와, ○·- 항목 첫머리 괄호 이름표에만 쓴다(사용자 원칙)."""
        four = re.compile(r"^([가-힣]{2}) ([가-힣]{2})$")
        joined = 0
        for n, b in enumerate(blocks):
            proto = self._proto_of(b)
            if proto is None or "text" not in b or para_tables(proto):
                continue
            text = b["text"]
            lv = marker_level(para_text(proto))
            upre, umark, ubody = split_marker(text)
            body = ubody if umark else text
            if lv == 1:
                m = four.match(body.strip())
                if m:
                    blocks[n] = dict(b, text=upre + m.group(1) + m.group(2))
                    joined += 1
            elif lv in (2, 3):
                lm = LABEL_RE.match(body)
                if lm and four.match(lm.group("core").strip()):
                    core = lm.group("core").strip().replace(" ", "")
                    new_body = body[:lm.start("core")] + core + body[lm.end("core"):]
                    blocks[n] = dict(b, text=upre + new_body)
                    joined += 1
        if joined:
            self.warn(f"네 글자 제목·이름표 {joined}곳을 붙여 썼습니다(예: 추진 배경 → 추진배경).")

    def table_notes(self, blocks):
        """표 바로 뒤 ※ 줄은 표 왼쪽 끝선에서 시작하는 ※ 모양(견본에서 왼쪽 여백이 0인 ※ 문단)으로 바꾼다
        (사용자 원칙 2026-10-31: 표 밑 ※는 표 왼쪽 끝선에 맞추고 본문보다 2pt 작게)."""
        notes = [i for i, p in enumerate(self.protos)
                 if not para_tables(p) and split_marker(para_text(p))[1] == "※"
                 and self.styles.para.get(p.get("paraPrIDRef"), {}).get("left", 0) == 0]
        if not notes:
            return
        target, moved, prev, after_table = notes[0], 0, None, False
        for n, b in enumerate(blocks):
            proto = self._proto_of(b)
            if proto is None:
                continue
            is_note = not para_tables(proto) and split_marker(para_text(proto))[1] == "※"
            # 표 바로 뒤 ※ 줄과, 그 뒤로 이어지는 ※ 줄 모두(한 줄만 바꾸면 들여쓰기가 섞임)
            after_table = is_note and (after_table or (prev is not None and para_tables(prev)
                                                       and para_tables(prev)[0].get("rowCnt") != "1"))
            if after_table and b["like"] != target:
                blocks[n] = dict(b, like=target)
                moved += 1
            prev = proto
        if moved:
            self.warn(f"표 바로 뒤 ※ {moved}줄은 표 왼쪽 끝선에서 시작하는 ※ 모양(견본 {target}번)으로 넣었습니다.")

    def table_units(self, blocks):
        """표 위 기준·단위 줄 '(기준 : ’26.9월) (단위 : 백만원)'(사용자 원칙 2026-11-01): 표 오른쪽 끝에 맞추고 표 글자보다
        2pt 작게. 표 블록의 "unit"은 표 바로 앞 줄로 넣고, 표 바로 앞 글 블록이 이 꼴이면 견본의 기준·단위 줄 모양
        (기본 양식 18번)으로 바꾼다. 견본에 그 모양이 없으면 표 아래 ※ 모양을 빌려 오른쪽 정렬로. 크기는 fit이 맞춘다."""
        target = next((i for i, p in enumerate(self.protos)
                       if not para_tables(p) and UNIT_RE.match(para_text(p))), None)
        fallback = None
        if target is None:
            fallback = next((i for i, p in enumerate(self.protos)
                             if not para_tables(p) and para_text(p).strip()
                             and self.styles.para.get(p.get("paraPrIDRef"), {}).get("left", 0) == 0), None)

        def unit_block(b, text):
            if target is not None:
                return dict(b, like=target, text=text)
            return dict(b, like=fallback, text=text, marker=False, _align="RIGHT")

        out, made = [], 0
        for b in blocks:
            proto = self._proto_of(b)
            if proto is not None and para_tables(proto) and isinstance(b, dict):
                if b.get("unit") and (target is not None or fallback is not None):
                    out.append(unit_block({"_src": b.get("_src")}, b["unit"]))
                    made += 1
                elif out and isinstance(out[-1], dict) and "text" in out[-1] and UNIT_RE.match(out[-1]["text"]) \
                        and out[-1].get("like") not in (target, None) and (target is not None or fallback is not None):
                    out[-1] = unit_block(out[-1], out[-1]["text"])
                    made += 1
                b = {k: v for k, v in b.items() if k != "unit"}
            out.append(b)
        if made:
            where = f"견본 {target}번" if target is not None else f"견본 {fallback}번을 오른쪽 정렬로"
            self.warn(f"표 위 기준·단위 줄 {made}개를 표 오른쪽 끝에 맞춘 모양({where})으로 넣었습니다.")
        elif any(isinstance(b, dict) and b.get("unit") for b in blocks):
            self.warn("견본에 기준·단위 줄로 쓸 문단이 없어 표 위 \"unit\"을 넣지 못했습니다.")
        return out

    def _block_spacer(self):
        """□ 블록 사이에 둘 '한 줄 빈 줄' 견본: □ 바로 앞의 빈 문단, 없으면 가장 높은 빈 문단."""
        def blank(p):
            return is_blank(p)
        before = [i - 1 for i, p in enumerate(self.protos)
                  if i > 0 and marker_level(para_text(p)) == 1 and blank(self.protos[i - 1])]
        if before:
            return max(set(before), key=before.count)
        blanks = [i for i, p in enumerate(self.protos) if blank(p)]
        if not blanks:
            return None
        sizes = {i: max((self.styles.char.get(r.get("charPrIDRef"), {}).get("size", 0)
                         for r in para_runs(self.protos[i])), default=0) for i in blanks}
        return max(blanks, key=lambda i: sizes[i])

    def space_blocks(self, blocks):
        """□ 블록·Ⅰ. 장 앞에 한 줄 빈 줄을 둔다(사용자 원칙 9). 계획에 이미 빈 줄이 있거나 바로 앞이 장 제목이면 두지 않는다."""
        sp = self._block_spacer()
        if sp is None:
            return blocks
        out = []
        for b in blocks:
            proto = self._proto_of(b)
            if (proto is not None and out and not para_tables(proto) and marker_level(para_text(proto)) == 1
                    and not b.get("page_break")):
                prev = self._proto_of(out[-1])
                if prev is not None:
                    prev_blank = is_blank(prev) and "text" not in out[-1]
                    mark = split_marker(para_text(prev))[1]
                    prev_chapter = bool(mark) and mark[0] in ROMAN and "text" in out[-1]  # 기호 없는 글(요약 상자 등)은 장 제목 아님
                    if not prev_blank and not prev_chapter:
                        out.append({"like": sp})
            out.append(b)
        return out

    # ------------------------------------------------------------ 근거법령 1번
    def _is_basis(self, text):
        """근거법령 ○인가: 괄호 이름표에 근거·법령이 들어 있음((추진근거)·(평가근거)·(근  거)·(관계법령))."""
        body = split_marker(text)[2].replace("**", "").strip()
        m = re.match(r"\(([^)]{1,12})\)", body)
        return bool(m) and bool(BASIS_RE.search(m.group(1)))

    def basis_first(self, blocks):
        """근거법령은 무조건 1번(사용자 원칙 2026-11-01 — 모든 공문·보고서·계획서에 근거법령이 옴):
        - 표지 개요 상자: 첫 □ 아래 첫 ○
        - 본문: 로마자 장이 있으면 Ⅰ.이 근거법령 장(Ⅰ. 근거법령 → ○ 「…법」 제○조), 없으면 첫 □가 근거법령
          (□ 근거법령 → ○ 「…법」 제○조, 사용자 원칙 2026-11-03 — 근거법령이 들어가면 첫 □가 근거법령)
        뒤에 있으면 그 장·□ 묶음째 맨 앞으로 옮기고, 다른 □ 안의 ○ (추진근거)이면 □ 근거법령으로 떼어 첫 □로 세우며,
        없으면 알린다."""
        moved, missing = [], []
        # 표지 개요 상자(그림으로 시작하는 계획의 첫 쪽, 한 칸 상자 글이 □·○ 줄)
        first = self._proto_of(blocks[0]) if blocks else None
        if first is not None and para_pics(first):
            for b in blocks:
                proto = self._proto_of(b)
                if proto is not None and proto.find(".//" + T("hp:secPr")) is not None:
                    break
                text = b.get("text") if isinstance(b, dict) else None
                if not isinstance(text, str) or proto is None or not para_tables(proto) or "□" not in text:
                    continue
                lines = text.split(NL)
                heads = [i for i, ln in enumerate(lines) if marker_level(ln) == 1]
                if not heads:
                    continue
                h = heads[0]
                end = heads[1] if len(heads) > 1 else len(lines)
                items = [i for i in range(h + 1, end) if marker_level(lines[i]) == 2]
                basis = next((i for i in items if self._is_basis(lines[i])), None)
                if basis is None:
                    missing.append("표지 개요 상자")
                elif items and basis != items[0]:
                    stop = next((k for k in items if k > basis), end)  # 근거 ○ 묶음 = 근거 ○ ~ 다음 ○ 앞
                    lines = lines[:items[0]] + lines[basis:stop] + lines[items[0]:basis] + lines[stop:]
                    b["text"] = NL.join(lines)
                    moved.append("표지 개요 상자")
        # 본문: 로마자 장이 있으면 Ⅰ.이 근거법령 장, 없으면 첫 □가 근거법령
        start = next((n for n, b in enumerate(blocks) if (p := self._proto_of(b)) is not None
                      and p.find(".//" + T("hp:secPr")) is not None), 0)
        ref = next((n for n in range(start, len(blocks)) if self._is_ref_proto(blocks[n])), len(blocks))
        level = {}
        for n in range(start, ref):
            proto = self._proto_of(blocks[n])
            if proto is None or para_tables(proto) or "text" not in blocks[n]:
                level[n] = None
                continue
            mark = split_marker(para_text(proto))[1]
            level[n] = 0 if not mark else (5 if mark[0] in ROMAN else marker_level(para_text(proto)))
        heads = [n for n in range(start, ref) if level.get(n) in (1, 5)]
        if not heads:
            return self._basis_report(blocks, moved, missing)
        first = heads[0]

        def move(lo, hi, to):  # blocks[lo:hi]를 to 자리 앞으로
            group = blocks[lo:hi]
            rest = blocks[:lo] + blocks[hi:]
            at = rest.index(blocks[to])
            return rest[:at] + group + rest[at:]

        if level[first] == 5:  # 로마자 장 문서: Ⅰ. 근거법령
            chapters = [n for n in heads if level[n] == 5]
            if not BASIS_TITLE_RE.search(blocks[first]["text"]):
                c = next((c for c in chapters if BASIS_TITLE_RE.search(blocks[c]["text"])), None)
                if c is None:
                    missing.append("Ⅰ. 근거법령 장")
                else:
                    nxt = next((k for k in chapters if k > c), ref)
                    blocks = move(c, nxt, first)
                    moved.append(f"‘{blocks[first]['text'][:8]}’ 장을 Ⅰ.로")
            return self._basis_report(blocks, moved, missing)
        if BASIS_TITLE_RE.search(blocks[first]["text"]):
            return self._basis_report(blocks, moved, missing)  # □ 근거법령처럼 첫 □ 자체가 근거
        later = next((h for h in heads[1:] if level[h] == 1 and BASIS_TITLE_RE.search(blocks[h]["text"])), None)
        if later is not None:
            nxt = next((h for h in heads if h > later), ref)
            blocks = move(later, nxt, first)
            moved.append(f"□ ‘{blocks[first]['text'][:10]}’")
            return self._basis_report(blocks, moved, missing)
        # 근거가 어느 □ 안의 ○ (추진근거)이면 □ 근거법령으로 떼어 첫 □로(사용자 원칙 2026-11-03: 근거법령이 들어가면 첫 □가 근거법령)
        for h in (h for h in heads if level[h] == 1):
            end = next((k for k in heads if k > h), ref)
            items = [n for n in range(h + 1, end) if level.get(n) == 2]
            basis = next((n for n in items if self._is_basis("○ " + blocks[n]["text"])), None)
            if basis is None:
                continue
            stop = next((k for k in items if k > basis), end)
            while stop - 1 > basis and "text" not in blocks[stop - 1] and level.get(stop - 1) == 0:
                stop -= 1  # 묶음 끝의 빈 줄은 두고 감
            group, dropped = self._basis_square(blocks, first, basis, stop, level)
            moved.append(f"□ ‘{blocks[h]['text'][:10]}’ 안의 근거 ○를 □ 근거법령으로 떼어"
                         + (f" — 법령 아닌 요약 ‘{dropped}’은 빼고 아래 법령 줄을 ○로" if dropped else ""))
            blocks = blocks[:first] + group + blocks[first:basis] + blocks[stop:]
            return self._basis_report(blocks, moved, missing)
        missing.append(f"본문 첫 □ ‘{blocks[first]['text'][:10]}’")
        return self._basis_report(blocks, moved, missing)

    def _basis_square(self, blocks, first, basis, stop, level):
        """'○ (추진근거) …' 묶음(blocks[basis:stop])을 '□ 근거법령 + ○ 법령 하나씩'으로 바꾼다. □ 모양은 첫 □를 빌림.
        이름표 뒤 글은 ○로 두고, 아래 줄(-·번호)이 모두 법령(「)이면 ○로 올린다. 이때 이름표 뒤 글이 법령이 아닌
        요약(예: '행정업무 규정·조례')이면 아래 법령 줄과 겹치므로 뺀다(돌려주는 두 번째 값)."""
        head = blocks[basis]
        body = split_marker("○ " + head["text"])[2]
        lm = LABEL_RE.match(body)
        rest = body[lm.end():].strip() if lm else body.strip()
        kids = [n for n in range(basis + 1, stop) if level.get(n) == 3]
        lift = bool(kids) and (not rest or all("「" in blocks[n].get("text", "") for n in kids))
        dropped = rest if rest and lift and "「" not in rest else ""
        out = [{"like": blocks[first]["like"], "text": "근거법령", "_src": head.get("_src")}]
        if rest and not dropped:
            out.append(dict(head, text=rest))
        for n in range(basis + 1, stop):
            b = blocks[n]
            if lift and n in kids:
                _, mark, kbody = split_marker(b["text"])
                b = dict(b, like=head["like"], text=kbody if mark else b["text"])
            out.append(b)
        return out, dropped

    def _basis_report(self, blocks, moved, missing):
        if moved:
            self.warn("근거법령을 맨 앞(1번)으로 옮겼습니다(" + ", ".join(moved) + ") — 근거법령은 무조건 1번(사용자 원칙).")
        if missing:
            self.warn("근거법령이 없습니다(" + ", ".join(missing) + ") — 모든 공문·보고서·계획서에 근거법령이 옵니다: "
                      "로마자 장이 있으면 Ⅰ. 근거법령, 없으면 첫 □ 근거법령(아래 ○ 「…법」 제○조 하나씩). "
                      "근거를 모르면 사용자에게 묻습니다.")
        return blocks

    def _is_ref_proto(self, b):
        proto = self._proto_of(b)
        tables = para_tables(proto) if proto is not None else []
        return bool(tables) and tables[0].get("rowCnt") == "1" and tables[0].get("colCnt") != "1"

    # ------------------------------------------------------------ 표지·요약 상자
    def cover_break(self, blocks):
        """계획이 표지(그림이 든 견본 문단)로 시작하면 본문 첫 문단(쪽 설정이 든 견본 = 제목 상자)을 새 쪽에서 시작한다."""
        first = self._proto_of(blocks[0]) if blocks else None
        if first is None or not para_pics(first):
            return
        sec_idx = next((i for i, p in enumerate(self.protos) if p.find(".//" + T("hp:secPr")) is not None), None)
        for b in blocks[1:]:
            if isinstance(b, dict) and b.get("like") == sec_idx:
                b.setdefault("page_break", True)
                return

    @staticmethod
    def _first_text_para(paras):
        """첫 쪽의 첫 글 문단(표·그림 없이 글이 있는 문단 — 날짜 줄 등). 조종 조각(쪽 번호 넣기·새 번호로 시작)을 두는 자리."""
        return next((q for q in paras[:6] if para_text(q).strip() and not para_tables(q) and not para_pics(q)), None)

    def cover_numbers(self, paras):
        """표지에는 쪽 번호를 감추고(쪽 번호 감추기), 본문 첫 쪽부터 1로 다시 센다(새 번호로 시작)."""
        end = cover_end(paras)
        if end is None:
            return
        # '새 번호로 시작'을 제목 상자(쪽 너비 표) 앞에 따로 두면 한글이 그 표를 다음 줄로 밀어 제목 위에 빈 줄이 생긴다
        # (한글 확인 2026-11-01) — 같은 쪽의 첫 글 문단(날짜 줄 등) 맨 앞에 둔다
        first_text = next((q for q in paras[end:end + 4] if para_text(q).strip() and not para_tables(q)), None)
        for p, tag, attrs in ((paras[0], "hp:pageHiding",
                               (("hideHeader", "0"), ("hideFooter", "0"), ("hideMasterPage", "0"), ("hideBorder", "0"),
                                ("hideFill", "0"), ("hidePageNum", "1"))),
                              (first_text if first_text is not None else paras[end], "hp:newNum",
                               (("num", "1"), ("numType", "PAGE")))):
            if p is first_text:
                ctrl = etree.Element(T("hp:ctrl"))
                el = etree.SubElement(ctrl, T(tag))
                for k, v in attrs:
                    el.set(k, v)
                para_runs(p)[0].insert(0, ctrl)
                continue
            runs = para_runs(p)
            at = sum(1 for r in runs if any(is_struct(ch) for ch in r))  # 쪽 설정 run 뒤
            r = copy.deepcopy(runs[min(at, len(runs) - 1)])
            for ch in list(r):
                r.remove(ch)
            ctrl = etree.SubElement(r, T("hp:ctrl"))
            el = etree.SubElement(ctrl, T(tag))
            for k, v in attrs:
                el.set(k, v)
            p.insert(list(p).index(runs[at]) if at < len(runs) else len(p), r)

    def check_summary(self, blocks):
        """요약 상자(제목 상자 뒤 첫 한 칸 상자)는 번호·여러 항목 없이 한 문장으로 두세 줄, 끝맺음은 '~하고자 함' 또는
        '~에 대한 보고임'(사용자 원칙 2026-11-01)."""
        seen_title = False
        for b in blocks:
            proto = self._proto_of(b)
            if proto is None:
                continue
            if not para_tables(proto) and marker_level(para_text(proto)) == 1:
                return
            tables = para_tables(proto)
            if not tables or tables[0].get("rowCnt") != "1" or tables[0].get("colCnt") != "1":
                continue
            if proto.find(".//" + T("hp:secPr")) is not None or not seen_title:
                seen_title = seen_title or proto.find(".//" + T("hp:secPr")) is not None
                continue
            text = b.get("text") if isinstance(b.get("text"), str) else ""
            if "\n" in text.strip() or re.search(r"[①-⑳]|(^|\n)\s*(\d+[.)]|[-○·])\s", text):
                self.warn(f"블록 {b.get('_src')}: 요약 상자에는 번호·여러 항목을 넣지 않습니다 — 한 문장으로 두세 줄에 쓰세요"
                          "(세부 항목은 아래 □·○로).")
            if text.strip() and not SUMMARY_END_RE.search(text.strip()):
                self.warn(f"블록 {b.get('_src')}: 요약 상자 끝맺음은 ‘~하고자 함’ 또는 ‘~에 대한 보고임’으로 하세요"
                          f"(지금: ‘…{text.strip()[-12:]}’).")
            return

    def check_date_line(self, blocks):
        """제목 상자 아래 날짜·부서 줄은 빼지 않는다(사용자 원칙 2026-11-01 — ChatGPT가 날짜·부서를 받지 못하자 줄을
        통째로 뺀 일이 있음). 견본에 날짜 줄 문단이 있는데 계획이 그 줄을 쓰지 않으면 알린다. 모르면 ○로 채운다."""
        dates = [i for i, p in enumerate(self.protos) if not para_tables(p) and DATE_LINE_RE.match(para_text(p))]
        if not dates or not blocks:
            return
        for b in blocks:
            if isinstance(b, dict) and (b.get("like") in dates
                                        or DATE_LINE_RE.match(b.get("text") if isinstance(b.get("text"), str) else "")):
                return
        self.warn(f"날짜·부서 줄이 없습니다 — 제목 상자 바로 아래에 날짜·부서 줄(like {dates[0]})을 넣으세요. 날짜·부서를 "
                  "모르면 줄을 빼지 말고 ‘’26. ○. ○.(○)\\t○○○○과 ○○○’처럼 ○로 채웁니다.")

    def check_endings(self, out):
        """보고서 문장·항목은 '~으로'로 끝내지 않는다 — '통제 가능한 항목으로 편성'처럼 뒤에 할 일을 붙인다
        (사용자 원칙 2026-11-01). 끝 괄호(보충 설명)는 떼고 본다."""
        hits = []
        for p in out:
            for q in [p] + [c for t in para_tables(p) for _, _, _, _, tc in table_grid(t) for c in cell_paras(tc)]:
                text = para_text(q).replace("⎵", " ").replace("⍽", " ").strip()
                while True:
                    cut = re.sub(r"\s*\([^()]*\)\s*$", "", text).rstrip(" .")
                    if cut == text:
                        break
                    text = cut
                last = text.split(" ")[-1] if text else ""
                if last.endswith("로") and len(last) >= 2 and not last.endswith(LO_WORDS):
                    hits.append(f"‘…{text[-16:]}’")
        if hits:
            self.warn(f"‘~으로’로 끝나는 줄 {len(hits)}곳({', '.join(hits[:6])}{' 등' if len(hits) > 6 else ''}): "
                      "보고서 문장은 ‘~으로’로 끝내지 않습니다 — ‘통제 가능한 항목으로 편성’처럼 뒤에 할 일(편성·배정·전환 등)을 붙이세요.")

    def build(self, plan):
        blocks = plan["blocks"] if isinstance(plan, dict) else plan
        if not blocks:
            raise BuildError("계획에 블록이 하나도 없습니다.")
        opts = plan if isinstance(plan, dict) else {}
        blocks = [dict(b, _src=n + 1) if isinstance(b, dict) else b for n, b in enumerate(blocks)]
        blocks = self.table_units(blocks)  # 이름표 맞추기 등이 '(기준 : …)'을 괄호 이름표로 다루기 전에
        if opts.get("basis_first", True):
            blocks = self.basis_first(blocks)
        self.keep_numbers = opts.get("keep_numbers", True)
        self.colons = opts.get("colons", True)
        if opts.get("join_titles", True):
            self.join_titles(blocks)
        if opts.get("space_blocks", True):
            blocks = self.space_blocks(blocks)
        if opts.get("number_items", True):
            self.number_items(blocks)
        if opts.get("align_labels", True):
            self.align_labels(blocks)
        if opts.get("table_notes", True):
            self.table_notes(blocks)
        self.cover_break(blocks)
        self.check_summary(blocks)
        self.check_date_line(blocks)
        out = [self.make_block(n, b) for n, b in enumerate(blocks)]
        self.flow_gaps(out)
        self.lone_dashes(out)
        self.check_endings(out)
        self.ref_bullets(out)
        if opts.get("keep_groups", True):
            self.keep_groups(out)
        first = out[0]
        k = 0
        for r in self.struct_runs:
            if r.find(T("hp:secPr")) is None and self._first_text_para(out) is not None:
                # 쪽 번호 넣기 같은 조종 조각을 제목 상자(쪽 너비 표) 앞에 두면 한글이 그 조각에 한 줄을 주고 표를
                # 다음 줄로 밀어 제목 위에 빈 공간(10pt 한 줄 ≈ 3.5mm)이 생긴다(한글 확인 2026-11-03, 사용자 원칙 36번:
                # 제목 위에는 공간을 두지 않는다). 쪽 설정(secPr)만 첫 문단에 두고 나머지는 첫 글 문단(날짜 줄) 맨 앞에 둔다.
                self._first_text_para(out).insert(0, r)
                continue
            first.insert(k, r)
            k += 1
        if first.get("pageBreak") == "1":
            first.set("pageBreak", "0")
        self.cover_numbers(out)
        for ch in list(self.sec):
            self.sec.remove(ch)
        for p in out:
            self.sec.append(p)
        if opts.get("word_wrap", True):
            self.word_wrap()
        if opts.get("paren_small", 2):
            self.small_parens(opts.get("paren_small", 2))
        if opts.get("note_small", True):
            self.small_notes()
        if opts.get("tighten_quotes", True):
            self.tighten_quotes()
        if self.colons or opts.get("label_hang", True):
            self.colon_hang(colons=self.colons, labels=opts.get("label_hang", True))
        self.fit_notes = []
        if opts.get("fit", True):
            f = Fitter(self)
            f.push = opts.get("push_down", True)  # 끝 줄 한두 낱말 내리기(끄면 올리기만)
            f.fit_tables()
            f.fit_lines()
            f.order_hints()  # 쪽 나눔을 박기 전, 같은 조건으로 순서 바꾸기를 견줌
            f.fit_pages()
            f.relieve_pads()
            f.spread_pages()
            f.fit_refs()
            f.fit_cover()
            if opts.get("pull_corner", True):
                f.pull_corners()  # 맨 마지막: 내어쓰기를 다시 재는 단계들 뒤에(아랫줄은 그대로, 낫표만 당김)
            self.fit_notes = f.notes + [f.report()]
        self._finish(opts)

    # ------------------------------------------------------------ 마무리
    def _drop_unused_images(self):
        """결과 문서가 쓰지 않는 견본 그림(표지를 안 쓰면 대구시 마크·슬로건 등)은 묶음에서 뺀다."""
        if "Contents/content.hpf" not in self.pkg.data:
            return
        used = set()
        for name in ["Contents/header.xml"] + self.sec_names[:1]:
            for el in self.pkg.xml(name).iter():
                v = el.get("binaryItemIDRef")
                if v:
                    used.add(v)
        hpf = self.pkg.xml("Contents/content.hpf")
        for it in list(hpf.iter(T("opf:item"))):
            href = it.get("href", "")
            if href.startswith("BinData/") and it.get("id") not in used:
                it.getparent().remove(it)
                self.pkg.data.pop(href, None)

    def _finish(self, plan):
        used = set()
        for p in self.sec.iter(T("hp:p")):
            p.set("id", new_id(used))
        for tag in ("hp:tbl", "hp:pic", "hp:rect", "hp:line", "hp:ellipse", "hp:container", "hp:equation"):
            for el in self.sec.iter(T(tag)):
                if el.get("id") is not None:
                    el.set("id", new_id(used))
        for name in self.sec_names[1:]:
            self.pkg.drop_section(name)
            self.warn(f"견본의 {name}(둘째 구역부터)은 결과 문서에서 뺐습니다.")
        head = self.pkg.xml("Contents/header.xml")
        if head.get("secCnt"):
            head.set("secCnt", "1")
        self._drop_unused_images()
        first_id = next(self.sec.iter(T("hp:p"))).get("id")
        if "settings.xml" in self.pkg.data:
            st = self.pkg.xml("settings.xml")
            for el in st.iter():
                if el.tag.endswith("CaretPosition"):
                    el.set("listIDRef", "0")
                    el.set("paraIDRef", first_id)
                    el.set("pos", "0")
        if plan.get("title") and "Contents/content.hpf" in self.pkg.data:
            hpf = self.pkg.xml("Contents/content.hpf")
            t = hpf.find(".//{http://www.idpf.org/2007/opf/}title")
            if t is not None:
                t.text = plan["title"]
        text = "\r\n".join(para_text(p) for p in self.sec if p.tag == T("hp:p"))
        if "Preview/PrvText.txt" in self.pkg.data:
            self.pkg.data["Preview/PrvText.txt"] = text[:1000].encode("utf-16-le")
        if "Preview/PrvImage.png" in self.pkg.data:
            self.pkg.data["Preview/PrvImage.png"] = blank_png()


def main():
    ap = argparse.ArgumentParser(description="견본 hwpx의 서식으로 새 문서를 만든다")
    ap.add_argument("--template", required=True, help="견본 hwpx")
    ap.add_argument("--plan", required=True, help="계획 파일(JSON)")
    ap.add_argument("--out", required=True, help="만들 hwpx")
    a = ap.parse_args()
    if os.path.abspath(a.template) == os.path.abspath(a.out):
        raise SystemExit("견본 파일에 덮어쓰지 않습니다. --out에 다른 이름을 주세요.")
    with open(a.plan, encoding="utf-8") as f:
        try:
            plan = json.load(f)
        except json.JSONDecodeError as e:
            raise SystemExit(f"계획 파일이 JSON 모양이 아닙니다: {e}")
    pkg = Package(a.template)
    try:
        b = Builder(pkg, base_dir=os.path.dirname(os.path.abspath(a.plan)))
        b.build(plan)
    except BuildError as e:
        raise SystemExit(f"만들지 못함 — {e}")
    pkg.save(a.out)
    print(f"만듦: {a.out}")
    if b.image_notes:
        b.warnings.append(f"표 칸 배경 그림 {len(b.image_notes)}개를 넣었습니다({', '.join(b.image_notes)}) — 칸 높이를 그림 비율에 맞춤.")
    errors, notes, outline = check(a.out)
    fix = [w for w in b.warnings + b.fit_notes if FIX_RE.search(w)]
    info = [w for w in b.warnings + b.fit_notes if not FIX_RE.search(w)]
    if fix or errors or notes:
        print("## 고쳐야 함(전하기 전에 계획을 고쳐 다시 만들 것)")
        for w in fix:
            print(" - " + w)
    if info:
        print("## 알림(참고 — 도구가 한 일, 한글 없이 어림한 결과라 마지막 확인은 한글에서)")
        for w in info:
            print(" - " + w)
    tell = margin_note(page_info(b.sec))
    if tell:
        print("## 사용자에게 전할 말(결과를 건넬 때마다 빠짐없이 그대로 옮길 것)")
        print(" - " + tell)
    print_report(errors, notes, outline)
    sys.exit(1 if errors else 0)


def margin_note(pi):
    """만든 문서의 여백 안내 한 줄(사용자 요청 2026-11-03: 결과를 줄 때마다 여백이 몇 mm인지 알리고, 온나라 공문에
    붙여 넣을 때는 [쪽] → [편집 용지]에서 왼쪽·오른쪽 여백을 맞추라고 — 본문 폭이 같아야 도구가 맞춘 줄 바꿈이 그대로 감).
    한글은 위 여백 다음 머리말 칸, 그 아래부터 본문이므로 본문 칸 위·아래 = 여백 + 머리말·꼬리말."""
    if not pi or "left" not in pi:
        return None
    f = lambda v: f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}"  # noqa: E731
    paper = "A4" if sorted((round(pi["width"]), round(pi["height"]))) == [210, 297] else f"{f(pi['width'])}×{f(pi['height'])}mm"
    top, bottom = pi["top"] + pi["header"], pi["bottom"] + pi["footer"]
    return (f"여백: {paper}, 본문 칸 위 {f(top)}·아래 {f(bottom)}·왼쪽 {f(pi['left'])}·오른쪽 {f(pi['right'])}mm"
            f"(용지 여백 위 {f(pi['top'])}·아래 {f(pi['bottom'])}mm에 머리말·꼬리말 {f(pi['header'])}·{f(pi['footer'])}mm). "
            f"온나라 공문에 붙여 넣으실 때는 [쪽] → [편집 용지]에서 왼쪽·오른쪽 여백을 {f(pi['left'])}·{f(pi['right'])}mm로 "
            "맞춰 주세요(그래야 줄 바꿈이 그대로 갑니다).")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
