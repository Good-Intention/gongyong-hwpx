# -*- coding: utf-8 -*-
"""양식 칸 채우기: 양식 파일(신청서·안내서)의 표 칸에 글을 넣고 정돈까지 한다. 원본은 덮어쓰지 않는다.

    python scripts/form_fill.py 양식.hwpx --list                  # 문단·표·칸 번호를 본다
    python scripts/form_fill.py 양식.hwpx --plan 계획.json --out 결과.hwpx [--max-pages 5] [--no-tidy]

계획(JSON):
    {"keep": [12, 18],                    # 남길 문단 번호(처음~끝, 없으면 모두) — 여러 양식이 든 파일에서 한 양식만
     "drop": [15],                        # 그 안에서 뺄 문단(안내문)
     "pt": 10, "line": 125,               # (선택) 보고글 글자 크기·줄 간격(칸마다 줄 수도 있음). 줄 간격 없으면 양식 값, 130%보다 넓으면 130%
     "cells": [{"para": 14, "row": 1, "col": 1, "lines": [
                   "□ **제목**", "○ **이름표** : 내용", "- 세부",
                   {"table": [["구분", "값"], ["가", "1"]], "widths": [3, 1]},               # 칸 안 표(첫 줄이 머리, widths는 비율·없으면 글 길이로)
                   {"images": [{"image": "a.png", "caption": "설명"}, {"image": "b.png", "caption": "설명"}], "cols": 2}]},  # 칸 안 그림
               {"para": 14, "row": 0, "col": 1, "text": "짧은 글"},
               {"para": 14, "row": 2, "col": 1, "text": ""}],   # 안내문 지우기
     "widths_mm": {"14": [27, 143]}}      # (선택) 표 칸 너비 — 양식을 바꾸는 일이라 사용자가 허락할 때만

lines: 보고글(양쪽 정렬·검정 글자, 내어쓰기·간격·끝선은 정돈이 맞춤). ※ 줄은 1pt 작게. text: 칸의 정렬을 그대로 둔 짧은 글. **굵게** 쓸 수 있다.
lines를 넣은 표는 첫 줄이 짧은 머리 줄이면 쪽마다 반복한다(끄려면 "repeat_head": false). 칸 안 표는 칸 폭에 맞추고 글자는 보고글보다 1pt 작게, 칸 높이는 글 줄 수에 맞춘다. 칸 안 그림은 cols개씩 작은 표로 나눠(한 덩어리면 쪽을 못 넘김) 칸 배경으로
넣고, 같은 줄 그림은 칸 비율에 맞춰 흰 여백을 붙인다(자르지 않음, 설명은 2pt 작게). height_mm로 그림 높이의 상한을 준다.
안내문의 파란 기울임 글자 모양은 쓰지 않고 검정 보통 글자로 복제한다. 쪽 설정은 남긴 첫 문단으로 옮기고, 모아찍기 인쇄는 끈다.
"""
import argparse
import copy
import os
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from build_base import IMAGE_MAX_PX, encode_image  # noqa: E402
from hwpx_lib import (COMPOSE_CHAR, HWPUNIT_PER_MM, T, HeaderEdit, Package, Styles, cell_paras, drop_linesegs, etree, is_struct, new_id, para_runs,  # noqa: E402
                      para_tables, para_text, read_plan, run_text, same_path, set_run_text, table_grid)
from layout import Layout, Metrics  # noqa: E402
from tidy import tidy_file  # noqa: E402

CELL_LINE_MAX = 130  # 칸 보고글 줄 간격(%) — 사용자 표 안 보고서 실측 125·130%. 양식 값이 더 넓으면 이 값으로
INNER_LINE = 115  # 칸 안 표·그림 설명의 줄 간격(%)
INNER_GAP = 30  # 칸 안 표 문단 위아래 간격(HWPUNIT)
INNER_PAD = (200, 200, 60, 60)  # 칸 안 표 칸 여백(왼·오른·위·아래)
INNER_LINE_STYLE = ("SOLID", "0.15 mm", "#BBBBBB")
INNER_HEAD_FILL = "#D9D9D9"
INNER_SPARE = 100  # 칸 안 표 줄 높이 여유 — 칸 안 표는 칸이 저절로 늘지 않아, 모자라면 글 윗줄이 잘린다(사용자 견본: 9pt 한 줄 1250, 세 줄 3350)
INNER_SHORT = 8  # 본문 칸이 모두 이 글자 수 이하인 열은 가운데 정렬
IMAGE_TALL = 0.75  # 칸 안 그림 높이 기본 상한(칸 너비의 배수) — 세로 사진은 양옆에 여백
IMAGE_MIN_H = 1500  # 그림 줄 높이 하한(약 5mm) — 빈 문단 높이(약 920)보다 낮으면 한글이 줄을 늘려 그림이 세로로 늘어남
INNER_MIN_WIDTH = 5670  # 칸 안 표·그림을 넣을 칸 안쪽 폭 하한(20mm)
INNER_MIN_COL = 850  # 칸 안 표 한 칸 폭 하한(3mm — 칸 여백보다 좁으면 글이 안 들어감)
WIDTH_MIN_MM = 3  # widths_mm 칸 너비 하한


class FormError(Exception):
    pass


