# -*- coding: utf-8 -*-
"""정돈(v2.0): 이미 쓴 한글(hwpx) 파일 **그 자체를** 제자리에서 최소로 다듬는다. 원본은 덮어쓰지 않는다.

    python scripts/tidy.py 문서.hwpx                 # → 문서_정돈.hwpx
    python scripts/tidy.py 문서.hwpx --out 결과.hwpx

하는 일(모두 한글이 열 때 직접 계산하는 문단·칸 설정이라 어림 오차가 없다):
  1. 줄 나눔을 어절(띄어쓰기) 단위로
  2. 단락 사이 여백: ○ 위 간격을 문서에서 가장 많이 쓴 값(없으면 6pt)으로 맞춤 — 쪽이 늘면 4·3·2pt로 줄이고 그래도 늘면
     넣지 않음, 그 ○ 줄은 아래 줄과 같은 쪽에(다음 문단과 함께 — ○ 줄에만). □ 앞 빈 줄 높이를 한 가지로(뚜렷한 다수가 있을 때)
  3. 위아래 정렬: 두 줄 이상인 머리 기호 문단(○ - · ‣ * ※ 등)의 둘째 줄을 괄호 이름표·쌍점·머리 기호 뒤 첫 글자에 맞춤,
     표 칸 글은 세로 가운데
  4. 끝 줄 두세 글자(사용자 원칙): 자간을 줄여(-18%까지) 윗줄로 올리고, 겹칠 만큼이면 윗줄 낱말을 함께 내려 끝 줄을 다섯 글자
     넘게 — 윗줄에 빈 곳이 남지 않게 자간을 늘림(실제 값 +5%까지). 줄 바꿈으로 끝나 비는 줄도 같게

바꾸지 않는 것: 글자(빈칸 → 고정폭 빈칸, 끝 줄 균형용 빈칸 ↔ 줄 바꿈뿐 — 보이는 글은 같음), 글꼴, 크기, 기호, 문체,
줄 간격 비율, 쪽 나눔, 쪽 수, 표 칸 너비·표 글자 크기, ○ 줄 밖의 다음 문단과 함께, 차례.
**보고서 원칙(근거법령 1번·요약 상자·항목 수·■ 표 제목·네 글자 붙여 쓰기·괄호 작게 등)과 그 검사는 부르지 않는다**
(2026-11-07 시험: 작성 도구로 정돈하면 근거 조문을 맨 앞으로 옮기고 글을 고치라고 함 — 사용자 결정 2026-11-08 '문체 그대로').
"""
import argparse
import copy
import os
import re
import sys
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from style_profile import P as PROFILE  # noqa: E402 — 기준값(assets/profile.json)
from hwpx_lib import (HWPUNIT_PER_MM, T, HeaderEdit, Package, Styles, cell_paras, drop_linesegs,  # noqa: E402
                      head_length, is_blank, label_colon, label_content, marker_level, page_info, para_pics, para_runs,
                      para_tables, para_text, run_text, set_run_text, split_marker, table_grid)
from layout import FIT_FLOOR, FW_EM, Layout, Metrics, spacing_after  # noqa: E402
from spaces import compact_fw, lead_to_margin  # noqa: E402
from build_base import DATE_LINE_RE, read_doc_meta  # noqa: E402

FW = "⎵"  # 고정폭 빈칸(1/4 글자, 양쪽 정렬 때 늘어나지 않음)
O_GAP_DEFAULT = 600  # ○ 위 간격 기본(6pt) — 문서에 ○ 위 간격을 쓴 곳이 없을 때(기본 양식 값)
O_GAP_FALLBACK = (400, 300, 200)  # 쪽이 늘면 줄여 볼 ○ 위 간격(4·3·2pt)
HANG_MAX = 0.4  # 내어쓰기가 본문 폭의 이 비율을 넘으면(이름표가 너무 김) 하지 않음
NEAR_WRAP = 0.88  # 한 줄로 어림했어도 이만큼 차면 둘째 줄 맞춤을 걸어 둠(어림 오차로 한글이 줄을 넘길 수 있음)
SHORT_LAST = 4  # 끝 줄에 이 글자 수 이하(빈칸 빼고)만 남으면 자간을 줄여 윗줄로 올림 — 사용자 원칙 '두서너 자'
PUSH_LO, PUSH_HI = 5, 10  # 올리면 겹칠 때 끝 줄을 이만큼(빈칸 뺀 글자 수) 되게 내림 — 사용자 '다섯 글자 넘게'(작성 모드 7~10자). 가장 적게 내리는 자리를 골라 윗줄 빈 곳을 작게
WIDEN_MAX = PROFILE["spacing_max_pct"]  # 자간을 늘릴 때 상한(%) — 사용자 원칙 '늘리는 것은 +5%까지'
FULL = 0.95  # 윗줄을 이만큼 채우면 '빈 곳 없음'으로 봄
PULL = 0.97  # 줄이 이보다 덜 차면(다음 낱말이 넘어가 빈칸이 벌어짐) 자간을 줄여 다음 낱말을 당김 — 사용자 원칙(작성 모드와 같음)
SPARSE = 0.85  # 당기지 못하고 이보다 덜 차면 자간을 조금 늘려(+5%p까지) 빈칸이 덜 벌어지게
# 자간 맞춤을 하는 글꼴: 한글과 줄 바꿈을 맞대어 본 글꼴 + 폭 표가 한글 그림과 ±0.3%로 맞은 함초롬 두 글꼴(정돈 실험 2026-11-08)
TIDY_FONTS = {"함초롬바탕", "함초롬돋움"}
LABEL_RE = re.compile(r"\((?P<core>[^()\n]{1,12})\)")  # 괄호 이름표
DASH_NAME_RE = re.compile(r"(?P<core>[가-힣]{2})(?=[ ⎵]*:(?!\d))")  # '- 교체 : …'의 두 글자 항목명
BROKEN_MIN = 0.80  # 줄 바꿈으로 끝나는 줄이 이만큼 넘게 차 있으면 끝 줄 균형용 줄 바꿈으로 보고 빈 곳을 채움(덜 차면 일부러 끊은 줄)
SIZE_GAP_MAX = 4  # 같은 머리 기호 줄의 글자 크기를 맞출 때 이보다 크게 다르면 일부러 다르게 쓴 것으로 봄(pt)
SLACK = 0.995  # 자간을 바꿔 볼 때 쓸 수 있는 폭을 이만큼만 쓴다고 보고 어림(어림 오차 대비 — 작성 모드와 같음)
# 작성 모드가 모르는 머리 기호(전임자 문서에 흔함) — 기호 다음에 빈칸이 있어야 머리 기호로 봄
EXTRA_MARK_RE = re.compile(r"^(?P<lead>[ \t⎵⍽　]*)(?P<mark>[‣▸▹➢➤✓◦])(?P<gap>[ \t⎵⍽　]+)")


def own_linesegs(p):
    """문단 자신의 줄 배치 기록(한글이 저장한 실제 줄 나눔). 표 칸 안 문단 것은 빼고."""
    ls = p.find(T("hp:linesegarray"))
    return [] if ls is None else ls.findall(T("hp:lineseg"))


def flat(text):
    """글자 비교용: 잇단 빈칸(보통·고정폭·묶음)과 줄 바꿈은 빈칸 하나로 본다(정돈은 머리 기호 앞뒤 빈칸을 고정폭으로,
    끝 줄 두세 글자를 내릴 때 빈칸 하나를 줄 바꿈으로 바꿀 뿐 — 글자는 그대로)."""
    # 빈칸 종류(보통·고정폭·묶음·줄 바꿈)는 모두 빼고 보이는 글자 차례만 견준다 — 이름표 폭 맞추기는 빈칸이 없던
    # '(현황)'에도 고정폭 빈칸을 넣으므로(보이는 글자는 같음)
    return re.sub(r"[ ⎵⍽\n　]+", "", text)


