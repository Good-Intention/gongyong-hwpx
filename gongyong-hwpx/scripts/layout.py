# -*- coding: utf-8 -*-
"""한글 프로그램 없이 줄 나눔과 쪽 나눔을 어림한다.

- 글자 폭은 assets/font_widths.json(한컴오피스 2024 글꼴 파일에서 잰 값)을 쓴다.
  표에 없는 글꼴은 비슷한 글꼴 값을, 그것도 없으면 어림값(한글 1글자, 영문·숫자 0.55글자)을 쓴다.
- 한 글자 폭 = 글자 크기 × 글꼴 폭 × 장평/100 + 글자 크기 × 자간/100
- 줄 나눔은 어절(띄어쓰기) 단위. 다만 숫자·영문과 한글이 바뀌는 자리는 한글도 끊는다(실측) — 이런 자리에서
  끊기면 '어절 안 끊김'으로 보고 자간을 조정해 피한다.
- 여백 먼저: 쓸 수 있는 폭은 늘 '용지 폭 − 쪽 여백 − 문단 왼쪽·오른쪽 여백(− 내어쓰기)'으로 계산한다.
"""
import json
import os

from style_profile import P as PROFILE  # noqa: E402 — 기준값(assets/profile.json)
from hwpx_lib import UNIT_RE, T, cell_paras, head_length, is_num_char, para_pics, para_runs, para_tables, para_text, run_text, table_grid

HERE = os.path.dirname(os.path.abspath(__file__))
FONT_FILE = os.path.join(HERE, "..", "assets", "font_widths.json")

# 표에 없는 글꼴 → 폭이 비슷한 글꼴
ALIASES = {
    "HY중고딕": "HY견고딕", "견고딕": "HY견고딕", "HY견명조": "한컴바탕", "HY신명조": "한컴바탕",
    "신명조": "한컴바탕", "견명조": "한컴바탕", "함초롬바탕": "한컴바탕", "함초롬돋움": "한컴돋움", "바탕": "한컴바탕",
    "바탕체": "한컴바탕", "돋움": "한컴돋움", "돋움체": "한컴돋움", "굴림": "한컴돋움", "굴림체": "한컴돋움",
    "나눔고딕": "맑은 고딕", "나눔명조": "한컴바탕", "HY그래픽": "한컴돋움", "HY울릉도M": "HY헤드라인M",
    "HY견고딕": "HY견고딕", "한컴 고딕": "맑은 고딕", "Malgun Gothic": "맑은 고딕", "중고딕": "한양중고딕",
    "한양신명조": "한컴바탕", "한양견명조": "한컴바탕", "한양견고딕": "HY견고딕",
}
# 고정폭 빈칸(⎵) 폭: 글자 크기의 1/4(한글 2024 실측 — 빈칸 20개가 한글 5자 폭). 보통 빈칸은 글꼴마다 다름(휴먼명조 1/2)
FW_EM = 0.25
# 쪽 설정이 든 첫 문단의 표(제목 상자 등)에 한글이 더 두는 높이: 없음(2026-11-05 한글 PDF 글자 위치로 실측 — 1쪽 글 줄이
# 2쪽 이후와 같은 자리가 되는 값, 시험 문서 9개). 옛 값 4.7mm는 '쪽 번호 넣기' 조각이 제목 상자 앞에 있던 때(v1.2 전)의 몫과
# 요약 상자 줄 간격 여분(약 1.8mm, para_height)을 섞어 세던 것 — 1쪽을 실제보다 2.9mm 꽉 찼다고 어림했음
FIRST_TABLE_EXTRA = 0
# 그 문단에 '쪽 번호 넣기' 같은 조종 조각이 표 앞에 따로 있으면 한글이 그 조각에 한 줄을 더 준다 — 제목 상자가 4.9mm
# 내려감(사람이 쓴 쉼터 문서 실측 2026-11-05). 도구로 만든 문서는 그 조각을 날짜 줄로 옮겨 이 몫이 없다
CTRL_LINE_EXTRA = 1390
SUP_SCALE = 0.64  # 위·아래 첨자 폭 = 글자 크기 × 이 값(한글 2024 실측)
CLOSE = set(")]}>,.:;!?%’”」』】〉》、。…~°′″")
OPEN = set("([{<‘“「『【〈《")
SPACES = {" ", "　", "⍽"}  # 빈칸, 전각 빈칸, 묶음 빈칸(⍽ — 끊지 않음)


FIT_FLOOR = PROFILE["spacing_min_pct"]  # 줄 맞춤이 자간을 줄이는 하한(fit_base.FLOOR와 같게). 어림의 기본 바닥값도 이것 — 옛 기본 -10이면 자간을
                 # 더 줄여 보며 잴 때 -10%보다 이미 줄인 조각을 더 줄이지 않는 것으로 세어 맞춤 단계(-18%)와 어긋났음(사용자 작업 2026-11-06)