class Ctx:
    """칸 채우기에 함께 쓰는 것들."""

    def __init__(self, pkg, styles, hedit, sec, base_dir, plan):
        self.pkg, self.styles, self.hedit, self.base_dir, self.plan = pkg, styles, hedit, base_dir, plan
        self.lay = Layout(styles, Metrics())
        self.tbl_id = max((int(t.get("id", "0")) for t in sec.iter(T("hp:tbl"))), default=1000000000) + 1
        self.z = max((int(t.get("zOrder", "0")) for t in sec.iter(T("hp:tbl"))), default=0) + 1
        self.image_seq = 0
        self.inner = []  # 칸 안 표 (표가 든 문단, 표, 칸 폭, 계획에 widths가 있나) — 다 채운 뒤 본문 표 규칙을 건다(fit_inner)


def _is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def _is_num(x):
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def check_line(value, where):
    if not (_is_int(value) and 80 <= value <= 300):
        raise FormError(f"{where}: line(줄 간격 %)은 80~300 사이 정수여야 합니다.")


def top_paras(sec):
    return [p for p in sec if p.tag == T("hp:p")]


def show(path):
    """문단 번호·글, 표는 칸마다 줄·칸 번호와 글 앞부분."""
    pkg = Package(path)
    sec = pkg.xml(pkg.sections()[0])
    for k, p in enumerate(top_paras(sec)):
        tables = para_tables(p)
        if not tables:
            print(f"[{k}] {para_text(p).replace('⎵', ' ')[:60]}")
            continue
        for tn, t in enumerate(tables):
            print(f"[{k}] 표{'' if not tn else ' ' + str(tn)} {t.get('rowCnt')}줄×{t.get('colCnt')}칸")
            for r, c, rs, cs, tc in table_grid(t):
                text = " / ".join(para_text(cp).replace("⎵", " ").strip() for cp in cell_paras(tc) if para_text(cp).strip())
                span = f" 합침 {rs}×{cs}" if rs > 1 or cs > 1 else ""
                print(f"     ({r},{c}){span} {text[:60]}")
    if len(pkg.sections()) > 1:
        print(f"※ 이 파일은 구역이 {len(pkg.sections())}개입니다 — 위 번호는 첫 구역만. 칸 채우기도 첫 구역만 합니다.")


def plain_char(hedit, cid):
    """같은 글꼴·크기의 검정 보통 글자 — 안내문의 파란 기울임을 쓰지 않음."""
    key = ("plain", cid)
    if key not in hedit.cache:
        new = hedit._clone("hh:charProperties", "hh:charPr", cid)
        new.set("textColor", "#000000")
        for tag in ("hh:italic", "hh:bold"):
            el = new.find(T(tag))
            if el is not None:
                new.remove(el)
        ul = new.find(T("hh:underline"))
        if ul is not None:
            ul.set("type", "NONE")
        hedit.styles.char[new.get("id")] = hedit.styles._char(new)
        hedit.cache[key] = new.get("id")
    return hedit.cache[key]


def bold_char(hedit, cid):
    key = ("bold", cid)
    if key not in hedit.cache:
        new = hedit._clone("hh:charProperties", "hh:charPr", cid)
        if new.find(T("hh:bold")) is None:
            el = etree.Element(T("hh:bold"))
            ul = new.find(T("hh:underline"))
            if ul is not None:  # 한글이 쓰는 차례: … 기울임·굵게 다음 밑줄
                ul.addprevious(el)
            else:
                new.append(el)
        hedit.styles.char[new.get("id")] = hedit.styles._char(new)
        hedit.cache[key] = new.get("id")
    return hedit.cache[key]


def first_char(tc, styles):
    """칸의 글자 모양 하나 — 글이 있는 조각 먼저, 가장 흔한 크기."""
    runs = [r for cp in cell_paras(tc) for r in para_runs(cp)]
    with_text = [r for r in runs if run_text(r).strip()] or runs
    if not with_text:
        raise FormError("칸에 글자 모양이 없습니다.")
    return with_text[0].get("charPrIDRef")


def make_para(proto, text, cid, bold, pid):
    p = copy.deepcopy(proto)
    drop_linesegs(p)
    for ch in list(p):
        if ch.tag == T("hp:run"):
            p.remove(ch)
    p.set("paraPrIDRef", pid)
    parts = [x for x in re.split(r"(\*\*.+?\*\*)", text) if x] or [""]
    for part in parts:
        r = etree.SubElement(p, T("hp:run"))
        strong = part.startswith("**") and part.endswith("**") and len(part) > 4
        r.set("charPrIDRef", bold if strong else cid)
        set_run_text(r, part[2:-2] if strong else part)
    return p


def sized(hedit, cid, pt):
    """글자 크기를 pt로 맞춘 글자 모양."""
    now = hedit.styles.char.get(cid, {}).get("size") or pt
    return cid if abs(now - pt) < 0.01 else hedit.char_size(cid, pt - now)


def cell_inner_width(tc, tbl):
    """칸 안쪽 폭(칸 너비 - 왼·오른 여백). 칸 여백을 쓰지 않는 칸(hasMargin=0)은 표의 안 여백을 쓴다."""
    cm = tc.find(T("hp:cellMargin"))
    inm = tbl.find(T("hp:inMargin"))
    src = cm if tc.get("hasMargin") == "1" and cm is not None else inm
    pad = int(src.get("left", "510")) + int(src.get("right", "510")) if src is not None else 1020
    return int(tc.find(T("hp:cellSz")).get("width", "0")) - pad