class Tidier:
    def __init__(self, path, keep_o=True, gaps=None, blank_mm=None, all_rules=False):
        self.path = path
        self.all_rules = all_rules  # 작성 모드로 만든 문서도 모두 다시 맞춤(--all)
        self.blank_mm = blank_mm  # □ 앞 빈 줄을 이 높이(mm)에 가장 가까운 것으로(사용자가 고를 때)
        # ○ 줄에 '다음 문단과 함께'(○ 위 간격을 넣은 ○ 줄 전용 모양에만) — 사용자 결정 2026-11-08 "1"
        self.keep_o = keep_o
        self.gaps = gaps  # ○ 위 간격 후보를 직접 줄 때(시험용)
        self.pkg = Package(path)
        self.header = self.pkg.xml("Contents/header.xml")
        self.styles = Styles(self.header)
        self.hedit = HeaderEdit(self.header, self.styles)
        self.metrics = Metrics()
        self.lay = Layout(self.styles, self.metrics)
        self.lay.move_whole = False  # 쪽 어림은 한글이 하는 대로(쪽 나눔을 박지 않음)
        self.secs = [self.pkg.xml(n) for n in self.pkg.sections()]
        self.changes = {}  # 문단 → [무엇을 바꿨나]
        self.notes = []
        self.touched = set()  # 줄 배치 기록을 지울 문단(한글이 다시 계산)
        tab = self.secs[0].find(".//" + T("hp:tab")) if self.secs else None
        self.tab_proto = tab
        # 원본 상태(비교용)
        self.body = [p for sec in self.secs for p in sec if p.tag == T("hp:p")]
        # 문단은 요소 자체를 열쇠로(lxml 요소의 id()는 다시 쓰일 수 있어 열쇠로 못 씀 — 첫 시험에서 '글자 바뀜' 오판)
        self.orig_text = {p: flat(para_text(p)) for p in self.all_paras()}
        self.page_of = self._orig_pages()
        # 이 스킬의 작성 모드로 만든 문서(content.hpf 표시 made=판) — 작성 규칙이 맞춘 내어쓰기(낫표 당김·화살표 줄 포함)·
        # 끝 줄·이름표·칸·간격을 정돈의 어림으로 다시 만지면 되돌리게 된다(평가 2026-11-08: 낫표 줄 내어쓰기 5.4 → 3.1mm,
        # 화살표 줄 61.7 → 35.7mm). 그래서 내어쓰기가 아예 없는 문단(만든 뒤 사람이 더한 줄)·글자 단위 줄 나눔·빈칸만 손봄
        self.made = "" if all_rules else read_doc_meta(self.pkg).get("made", "")

    # ------------------------------------------------------------ 바탕
    def all_paras(self):
        for sec in self.secs:
            yield from sec.iter(T("hp:p"))

    def _orig_pages(self):
        """본문 문단마다 몇 쪽에서 시작하는지(1부터). 원본 줄 배치 기록(vertpos)이 있으면 그것으로, 없으면 어림으로
        (한글 2024로 저장한 파일 상당수에는 그 기록이 없다 — work 폴더 hwpx 200여 개 가운데 하나만 있었음 2026-11-08)."""
        if not any(own_linesegs(p) for p in self.body):
            self.page_guess = True
            out, base = {}, 0
            for sec in self.secs:
                body_w, body_h = self.box(sec)
                paras = [p for p in sec if p.tag == T("hp:p")]
                where, _ = self.lay.paginate(paras, body_w, body_h)
                for p, (s, _e) in zip(paras, where):
                    out[p] = base + s + 1
                base += (max(e for _, e in where) + 1) if where else 0
            return out
        self.page_guess = False
        out, page, last = {}, 1, None
        for p in self.body:
            segs = own_linesegs(p)
            if p.get("pageBreak") == "1" and last is not None:
                page, last = page + 1, None
            if not segs:
                out[p] = None
                continue
            for k, s in enumerate(segs):
                v = int(s.get("vertpos", "0"))
                if last is not None and v < last:
                    page += 1
                if k == 0:
                    out[p] = page
                last = v
        return out

    def box(self, sec):
        pg = page_info(sec) or {}
        w = pg.get("body_width", 170) * HWPUNIT_PER_MM
        h = (pg.get("height", 297) - sum(pg.get(k, 0) for k in ("top", "bottom", "header", "footer"))) * HWPUNIT_PER_MM
        return w, h

    def mark(self, p, what):
        self.changes.setdefault(p, []).append(what)
        self.touched.add(p)

    def name(self, p):
        text = para_text(p)
        pre, mark, _ = self.split(text)
        return re.sub(r"[ ⎵⍽\n]+", " ", text[len(pre):] if mark else text).strip()[:10] or "(빈 줄)"

    def near_wrap(self, p, body_w, fill=NEAR_WRAP):
        """한 줄로 어림했지만 거의 찬 문단(한글에서는 한 낱말이 넘어갈 수 있음 — 실험: '(대 상) … 호안 / 보강'이 어림 1줄,
        한글 2줄). 둘째 줄 맞춤은 한 줄로 들어가면 보이지 않으니 이런 문단도 맞춘다."""
        _, lines = self.lay.para_lines(p, body_w)
        return len(lines) == 1 and lines[0][3] > 0 and lines[0][2] / lines[0][3] >= fill

    def lines_of(self, p, body_w):
        """두 줄 이상인가 — 원본 기록과 어림 가운데 큰 쪽(어절 단위로 바꾸면 줄 수가 달라질 수 있음)."""
        _, lines = self.lay.para_lines(p, body_w)
        return max(len(own_linesegs(p)), len(lines))

    # ------------------------------------------------------------ 1. 어절 단위 줄 나눔
    def word_wrap(self):
        used = Counter(p.get("paraPrIDRef") for p in self.all_paras())
        changed = set()
        for pid in used:
            if self.hedit.word_wrap(pid):
                changed.add(pid)
                el = self.hedit._para(pid)
                self.styles.para[pid] = self.styles._para(el)
        if not changed:
            return
        n = 0
        body = set(self.body)
        for sec in self.secs:
            for p in sec.iter(T("hp:p")):
                if p.get("paraPrIDRef") in changed and para_text(p).strip():
                    self.touched.add(p)  # 줄 나눔 기준이 바뀐 문단은 한글이 다시 나누게
                    if p in body and len(own_linesegs(p)) >= 2:
                        self.mark(p, "줄 나눔을 어절 단위로")
                    n += 1
        self.notes.append(f"줄 나눔을 글자 단위에서 어절 단위로 바꾼 문단 모양 {len(changed)}개(그 모양을 쓰는 글 문단 {n}개).")

    # ------------------------------------------------------------ 2. 단락 사이 여백
    def o_gaps(self):
        os_ = [(k, p) for k, p in enumerate(self.body)
               if not para_tables(p) and marker_level(para_text(p)) == 2]
        if not os_:
            return
        prevs = [self.styles.para.get(p.get("paraPrIDRef"), {}).get("prev", 0) for _, p in os_]
        nonzero = [v for v in prevs if v > 0]
        target = Counter(nonzero).most_common(1)[0][0] if nonzero else O_GAP_DEFAULT
        todo = [(p, cur) for (k, p), cur in zip(os_, prevs)
                if cur < target and not (k and is_blank(self.body[k - 1]))]  # 빈 줄로 이미 띄운 ○는 두 번 띄우지 않음
        if not todo:
            return
        # 쪽 수를 지킨다: 넣어서 어림 쪽 수가 원본보다 늘면 간격을 줄여 보고(6 → 4 → 3 → 2pt), 그래도 늘면 넣지 않는다
        # (사용자 원고 4쪽 시험 2026-11-08: 6pt × 14곳으로 4쪽 → 5쪽, 작성자가 박은 강제 쪽 나눔 때문에 한 쪽이 거의 빔 — 어림도 5쪽을 맞힘)
        tries = self.gaps or [target] + [g for g in O_GAP_FALLBACK if g < target]
        old = [p.get("paraPrIDRef") for p, _ in todo]
        for g in tries:
            for p, cur in todo:
                if cur < g:
                    p.set("paraPrIDRef", self.hedit.para_margin(p.get("paraPrIDRef"), "prev", g))
                if self.keep_o and not self.styles.para.get(p.get("paraPrIDRef"), {}).get("keep_next"):
                    # ○ 줄만(위 간격을 넣으며 ○ 줄 전용 모양이 됨) '다음 문단과 함께' — 한글이 ○ 제목 줄을 쪽 끝에 홀로 두지 않게
                    # (사용자 원고 시험: 어림은 한 줄쯤 어긋나 홀로 남는 ○를 못 잡음 — 한글이 직접 막게 함)
                    p.set("paraPrIDRef", self.hedit.para_keep_next(p.get("paraPrIDRef")))
            pages, orphans = self.layout_state()
            if pages <= self.pages0 and orphans <= self.orphans0:
                break
            for (p, _), pid in zip(todo, old):
                p.set("paraPrIDRef", pid)
        else:
            self.notes.append(f"○ 위 간격을 넣으면 쪽이 늘어나 넣지 않았습니다(○ {len(todo)}곳 위 간격 0 — 쪽에 빈 곳이 모자람, "
                              f"{tries[-1] / 100:g}pt까지 줄여 봄).")
            return
        n = 0
        for p, cur in todo:
            if cur < g:
                self.mark(p, f"○ 위 간격 {cur / 100:g} → {g / 100:g}pt")
                n += 1
        why = "문서에서 가장 많이 쓴 값" if nonzero else "문서에 ○ 위 간격이 없어 기본값"
        if g < target:
            why = f"{why} {target / 100:g}pt를 넣으면 쪽이 늘어나 줄임"
        self.notes.append(f"○ 위 간격을 {g / 100:g}pt로 맞춘 문단 {n}개({why}).")
        if self.keep_o:
            for p, _ in todo:
                self.mark(p, "○ 줄을 아래 줄과 같은 쪽에")
            self.notes.append(f"○ 줄 {len(todo)}개는 바로 아래 줄과 같은 쪽에 오게(다음 문단과 함께) 했습니다 — ○ 제목만 쪽 끝에 홀로 남지 않게.")

    def blank_heights(self):
        """□ 바로 앞 빈 줄(묶음 사이 빈 줄)을 가장 많이 쓴 모양 하나로."""
        blanks = []
        for k, p in enumerate(self.body[1:], 1):
            prev = self.body[k - 1]
            if marker_level(para_text(p)) == 1 and not para_tables(p) and is_blank(prev):
                runs = para_runs(prev)
                if all(len(r) <= 1 and (len(r) == 0 or r[0].tag == T("hp:t")) for r in runs) and runs:
                    blanks.append(prev)
        if len(blanks) < 2:
            return
        body_w = self.box(self.secs[0])[0]
        size = lambda b: self.lay.para_height(b, body_w)[0]  # noqa: E731
        band = lambda b: round(size(b) / (0.5 * HWPUNIT_PER_MM))  # 0.5mm 눈금으로 묶음  # noqa: E731
        # 뚜렷한 다수(60% 이상)인 높이가 있을 때만 그 높이로. 제각각이면 어느 것이 '보통'인지 알 수 없어 그대로 두고 알림
        # (흐트러뜨린 예시 문서 시험: 좁힌 빈 줄이 가장 많아 보통 빈 줄을 좁은 쪽으로 맞춰 버렸음 2026-11-08)
        counts = Counter(band(b) for b in blanks)
        top, cnt = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
        if self.blank_mm:
            # 사용자가 높이를 정해 준 때: 문서에 있는 □ 앞 빈 줄 가운데 그 높이에 가장 가까운 모양으로 모두 맞춤
            want = self.blank_mm * HWPUNIT_PER_MM
            top = band(min(blanks, key=lambda b: abs(size(b) - want)))
        elif len(counts) > 1 and cnt < 0.6 * len(blanks):
            sizes = sorted({round(size(b) / HWPUNIT_PER_MM, 1) for b in blanks})
            self.notes.append(f"□ 앞 빈 줄 높이가 제각각({', '.join(f'{s:g}' for s in sizes)}mm)이라 그대로 두었습니다 — "
                              f"한 가지로 맞추려면 그 가운데 하나를 골라 `--blank-mm {sizes[-1]:g}`처럼 다시 정돈.")
            return
        ref = next(b for b in blanks if band(b) == top)
        h0 = size(ref)
        pid0, cid0 = ref.get("paraPrIDRef"), para_runs(ref)[0].get("charPrIDRef")
        todo = [(b, size(b), b.get("paraPrIDRef"), [r.get("charPrIDRef") for r in para_runs(b)])
                for b in blanks if band(b) != top]
        for b, *_ in todo:
            b.set("paraPrIDRef", pid0)
            for r in para_runs(b):
                r.set("charPrIDRef", cid0)
        if self.pages() > self.pages0:  # 쪽이 늘면 되돌림(쪽 수 지키기)
            for b, _, pid, cids in todo:
                b.set("paraPrIDRef", pid)
                for r, c in zip(para_runs(b), cids):
                    r.set("charPrIDRef", c)
            self.notes.append("□ 앞 빈 줄 높이를 한 가지로 맞추면 쪽이 늘어나 그대로 두었습니다.")
            return
        n = 0
        for b, h, *_ in todo:
            self.mark(b, f"빈 줄 높이 {h / HWPUNIT_PER_MM:.1f} → {h0 / HWPUNIT_PER_MM:.1f}mm")
            n += 1
        if n:
            which = "고르신 높이에 가장 가까운 빈 줄" if self.blank_mm else "가장 많이 쓴 빈 줄"
            self.notes.append(f"□ 앞 빈 줄 {n}개의 높이를 {which}({h0 / HWPUNIT_PER_MM:.1f}mm)과 같게 했습니다.")

    # ------------------------------------------------------------ 3. 위아래 정렬
    def _fw_per_space(self, run):
        font = self.styles.char.get(run.get("charPrIDRef"), {}).get("font")
        return max(1, round(self.metrics.em(font, " ") / FW_EM))

    @staticmethod
    def split(text):
        """머리 기호 나누기 — 작성 모드가 아는 기호에 전임자 문서에 흔한 ‣ ▸ ▹ ➢ ➤ ✓ ◦ 를 더함(다른 것은 hwpx_lib와 같음).
        돌려주는 것: (머리 기호까지 글, 기호, 분석용 글 — 더한 기호를 '-'로 바꿔 이름표·쌍점 찾기가 되게)."""
        pre, mark, _ = split_marker(text)
        if mark:
            return pre, mark, text
        m = EXTRA_MARK_RE.match(text)
        if not m:
            return "", "", text
        k = m.start("mark")
        return m.group(0), m.group("mark"), text[:k] + "-" + text[k + 1:]

    def level(self, text):
        lv = marker_level(text)
        if lv == 0 and self.split(text)[1]:
            return 3
        return lv

    def head_at(self, text):
        """둘째 줄을 맞출 자리: 괄호 이름표 뒤 → '항목 : ' 쌍점 뒤 → 머리 기호 뒤 첫 글자. 머리 기호가 없으면 0.
        쌍점 이름표는 사용자 원칙(쌍점 뒤 처음 시작하는 글자에 아랫줄을 맞춤) — 사람이 쓴 15쪽 계획서 시험에서 원본이 그렇게 맞춰 있었음."""
        pre, mark, t = self.split(text)
        if not mark:
            return 0
        return label_content(t) or label_colon(t) or len(pre)

    def head_kind(self, text):
        t = self.split(text)[2]
        return "이름표" if label_content(t) else ("쌍점" if label_colon(t) else "머리 기호")

    def aligned_spots(self, text):
        """작성자가 둘째 줄을 맞춰 두었을 만한 자리(글자 위치): 머리 기호 뒤·괄호 이름표 뒤·'항목 : ' 쌍점 뒤.
        지금 내어쓰기가 이 가운데 하나와 맞으면 작성자의 맞춤으로 보고 그대로 둔다(사람이 쓴 15쪽 계획서 첫 시험: 쌍점 뒤에 맞춘
        28.8mm 내어쓰기를 머리 기호 뒤 13.8mm로 줄여 버렸음)."""
        pre, mark, t = self.split(text)
        return {k for k in (len(pre) if mark else 0, label_content(t), label_colon(t)) if k}

    def _hang_one(self, p, box_w, in_cell=False):
        """문단 하나의 둘째 줄을 맞춘다. 돌려주는 것: 'done'·'indent'(첫 줄 들여쓰기를 바꿔 맞춤)·'break'(줄 바꿈 문단)·None."""
        text = para_text(p)
        lv = self.level(text)
        k = self.head_at(text)
        if not k or lv == 1 or k >= len(text):
            return None
        pp = self.styles.para.get(p.get("paraPrIDRef"), {})
        if pp.get("align") in ("CENTER", "RIGHT"):
            return None
        if self.made and pp.get("intent", 0) < 0:
            return None  # 작성 모드가 이미 내어쓰기를 맞춘 문단(낫표 당김·화살표 줄 등 작성 규칙의 자리) — 그대로
        if re.search(r"\n[ ⎵⍽　]+", text):
            # 줄 바꿈(Shift+Enter) 뒤 빈칸으로 둘째 줄을 맞춘 문단 — 내어쓰기를 걸면 빈칸만큼 두 번 들어감. 글을 바꿔야 해서 그대로.
            # (줄 바꿈 뒤가 바로 글이면 한글은 그 줄도 둘째 줄로 내어쓰므로 아래에서 보통대로 맞춤 — 실험: 작성 도구가 끝 줄
            # 균형으로 넣은 줄 바꿈을 건너뛰어 '보강, 산책로 정비'가 왼쪽 끝에 남았음)
            return "break"
        if self.lines_of(p, box_w) < 2 and not self.near_wrap(p, box_w):
            return None
        if "\t" in text[:k]:
            # 머리 기호 뒤를 탭으로 띄운 문단 — 탭이 닿는 자리는 문서의 기본 탭 간격·내어쓰기 자동 탭에 따라 달라 어림하면
            # 오히려 어긋남(실험: 둘째 줄이 2~7mm 어긋나거나 쌍점 항목은 내어쓰기를 못 함). 그대로 두고 알림
            return "tab"
        indent = max(0, pp.get("intent", 0))  # 첫 줄 들여쓰기(양수)
        cur = -pp.get("intent", 0) if not indent else 0
        chs, _ = self.lay.para_lines(p, box_w)
        # 작성자가 한글에서 눈으로 맞춘 값은 어림과 1mm쯤 다를 수 있다(사용자 원고: 23.2~23.7mm, 어림 22.7mm) — 0.4글자 안이면 그대로
        if cur > 0 and any(abs(cur - sum(c[1] for c in chs[:j])) <= 0.4 * (chs[j][1] if j < len(chs) else 1000)
                           for j in self.aligned_spots(text)):
            return None  # 작성자가 이미 머리 기호·이름표·쌍점 뒤에 맞춰 둔 문단
        if sum(c[1] for c in chs[:k]) + indent > box_w * HANG_MAX:
            return None
        # 머리 기호 앞뒤 보통 빈칸을 고정폭 빈칸으로(첫 줄이 양쪽 정렬로 늘어나도 내용 시작 자리가 그대로)
        pos = 0
        for r in para_runs(p):
            t = run_text(r)
            start, pos = pos, pos + len(t)
            if start >= k:
                break
            cut = min(len(t), k - start)
            new = t[:cut].replace(" ", FW * self._fw_per_space(r)) + t[cut:]
            if new != t and len(r) == 1 and r[0].tag == T("hp:t"):
                set_run_text(r, new, self.tab_proto)
        text = para_text(p)
        k = self.head_at(text)
        chs, _ = self.lay.para_lines(p, box_w)
        hang = sum(c[1] for c in chs[:k])
        em = chs[k][1] if k < len(chs) else 1000
        if indent:
            # 첫 줄 들여쓰기 Y → 왼쪽 여백을 Y만큼 늘리고 내어쓰기로(첫 줄 자리는 그대로, 둘째 줄은 내용 첫 글자 밑)
            pid = self.hedit.para_margin(p.get("paraPrIDRef"), "left", pp.get("left", 0) + indent)
            p.set("paraPrIDRef", self.hedit.para_hang(pid, hang))
            if p in getattr(self, "_lead_moved", ()):
                # 줄머리 빈칸을 옮기며 생긴 첫 줄 들여쓰기 — 작성자가 둔 들여쓰기가 아님
                self.mark(p, f"둘째 줄을 {self.head_kind(text)} 뒤 첫 글자에(내어쓰기 {hang / HWPUNIT_PER_MM:.1f}mm)"
                             + (" — 표 칸" if in_cell else ""))
                return "done"
            self.mark(p, f"첫 줄 들여쓰기 {indent / HWPUNIT_PER_MM:.1f}mm를 왼쪽 여백으로 옮기고 둘째 줄을 {self.head_kind(text)} 뒤에"
                         f"(내어쓰기 {hang / HWPUNIT_PER_MM:.1f}mm)" + (" — 표 칸" if in_cell else ""))
            return "indent"
        if abs(cur - hang) <= 0.05 * em:
            return None
        p.set("paraPrIDRef", self.hedit.para_hang(p.get("paraPrIDRef"), hang))
        self.mark(p, f"둘째 줄을 {self.head_kind(text)} 뒤 첫 글자에"
                     f"(내어쓰기 {cur / HWPUNIT_PER_MM:.1f} → {hang / HWPUNIT_PER_MM:.1f}mm)" + (" — 표 칸" if in_cell else ""))
        return "done"

    def hangs(self):
        got = Counter()
        cells = Counter()
        for sec in self.secs:
            body_w, _ = self.box(sec)
            for p in [x for x in sec if x.tag == T("hp:p")]:
                if para_tables(p) or para_pics(p):
                    continue
                got[self._hang_one(p, body_w)] += 1
            # 표 칸 안 문단(· 항목 등) — 칸 안쪽 폭 = 칸 너비 − 칸 안 여백
            for tbl in sec.iter(T("hp:tbl")):
                inm = tbl.find(T("hp:inMargin"))
                dl = int(inm.get("left", "510")) + int(inm.get("right", "510")) if inm is not None else 1020
                for *_, tc in table_grid(tbl):
                    sz = tc.find(T("hp:cellSz"))
                    w = int(sz.get("width", "0")) if sz is not None else 0
                    ml = dl
                    if tc.get("hasMargin") == "1" and tc.find(T("hp:cellMargin")) is not None:
                        cm = tc.find(T("hp:cellMargin"))
                        ml = int(cm.get("left", "0")) + int(cm.get("right", "0"))
                    for cp in cell_paras(tc):
                        if para_tables(cp) or para_pics(cp) or w - ml <= 0:
                            continue
                        cells[self._hang_one(cp, w - ml, in_cell=True)] += 1
        n = got["done"] + got["indent"]
        if n:
            self.notes.append(f"두 줄 이상인 머리 기호 문단 {n}개의 둘째 줄을 이름표·쌍점·머리 기호 뒤 첫 글자에 맞췄습니다"
                              + (f"(첫 줄 들여쓰기를 왼쪽 여백으로 옮긴 것 {got['indent']}개)" if got["indent"] else "") + ".")
        c = cells["done"] + cells["indent"]
        if c:
            self.notes.append(f"표 칸 안 두 줄 이상인 항목 {c}개의 둘째 줄을 머리 기호 뒤 첫 글자에 맞췄습니다.")
        tb = got["tab"] + cells["tab"]
        if tb:
            self.notes.append(f"머리 기호 뒤를 탭으로 띄운 문단 {tb}개는 둘째 줄을 맞추지 않았습니다 — 탭이 닿는 자리는 문서 설정마다 달라 "
                              "어림하지 않음(한글에서 확인).")
        b = got["break"] + cells["break"]
        if b:
            self.notes.append(f"줄 바꿈(Shift+Enter)과 빈칸으로 둘째 줄을 맞춘 문단 {b}개는 그대로 두었습니다 — 고치려면 글을 바꿔야 함"
                              "(줄 바꿈을 지우고 한 문단으로 이으면 정돈이 맞춤).")

    # ------------------------------------------------------------ 0. 이름표 폭(사용자 원칙 — 네 글자가 기준)
    def labels(self):
        """두세 글자 괄호 이름표 '(대 상)'·'(사 업 비)'는 네 글자 폭으로, 작대기 줄의 두 글자 항목명 '- 교체 : …'은 세 글자 폭으로
        고정폭 빈칸을 고르게 넣어 맞춘다(style-guide 2절 '이름표 폭 맞추기' — 작성 모드와 같은 규칙). 보이는 글자는 그대로
        (이름표 안 빈칸 수만). 네 글자 넘는 이름표·네 글자 이름표는 그대로(붙여 쓰기는 글을 바꾸므로 하지 않음)."""
        self._label_n0, self._widened, self._head_changed, self._fit_note, self._box_group = {}, {}, {}, {}, {}
        group = 0
        for sec in self.secs:
            body_w, _ = self.box(sec)
            for p in [x for x in sec if x.tag == T("hp:p")]:
                if para_tables(p) or para_pics(p):
                    continue
                text = para_text(p)
                if self.level(text) == 1:
                    group += 1
                    continue
                pre, mark, _ = self.split(text)
                if not mark:
                    continue
                self._box_group[p] = group
                self._label_n0[p] = (len(self.lay.para_lines(p, body_w)[1]), body_w)
                body = text[len(pre):]
                m = LABEL_RE.match(body)
                want = 4
                if not m and self.level(text) == 3:
                    m, want = DASH_NAME_RE.match(body), 3
                if not m:
                    continue
                core = m.group("core")
                letters = re.sub(r"[ ⎵⍽]", "", core)
                if not (2 <= len(letters) < want) or not all("가" <= c <= "힣" for c in letters):
                    continue
                fw = int(round((want - len(letters)) / FW_EM))  # 한글 한 글자 = 고정폭 빈칸 4개
                gaps = len(letters) - 1
                new_core = "".join(c + FW * (fw // gaps + (1 if i < fw % gaps else 0)) for i, c in enumerate(letters[:-1])) + letters[-1]
                if new_core == core:
                    continue
                k = len(pre) + m.start("core")
                if self._replace_span(p, k, k + len(core), new_core):
                    self._widened[p] = (k, core, new_core, want)
        self.head_spacing()
        reverted, shrunk = self._fit_heads()
        n = 0
        for p, (_, core, _, want) in self._widened.items():
            self.mark(p, f"이름표 ‘{core.replace('⎵', ' ')}’ 폭을 {want}글자로")
            n += 1
        heads = 0
        for p, (was, mode, _) in self._head_changed.items():
            self.mark(p, f"머리 기호·이름표 자간을 같은 수준과 같게({was:+d} → {mode:+d}%)")
            heads += 1
        for p, notes in self._fit_note.items():
            for t in notes:
                self.mark(p, t)
        if n:
            self.notes.append(f"두세 글자 이름표 {n}개를 네 글자 폭(작대기 항목명은 세 글자 폭)으로 맞췄습니다(고정폭 빈칸 — 글자 그대로).")
        if heads:
            self.notes.append(f"머리 기호·이름표 자간이 문단마다 다르던 {heads}곳을 같은 수준에서 가장 많이 쓴 값으로 맞췄습니다(내용 시작점이 위아래로 같게).")
        if shrunk:
            self.notes.append(f"이름표를 맞추면 줄이 늘고 내용 자간으로도 못 지키던 곳은 같은 □ 아래 같은 꼴 이름표 {shrunk}개의 자간을 함께 줄여 "
                              "괄호·쌍점이 위아래 한 줄로 선 채 줄 수를 지켰습니다.")
        if reverted:
            self.notes.append(f"이름표를 맞추면 줄이 하나 늘어나고 이름표를 함께 줄여도(-18%까지) 못 지키는 문단 {reverted}개"
                              f"(예: ‘{self._reverted_names[0]}…’)는 이름표·머리 자간을 원래대로 두었습니다(그 줄만 머리 자리가 다름 — "
                              "낱말을 줄이면 맞출 수 있음).")

    def _label_key(self, p):
        """이름표를 함께 줄일 묶음: 같은 □ 아래·같은 수준·같은 꼴(괄호 이름표 / 쌍점 항목명)."""
        text = para_text(p)
        pre, _, t = self.split(text)
        kind = "괄호" if LABEL_RE.match(t[len(pre):]) else ("쌍점" if label_colon(t) else "")
        return (self._box_group.get(p), self.level(text), kind)

    def _label_sp(self, p):
        """이름표 첫 글자(머리 기호 뒤)의 자간(%)."""
        text = para_text(p)
        k, pos = len(self.split(text)[0]), 0
        for r in para_runs(p):
            t = run_text(r)
            if pos <= k < pos + len(t):
                return self.styles.char.get(r.get("charPrIDRef"), {}).get("spacing", 0)
            pos += len(t)
        return None

    def _label_runs(self, p):
        """머리 기호 뒤부터 내용 앞까지(이름표·쌍점과 그 뒤 빈칸)의 글 조각 — 머리 기호와 그 앞 빈칸은 빼서 '-'가 ○ 이름표 '('
        아래 자리를 지키게."""
        text = para_text(p)
        lo, hi = len(self.split(text)[0]), head_length(text)
        if hi <= lo or not self._split_at(p, lo) or not self._split_at(p, hi):
            return []
        return self._content_runs(p, lo, hi)

    def _fit_heads(self):
        """이름표를 넓히고 머리 자간을 맞춘 뒤 줄이 는 문단을 맞춘다 — 사용자 원칙(2026-11-08): '네 글자까지는 : 는 위아래가 직선
        정렬, ( )도 위아래가 직선 정렬. 그러므로 뒤에 글자의 자간만 줄이는 거죠. 그런데 제목들의 자간을 줄여야 되는 경우는 처음에
        언급한 규칙을 지키며 함께 줄였다 늘였다 함.' ① 내용 글자 자간을 -18%까지 ② 그래도 늘면 같은 □ 아래 같은 수준·같은 꼴
        이름표의 자간을 함께 1%씩(-18%까지) — 괄호·쌍점이 위아래 한 줄로 선 채 ③ 그래도 안 되면 그 문단만 이름표·머리 자간을
        되돌림. 돌려주는 것: (되돌린 문단 수, 함께 줄인 이름표 수)."""
        stuck = []
        for p, (n0, w) in self._label_n0.items():
            if len(self.lay.para_lines(p, w, shrink=SLACK)[1]) <= n0:
                continue
            got = self._keep_lines(p, w, n0)
            if got is None:
                stuck.append(p)
            else:
                self._fit_note.setdefault(p, []).append(f"줄이 늘지 않게 내용 자간 {got[0]:+d}%")
        self._reverted_names = []
        if not stuck:
            return 0, 0
        sp = lambda r: self.styles.char.get(r.get("charPrIDRef"), {}).get("spacing", 0)  # noqa: E731
        keys = {p: self._label_key(p) for p in self._label_n0}
        reverted = shrunk = 0
        for key in dict.fromkeys(keys[p] for p in stuck):
            mine = [p for p in stuck if keys[p] == key]
            members = [p for p in self._label_n0 if keys[p] == key and key[2]]
            runs = {p: self._label_runs(p) for p in members}
            ok_s = None
            orig = {r: r.get("charPrIDRef") for p in members for r in runs[p]}
            content_old = []
            if key[2] and all(runs.get(p) for p in mine):
                base = sp(runs[mine[0]][0])
                for s in range(base - 1, FIT_FLOOR - 1, -1):
                    for r, cid in orig.items():
                        r.set("charPrIDRef", self.hedit.char_spacing(cid, s))
                    fit = True
                    for p in mine:
                        n0, w = self._label_n0[p]
                        if len(self.lay.para_lines(p, w, shrink=SLACK)[1]) <= n0:
                            continue
                        got = self._keep_lines(p, w, n0)
                        if got is None:
                            fit = False
                            break
                        content_old += got[1]
                    if fit:
                        ok_s = s
                        break
            if ok_s is not None:
                for p in members:
                    self._fit_note.setdefault(p, []).append(f"이름표 자간을 같은 묶음과 함께 {ok_s:+d}%로(괄호·쌍점 맞춤 그대로)")
                shrunk += len(members)
                continue
            for r, cid in orig.items():
                r.set("charPrIDRef", cid)
            self._undo(content_old)
            for p in mine:
                if p in self._widened:
                    k, core, new_core, _ = self._widened.pop(p)
                    self._replace_span(p, k, k + len(new_core), core)
                if p in self._head_changed:
                    was, mode, _ = self._head_changed.pop(p)
                    # 이름표 조각을 나눈 뒤라 되돌릴 목록 대신 머리 조각을 다시 찾아 원래 자간으로
                    for r in self._content_runs(p, 0, head_length(para_text(p))):
                        if sp(r) == mode:
                            r.set("charPrIDRef", self.hedit.char_spacing(r.get("charPrIDRef"), was))
                reverted += 1
                self._reverted_names.append(self.name(p))
        return reverted, shrunk

    def head_spacing(self):
        """머리 기호·이름표(문단 첫머리) 글자의 자간을 같은 수준(○끼리, -끼리 …)에서 가장 많이 쓴 값 하나로 — 머리 자간이 문단마다
        다르면(전임자 문서에서 문단마다 -4%·-16% …) 이름표를 네 글자 폭으로 맞춰도 내용 시작점이 갈린다(실험: 31.6mm·36.1mm,
        사용자 '사업개요부분은 여전히 이상하군요'). 사용자 원칙 '머리 기호·괄호 이름표 조각에는 자간 조정을 하지 않는다'."""
        heads = {}
        for sec in self.secs:
            body_w, _ = self.box(sec)
            for p in [x for x in sec if x.tag == T("hp:p")]:
                if para_tables(p) or para_pics(p):
                    continue
                text = para_text(p)
                lv = self.level(text)
                k = head_length(text)
                if lv not in (2, 3, 4) or not k or k >= len(text) or not self._split_at(p, k):
                    continue
                runs = self._content_runs(p, 0, k)
                if runs:
                    heads.setdefault(lv, []).append((p, runs, body_w))
        sp = lambda r: self.styles.char.get(r.get("charPrIDRef"), {}).get("spacing", 0)  # noqa: E731
        # 같은 □ 아래 같은 수준·같은 꼴 이름표가 둘 넘게 모두 같은 자간이면(이름표를 함께 줄인 묶음 — _fit_heads) 그 묶음 값으로 봄:
        # 수준 전체 값으로 되돌리면 두 번째 정돈이 다시 줄이며 '바뀜'을 냄
        lab = {}
        for p in self._box_group:
            key = self._label_key(p)
            if key[2]:
                lab.setdefault(key, []).append(self._label_sp(p))
        same = {k for k, v in lab.items() if len(v) >= 2 and len(set(v)) == 1}
        for lv, items in heads.items():
            mode = Counter(sp(rs[0]) for _, rs, _ in items).most_common(1)[0][0]
            for p, runs, w in items:
                # 일부러 크게 좁힌 조각(낫표 당기기 -36·-50% 등, -30% 밑)은 그대로 — 그 밖에서 값이 다른 조각만 맞춤
                todo = [r for r in runs if -30 <= sp(r) <= 10 and sp(r) != mode]
                if p in self._box_group and self._label_key(p) in same:
                    lo = len(self.split(para_text(p))[0])
                    keep = set(self._content_runs(p, lo, head_length(para_text(p))))
                    todo = [r for r in todo if r not in keep]
                if not todo:
                    continue
                was = sp(todo[0])
                old = [(r, r.get("charPrIDRef")) for r in todo]
                for r in todo:
                    r.set("charPrIDRef", self.hedit.char_spacing(r.get("charPrIDRef"), mode))
                self._head_changed[p] = (was, mode, old)  # 줄이 늘면 _fit_heads가 맞추거나 되돌림, 알림은 labels()가

    # ------------------------------------------------------------ 2-1. 같은 머리 기호 줄의 글자 크기(사용자 2026-11-08 '둘 다 고치기')
    def _para_size(self, p):
        """문단 글자 크기 — 머리 기호·이름표 뒤 내용 첫 글자의 크기. 글자 수로 세면 2pt 작게 쓴 긴 괄호 부연설명
        '(daegu.sharedata.go.kr)' 때문에 문단 전체가 작은 글자로 잡혀 그 괄호까지 키워 버렸음(사람이 쓴 15쪽 계획서)."""
        text = para_text(p)
        k = head_length(text)
        while k < len(text) and text[k] in " ⎵⍽　\t":
            k += 1
        pos = 0
        for r in para_runs(p):
            t = run_text(r)
            if pos <= k < pos + len(t) and r.find(T("hp:t")) is not None:
                return self.styles.char.get(r.get("charPrIDRef"), {}).get("size")
            pos += len(t)
        return None

    def sizes(self):
        """같은 머리 기호(○끼리, -끼리, ‣끼리) 줄인데 한 줄만 글자 크기가 다른 문단 — 전임자 문서에서 한 줄만 12pt로 남아 내용
        시작점·줄 높이가 그 줄만 다름(사용자: '사업개요부분은 여전히 이상하군요', 샘플 뒤 '둘 다 고치기').
        맞추는 때: 문서 전체에서 그 기호 줄의 3분의 2 넘게(3줄 이상) 한 크기를 쓰고, 그 줄이 든 □ 묶음 안에서도 그 크기가 더
        많고, 차이가 SIZE_GAP_MAX pt 이하일 때 — 그 크기를 쓰던 조각만 많이 쓴 크기로. 번호(1. 가. ①)와 □ 줄은 제목이라
        건드리지 않고, ‣처럼 기호가 다르면 크기가 원래 다른 아래 수준으로 봄. □ 묶음 하나가 통째로 다른 크기(참고 쪽 등)면 그대로.
        쪽이 늘면 모두 되돌림."""
        items = []  # (문단, 기호, 크기, □ 묶음)
        group = 0
        for sec in self.secs:
            for p in [x for x in sec if x.tag == T("hp:p")]:
                if para_tables(p) or para_pics(p):
                    continue
                text = para_text(p)
                lv = self.level(text)
                if lv == 1:
                    group += 1
                    continue
                _, mark, _ = self.split(text)
                if lv not in (2, 3) or not mark or any(c.isalnum() for c in mark):
                    continue
                size = self._para_size(p)
                if size:
                    items.append((p, mark.strip(), size, group))
        todo, left = [], []
        by_mark = {}
        for it in items:
            by_mark.setdefault(it[1], []).append(it)
        for its in by_mark.values():
            cnt = Counter(s for _, _, s, _ in its)
            if len(cnt) < 2:
                continue
            want, n_want = cnt.most_common(1)[0]
            for p, _, a, g in its:
                if a == want:
                    continue
                grp = Counter(s for _, _, s, gg in its if gg == g)
                ok = n_want >= 3 and n_want * 3 > len(its) * 2 and grp[want] > grp[a] and abs(a - want) <= SIZE_GAP_MAX
                (todo if ok else left).append((p, a, want))
        old = []
        for p, a, want in todo:
            for r in para_runs(p):
                cid = r.get("charPrIDRef")
                s = self.styles.char.get(cid, {}).get("size")
                # 그 크기와 그보다 작게 쓴 조각(괄호 부연설명 2pt 작게 등)을 같은 만큼 — 서로의 크기 차이는 그대로
                if s is not None and s <= a:
                    old.append((r, cid))
                    r.set("charPrIDRef", self.hedit.char_size(cid, want - a))
        if todo and self.pages() > self.pages0:
            self._undo(old)
            left += todo
            todo = []
        for p, a, want in todo:
            self.mark(p, f"글자 크기를 같은 머리 기호 줄과 같게({a:g} → {want:g}pt)")
        if todo:
            p, a, want = todo[0]
            self.notes.append(f"같은 머리 기호 줄인데 글자 크기만 다르던 문단 {len(todo)}개를 많이 쓴 크기로 맞췄습니다"
                              f"(예: ‘{self.name(p)}…’ {a:g} → {want:g}pt — 내용 시작점·줄 높이가 위아래로 같게).")
        if left:
            p, a, want = left[0]
            self.notes.append(f"같은 머리 기호인데 글자 크기가 다른 문단 {len(left)}개는 일부러 다르게 썼을 수 있어 그대로 두었습니다"
                              f"(예: ‘{self.name(p)}…’ {a:g}pt, 많이 쓴 크기 {want:g}pt).")

    def _keep_lines(self, p, w, n0):
        """머리(이름표)를 넓혀 줄이 n0보다 늘었을 때 내용 글자 자간을 1%씩 줄여(-18%까지) 줄 수를 n0로 지킨다(어림 오차 대비 폭을
        조금 줄여 봄). 지키면 (쓴 값, 되돌릴 목록), 못 지키면 None(바꾼 것 없음)."""
        text = para_text(p)
        head = head_length(text)
        if head and not self._split_at(p, head):
            return None
        content = self._content_runs(p, head, len(text))
        for d in range(-1, FIT_FLOOR - 1, -1):
            if len(self.lay.para_lines(p, w, delta=d, shrink=SLACK)[1]) <= n0:
                old = self._set_delta(content, d)
                if old and len(self.lay.para_lines(p, w, shrink=SLACK)[1]) <= n0:
                    return d, old
                self._undo(old)  # -18%에 걸린 조각이 있어 실제로는 덜 줄었음 — 더 줄여 봄
        return None

    def _replace_span(self, p, a, b, new):
        """글자 위치 [a, b)를 new로(한 조각 안에 있고 그 조각이 글 하나뿐일 때만)."""
        pos = 0
        for r in para_runs(p):
            t = run_text(r)
            if pos <= a and b <= pos + len(t):
                if not (len(r) == 1 and r[0].tag == T("hp:t")):
                    return False
                set_run_text(r, t[:a - pos] + new + t[b - pos:], self.tab_proto)
                return True
            pos += len(t)
        return False

    # ------------------------------------------------------------ 3-2. 빈칸이 벌어지는 줄(사용자 원칙 — 다음 낱말 당기기)
    def _sparse(self, chs, lines, limit):
        """끝 줄을 빼고 limit보다 덜 찬 줄이 있는가(줄 바꿈으로 끝나는 줄은 한글이 벌리지 않으므로 뺌)."""
        return any(a and u / a < limit and not (e < len(chs) and chs[e][0] == "\n") for _, e, u, a in lines[:-1])

    def _pull_sparse(self, p, w, head, mark=True):
        """다음 낱말이 넘어가 빈칸이 벌어질 줄(97% 미만)이 있으면 ① 자간을 줄여(-18%까지) 그 낱말을 당기고, ② 안 되면 줄 나눔은
        그대로 두고 자간을 조금 늘려(+5%p까지) 덜 벌어지게. 끝 줄이 두세 글자로 짧아지는 당김은 쓰지 않음. 벌어진 줄이 남지 않으면 True."""
        chs, lines = self.lay.para_lines(p, w)
        if len(lines) < 2 or not self._sparse(chs, lines, PULL):
            return True
        if head and not self._split_at(p, head):
            return False
        text = para_text(p)
        content = self._content_runs(p, head, len(text))
        short0 = self._tail_len(chs, lines[-1]) <= SHORT_LAST
        for d in range(-1, FIT_FLOOR - 1, -1):
            c2, l2 = self.lay.para_lines(p, w, delta=d, shrink=SLACK)
            if (len(l2) <= len(lines) and not self._sparse(c2, l2, PULL)
                    and (short0 or self._tail_len(c2, l2[-1]) > SHORT_LAST)):
                old = self._set_delta(content, d)
                c3, l3 = self.lay.para_lines(p, w)
                if not self._sparse(c3, l3, PULL):
                    if mark:
                        self.mark(p, f"빈칸이 벌어지던 줄 — 자간 {d:+d}%로 다음 낱말을 당김")
                    return True
                self._undo(old)
                break
        if not self._sparse(chs, lines, SPARSE):
            return False
        starts = [x[0] for x in lines]
        best = 0
        for d in range(1, WIDEN_MAX + 1):
            _, l2 = self.lay.para_lines(p, w, delta=d, shrink=SLACK)
            if [x[0] for x in l2] != starts:
                break
            best = d
        if best and mark:
            self._set_delta(content, best)
            self.mark(p, f"빈칸이 벌어지던 줄 — 당길 수 없어 자간 {best:+d}%p로 덜 벌어지게")
        return False

    def sparse_lines(self):
        n_ok = n_left = 0
        for sec in self.secs:
            body_w, _ = self.box(sec)
            for p in [x for x in sec if x.tag == T("hp:p")]:
                text = para_text(p)
                if para_tables(p) or para_pics(p) or re.search(r"\n[ ⎵⍽　]+", text) or "\t" in text or not text.strip():
                    continue
                if self.styles.para.get(p.get("paraPrIDRef"), {}).get("align") not in ("JUSTIFY", "DISTRIBUTE", None):
                    continue
                if not self.fonts_ok(p):
                    continue
                chs, lines = self.lay.para_lines(p, body_w)
                if len(lines) < 2 or not self._sparse(chs, lines, PULL):
                    continue
                if self._pull_sparse(p, body_w, head_length(text)):
                    n_ok += 1
                else:
                    n_left += 1
        if n_ok:
            self.notes.append(f"다음 낱말이 넘어가 빈칸이 벌어지던 문단 {n_ok}개는 자간을 줄여(-18%까지) 그 낱말을 당겼습니다.")
        if n_left:
            self.notes.append(f"빈칸이 벌어지는 줄이 남은 문단 {n_left}개 — 긴 낱말이 넘어가 자간으로는 못 당김(+5%p로 덜 벌어지게 한 것 포함).")

    # ------------------------------------------------------------ 4. 끝 줄 두세 글자 올리기(사용자 원칙 — 자간으로만)
    def _split_at(self, p, k):
        """글자 위치 k에서 조각을 나눠(같은 글자 모양) k 뒤 글만 자간을 바꿀 수 있게. 나누지 못하면 False."""
        pos = 0
        for r in para_runs(p):
            t = run_text(r)
            if pos < k < pos + len(t):
                if not (len(r) == 1 and r[0].tag == T("hp:t")):
                    return False
                twin = copy.deepcopy(r)
                set_run_text(r, t[:k - pos], self.tab_proto)
                set_run_text(twin, t[k - pos:], self.tab_proto)
                r.addnext(twin)
                return True
            pos += len(t)
        return True

    def fonts_ok(self, p):
        fonts = {self.styles.char.get(r.get("charPrIDRef"), {}).get("font") for r in para_runs(p)
                 if r.find(T("hp:t")) is not None and run_text(r).strip()}
        return all(self.metrics.checked(f) or f in TIDY_FONTS for f in fonts if f)

    def _content_runs(self, p, lo, hi):
        """글자 위치 [lo, hi) 안에 통째로 든 글 조각(자간을 바꿀 조각)."""
        out, pos = [], 0
        for r in para_runs(p):
            t = run_text(r)
            st, pos = pos, pos + len(t)
            if r.find(T("hp:t")) is not None and st >= lo and pos <= hi and t:
                out.append(r)
        return out

    @staticmethod
    def _shift(base, d):
        """자간 base에 d를 더한 값. 줄일 때는 -18%까지(이미 그보다 좁은 조각은 그대로), 늘릴 때는 +5%까지 —
        이미 -18% 언저리로 좁힌 글도 늘릴 수 있게(따옴표처럼 일부러 -30% 넘게 좁힌 조각만 그대로).
        (실험: 원래 -18%인 문단은 늘리기도 안 돼 윗줄 빈 곳이 그대로였음)"""
        if d < 0:
            return base if base <= FIT_FLOOR else max(FIT_FLOOR, base + d)
        if d > 0:
            return base if base < -30 or base >= WIDEN_MAX else min(WIDEN_MAX, base + d)  # 실제 값 +5%가 상한
        return base

    def _set_delta(self, runs, d):
        """조각마다 지금 자간에 d를 더한다(_shift). 되돌릴 목록을 돌려준다(바뀐 조각만)."""
        old = []
        for r in runs:
            cid = r.get("charPrIDRef")
            cur = self.styles.char.get(cid, {}).get("spacing", 0)
            new = self._shift(cur, d)
            if new != cur:
                old.append((r, cid))
                r.set("charPrIDRef", self.hedit.char_spacing(cid, new))
        return old

    @staticmethod
    def _undo(old):
        for r, cid in old:
            r.set("charPrIDRef", cid)

    def _break_at(self, p, i):
        """글자 위치 i의 보통 빈칸을 줄 바꿈으로 바꾼다(한글 Shift+Enter). 그 조각이 글 하나뿐일 때만."""
        pos = 0
        for r in para_runs(p):
            t = run_text(r)
            if pos <= i < pos + len(t):
                if t[i - pos] != " " or not (len(r) == 1 and r[0].tag == T("hp:t")):
                    return False
                set_run_text(r, t[:i - pos] + "\n" + t[i - pos + 1:], self.tab_proto)
                return True
            pos += len(t)
        return False

    @staticmethod
    def _tail_len(chs, line):
        return len(re.sub(r"[ ⎵⍽\n]", "", "".join(c[0] for c in chs[line[0]:line[1]])))

    def short_lines(self):
        """끝 줄에 두세 글자(빈칸 빼고 SHORT_LAST자 이하)만 남은 글 문단 — 사용자 원칙(style-guide 2절):
        ① 내용 글자의 자간을 1%씩 줄여(본문 -18%까지, 겹칠 만큼은 안 됨) 그 글자를 윗줄로 올린다.
        ② 올리면 겹칠 만큼 줄여야 하면, 문단 자간을 1%씩 늘려(+5%까지) 윗줄 낱말이 끝 줄로 자연스럽게 내려와 끝 줄이
           PUSH_LO자를 넘게 한다 — 윗줄은 양쪽 정렬로 꽉 찬 채(빈 곳이 남지 않음).
        ③ 그래도 안 되면 윗줄 낱말 경계의 빈칸을 줄 바꿈으로 바꿔 끝 줄을 PUSH_LO~PUSH_HI자로 내리고, 짧아진 윗줄의 자간을
           늘려(+5%까지) 빈 곳을 줄인다(한글은 줄 바꿈 바로 앞 줄을 벌리지 않아 그대로 두면 윗줄 끝이 빔).
        머리 기호·이름표는 자간을 바꾸지 않는다(둘째 줄 맞춤 그대로). 맞대어 보지 않은 글꼴은 건드리지 않음."""
        pulled, lowered, broke, cannot, unsure = [], [], [], [], 0
        self._lowered = {}
        for sec in self.secs:
            body_w, _ = self.box(sec)
            for p in [x for x in sec if x.tag == T("hp:p")]:
                if para_tables(p) or para_pics(p) or "\n" in para_text(p) or "\t" in para_text(p):
                    continue
                if self.styles.para.get(p.get("paraPrIDRef"), {}).get("align") not in ("JUSTIFY", "DISTRIBUTE", "LEFT", None):
                    continue
                chs, lines = self.lay.para_lines(p, body_w)
                if len(lines) < 2:
                    continue
                tail = "".join(c[0] for c in chs[lines[-1][0]:lines[-1][1]]).strip()
                if not tail or self._tail_len(chs, lines[-1]) > SHORT_LAST:
                    continue
                if not self.fonts_ok(p):
                    unsure += 1
                    continue
                text = para_text(p)
                head = head_length(text)
                # 머리 기호·이름표와 내용을 다른 조각으로 먼저 나눔 — 어림(Layout.chars)은 내용 조각에만 자간을 더해 보고,
                # 실제로도 내용만 바꿔야 둘째 줄 맞춤이 그대로(한 조각 문단이면 자간이 아예 안 걸려 '못 올림'으로 나왔음)
                if head and not self._split_at(p, head):
                    unsure += 1
                    continue
                content = self._content_runs(p, head, len(text))
                n = len(lines)
                # ① 올리기
                need = next((d for d in range(-1, FIT_FLOOR - 1, -1)
                             if len(self.lay.para_lines(p, body_w, delta=d, shrink=SLACK)[1]) < n), None)
                if need is not None:
                    old = self._set_delta(content, need)
                    if len(self.lay.para_lines(p, body_w)[1]) < n:
                        self.mark(p, f"끝 줄 ‘{tail}’ — 자간 {need:+d}%로 윗줄에")
                        pulled.append(tail)
                        continue
                    self._undo(old)
                # ② 문단 자간을 조금 늘려 윗줄 낱말을 자연스럽게 내리기(윗줄은 꽉 찬 채)
                # 낱말이 내려오는 가장 작은 값에서 멈추면 윗줄이 95%쯤 차 양쪽 정렬로 낱말 사이가 벌어진다(샘플: '총 ○○억원 …
                # 따라' 줄 — 사용자 '위에 어색한 빈공간이 남지 않게'). 같은 낱말이 내려온 채로 자간을 더 늘려 윗줄이 가장 꽉 차는
                # 값을 고른다 — 어림 오차 대비 쓸 수 있는 폭을 조금 줄여 봐도 줄 나눔이 같은 값까지만.
                got, best_fill, cut, cands = None, 0.0, None, []
                base_c = min((self.styles.char.get(r.get("charPrIDRef"), {}).get("spacing", 0) for r in content), default=0)
                for d in range(1, max(WIDEN_MAX, WIDEN_MAX - base_c) + 1):
                    c2, l2 = self.lay.para_lines(p, body_w, delta=d)
                    ok = (len(l2) == n and self._tail_len(c2, l2[-1]) > PUSH_LO - 1
                          and all(u / a >= FULL for _, _, u, a in l2[:-1]))
                    if not ok:
                        if got is not None:
                            break
                        continue
                    starts = [x[0] for x in l2]
                    if got is not None:
                        _, l3 = self.lay.para_lines(p, body_w, delta=d, shrink=SLACK)
                        if starts != cut or [x[0] for x in l3] != starts:
                            break
                    fill = min(u / a for _, _, u, a in l2[:-1])
                    cands.append((d, fill))
                    if got is None or fill > best_fill:
                        got, best_fill, cut = d, fill, starts
                if got is not None:
                    first0 = self._content_spacing(p)
                    old = self._set_delta(content, got)
                    c2, l2 = self.lay.para_lines(p, body_w)
                    if (len(l2) == n and self._tail_len(c2, l2[-1]) > PUSH_LO - 1
                            and all(u / a >= FULL for _, _, u, a in l2[:-1])):
                        last ="".join(c[0] for c in c2[l2[-1][0]:l2[-1][1]]).strip()
                        self.mark(p, f"끝 줄 ‘{tail}’ — 올리면 글자가 겹쳐 문단 자간을 {got:+d}%p 늘려 윗줄 낱말을 함께 내림(끝 줄 ‘{last}’)")
                        lowered.append(last)
                        self._lowered[p] = dict(content=content, cands=cands, got=got, old=old, w=body_w, n=n, tail=tail,
                                                first0=first0, idx=len(self.changes[p]) - 1)
                        continue
                    self._undo(old)
                # ③ 줄 바꿈으로 내리고 윗줄 자간을 늘려 빈 곳 줄이기
                ps, pe = lines[-2][0], lines[-2][1]
                tn = self._tail_len(chs, lines[-1])
                best = None
                for i in range(pe - 1, max(ps, head), -1):
                    if chs[i][0] != " " or chs[i - 1][0] in (" ", "⎵", "⍽"):
                        continue
                    k = tn + len(re.sub(r"[ ⎵⍽]", "", "".join(c[0] for c in chs[i + 1:pe])))
                    if k > PUSH_HI:
                        break
                    if k >= PUSH_LO:
                        best = i  # 가장 적게 내리는 자리(윗줄 빈 곳이 가장 작음)
                        break
                if best is None or not self._break_at(p, best):
                    cannot.append(tail)
                    continue
                c2, l2 = self.lay.para_lines(p, body_w)
                if len(l2) != n:  # 줄 수가 바뀌면 되돌림
                    self._unbreak(p)
                    cannot.append(tail)
                    continue
                lo = max(head, l2[-2][0])
                hi = l2[-2][1]
                if lo > head:
                    self._split_at(p, lo)
                self._split_at(p, hi)  # 윗줄 글만 한 조각으로(줄 바꿈 뒤 끝 줄은 그대로)
                upper = self._content_runs(p, lo, hi)
                wide = 0
                # 늘리는 폭: 실제 자간이 +5%(사용자 상한)가 될 때까지 — 원래 -18%로 좁힌 줄이면 보통 간격 쪽으로 되돌아가며 채움
                base = min((self.styles.char.get(r.get("charPrIDRef"), {}).get("spacing", 0) for r in upper), default=0)
                for d in range(1, WIDEN_MAX + 1):
                    old = self._set_delta(upper, d)
                    ok = bool(old) and len(self.lay.para_lines(p, body_w, shrink=SLACK)[1]) == n
                    self._undo(old)
                    if not ok:
                        break
                    wide = d
                if wide:
                    self._set_delta(upper, wide)
                c3, l3 = self.lay.para_lines(p, body_w)
                last = "".join(c[0] for c in c3[l3[-1][0]:l3[-1][1]]).strip()
                fill = l3[-2][2] / l3[-2][3] if l3[-2][3] else 1
                now = self.styles.char.get(upper[0].get("charPrIDRef"), {}).get("spacing", 0) if upper else 0
                self.mark(p, f"끝 줄 ‘{tail}’ — 올리면 글자가 겹쳐 윗줄 낱말을 함께 내림(끝 줄 ‘{last}’, 줄 바꿈)"
                             + (f", 윗줄 자간 {base:+d} → {now:+d}%로 빈 곳 채움(채움 {fill:.0%})" if wide else ""))
                broke.append((last, fill))
        if pulled:
            self.notes.append(f"끝 줄에 두세 글자만 남은 문단 {len(pulled)}개는 자간을 조금 줄여 윗줄로 올렸습니다"
                              f"(예: ‘{pulled[0]}’ — 글은 그대로, 본문 -18%까지).")
        if lowered:
            self.notes.append(f"올리면 글자가 겹치는 문단 {len(lowered)}개는 문단 자간을 조금 늘려(실제 값 +5%까지) 윗줄 낱말을 함께 내렸습니다"
                              f"(끝 줄 {PUSH_LO}자 넘게, 윗줄은 꽉 찬 채 — 예: ‘{lowered[0]}’).")
        if broke:
            low = [f for _, f in broke if f < FULL]
            self.notes.append(f"올리면 글자가 겹치고 자간을 늘려도 안 내려오는 문단 {len(broke)}개는 윗줄 낱말 앞에 줄 바꿈을 넣어 함께 내리고 "
                              f"윗줄 자간을 늘려 빈 곳을 줄였습니다(예: ‘{broke[0][0]}’)"
                              + (f" — 그래도 윗줄 끝이 조금 빈 곳 {len(low)}개(한글에서 확인)" if low else "") + ".")
        if cannot:
            self.notes.append(f"끝 줄 두세 글자 {len(cannot)}곳은 올리지도 내리지도 못해 그대로 두었습니다(예: ‘{cannot[0]}’) — "
                              "낱말 하나를 빼거나 순서를 바꾸면 됨(글 고침은 정돈이 하지 않음).")
        if unsure:
            self.notes.append(f"끝 줄 두세 글자가 남은 문단 {unsure}개는 폭을 맞대어 보지 않은 글꼴이라 자간을 바꾸지 않았습니다(한글에서 확인).")

    def _content_spacing(self, p):
        """머리 기호·이름표 뒤 내용 첫 글자의 자간(%)."""
        text = para_text(p)
        k = head_length(text)
        while k < len(text) and text[k] in " ⎵⍽　\t":
            k += 1
        pos = 0
        for r in para_runs(p):
            t = run_text(r)
            if pos <= k < pos + len(t) and r.find(T("hp:t")) is not None:
                return self.styles.char.get(r.get("charPrIDRef"), {}).get("spacing", 0)
            pos += len(t)
        return None

    def harmonize(self):
        """끝 줄을 내리려고 문단 자간을 늘린 문단(short_lines ②)은 같은 낱말이 내려오는 자간이 여럿일 수 있다 — 그 가운데 같은 □
        아래 같은 수준 이웃 줄(앞·뒤)의 내용 자간에 가장 가까운 값을 고른다(같으면 윗줄이 더 꽉 차는 값). 이웃 줄보다 자간이 넓으면
        그 줄 글자만 커 보인다(사용자: '사업비 글자가 조금 큰거 같은데' — 크기는 같고 자간 -2% 대 -7%였음, '이름표는 위아래 직선
        정렬이니 뒤에 글자의 자간만 줄이는 거죠')."""
        if not self._lowered:
            return
        order, group = [], 0
        for sec in self.secs:
            for p in [x for x in sec if x.tag == T("hp:p")]:
                if para_tables(p) or para_pics(p):
                    continue
                lv = self.level(para_text(p))
                if lv == 1:
                    group += 1
                elif lv:
                    order.append((p, group, lv))
        pos = {p: i for i, (p, _, _) in enumerate(order)}
        moved = 0
        for p, info in self._lowered.items():
            if p not in pos or len(info["cands"]) < 2 or info["first0"] is None:
                continue
            i = pos[p]
            _, g, lv = order[i]
            near = []
            for step in (-1, 1):
                j = i + step
                while 0 <= j < len(order) and order[j][1] == g and order[j][2] > lv:
                    j += step
                if 0 <= j < len(order) and order[j][1] == g and order[j][2] == lv:
                    v = self._content_spacing(order[j][0])
                    if v is not None:
                        near.append(v)
            if not near:
                continue
            target = sum(near) / len(near)
            d = min(info["cands"], key=lambda c: (abs(self._shift(info["first0"], c[0]) - target), -c[1]))[0]
            if d == info["got"]:
                continue
            self._undo(info["old"])
            old = self._set_delta(info["content"], d)
            c2, l2 = self.lay.para_lines(p, info["w"])
            if not (len(l2) == info["n"] and self._tail_len(c2, l2[-1]) > PUSH_LO - 1
                    and all(u / a >= FULL for _, _, u, a in l2[:-1])):
                self._undo(old)
                self._set_delta(info["content"], info["got"])
                continue
            last = "".join(c[0] for c in c2[l2[-1][0]:l2[-1][1]]).strip()
            now = self._content_spacing(p)
            self.changes[p][info["idx"]] = (f"끝 줄 ‘{info['tail']}’ — 올리면 글자가 겹쳐 문단 자간을 {d:+d}%p 늘려 윗줄 낱말을 함께 "
                                            f"내림(끝 줄 ‘{last}’, 내용 자간 {now:+d}% — 이웃 줄과 비슷하게)")
            moved += 1
        if moved:
            self.notes.append(f"끝 줄을 내리려 자간을 늘린 문단 {moved}개는 내용 자간을 이웃 줄(같은 □ 아래 같은 수준)과 비슷하게 "
                              "골랐습니다 — 그 줄 글자만 커 보이지 않게.")

    def fill_broken(self):
        """줄 바꿈(Shift+Enter)으로 끝나는 줄은 한글이 양쪽 정렬로 벌리지 않아 줄 끝이 빈다 — 끝 줄 균형을 맞추려고 넣은 줄 바꿈
        (작성 도구의 '함께 내리기' 등)이면 그 줄이 80% 넘게 찬 것 — 자간을 늘려(실제 값 +5%까지) 빈 곳을 채운다
        (사용자: '다섯 글자 넘게 아래로 내리는 경우 위에 어색한 빈 공간이 남지 않게 글자 간격을 조정'). 줄 바꿈 뒤를 빈칸으로
        들인 문단(둘째 줄 흉내)과 맞대어 보지 않은 글꼴은 건드리지 않음."""
        n = unbroken = 0
        for sec in self.secs:
            body_w, _ = self.box(sec)
            for p in [x for x in sec if x.tag == T("hp:p")]:
                text = para_text(p)
                if "\n" not in text or "\t" in text or para_tables(p) or para_pics(p) or re.search(r"\n[ ⎵⍽　]+", text):
                    continue
                if not self.fonts_ok(p):
                    continue
                head = head_length(text)
                chs, lines = self.lay.para_lines(p, body_w)
                count = len(lines)
                for li in range(len(lines) - 1):
                    chs, lines = self.lay.para_lines(p, body_w)
                    s0, e0, used, avail = lines[li]
                    if not (e0 < len(chs) and chs[e0][0] == "\n") or not avail or not (BROKEN_MIN <= used / avail < FULL):
                        continue
                    # 먼저 그 줄 바꿈을 풀어(빈칸으로) 한글이 저절로 나누게 해 본다 — 정돈으로 내어쓰기가 바뀌어 더는 필요 없는
                    # 줄 바꿈이면 윗줄이 양쪽 정렬로 꽉 차고 끝 줄도 짧지 않음(그러면 푼 채로 둠)
                    if self._swap_char(p, e0, "\n", " "):
                        ok = self._pull_sparse(p, body_w, head, mark=False)
                        c2, l2 = self.lay.para_lines(p, body_w)
                        if ok and len(l2) <= count and self._tail_len(c2, l2[-1]) > SHORT_LAST:
                            self.mark(p, f"줄 바꿈을 풀어 저절로 나눔(윗줄 채움 {used / avail:.0%} → 꽉 참)")
                            unbroken += 1
                            count = len(l2)
                            break
                        self._swap_char(p, e0, " ", "\n")
                    lo = max(head, s0)
                    if not (self._split_at(p, lo) and self._split_at(p, e0)):
                        continue
                    seg = self._content_runs(p, lo, e0)
                    base = min((self.styles.char.get(r.get("charPrIDRef"), {}).get("spacing", 0) for r in seg), default=0)
                    wide = 0
                    for d in range(1, WIDEN_MAX + 1):
                        old = self._set_delta(seg, d)
                        _, l2 = self.lay.para_lines(p, body_w, shrink=SLACK)
                        ok = bool(old) and len(l2) == count
                        self._undo(old)
                        if not ok:
                            break
                        wide = d
                    if wide:
                        self._set_delta(seg, wide)
                        _, l3 = self.lay.para_lines(p, body_w)
                        now = self.styles.char.get(seg[0].get("charPrIDRef"), {}).get("spacing", 0) if seg else 0
                        self.mark(p, f"줄 바꿈으로 끝나는 줄의 빈 곳을 자간 {base:+d} → {now:+d}%로 채움"
                                     f"(채움 {used / avail:.0%} → {l3[li][2] / l3[li][3]:.0%})")
                        n += 1
        if unbroken:
            self.notes.append(f"줄 바꿈으로 끝나 줄 끝이 비던 줄 {unbroken}개는 줄 바꿈이 더는 필요 없어 풀었습니다(한글이 저절로 나눠 윗줄이 꽉 참).")
        if n:
            self.notes.append(f"줄 바꿈으로 끝나 줄 끝이 비던 줄 {n}개는 자간을 늘려(실제 값 +5%까지) 빈 곳을 채웠습니다"
                              "(한글은 줄 바꿈 앞 줄을 양쪽으로 벌리지 않음).")

    def _swap_char(self, p, i, a, b):
        """글자 위치 i의 a를 b로(줄 바꿈 ↔ 빈칸). 그 조각이 글 하나뿐일 때만."""
        pos = 0
        for r in para_runs(p):
            t = run_text(r)
            if pos <= i < pos + len(t):
                if t[i - pos] != a or not (len(r) == 1 and r[0].tag == T("hp:t")):
                    return False
                set_run_text(r, t[:i - pos] + b + t[i - pos + 1:], self.tab_proto)
                return True
            pos += len(t)
        return False

    def _unbreak(self, p):
        for r in para_runs(p):
            t = run_text(r)
            if "\n" in t and len(r) == 1 and r[0].tag == T("hp:t"):
                set_run_text(r, t.replace("\n", " "), self.tab_proto)

    def cell_middle(self):
        n_tbl = 0
        for sec in self.secs:
            for tbl in sec.iter(T("hp:tbl")):
                hit = 0
                for *_, tc in table_grid(tbl):
                    sub = tc.find(T("hp:subList"))
                    if sub is None or sub.get("vertAlign") in (None, "CENTER"):
                        continue
                    if any(para_pics(cp) for cp in cell_paras(tc)):
                        continue
                    sub.set("vertAlign", "CENTER")
                    hit += 1
                if hit:
                    n_tbl += 1
        if n_tbl:
            self.notes.append(f"표 {n_tbl}개의 칸 글을 세로 가운데로 맞췄습니다(위·아래 붙임이던 칸).")
        return n_tbl

    # ------------------------------------------------------------ 6. 빈칸 한 칸(사용자 2026-11-08)
    def one_space(self):
        """조판 부호를 켜면 ○·- 뒤마다 [고정폭 빈 칸]이 두 개, 이름표 안에는 여덟 개씩 보였다(사용자: '한칸만 띄워야 하는 곳에
        두칸 띄움이 있는 곳이 많다 … 불필요한 연속 두칸 띄우기는 한칸 띄우기로 바꾸라. 지금까지 정한 규칙이 흐트러지면 안되겠지').
        보통 빈칸·묶음 빈칸·반각 빈칸 한 개로 바꾸면 양쪽 정렬에서 늘고 줄어 둘째 줄 맞춤이 0.5~1mm 어긋났다(한글 2024 시험).
        그래서 폭은 그대로 두고 글자 수만 줄인다: ① 머리(내용 앞)의 고정폭 빈칸 두 개 = 장평 200% 고정폭 빈칸 한 개(실측
        0.498글자 — 보통 빈칸 한 칸, 양쪽 정렬에도 그대로) ② 머리 기호 앞 줄머리 빈칸은 문단 여백으로 옮김(자리 그대로, 부호 없음).
        폭이 같아 둘째 줄 맞춤·이름표 폭·쪽 나눔은 바뀌지 않는다."""
        n_gap = sum(self._compact_fw(p) for p in self.all_paras())
        if n_gap:
            self.notes.append(f"머리 기호 뒤·이름표 안의 고정폭 빈칸 두 개(보통 빈칸 한 칸 폭) {n_gap}곳을 장평을 두 배로 한 고정폭 빈칸 "
                              "한 개로 바꿨습니다 — 폭은 같고 조판 부호는 한 칸(둘째 줄 맞춤 그대로).")

    def double_spaces(self):
        """글 가운데 보통 빈칸 두 칸 넘게 잇단 곳을 한 칸으로(사용자: '불필요한 연속 두칸 띄우기는 한칸 띄우기로'). 머리(머리 기호·
        이름표 — 작성자가 빈칸으로 폭을 맞춘 '- 대   상 :')와 줄머리, 표 머리 칸처럼 낱자 사이를 벌린 짧은 칸('구  분'·'하  천' —
        style-guide 비교표 꼴)은 그대로. 줄 맞춤 단계보다 먼저 한다(줄 나눔이 바뀔 수 있어서)."""
        n = 0
        for p in self.all_paras():
            text = para_text(p)
            if "  " not in text or re.fullmatch(r"\s*[가-힣](?: +[가-힣]){1,3}\s*", text):
                continue
            if DATE_LINE_RE.match(text):
                continue  # 날짜·부서 줄('’26. 11. 2.(월)  ○○과')은 두 칸으로 갈라 둔 것
            k = head_length(text) if self.split(text)[1] else 0
            m0 = re.match(r"^[ ⎵⍽　]*", text)
            k = max(k, m0.end() if m0 else 0)
            pos, hit = 0, False
            for r in para_runs(p):
                t = run_text(r)
                st, pos = pos, pos + len(t)
                if pos <= k or not (len(r) == 1 and r[0].tag == T("hp:t")) or "  " not in t:
                    continue
                lo = max(0, k - st)
                new = t[:lo] + re.sub(r"(?<=\S) {2,}(?=\S)", " ", t[lo:])
                if new != t:
                    set_run_text(r, new, self.tab_proto)
                    hit = True
            if hit:
                self.touched.add(p)
                n += 1
        if n:
            self.notes.append(f"글 가운데 보통 빈칸이 두 칸 넘게 잇단 문단 {n}개를 한 칸으로 줄였습니다(이름표 안·표 머리 칸 '구  분' 꼴은 그대로).")

    def leading(self):
        """머리 기호 앞 줄머리 빈칸을 문단 왼쪽 여백(또는 첫 줄 들여쓰기)으로 옮긴다 — 자리는 같고 빈칸 부호는 없음. 줄 맞춤
        단계보다 먼저 해야 줄 채움(%)을 같은 폭으로 잰다(나중에 하면 두 번째 정돈이 다른 줄을 '덜 참'으로 보고 다시 당겼음)."""
        n = 0
        self._lead_moved = set()
        w = self.box(self.secs[0])[0] if self.secs else 0  # 글자 폭만 쓰므로 표 칸 문단도 본문 폭으로 어림해도 같음
        for p in self.all_paras():  # 표 칸 안 '  ○ (평가근거) …'도
            if not (para_tables(p) or para_pics(p)) and self._lead_to_margin(p, w):
                self._lead_moved.add(p)
                n += 1
        if n:
            self.notes.append(f"머리 기호 앞 줄머리 빈칸 {n}곳을 문단 왼쪽 여백으로 옮겼습니다 — 자리는 같고 빈칸 부호는 없음.")

    def _lead_to_margin(self, p, w):
        """머리 기호 앞 줄머리 빈칸을 문단 여백으로(spaces.lead_to_margin — 작성과 같은 규칙)."""
        if lead_to_margin(p, self.styles, self.hedit, self.lay, self.split, self.fonts_ok, self.tab_proto, w):
            self.touched.add(p)
            return True
        return False

    def _compact_fw(self, p):
        """머리의 고정폭 빈칸 두 개를 장평 두 배 한 개로(spaces.compact_fw — 작성과 같은 규칙). 바꾼 묶음 수."""
        n = compact_fw(p, self.styles, self.hedit, self.split, self.tab_proto)
        if n:
            self.touched.add(p)
        return n

    # ------------------------------------------------------------ 확인·저장
    def pages(self):
        return self.layout_state()[0]

    def layout_state(self):
        """(어림 쪽 수, 쪽 끝에 홀로 남은 ○ 제목 줄 수). ○ 줄이 쪽 끝에 있고 바로 아래 딸린 줄(-·*·※·표)이 다음 쪽에서
        시작하면 홀로 남은 것(사용자 원고 시험: ○ 위 간격 3pt를 넣자 ○ 제목 줄 하나만 3쪽 끝에 남음)."""
        total = orphans = 0
        for sec in self.secs:
            body_w, body_h = self.box(sec)
            paras = [p for p in sec if p.tag == T("hp:p")]
            where, _ = self.lay.paginate(paras, body_w, body_h)
            for k in range(len(paras) - 1):
                if (not para_tables(paras[k]) and marker_level(para_text(paras[k])) == 2
                        and (para_tables(paras[k + 1]) or self.level(para_text(paras[k + 1])) in (3, 4))
                        and where[k + 1][0] > where[k][1]):
                    orphans += 1
            total += (max(e for _, e in where) + 1) if where else 0
        return total, orphans

    def line_counts(self):
        """본문 글 문단마다 어림 줄 수 — 정돈 전후를 견줘 줄이 늘어난 문단을 알린다(이름표·머리 자간을 넓혀 한 줄이 두 줄로
        넘어간 일을 한글 그림을 보기 전에는 몰랐음)."""
        out = {}
        for sec in self.secs:
            body_w, _ = self.box(sec)
            for p in [x for x in sec if x.tag == T("hp:p")]:
                if not (para_tables(p) or para_pics(p)) and para_text(p).strip():
                    out[p] = len(self.lay.para_lines(p, body_w)[1])
        return out

    def run(self, out):
        self.pages0, self.orphans0 = self.layout_state()
        before = self.pages0
        lines0 = self.line_counts()
        # 높이가 바뀌지 않는 것 먼저, 높이를 늘릴 수 있는 것(빈 줄·○ 위 간격)은 쪽 수를 재 보며 나중에
        self.word_wrap()
        if not self.made:
            self.double_spaces()  # 작성 문서의 글 속 빈칸은 계획에 적은 그대로(날짜·부서 줄 '…(월)  ○○과' 등)
        if self.made:
            # 작성 모드로 만든 문서: 작성 규칙이 맞춘 것은 그대로, 사람이 더한 줄(내어쓰기 없음)·줄 나눔·빈칸만
            self.leading()
            self.hangs()
            self.one_space()
            self.notes.insert(0, f"이 스킬의 작성 모드로 만든 문서(판 {self.made})라 작성 규칙이 맞춘 끝 줄·이름표·내어쓰기·칸·간격은 "
                                 "그대로 두고, 내어쓰기가 없는 문단(만든 뒤 더한 줄)·글자 단위 줄 나눔·빈칸만 손봤습니다 — "
                                 "글을 크게 고쳤으면 계획을 고쳐 다시 만드는 것이 정확합니다(모두 다시 맞추려면 --all).")
        else:
            self.sizes()
            self.labels()
            self.leading()  # 머리 자간을 같은 수준 값으로 맞춘 뒤에 — 그래야 줄머리 폭(여백)도 위아래 같은 값(○ 자리 한 줄로)
            self.hangs()
            self.sparse_lines()
            self.short_lines()
            self.fill_broken()
            self.harmonize()
            self.cell_middle()
            self.blank_heights()
            self.o_gaps()
            self.one_space()
        now = self.line_counts()
        grown = [p for p, k in lines0.items() if now.get(p, k) > k]
        if grown:
            self.notes.append(f"정돈 뒤 줄 수가 늘어난 문단 {len(grown)}개(예: ‘{self.name(grown[0])}…’) — 둘째 줄 맞춤·글자 크기 맞춤 때문일 수 있음(한글에서 확인).")
        self.grown = grown
        for p in self.touched:
            drop_linesegs(p)
        bad = [p for p in self.all_paras() if flat(para_text(p)) != self.orig_text.get(p, flat(para_text(p)))]
        after = self.pages()
        self.pkg.save(out)
        return before, after, bad

    def report(self, before, after, bad, out):
        print(f"만듦: {out}  (원본은 그대로)")
        if bad:
            print("## 문제 있음")
            print(f" - 글자가 바뀐 문단 {len(bad)}개 — 정돈은 글자를 바꾸면 안 됩니다(도구 오류): "
                  + ", ".join(f"‘{flat(para_text(p))[:12]}…’" for p in bad[:3]))
        print("## 한 일")
        for n in self.notes or ["바꿀 곳이 없었습니다(이미 정돈된 문서)."]:
            print(" - " + n)
        print("## 바뀐 곳(실제로 바뀐 문단만, 쪽은 원본 기준" + (" 어림" if self.page_guess else "") + ")")
        order = {p: k for k, p in enumerate(self.body)}
        rows = sorted(self.changes.items(), key=lambda x: order.get(x[0], 10 ** 6))
        if not rows:
            print(" - 없음")
        for p, whats in rows[:80]:
            pg = self.page_of.get(p)
            print(f" - {pg or '?'}쪽 ‘{self.name(p)}’: " + ", ".join(dict.fromkeys(whats)))
        if len(rows) > 80:
            print(f" - … 그 밖 {len(rows) - 80}곳")
        print("## 쪽")
        line = f" - 어림 쪽 수 {before}쪽 → {after}쪽(한글 없이 어림 — 마지막 확인은 한글에서)"
        if after > before:
            line += f" — 쪽이 늘어날 수 있습니다. 정돈은 글·쪽 나눔을 고치지 않으니, 넘치는 쪽을 한글에서 확인해 주세요"
        print(line)


def main():
    ap = argparse.ArgumentParser(description="이미 쓴 한글(hwpx) 파일을 제자리에서 최소로 정돈(글자·차례·문체 그대로)")
    ap.add_argument("path")
    ap.add_argument("--out")
    ap.add_argument("--no-keep-o", action="store_true",
                    help="○ 줄에 '다음 문단과 함께'를 넣지 않음(기본은 넣음 — ○ 제목이 쪽 끝에 홀로 남지 않게)")
    ap.add_argument("--gap", type=float, help="○ 위 간격(pt)을 이 값 하나로만 해 봄(시험용)")
    ap.add_argument("--blank-mm", type=float, help="□ 앞 빈 줄 높이가 제각각일 때 이 높이(mm)에 가장 가까운 빈 줄로 모두 맞춤")
    ap.add_argument("--all", action="store_true",
                    help="이 스킬의 작성 모드로 만든 문서도 정돈 규칙으로 모두 다시 맞춤(기본은 작성 규칙이 맞춘 것을 그대로 둠)")
    a = ap.parse_args()
    if not a.path.lower().endswith(".hwpx"):
        raise SystemExit("정돈은 한글(HWPX) 파일만 받습니다. PDF·그림 문서는 '옮겨 쓰기'(내용 그대로 새로 만들기)로 하세요."
                         " 옛 형식(.hwp)이면 한글에서 [다른 이름으로 저장] → 'HWPX'로 저장해 주세요.")
    out = a.out or re.sub(r"\.hwpx$", "", a.path, flags=re.I) + "_정돈.hwpx"
    if os.path.abspath(out) == os.path.abspath(a.path):
        raise SystemExit("결과를 원본과 같은 이름으로 저장하지 않습니다 — 다른 이름을 주세요.")
    t = Tidier(a.path, keep_o=not a.no_keep_o, gaps=[int(round(a.gap * 100))] if a.gap else None, blank_mm=a.blank_mm,
               all_rules=a.all)
    before, after, bad = t.run(out)
    t.report(before, after, bad, out)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