def spacing_after(base, delta, floor=FIT_FLOOR, ceil=PROFILE["spacing_max_pct"]):
    """자간 base에 delta를 더한 값. 늘릴 때는 ceil(사용자 원칙 +5%)까지만 — 이미 그 위인 조각은 더 늘리지 않음(옛 상한 +10%, 평가 2026-11-09).
    줄일 때는 floor까지. floor 밑(따옴표 붙이기 등)과 +10% 위 조각은 그대로."""
    if not delta or base < floor or base > 10:
        return base
    if delta > 0:
        return base if base >= ceil else min(ceil, base + delta)
    return max(floor, base + delta)


def is_hangul(ch):
    return "가" <= ch <= "힣" or "ᄀ" <= ch <= "ᇿ" or "㄰" <= ch <= "㆏"


def is_cjk(ch):
    return "一" <= ch <= "鿿" or "㐀" <= ch <= "䶿" or "豈" <= ch <= "﫿"


def script(ch):
    if is_hangul(ch) or is_cjk(ch):
        return "ko"
    if ch.isascii() and ch.isalnum():
        return "en"
    return "sym"


class Metrics:
    def __init__(self, path=FONT_FILE):
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except OSError:
            data = {}
        self.fonts = {k: v for k, v in data.items() if not k.startswith("_")}
        self.checked_fonts = set(data.get("_한글대조", []))
        self.unknown = set()

    def checked(self, face):
        """한글로 줄 바꿈 자리를 맞대어 본 글꼴인가(어림 오차가 작음)."""
        return face in self.checked_fonts or ALIASES.get(face) in self.checked_fonts

    def known(self, face, bold=False):
        """폭 표에 있는 글꼴인가('없는 글꼴' 알림에 올리지 않고 봄)."""
        if bold and face == "맑은 고딕":
            face = "맑은 고딕 굵게"
        return bool(self.fonts.get(face) or self.fonts.get(ALIASES.get(face, "")))

    def font(self, face, bold=False):
        if bold and face == "맑은 고딕":
            face = "맑은 고딕 굵게"
        f = self.fonts.get(face) or self.fonts.get(ALIASES.get(face, ""))
        if f is None and face:
            self.unknown.add(face)
        return f

    def em(self, face, ch, bold=False):
        """글자 하나의 폭(글자 크기 1에 대한 비율)."""
        if ch in "\u20e3\u200b\u200c\u200d":
            return 0.0  # 키캡(1⃣의 네모)은 앞 글자에 겹침, U+200B~D는 찍히지 않음 — 폭이 없음(한글 2024 실측 2026-11-09)
        f = self.font(face, bold)
        if f is not None:
            w = f["chars"].get(ch)
            if w is not None:
                return w / 1000
            if is_hangul(ch) or is_num_char(ch):  # 번호 글자 폭은 글꼴의 한글 폭과 같음(한글 2024로 10개 글꼴 실측 2026-11-09 — 차이 0.03글자 안, tools/num_char_probe.py)
                return f["hangul"] / 1000
            if is_cjk(ch):
                return f["hanja"] / 1000
        if ch == " ":
            return 0.33
        if ch.isascii():
            return 0.55
        return 1.0