def new_tbl(holder, cid, ctx, rows, cols, width, border):
    """칸 안 표 뼈대(글자처럼 취급, 쪽을 나누지 않음)를 문단 holder에 넣어 돌려준다."""
    run = etree.SubElement(holder, T("hp:run"))
    run.set("charPrIDRef", cid)
    tbl = etree.SubElement(run, T("hp:tbl"))
    ctx.tbl_id += 1
    ctx.z += 1
    for k, v in (("id", ctx.tbl_id), ("zOrder", ctx.z), ("numberingType", "TABLE"), ("textWrap", "TOP_AND_BOTTOM"), ("textFlow", "BOTH_SIDES"),
                 ("lock", 0), ("dropcapstyle", "None"), ("pageBreak", "NONE"), ("repeatHeader", 0), ("rowCnt", rows), ("colCnt", cols),
                 ("cellSpacing", 0), ("borderFillIDRef", border), ("noAdjust", 1)):
        tbl.set(k, str(v))
    for tag, attrs in (("hp:sz", (("width", width), ("widthRelTo", "ABSOLUTE"), ("height", 0), ("heightRelTo", "ABSOLUTE"), ("protect", 0))),
                       ("hp:pos", (("treatAsChar", 1), ("affectLSpacing", 0), ("flowWithText", 1), ("allowOverlap", 0), ("holdAnchorAndSO", 0),
                                   ("vertRelTo", "PARA"), ("horzRelTo", "PARA"), ("vertAlign", "TOP"), ("horzAlign", "LEFT"), ("vertOffset", 0), ("horzOffset", 0))),
                       ("hp:outMargin", (("left", 0), ("right", 0), ("top", 60), ("bottom", 60))),
                       ("hp:inMargin", zip(("left", "right", "top", "bottom"), INNER_PAD))):
        el = etree.SubElement(tbl, T(tag))
        for k, v in attrs:
            el.set(k, str(v))
    etree.SubElement(run, T("hp:t"))
    return tbl


def new_cell(tr, r, c, width, border, paras, pad=INNER_PAD):
    tc = etree.SubElement(tr, T("hp:tc"))
    for k, v in (("name", ""), ("header", 0), ("hasMargin", 1), ("protect", 0), ("editable", 0), ("dirty", 0), ("borderFillIDRef", border)):
        tc.set(k, str(v))
    sub = etree.SubElement(tc, T("hp:subList"))
    for k, v in (("id", ""), ("textDirection", "HORIZONTAL"), ("lineWrap", "BREAK"), ("vertAlign", "CENTER"), ("linkListIDRef", 0), ("linkListNextIDRef", 0),
                 ("textWidth", 0), ("textHeight", 0), ("hasTextRef", 0), ("hasNumRef", 0)):
        sub.set(k, str(v))
    for p in paras:
        sub.append(p)
    for tag, attrs in (("hp:cellAddr", (("colAddr", c), ("rowAddr", r))), ("hp:cellSpan", (("colSpan", 1), ("rowSpan", 1))),
                       ("hp:cellSz", (("width", width), ("height", 0))), ("hp:cellMargin", zip(("left", "right", "top", "bottom"), pad))):
        el = etree.SubElement(tc, T(tag))
        for k, v in attrs:
            el.set(k, str(v))
    return tc


def holder_para(proto, ctx, pid):
    """칸 안 표를 담을 문단 — 왼쪽 맞춤, 여백 없음, 위아래 조금 띄움."""
    p = copy.deepcopy(proto)
    drop_linesegs(p)
    for ch in list(p):
        if ch.tag == T("hp:run"):
            p.remove(ch)
    p.set("paraPrIDRef", pid)
    return p


def share_widths(want, total):
    """열마다 바라는 폭으로 total을 나눈다 — 다 들어가면 비율대로 늘리고, 모자라면 짧은 열은 제 폭, 남은 폭을 긴 열이 비율대로."""
    n = len(want)
    if sum(want) <= total:
        ws = [x * total / sum(want) for x in want]
    else:
        fixed, rest = {}, set(range(n))
        while rest:
            left = total - sum(fixed.values())
            fair = left / len(rest)
            small = [i for i in rest if want[i] <= fair]
            if not small:
                break
            for i in small:
                fixed[i] = want[i]
                rest.discard(i)
        left = total - sum(fixed.values())
        big = sum(want[i] for i in rest) or 1
        ws = [fixed.get(i, want[i] * left / big) for i in range(n)]
    out = [int(x) for x in ws]
    out[-1] = total - sum(out[:-1])
    return out


def set_row_heights(tbl, ctx, spare=INNER_SPARE):
    """줄 높이를 글 줄 수에 맞춘다 — 칸 높이가 모자라면 글 윗줄이 잘려 보인다(애로 4-3)."""
    rows = {}
    for r, c, _, _, tc in table_grid(tbl):
        sz = tc.find(T("hp:cellSz"))
        cm = tc.find(T("hp:cellMargin"))
        inner = int(sz.get("width")) - int(cm.get("left")) - int(cm.get("right"))
        need = sum(ctx.lay.para_height(cp, inner)[0] for cp in cell_paras(tc)) + int(cm.get("top")) + int(cm.get("bottom")) + spare
        rows[r] = max(rows.get(r, 0), int(need), int(sz.get("height", "0")))
    for r, c, _, _, tc in table_grid(tbl):
        tc.find(T("hp:cellSz")).set("height", str(rows[r]))
    tbl.find(T("hp:sz")).set("height", str(sum(rows.values())))