class Layout:
    """문단·표의 줄 수와 높이, 문서의 쪽 나눔을 어림한다(단위 HWPUNIT, 1mm ≈ 283.5)."""

    def __init__(self, styles, metrics=None):
        self.st = styles
        self.m = metrics or Metrics()
        # 큰 표를 통째로 다음 쪽으로 넘기는 어림(2026-11-04). 만들 때는 쪽 맞춤이 그 자리에 쪽 나눔을 박아 한글도 그렇게 되고,
        # 검사만·다듬기는 쪽 나눔을 박지 않으므로 False — 한글이 하는 대로(빈 곳이 크면 표를 쪽 사이에서 나눔) 센다.
        self.move_whole = True
        self.head_of = head_length  # 자간을 더해 볼 때 뺄 머리 글자 수(정돈은 더한 기호 ‣▸✓까지 봄)
        # 쪽 맞춤이 안을 찾는 동안만 쓰는 표 줄 높이 저장소 — 안마다 표 글은 그대로라 다시 재지 않음(안이 31개면 표 줄 높이를 62번 쟀음).
        # row_nocache: 안이 높이를 바꾸는 표(그래프 상자)
        self.row_cache = None
        self.row_nocache = set()

    # ------------------------------------------------------------ 글자 폭
    def chars(self, p, delta=0, floor=FIT_FLOOR):
        """문단의 글자 목록: [(글자, 폭, 크기, 위첨자 여부, 자간 빼기 전 폭)]. delta는 모든 조각에 더해 볼 자간(%).
        자간은 floor(겹치지 않는 한계) 밑으로 내리지 않는다. 이미 그보다 좁은 조각(따옴표 등)은 그대로 둔다.
        마지막 칸(자간 빼기 전 폭)은 줄 끝 글자에 쓴다 — 한글은 줄 끝 글자를 자간을 줄이기 전 제 폭으로 센다(wrap)."""
        out = []
        head = self.head_of(para_text(p)) if delta else 0
        pos = 0
        for r in para_runs(p):
            if r.find(T("hp:tbl")) is not None:
                continue
            c = self.st.char.get(r.get("charPrIDRef"), {})
            size = c.get("size", 10) * 100
            sup = c.get("superscript") or c.get("subscript")
            # 위·아래 첨자는 한글이 0.64배 폭으로 찍는다(40pt 실측 2026-11-01: 일반 55.6px, 첨자 35.6px — 0.6으로 어림하면
            # 긴 첨자(줄임말 뒤 정식 이름)가 든 줄을 짧게 보아 끝 두세 글자가 넘어가는 것을 못 잡았음)
            eff = size * (SUP_SCALE if sup else 1.0) * c.get("rel", 100) / 100  # 상대 크기(작은 ○ 등)는 폭도 줄어듦
            ratio = c.get("ratio", 100) / 100
            text = run_text(r)
            # 머리 기호·괄호 이름표 조각에는 자간 조정을 하지 않는다(fit.py set_delta와 같은 규칙)
            sp = spacing_after(c.get("spacing", 0), delta if pos >= head else 0, floor) / 100
            en_sp = spacing_after(c.get("latin_spacing", c.get("spacing", 0)), delta if pos >= head else 0, floor) / 100
            en_ratio = c.get("latin_ratio", c.get("ratio", 100)) / 100
            en_face = c.get("latin_font")
            if not (en_face and self.m.known(en_face, c.get("bold"))):
                en_face = c.get("font")  # 폭 표에 없는 글꼴은 한글 글꼴 폭으로(모르는 글꼴은 0.55로 어림해 더 어긋남)
            pos += len(text)
            for ch in text:
                if ch == "\n":
                    out.append((ch, 0, size, sup, 0))
                    continue
                # 자간 %는 글자 크기가 아니라 '그 글자 자신의 폭'에 대한 비율이다(한글 2024 실측:
                # -20%에서 한글은 0.2글자, 빈칸(0.5)은 0.1글자, 고정폭 빈칸(0.25)은 0.05글자 줄어듦).
                if ch == "\t":
                    w0 = 4000
                    w = w0
                elif ch == "⎵":  # 고정폭 빈칸 = 글자 크기의 1/4(한글 2024 실측)
                    w0 = eff * FW_EM * ratio
                    w = w0 * (1 + sp)
                else:
                    base = " " if ch == "⍽" else ch
                    # 첨자 안 빈칸은 줄지 않고 보통 크기 빈칸으로 찍힌다(40pt 실측 2026-11-01: 첨자 빈칸 27.6px = 보통 27.8px)
                    k = size * c.get("rel", 100) / 100 if sup and base == " " else eff
                    if base.isascii() and base.isalnum():
                        w0 = k * self.m.em(en_face, base, c.get("bold")) * en_ratio
                        w = w0 * (1 + en_sp)
                    else:
                        w0 = k * self.m.em(c.get("font"), base, c.get("bold")) * ratio
                        w = w0 * (1 + sp)
                out.append((ch, w, size, sup, w0))
        return out

    @staticmethod
    def end_extra(chs, k):
        """줄이 글자 k에서 끝날 때 더 드는 폭: 한글은 줄 끝 글자를 자간을 줄이기 전 제 폭으로 센다(한글 2024 실측 2026-11-04 —
        자간 -50%인 닫는 따옴표 ’로 끝나는 낱말이 남은 폭 1.2~1.5mm에 들어가야 하는데 다음 줄로 넘어감, 자간을 1% 더 줄여
        제 폭이 들어가자 올라옴). 자간을 늘린 글자는 확인하지 않아 그대로(0)."""
        if k < 0 or k >= len(chs) or len(chs[k]) < 5:
            return 0.0
        return max(0.0, chs[k][4] - chs[k][1])

    # ------------------------------------------------------------ 줄 나눔
    @staticmethod
    def _units(chs):
        """끊을 수 없는 덩어리로 나눈다: [(시작, 끝, 글자 폭, 뒤 빈칸 폭, 강제 줄바꿈 뒤인가)]."""
        units = []
        i, n = 0, len(chs)
        lead = 0.0
        while i < n and chs[i][0] in (" ", "　"):
            lead += chs[i][1]
            i += 1
        start, w = i, lead
        forced = False
        while i < n:
            ch, cw = chs[i][0], chs[i][1]
            if ch == "\n":
                # 잇단 줄 바꿈·맨 앞 줄 바꿈의 빈 줄도 한 줄(옛 판은 안 세어 줄 수가 모자랐음 — 평가 2026-11-09)
                if i > start or forced or not units:
                    units.append([start, i, w, 0.0, forced])
                forced, start, w = True, i + 1, 0.0
                i += 1
                continue
            if ch in (" ", "　"):
                end = i
                trail = 0.0
                while i < n and chs[i][0] in (" ", "　"):
                    trail += chs[i][1]
                    i += 1
                units.append([start, end, w, trail, forced])
                forced, start, w = False, i, 0.0
                continue
            w += cw
            i += 1
        if i > start or forced or not units:  # 끝 줄 바꿈 뒤 빈 줄도 한 줄
            units.append([start, i, w, 0.0, forced])
        return units

    def wrap(self, chs, first_w, rest_w, condense=0):
        """줄 목록 [(시작, 끝, 쓴 폭, 쓸 수 있는 폭)]."""
        lines = []
        cur = None  # [시작, 끝, 글자 폭, 빈칸 폭]
        keep = 1 - condense / 100
        for s, e, w, trail, forced in self._units(chs):
            avail = first_w if not lines else rest_w
            # 줄 끝에 놓일 덩어리는 끝 글자를 자간 빼기 전 제 폭으로(end_extra)
            if cur is not None and not forced and cur[2] + cur[3] * keep + w + self.end_extra(chs, e - 1) <= avail + 1:
                cur[1], cur[2] = e, cur[2] + cur[3] + w
                cur[3] = trail
                continue
            if cur is not None:
                lines.append((cur[0], cur[1], cur[2], first_w if not lines else rest_w))
            avail = first_w if not lines else rest_w
            if w > avail:  # 한 덩어리가 한 줄보다 길면 글자 단위로 자른다
                x, st = 0.0, s
                for k in range(s, e):
                    if x + chs[k][1] > avail and k > st:
                        lines.append((st, k, x, avail))
                        x, st = 0.0, k
                        avail = rest_w
                    x += chs[k][1]
                cur = [st, e, x, trail]
            else:
                cur = [s, e, w, trail]
        if cur is not None:
            lines.append((cur[0], cur[1], cur[2], first_w if not lines else rest_w))
        return lines

    def widths(self, p, box_w):
        pp = self.st.para.get(p.get("paraPrIDRef"), {})
        base = box_w - pp.get("left", 0) - pp.get("right", 0)
        intent = pp.get("intent", 0)
        if intent < 0:
            return base, base + intent
        return base - intent, base

    def para_lines(self, p, box_w, delta=0, shrink=1.0, floor=FIT_FLOOR):
        """shrink<1이면 쓸 수 있는 폭을 그만큼 줄여 본다(자간으로 당길 때 어림 오차 여유).
        floor는 자간을 줄여 볼 때의 하한 — 실제로 바꿀 하한(fit.FLOOR)과 같게 넘겨야 어림이 맞다."""
        chs = self.chars(p, delta, floor)
        if not chs and para_tables(p):
            return chs, []
        first, rest = self.widths(p, box_w)
        first, rest = first * shrink, rest * shrink
        pp = self.st.para.get(p.get("paraPrIDRef"), {})
        if pp.get("squeeze"):  # 한 줄로 입력: 한글이 자간을 줄여 넣으므로 강제 줄 바꿈에서만 줄이 바뀜
            return chs, [(s, e, u, first if not k else rest)
                         for k, (s, e, u, _) in enumerate(self.wrap(chs, 1e12, 1e12))]
        return chs, self.wrap(chs, first, rest, pp.get("condense", 0))

    def line_pitch(self, p, size):
        pp = self.st.para.get(p.get("paraPrIDRef"), {})
        kind, v = pp.get("line_type", "PERCENT"), pp.get("line", 160)
        if kind == "PERCENT":
            return size * v / 100
        if kind == "FIXED":
            return v
        if kind == "BETWEEN_LINES":
            return size + v
        return max(size, v)  # AT_LEAST

    def para_height(self, p, box_w):
        """(문단 높이, [줄 높이…], 위 간격, 아래 간격)."""
        pp = self.st.para.get(p.get("paraPrIDRef"), {})
        prev, nxt = pp.get("prev", 0), pp.get("next", 0)
        tables = para_tables(p)
        if tables:
            # 줄 단위 높이: 긴 표는 한글이 줄 사이에서 다음 쪽으로 나눈다
            hs = [h for t in tables for h in self.table_rows(t)]
            tr = next(r for r in para_runs(p) if r.find(T("hp:tbl")) is not None)
            size = self.st.char.get(tr.get("charPrIDRef"), {}).get("size", 10) * 100
            # 표 문단 줄 간격 여분과 표 바깥 아래 여백은 겹친다 — 큰 쪽만(표 밑 글 띄움을 두 번 세어 105쪽 문서를 109쪽으로
            # 어림하던 일, 한글 실측 2026-11-04)
            om = tables[-1].find(T("hp:outMargin"))
            om_b = int(om.get("bottom", "0")) if om is not None else 0
            pos = tables[-1].find(T("hp:pos"))
            extra = max(0.0, self.line_pitch(p, size) - size)
            if pos is not None and pos.get("treatAsChar") == "1":
                # 글자처럼 취급한 표(제목·요약 상자): 표는 줄 안의 글자라 줄 간격 여분이 표 바깥 아래 여백과 따로 붙는다
                # (한글 PDF 실측 2026-11-05 — 요약 상자 아래가 1.8mm 더 넓었음)
                hs[-1] += extra
            else:
                hs[-1] += max(0.0, extra - om_b)
            if p.find(".//" + T("hp:secPr")) is not None:
                hs[0] += FIRST_TABLE_EXTRA
                runs = para_runs(p)
                k = next((n for n, r in enumerate(runs) if r.find(T("hp:tbl")) is not None), 0)
                if any(r.find(T("hp:ctrl")) is not None and r.find(T("hp:secPr")) is None for r in runs[:k]):
                    hs[0] += CTRL_LINE_EXTRA
            return prev + sum(hs) + nxt, hs, prev, nxt
        pics = [x for x in para_pics(p) if x.find(T("hp:pos")) is not None
                and x.find(T("hp:pos")).get("treatAsChar") == "1"]
        if pics:
            # 글자처럼 취급한 그림: 줄 높이 = 그림 높이 + 줄 간격 여분(표와 같은 셈, 표지 마크·슬로건)
            h = max(int(x.find(T("hp:sz")).get("height", "0")) for x in pics)
            tr = next(r for r in para_runs(p) if r.find(T("hp:pic")) is not None)
            size = self.st.char.get(tr.get("charPrIDRef"), {}).get("size", 10) * 100
            h += max(0.0, self.line_pitch(p, size) - size)
            return prev + h + nxt, [h], prev, nxt
        chs, lines = self.para_lines(p, box_w)
        hs = []
        for s, e, _, _ in lines or [(0, 0, 0, 0)]:
            sizes = [c[2] for c in chs[s:e] if not c[3]] or [max((c[2] for c in chs), default=1000)]
            if not chs:
                sizes = [max((self.st.char.get(r.get("charPrIDRef"), {}).get("size", 10) * 100
                              for r in para_runs(p)), default=1000)]
            hs.append(self.line_pitch(p, max(sizes)))
        return prev + sum(hs) + nxt, hs, prev, nxt

    # ------------------------------------------------------------ 표
    def cell_content(self, tc, inner_w):
        """칸 안 글의 높이(HWPUNIT, 칸 안 위아래 여백 빼고)."""
        cps = cell_paras(tc)
        content = sum(self.para_height(cp, inner_w)[0] for cp in cps)
        if cps and not para_tables(cps[-1]):
            # 칸 안 마지막 줄 아래에는 줄 간격 여분이 붙지 않는다(한글 2024 실측: 2줄 11.4mm·4줄 24.9mm, 13pt 140%)
            size = max((self.st.char.get(r_.get("charPrIDRef"), {}).get("size", 10) * 100
                        for r_ in para_runs(cps[-1])), default=1000)
            content -= max(0.0, self.line_pitch(cps[-1], size) - size)
        return content

    def table_rows(self, tbl):
        """표의 줄마다 높이(HWPUNIT) 목록. 한글은 긴 표를 줄 사이에서 다음 쪽으로 나누므로 쪽 나눔은 줄 단위로 어림한다."""
        if self.row_cache is not None and tbl in self.row_cache:
            return list(self.row_cache[tbl])
        inm = tbl.find(T("hp:inMargin"))
        dt = int(inm.get("top", "141")) + int(inm.get("bottom", "141")) if inm is not None else 282
        dl = int(inm.get("left", "510")) + int(inm.get("right", "510")) if inm is not None else 1020
        rows, spans = {}, []
        for r, c, rs, cs, tc in table_grid(tbl):
            sz = tc.find(T("hp:cellSz"))
            w, h = int(sz.get("width", "0")), int(sz.get("height", "0"))
            mt, ml = dt, dl
            if tc.get("hasMargin") == "1":
                cm = tc.find(T("hp:cellMargin"))
                mt = int(cm.get("top", "0")) + int(cm.get("bottom", "0"))
                ml = int(cm.get("left", "0")) + int(cm.get("right", "0"))
            content = self.cell_content(tc, w - ml) + mt
            if rs == 1:
                rows[r] = max(rows.get(r, 0), h, content)
            else:
                rows.setdefault(r, 0)
                spans.append((r, rs, h, content))
        # 세로로 합친 칸: 합친 줄들의 높이 합이 칸 글보다 낮으면 마지막 줄이 늘어남(옛 판은 합친 칸 높이를 안 세어 같은 긴 글이
        # 합친 칸이면 24mm, 안 합치면 86mm — 평가 2026-11-09). 칸 높이 값은 합친 줄이 모두 비었을 때만 믿음(줄 높이를 맞춘 뒤 옛 값이 남음)
        for r, rs, h, content in spans:
            span = [k for k in range(r, r + rs) if k in rows]
            have = sum(rows[k] for k in span)
            want = max(content, h if not have else 0)
            if span and want > have:
                rows[span[-1]] += want - have
        out = [rows[r] for r in sorted(rows)] or [0]
        om = tbl.find(T("hp:outMargin"))
        out[-1] += int(om.get("top", "0")) + int(om.get("bottom", "0")) if om is not None else 0
        if self.row_cache is not None and tbl not in self.row_nocache:
            self.row_cache[tbl] = list(out)
        return out

    def row_pieces(self, tbl):
        """칸 안에서 쪽을 나누는 표(pageBreak=CELL)의 줄마다 나눌 수 있는 조각 높이 — 가장 높은 칸의 글 줄 단위, 칸 안 표는 글자처럼 취급되어 통째로.
        줄을 통째로 옮겨 세면 355mm 줄 하나로 실제 5쪽 문서가 6쪽이 된다(공모전 양식 시험 2026-11-09)."""
        inm = tbl.find(T("hp:inMargin"))
        dt = int(inm.get("top", "141")) + int(inm.get("bottom", "141")) if inm is not None else 282
        dl = int(inm.get("left", "510")) + int(inm.get("right", "510")) if inm is not None else 1020
        best = {}
        for r, c, rs, cs, tc in table_grid(tbl):
            sz = tc.find(T("hp:cellSz"))
            w = int(sz.get("width", "0"))
            mt, ml = dt, dl
            if tc.get("hasMargin") == "1":
                cm = tc.find(T("hp:cellMargin"))
                mt = int(cm.get("top", "0")) + int(cm.get("bottom", "0"))
                ml = int(cm.get("left", "0")) + int(cm.get("right", "0"))
            units = [mt / 2]
            for cp in cell_paras(tc):
                h, hs, prev, nxt = self.para_height(cp, w - ml)
                if para_tables(cp) or para_pics(cp):
                    units.append(h)  # 칸 안 표·그림은 쪽에서 나뉘지 않음
                else:
                    units += [prev + hs[0]] + list(hs[1:])
                    units[-1] += nxt
            units[-1] += mt / 2
            if rs == 1 and sum(units) > sum(best.get(r, [])):
                best[r] = units
        rows = self.table_rows(tbl)
        out = []
        for k, h in enumerate(rows):
            units = list(best.get(k, []))
            extra = h - sum(units)  # 칸 높이 값이 글보다 큰 몫 — 줄 끝에 빈 조각으로
            if extra > 1 or not units:
                units.append(max(extra, 0.0))
            out.append(units)
        return out

    def table_header(self, tbl):
        """다음 쪽에서 되풀이되는 머리 줄 높이(표 '제목 줄 반복'이 켜져 있고 머리 칸이 있을 때)."""
        if tbl.get("repeatHeader") != "1":
            return 0
        heads = {r for r, c, rs, cs, tc in table_grid(tbl) if tc.get("header") == "1"}
        rows = self.table_rows(tbl)
        return sum(rows[r] for r in sorted(heads) if r < len(rows) - 1)

    def table_height(self, tbl):
        return sum(self.table_rows(tbl))

    def table_width(self, tbl):
        sz = tbl.find(T("hp:sz"))
        return int(sz.get("width", "0")) if sz is not None else 0

    # ------------------------------------------------------------ 쪽 나눔
    def paginate(self, paras, body_w, body_h, heads=None, block_gap=None):
        """문단마다 (시작 쪽, 끝 쪽)과 쪽마다 쓴 높이를 어림한다.
        heads: 큰 묶음(□ 블록·참고)의 첫 문단들. 주면 큰 묶음이 쪽에 다 들어가지 않을 때 묶음째 다음 쪽으로 넘긴다
        (한 쪽보다 긴 묶음은 넘기지 않고, 그 안의 ○ 묶음 단위로 나눈다).
        block_gap: 묶음째 넘기면 쪽 아래 빈 곳이 본문 높이의 이 비율보다 커질 때는 넘기지 않고 ○ 묶음 단위로 나눈다
        (빈 곳이 너무 크다는 사용자 의견, 2026-10-31).
        ○ 단위로 나눌 때 묶음의 마지막 ○ 하나만 다음 쪽으로 떨어지면 그 앞 ○도 함께 넘긴다
        ('(시제품) 줄이 다음 장으로 넘어감' 지적 두 번, 2026-10-31)."""
        items = []
        for p in paras:
            h, hs, prev, nxt = self.para_height(p, body_w)
            pp = self.st.para.get(p.get("paraPrIDRef"), {})
            tables = para_tables(p)
            text = para_text(p)
            items.append({"hs": hs, "prev": prev, "next": nxt, "keep": pp.get("keep_next", False),
                          "brk": p.get("pageBreak") == "1", "h": h,
                          # 한글이 쪽 경계에서 나누는가: 글 문단은 '문단 보호'가 없으면 줄 사이에서, 표는 글자처럼 취급하지 않고 나눔을 끄지 않았으면 줄 사이에서
                          "splits": (all(t.get("pageBreak") != "NONE" and t.find(T("hp:pos")) is not None
                                         and t.find(T("hp:pos")).get("treatAsChar") != "1" for t in tables)
                                     if tables else not pp.get("keep_lines", False)),
                          "repeat": self.table_header(tables[0]) if tables else 0, "table": bool(tables),
                          "pieces": (self.row_pieces(tables[0]) if len(tables) == 1 and tables[0].get("pageBreak") == "CELL"
                                     and tables[0].find(T("hp:pos")) is not None and tables[0].find(T("hp:pos")).get("treatAsChar") != "1"
                                     else None),
                          "blank": not tables and not para_pics(p) and not text.strip(),
                          # 글자처럼 취급하지 않은 표: 한글은 바로 뒤 문단의 위 간격을 쓰지 않는다(실측 — 표 바깥 아래 여백만)
                          "float": bool(tables) and all(t.find(T("hp:pos")) is None
                                                        or t.find(T("hp:pos")).get("treatAsChar") != "1" for t in tables),
                          # 표 바로 위 기준·단위 줄과 ■ 표 제목 줄(표와 한 몸 — 묶음을 나눌 때 표와 함께 감)
                          "lead": not tables and bool(UNIT_RE.match(text) or text.lstrip().startswith("■"))})
        n = len(items)
        starts = {k for k, p in enumerate(paras) if heads and p in heads}
        ends, block_h = {}, {}
        for s in starts:
            e = s + 1
            while e < n and e not in starts and not items[e]["brk"]:
                e += 1
            last = e - 1
            while last > s and items[last]["blank"]:
                last -= 1  # 묶음 끝의 빈 줄은 쪽 끝에 걸려도 됨
            ends[s] = last
            block_h[s] = sum(items[k]["h"] for k in range(s, last + 1))
        extra = set()
        for _ in range(8):
            where, used, chains = self._paginate_pass(items, starts, block_h, body_h, block_gap, extra)
            add = set()
            for s in starts:
                inner = [c for c in chains if s <= c[0] <= ends[s]]
                cut = [k for k in range(1, len(inner)) if inner[k][2] > where[inner[k - 1][1]][1]]
                # 나뉜 자리 뒤에 ○ 묶음이 하나뿐이고, 그 앞 묶음이 □ 제목 묶음이 아니면 앞 묶음도 넘긴다
                # (뒤 묶음이 기준·단위·■ 제목 줄이나 표로 시작하면 — 큰 표를 다음 쪽 한 장에 넣으려고 끊은 것 — 앞 ○는 그대로)
                last0 = inner[cut[-1]][0] if cut else None
                if (cut and len(inner) - cut[-1] == 1 and cut[-1] >= 2 and inner[cut[-1] - 1][0] not in extra
                        and not (self.move_whole and (items[last0]["lead"] or items[last0]["table"]))):
                    add.add(inner[cut[-1] - 1][0])
            if not add:
                break
            extra |= add
        # 두 쪽에 걸친 큰 묶음(한 쪽에 들어갈 만한데 나뉜 것): 줄 간격으로 다시 맞출 거리
        self.split = [s for s in sorted(starts)
                      if where[s][0] != where[ends[s]][1] and block_h[s] <= body_h]
        return where, used

    def _paginate_pass(self, items, starts, block_h, body_h, block_gap, extra):
        n = len(items)
        page, y = 0, 0.0
        used = [0.0]
        where, chains = [], []
        self.tops = []  # 문단마다 첫 줄 (쪽, 위치) — 시험·맞춤용
        self.moved = []  # 다음 쪽에서 시작하게 넘긴 묶음의 첫 문단 번호
        self.split_rows = 0  # 쪽에 갈라진 표 줄 수(칸 안에서 나누는 표)
        self.row_pos = {}  # 표 문단 번호 → 줄마다 (시작 쪽, 시작 위치, 끝 쪽, 끝 위치) — 정돈의 쪽 끝 줄 넘기기·나누기(2026-11-11)
        i = 0
        while i < n:
            def chain_to(i, last):
                j, chain = i, 0.0
                while True:
                    it = items[j]
                    chain += it["h"] if (j == i or it["keep"]) else it["prev"] + it["hs"][0]
                    if not it["keep"] or j + 1 >= n or items[j + 1]["brk"] or j + 1 in starts or j >= last:
                        break
                    j += 1
                return j, chain

            j, chain = chain_to(i, n)
            if chain > body_h and self.move_whole:
                # 한 쪽보다 긴 묶음(○ 글 + 큰 표): 표가 기준·단위·■ 제목 줄과 함께 한 쪽에 들어가면 그 앞에서 묶음을 끊어
                # 표를 다음 쪽에서 한 장에(사용자 원칙 2026-11-04 '큰 표는 밑으로 내려 한 장에, 제목도 붙여서')
                for k in range(i + 1, j + 1):
                    if items[k]["table"] and len(items[k]["hs"]) > 2:
                        u = k
                        while u - 1 > i and items[u - 1]["lead"]:
                            u -= 1
                        if u > i and chain_to(u, n)[1] <= body_h:
                            j, chain = chain_to(i, u - 1)
                        break
            # 묶음 안의 표가 쪽 끝에서 시작하면 머리 줄과 내용 두 줄까지는 같은 쪽에 들어가야 한다
            # (머리 줄만 쪽 끝에 남고 내용이 다음 쪽으로 가는 것을 막음 — 2026-10-31 시험 문서 참고1)
            head_need, has_table = 0.0, False
            for k in range(i, j + 1):
                it = items[k]
                if it["table"] and len(it["hs"]) > 2:
                    head_need += (it["prev"] if k > i else 0) + sum(it["hs"][:3])
                    has_table = True
                    break
                head_need += it["h"] if k == i else it["prev"] + it["h"] - it["prev"]
            if items[i]["brk"] and (y > 0 or page > 0) and i > 0:
                page, y = page + 1, 0.0
                used.append(0.0)
            elif self.move_whole and has_table and y > 0 and y + head_need > body_h and head_need <= body_h:
                page, y = page + 1, 0.0
                used.append(0.0)
                self.moved.append(i)
            elif i in extra and y > 0:
                page, y = page + 1, 0.0
                used.append(0.0)
                self.moved.append(i)
            elif (i in starts and y > 0 and y + block_h[i] > body_h and block_h[i] <= body_h
                  and (block_gap is None or body_h - y <= body_h * block_gap)):
                page, y = page + 1, 0.0
                used.append(0.0)
                self.moved.append(i)
            elif (y > 0 and y + chain > body_h and chain <= body_h
                  and (self.move_whole or (j > i or not items[i]["splits"]))):
                # 한 쪽에 들어가는 묶음은 통째로 다음 쪽으로 — 표가 든 묶음도 쪽 아래가 많이 비더라도 두 쪽에 나누지 않는다
                # (사용자 원칙 2026-11-04 '큰 표가 두 장에 걸치면 차라리 밑으로 내려서 한 장에 딱 들어가게, 제목도 붙여서'
                #  — 2026-10-31의 '빈 곳이 block_gap보다 크면 표를 나눔'을 바꿈). 한 쪽보다 긴 표만 나눈다(머리 줄 되풀이).
                # 쪽 나눔을 박지 않는 어림(move_whole 끔 — 정돈·검사만)은 한글이 하는 대로: '다음 문단과 함께'로 묶인 것과 나눌 수 없는 것만
                # 통째로, 그 밖 문단·표는 줄 사이에서 나눔(옛 판: 8줄 문단이 7줄 자리에도 넘어감, 평가 2026-11-09)
                page, y = page + 1, 0.0
                used.append(0.0)
                if j > i:
                    self.moved.append(i)
            chain_page = None
            for k in range(i, j + 1):
                it = items[k]
                # 글자처럼 취급하지 않은 표 바로 뒤 문단은 위 간격 없이(한글 실측 — 그 자리는 표 바깥 아래 여백이 맡음)
                y += it["prev"] if y > 0 and not (k > 0 and items[k - 1]["float"]) else 0
                start = None
                # 칸 안에서 나누는 표는 줄 대신 칸 글 조각 단위로 — 쪽 경계에서 줄이 갈라짐(표 문단 끝 여분은 마지막 조각에)
                units, row_end = it["hs"], {}
                if it.get("pieces") and len(it["pieces"]) == len(it["hs"]):
                    units = [u for row in it["pieces"] for u in row]
                    units[-1] += sum(it["hs"]) - sum(units)
                    at = 0
                    for row in it["pieces"]:
                        row_end[at] = at + len(row) - 1  # 줄 첫 조각 → 끝 조각
                        at += len(row)
                row_start = None
                rec = self.row_pos.setdefault(k, []) if it["table"] else None
                for u_i, lh in enumerate(units):
                    if y + lh > body_h + 1 and y > 0:
                        used[page] = y
                        page, y = page + 1, 0.0
                        used.append(0.0)
                        if start is not None and it["repeat"] < body_h / 2:
                            y += it["repeat"]  # 표가 나뉘면 다음 쪽에 머리 줄이 되풀이됨(쪽을 넘을 만큼 긴 머리 줄은 되풀이되지 않는 것으로 봄)
                    if start is None:
                        start = page
                        self.tops.append((page, y))
                    if u_i in row_end:
                        row_start = (page, row_end[u_i])
                        row_y = y
                    if row_start and u_i == row_start[1]:
                        self.split_rows += page != row_start[0]
                        rec.append((row_start[0], row_y, page, y + lh))
                    elif not row_end and rec is not None:  # 줄 사이에서만 나누는 표: 조각 하나 = 줄 하나
                        rec.append((page, y, page, y + lh))
                    y += lh
                y += it["next"]
                used[page] = y
                where.append((start, page))
                chain_page = start if chain_page is None else chain_page
            if not items[i]["blank"]:
                chains.append((i, j, chain_page))
            i = j + 1
        return where, used, chains