def inner_table(item, proto, cid, ctx, width, border, tpid, where):
    """칸 안 표 문단 — 첫 줄은 머리(회색 바탕·굵게·가운데, 머리 칸 표시), 글자는 보고글보다 1pt 작게. 칸 글은 본문 표처럼 가운데에서
    시작하고(사용자 2026-11-11 '본문표에 적용된 스킬 … 모두 적용'), 칸 너비·금액·수량 오른쪽·날짜·번호 가운데·'·' 줄 등은
    다 채운 뒤 fit_inner가 작성 모드의 표 맞춤(fit_tables)으로 맞춘다."""
    rows = item["table"]
    if not (isinstance(rows, list) and rows and all(isinstance(r, list) and r for r in rows)):
        raise FormError(f"{where}: table은 줄 목록의 목록이어야 합니다([[\"구분\", \"값\"], [\"가\", \"1\"]]).")
    n = len(rows[0])
    if any(len(r) != n for r in rows):
        raise FormError(f"{where}: 칸 안 표의 칸 수가 줄마다 다릅니다(첫 줄 {n}칸).")
    if width / n < INNER_MIN_COL:
        raise FormError(f"{where}: 칸 폭에 비해 칸 안 표의 칸이 너무 많습니다({n}칸) — 칸 수를 줄여 주세요.")
    hedit, styles = ctx.hedit, ctx.styles
    small = sized(hedit, cid, (styles.char.get(cid, {}).get("size") or 10) - 1)
    small_bold = bold_char(hedit, small)
    line = hedit.para_hang(hedit.para_margin(tpid, "prev", 0), 0)
    line = hedit.para_margin(line, "next", 0)
    left, center = hedit.para_align(line, "LEFT"), hedit.para_align(line, "CENTER")
    body = rows[1:] if item.get("head", True) else rows
    plain = lambda v: re.sub(r"\*\*", "", str(v)).strip()  # noqa: E731
    aligns = item.get("align")
    if aligns is not None and not (isinstance(aligns, list) and all(isinstance(x, str) for x in aligns)):
        raise FormError(f"{where}: align은 칸마다 \"left\"·\"center\"·\"right\"로 적은 목록이어야 합니다.")
    holder = holder_para(proto, ctx, tpid)
    grey = hedit.border_fill(border, INNER_HEAD_FILL)
    tbl = new_tbl(holder, cid, ctx, len(rows), n, width, border)
    for r, row in enumerate(rows):
        tr = etree.SubElement(tbl, T("hp:tr"))
        head = r == 0 and item.get("head", True)
        for c, text in enumerate(row):
            if not isinstance(text, (str, int, float)):
                raise FormError(f"{where}: 칸 안 표의 칸은 글이어야 합니다({r + 1}줄 {c + 1}칸).")
            al = aligns[c].upper() if aligns and c < len(aligns) else "CENTER"  # 본문 표처럼 가운데(옛 판: 긴 글 열은 왼쪽)
            pid = hedit.para_align(line, al) if al in ("LEFT", "CENTER", "RIGHT") else left
            # 칸 글의 줄 바꿈은 줄마다 문단으로(본문 표와 같게 — 한 문단 안 줄 바꿈이면 둘째 '· 항목'이 첫 줄 글 밑으로 들어감)
            cps = [make_para(proto, part, small_bold if head else small, small_bold, center if head else pid)
                   for part in (str(text).split("\n") or [""])]
            cell = new_cell(tr, r, c, width // n, grey if head else border, cps)
            if head:
                cell.set("header", "1")  # 머리 칸 — 본문 표 규칙(데이터 표)이 알아보게
    grid = table_grid(tbl)
    given = item.get("widths")
    if given is not None:
        if not (isinstance(given, list) and len(given) == n and all(_is_num(x) and x > 0 for x in given)):
            raise FormError(f"{where}: widths는 칸 수({n})만큼의 양수여야 합니다.")
        want = [float(x) for x in given]
    else:
        want = [1.0] * n
        for _, c, _, _, tc in grid:
            for cp in cell_paras(tc):
                want[c] = max(want[c], sum(x[1] for x in ctx.lay.chars(cp)) + INNER_PAD[0] + INNER_PAD[1] + 100)
    ws = share_widths(want, width)
    if given is not None and min(ws) < INNER_MIN_COL:
        raise FormError(f"{where}: widths 비율대로면 가장 좁은 칸이 너무 좁습니다 — 비율을 고쳐 주세요.")
    for _, c, _, _, tc in grid:
        tc.find(T("hp:cellSz")).set("width", str(ws[c]))
    set_row_heights(tbl, ctx)
    ctx.inner.append((holder, tbl, width, given is not None))
    return holder


def fit_inner(ctx):
    """칸 안 표에 본문 표 규칙(작성 모드 fit_tables — 칸 너비를 내용에 맞추기·옆 열 폭 빌리기·금액·수량 열 오른쪽 + 1.5mm·날짜·번호 가운데·
    '·' 줄·칸 글 줄 균형·한 줄로 입력·표 안 날짜 붙이기·△·■ 제목·단위 줄·표 밑 ※ 등)을 건다 — 같은 문서에 한 번 더 걸어 고정점으로.
    칸 안 표는 한글이 줄 높이를 늘리지 않으므로 끝에 줄 높이를 글에 맞춘다. 알림을 돌려줌."""
    if not ctx.inner:
        return []
    from build import Builder
    from fit import Fitter
    b = Builder(ctx.pkg)
    b.fixed_widths |= {tbl for _, tbl, _, fixed in ctx.inner if fixed}
    f = Fitter(b)
    targets = [(holder, tbl, width) for holder, tbl, width, _ in ctx.inner]
    f.fit_tables(inner=targets)
    f.fit_tables(again=True, inner=targets)
    for _, tbl, _, _ in ctx.inner:
        fit_row_heights(tbl, f.lay)
    return f.notes


def fit_row_heights(tbl, lay, spare=INNER_SPARE):
    """칸 안 표 줄 높이 = 글 + 칸 위아래 여백 + 여유(칸 너비가 바뀐 뒤 — 줄이 줄면 줄 높이도 줄임)."""
    rows = {}
    for r, c, _, _, tc in table_grid(tbl):
        sz = tc.find(T("hp:cellSz"))
        cm = tc.find(T("hp:cellMargin"))
        inner = int(sz.get("width")) - int(cm.get("left")) - int(cm.get("right"))
        need = sum(lay.para_height(cp, inner)[0] for cp in cell_paras(tc)) + int(cm.get("top")) + int(cm.get("bottom")) + spare
        rows[r] = max(rows.get(r, 0), int(need))
    for r, c, _, _, tc in table_grid(tbl):
        tc.find(T("hp:cellSz")).set("height", str(rows[r]))
    tbl.find(T("hp:sz")).set("height", str(sum(rows.values())))


def _add_image(ctx, data, ext):
    hpf = ctx.pkg.xml("Contents/content.hpf")
    man = hpf.find(".//" + T("opf:manifest"))
    have = {it.get("id") for it in man}
    ctx.image_seq += 1
    while f"cellimg{ctx.image_seq}" in have:
        ctx.image_seq += 1
    item_id = f"cellimg{ctx.image_seq}"
    href = f"BinData/{item_id}.{ext}"
    ctx.pkg.data[href] = data
    it = etree.SubElement(man, T("opf:item"))
    for k, v in (("id", item_id), ("href", href), ("media-type", "image/png" if ext == "png" else "image/jpg"), ("isEmbeded", "1")):
        it.set(k, v)
    return item_id


def _open_image(ctx, name, where):
    """그림을 열어 세운다(휴대전화 사진의 회전 정보대로)."""
    try:
        from PIL import Image, ImageOps, UnidentifiedImageError
    except ImportError:
        raise FormError(f"{where}: 칸 안 그림에는 그림 라이브러리(Pillow)가 필요합니다. 글만 채운 뒤 한글에서 넣어 주세요.") from None
    path = str(name)
    if not path.strip():
        raise FormError(f"{where}: 그림 파일 이름이 비었습니다.")
    if not os.path.isabs(path) and ctx.base_dir:
        path = os.path.join(ctx.base_dir, path)
    if not os.path.isfile(path):
        raise FormError(f"{where}: 그림 파일을 찾지 못했습니다: {path}")
    try:
        im = Image.open(path)
        im.load()
    except (UnidentifiedImageError, OSError):
        raise FormError(f"{where}: 그림 파일이 아니거나 깨져 읽지 못했습니다(PNG·JPEG만 됩니다): {path}") from None
    return ImageOps.exif_transpose(im)


def _pad_image(im, aspect):
    """칸 비율(가로/세로)에 맞춰 흰 여백을 붙인다(자르지 않음, 애로 4-5) — 칸 배경 그림은 칸 크기로 늘어나므로 비율이 같아야 찌그러지지 않는다."""
    from PIL import Image
    w, h = im.size
    nw, nh = (round(h * aspect), h) if w / h < aspect else (w, round(w / aspect))
    f = IMAGE_MAX_PX / max(nw, nh)
    if f < 1:  # 캔버스를 만들기 전에 줄임 — 여백이 넓으면 캔버스가 아주 커짐(검토: 큰 사진에 낮은 높이를 주면 2분 걸렸음)
        im = im.resize((max(1, round(w * f)), max(1, round(h * f))), Image.LANCZOS)
        w, h = im.size
        nw, nh = max(w, round(nw * f)), max(h, round(nh * f))
    if abs(w / h - aspect) < 0.01:
        return im
    if im.mode in ("RGBA", "LA", "P"):
        rgba = im.convert("RGBA")
        flat = Image.new("RGB", rgba.size, (255, 255, 255))
        flat.paste(rgba, mask=rgba.getchannel("A"))
        im = flat
    canvas = Image.new("RGB", (nw, nh), (255, 255, 255))
    canvas.paste(im.convert("RGB"), ((nw - w) // 2, (nh - h) // 2))
    return canvas


def inner_images(item, proto, cid, ctx, width, border, tpid, where):
    """칸 안 그림 — cols개씩 작은 표(그림 줄 + 설명 줄)로 나눈다. 한 덩어리 표는 쪽을 못 넘겨 쪽이 는다(애로 4-4)."""
    items = item["images"]
    if not (isinstance(items, list) and items and all(isinstance(x, dict) and x.get("image") for x in items)):
        raise FormError(f"{where}: images는 [{{\"image\": \"a.png\", \"caption\": \"설명\"}}] 꼴이어야 합니다.")
    cols = item.get("cols", 2)
    if not (_is_int(cols) and 1 <= cols <= 6):
        raise FormError(f"{where}: cols(한 줄 그림 수)는 1~6 사이 정수여야 합니다.")
    hedit, styles = ctx.hedit, ctx.styles
    small = sized(hedit, cid, (styles.char.get(cid, {}).get("size") or 10) - 2)
    line = hedit.para_margin(hedit.para_hang(hedit.para_margin(tpid, "prev", 0), 0), "next", 0)
    center = hedit.para_align(line, "CENTER")
    cw = width // cols
    tall = item.get("height_mm")
    if tall is not None and not (_is_num(tall) and 10 <= tall <= 250):
        raise FormError(f"{where}: height_mm(그림 높이 상한)는 10~250 사이 숫자여야 합니다.")
    cap = tall * HWPUNIT_PER_MM if tall is not None else cw * IMAGE_TALL
    out = []
    for k in range(0, len(items), cols):
        part = items[k:k + cols]
        opened = [_open_image(ctx, x["image"], f"{where} 그림 {k + i + 1}") for i, x in enumerate(part)]
        h = max(IMAGE_MIN_H, int(min(cap, max(cw * im.size[1] / im.size[0] for im in opened))))
        holder = holder_para(proto, ctx, tpid)
        tbl = new_tbl(holder, cid, ctx, 2, len(part), cw * len(part), border)
        pics, caps = etree.SubElement(tbl, T("hp:tr")), etree.SubElement(tbl, T("hp:tr"))
        for c, (x, im) in enumerate(zip(part, opened)):
            data, ext, _, _ = encode_image(_pad_image(im, cw / h))
            bid = hedit.border_image(border, _add_image(ctx, data, ext))
            tc = new_cell(pics, 0, c, cw, bid, [make_para(proto, "", small, small, center)], pad=(0, 0, 0, 0))
            tc.find(T("hp:cellSz")).set("height", str(h))
            new_cell(caps, 1, c, cw, border, [make_para(proto, str(x.get("caption") or ""), small, small, center)])
        set_row_heights(tbl, ctx, spare=0)
        out.append(holder)
    return out


def fill_cell(tc, spec, ctx, tbl, where):
    styles, hedit = ctx.styles, ctx.hedit
    proto = cell_paras(tc)[0]
    sub = tc.find(T("hp:subList"))
    if sub is None:
        raise FormError(f"{where}: 칸 구조를 읽지 못했습니다.")
    cid = plain_char(hedit, first_char(tc, styles))
    pt = spec.get("pt", ctx.plan.get("pt"))
    if pt is not None:
        if not (isinstance(pt, (int, float)) and 6 <= pt <= 30):
            raise FormError(f"{where}: pt(글자 크기)는 6~30 사이 숫자여야 합니다.")
        cid = sized(hedit, cid, pt)
    bold = bold_char(hedit, cid)
    pid0 = proto.get("paraPrIDRef")
    if "lines" in spec:
        lines = spec["lines"]
        if not isinstance(lines, list) or not all(isinstance(x, str) or (isinstance(x, dict) and ("table" in x or "images" in x)) for x in lines):
            raise FormError(f"{where}: lines는 글 또는 {{\"table\": …}}·{{\"images\": …}}의 목록이어야 합니다.")
        pid = hedit.para_align(pid0, "JUSTIFY")  # 윗줄이 끝선에 닿게(사용자 2026-11-09)
        pid = hedit.para_hang(hedit.para_margin(pid, "left", 0), 0)
        want = spec.get("line", ctx.plan.get("line"))
        cur = styles.para.get(pid, {})
        if want is None and cur.get("line_type", "PERCENT") == "PERCENT" and cur.get("line", 160) > CELL_LINE_MAX:
            want = CELL_LINE_MAX
        if want is not None:
            check_line(want, where)
            pid = hedit.para_line(pid, want)
    elif isinstance(spec.get("text"), str):
        lines, pid = spec["text"].split("\n"), pid0
        if pt is not None and "line" in spec:
            check_line(spec["line"], where)
            pid = hedit.para_line(pid, spec["line"])
    else:
        raise FormError(f"{where}: 칸마다 lines(글 목록) 또는 text(짧은 글)가 있어야 합니다.")
    made = []
    width = cell_inner_width(tc, tbl) - 60  # 칸 선에 닿지 않게
    tpid = None
    if any(isinstance(x, dict) for x in lines):
        if width < INNER_MIN_WIDTH:
            raise FormError(f"{where}: 칸이 좁아({max(width, 0) / HWPUNIT_PER_MM:.0f}mm) 칸 안 표·그림을 넣지 못합니다 — 칸을 넓히거나 글로 써 주세요.")
        tpid = hedit.para_line(hedit.para_margin(hedit.para_margin(hedit.para_hang(hedit.para_margin(hedit.para_align(pid0, "LEFT"), "left", 0), 0), "prev", INNER_GAP), "next", INNER_GAP), INNER_LINE)
        base = tc.get("borderFillIDRef")
        border = hedit.border_lines(base, *INNER_LINE_STYLE)
    small_mark = None
    for n, line in enumerate(lines or [""], 1):
        if isinstance(line, dict):
            kw = dict(proto=proto, cid=cid, ctx=ctx, width=width, border=border, tpid=tpid, where=f"{where} {n}번째 줄")
            if "table" in line:
                for key in ("title", "unit"):  # 본문 표처럼 ■ 제목·기준·단위 줄(모양은 fit_inner가 본문 규칙대로)
                    v = line.get(key)
                    if v is not None and not (isinstance(v, str) and v.strip()):
                        raise FormError(f"{where} {n}번째 줄: {key}는 글이어야 합니다.")
                if line.get("title"):
                    t = line["title"].strip()
                    made.append(make_para(proto, t if t.startswith("■") else "■ " + t, bold, bold,
                                          hedit.para_align(hedit.para_hang(hedit.para_margin(pid0, "left", 0), 0), "LEFT")))
                if line.get("unit"):
                    made.append(make_para(proto, line["unit"].strip(), cid, bold,
                                          hedit.para_align(hedit.para_hang(hedit.para_margin(pid0, "left", 0), 0), "RIGHT")))
                made.append(inner_table(line, **kw))
            else:
                made.extend(inner_images(line, **kw))
        elif "lines" in spec and line.lstrip().startswith("※"):
            small_mark = small_mark or sized(hedit, cid, (styles.char.get(cid, {}).get("size") or 10) - 1)
            made.append(make_para(proto, line, small_mark, bold_char(hedit, small_mark), pid))
        else:
            made.append(make_para(proto, line, cid, bold, pid))
    for cp in cell_paras(tc):
        sub.remove(cp)
    for p in made:
        sub.append(p)


def repeat_head(tbl):
    """표 칸 안 보고서는 쪽을 넘으므로 첫 줄(구분·내용 같은 짧은 머리 줄)을 쪽마다 반복한다(사용자 견본). 표 속성만 — 첫 쪽 모양은 그대로."""
    grid = table_grid(tbl)
    first = [tc for r, _, _, _, tc in grid if r == 0]
    if int(tbl.get("rowCnt", "1")) < 3 or tbl.get("pageBreak") == "NONE" or len(first) < 2:  # '❶ 참가 정보'처럼 한 칸짜리 줄은 머리 줄이 아님
        return
    if not all(len(cell_paras(tc)) == 1 and 0 < len(para_text(cell_paras(tc)[0]).strip()) <= INNER_SHORT for tc in first):
        return
    tbl.set("repeatHeader", "1")
    for tc in first:
        tc.set("header", "1")


def set_widths(tbl, mm, where):
    n = int(tbl.get("colCnt", "1"))
    if not (isinstance(mm, list) and len(mm) == n and all(_is_num(x) and x >= WIDTH_MIN_MM for x in mm)):
        raise FormError(f"{where}: widths_mm는 칸 수({n})만큼의 숫자({WIDTH_MIN_MM}mm 이상)여야 합니다.")
    ws = [int(round(x * HWPUNIT_PER_MM)) for x in mm]
    for _, c, _, cs, tc in table_grid(tbl):
        tc.find(T("hp:cellSz")).set("width", str(sum(ws[c:c + cs])))
    tbl.find(T("hp:sz")).set("width", str(sum(ws)))


def check_plan(plan, n):
    """계획 모양 — 틀리면 어디가 틀렸는지 쉬운 말로(검토: 모양이 틀리면 파이썬 오류로 멈췄음)."""
    if not isinstance(plan, dict):
        raise FormError("계획은 { … } 꼴이어야 합니다.")
    cells = plan.get("cells")
    if cells is not None and not isinstance(cells, list):
        raise FormError("cells는 칸 목록이어야 합니다([{\"para\": 1, \"row\": 0, \"col\": 0, \"text\": \"글\"}]).")
    keep = plan.get("keep")
    if keep is not None and not (isinstance(keep, list) and len(keep) == 2 and all(_is_int(x) for x in keep)):
        raise FormError(f"keep은 [처음, 끝] 문단 번호여야 합니다(0~{n - 1}).")
    drop = plan.get("drop")
    if drop is not None and not (isinstance(drop, list) and all(_is_int(x) for x in drop)):
        raise FormError("drop은 뺄 문단 번호의 목록이어야 합니다.")
    out = [x for x in drop or [] if not 0 <= x < n]
    if out:
        raise FormError(f"drop: {out[0]}번 문단이 없습니다(0~{n - 1}).")
    if plan.get("widths_mm") is not None and not isinstance(plan["widths_mm"], dict):
        raise FormError("widths_mm는 {\"문단 번호\": [칸 너비 mm, …]} 꼴이어야 합니다.")


def fill(path, plan, out, base_dir=None):
    if not isinstance(plan, dict):
        raise FormError("계획은 { … } 꼴이어야 합니다.")
    pkg = Package(path)
    head = pkg.xml("Contents/header.xml")
    styles = Styles(head)
    hedit = HeaderEdit(head, styles)
    names = pkg.sections()
    sec = pkg.xml(names[0])
    tops = top_paras(sec)
    check_plan(plan, len(tops))
    ctx = Ctx(pkg, styles, hedit, sec, base_dir, plan)
    # 칸 너비 먼저 — 칸 안 표가 칸 폭에 맞춘다
    for key, mm in (plan.get("widths_mm") or {}).items():
        try:
            k = int(key)
        except ValueError:
            raise FormError(f"widths_mm: '{key}'는 문단 번호가 아닙니다.") from None
        if not 0 <= k < len(tops) or not para_tables(tops[k]):
            raise FormError(f"widths_mm: {k}번 문단은 표가 아닙니다.")
        set_widths(para_tables(tops[k])[0], mm, f"widths_mm {k}번")
    # 칸 채우기(문단 번호는 원본 기준이므로 떼기 전에)
    for n, spec in enumerate(plan.get("cells") or [], 1):
        where = f"칸 {n}"
        try:
            para, row, col = spec["para"], spec["row"], spec["col"]
        except (KeyError, TypeError):
            raise FormError(f"{where}: para·row·col(문단·줄·칸 번호)이 있어야 합니다 — --list로 번호를 보세요.") from None
        if not isinstance(para, int) or not 0 <= para < len(tops) or not para_tables(tops[para]):
            raise FormError(f"{where}: {para}번 문단은 표가 아닙니다 — --list로 번호를 보세요.")
        tables, tn = para_tables(tops[para]), spec.get("table", 0)
        if not _is_int(tn) or not 0 <= tn < len(tables):
            raise FormError(f"{where}: {para}번 문단에 {tn}번 표가 없습니다(표 {len(tables)}개, 0부터 셉니다).")
        tbl = tables[tn]
        tc = next((x[4] for x in table_grid(tbl) if x[0] == row and x[1] == col), None)
        if tc is None:
            raise FormError(f"{where}: {para}번 표에 ({row},{col}) 칸이 없습니다(합친 칸은 왼쪽 위 칸 번호로).")
        fill_cell(tc, spec, ctx, tbl, where)
        if "lines" in spec and plan.get("repeat_head", True):
            repeat_head(tbl)
    for note in fit_inner(ctx):  # 칸 안 표에 본문 표 규칙
        print("알림(칸 안 표): " + str(note))
    # 양식 구간 떼기
    keep = plan.get("keep")
    drop = set(plan.get("drop") or [])
    a, b = (keep if keep else (0, len(tops) - 1))
    if not 0 <= a <= b < len(tops):
        raise FormError(f"keep은 [처음, 끝] 문단 번호여야 합니다(0~{len(tops) - 1}).")
    kept = [p for k, p in enumerate(tops) if a <= k <= b and k not in drop]
    if not kept:
        raise FormError("남길 문단이 없습니다.")
    # 떼어 내는 앞 문단의 쪽 설정·쪽 번호·머리말은 남긴 첫 문단으로(글·표는 옮기지 않음)
    moved = 0
    for p in tops:
        if p is kept[0]:
            break
        for r in para_runs(p):
            marks = [ch for ch in r if is_struct(ch)]
            if marks:
                twin = etree.Element(r.tag, dict(r.attrib))
                twin.extend(copy.deepcopy(x) for x in marks)
                kept[0].insert(moved, twin)
                moved += 1
    kept[0].set("pageBreak", "0")
    for p in tops:
        if p not in kept:
            sec.remove(p)
    if keep and len(names) > 1:  # 구간을 고른 때만 뒤 구역을 뺀다 — 고르지 않았으면 남겨 둠(검토: 말없이 없어졌음)
        for name in names[1:]:
            pkg.drop_section(name)
        if head.get("secCnt"):
            head.set("secCnt", "1")
        print(f"알림: keep으로 구간을 골라 뒤 구역 {len(names) - 1}개도 뺐습니다.")
    # 번호 새로, 줄 배치 기록 지움(한글이 다시 계산)
    used = set()
    for p in sec.iter(T("hp:p")):
        p.set("id", new_id(used))
    for p in kept:
        drop_linesegs(p)
    if "Preview/PrvText.txt" in pkg.data:
        pkg.data["Preview/PrvText.txt"] = "\r\n".join(para_text(p).replace(COMPOSE_CHAR, "") for p in kept)[:1000].encode("utf-16-le")
    pkg.save(out)
    return len(tops), len(kept)


def main():
    ap = argparse.ArgumentParser(description="양식 파일의 표 칸에 글을 넣고 정돈한다(원본은 그대로)")
    ap.add_argument("path")
    ap.add_argument("--list", action="store_true", help="문단·표·칸 번호를 보임")
    ap.add_argument("--plan", help="계획 파일(JSON)")
    ap.add_argument("--out", help="만들 hwpx")
    ap.add_argument("--max-pages", type=int, help="쪽 상한 — 넘으면 간격부터 줄이고, 그래도 넘으면 끝 번호 3")
    ap.add_argument("--no-tidy", action="store_true", help="칸만 채우고 정돈은 하지 않음")
    a = ap.parse_args()
    if not a.path.lower().endswith(".hwpx"):
        raise SystemExit("양식 칸 채우기는 한글(HWPX) 파일만 받습니다. 옛 형식(.hwp)이면 한글에서 'HWPX'로 저장해 주세요.")
    if a.list:
        show(a.path)
        return
    if not a.plan or not a.out:
        raise SystemExit("--plan과 --out을 주세요(번호는 --list로 봅니다).")
    if same_path(a.out, a.path):
        raise SystemExit("결과를 양식 원본과 같은 이름으로 저장하지 않습니다 — 다른 이름을 주세요.")
    plan = read_plan(a.plan)
    base_dir = os.path.dirname(os.path.abspath(a.plan))
    try:
        if a.no_tidy:
            total, kept = fill(a.path, plan, a.out, base_dir)
            print(f"칸을 채웠습니다(문단 {total}개 중 {kept}개 남김, 정돈은 하지 않음): {a.out}")
            return
        with tempfile.TemporaryDirectory() as td:
            raw = os.path.join(td, "filled.hwpx")
            total, kept = fill(a.path, plan, raw, base_dir)
            print(f"칸을 채웠습니다(문단 {total}개 중 {kept}개 남김) — 이어서 정돈합니다")
            sys.exit(tidy_file(raw, a.out, max_pages=a.max_pages))
    except FormError as e:
        raise SystemExit(f"만들지 못함 — {e}") from None


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
