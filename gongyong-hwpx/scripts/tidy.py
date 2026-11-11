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

  5. 표 칸 글도 본문과 같은 규칙으로(표 안에 보고서가 들어가는 양식 — 사용자 2026-11-09): 폭은 칸 안쪽 폭, 많이 쓴 값은 칸마다,
     ○·□ 위 간격은 칸 높이 안에서. 일부러 벌린 빈칸(팀명 칸·날짜·서명란)은 그대로. 표 칸만: 붙어 보이는 줄 간격은 칸 높이 안에서
     넓히고, □와 같은 자리에서 시작한 ○·-는 □보다 들임

바꾸지 않는 것: 글자(빈칸 → 고정폭 빈칸, 끝 줄 균형용 빈칸 ↔ 줄 바꿈뿐 — 보이는 글은 같음), 글꼴, 크기, 기호, 문체,
본문 줄 간격 비율·들여쓰기, 쪽 나눔, 쪽 수, 표 칸 너비, ○ 줄 밖의 다음 문단과 함께, 차례.
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
from hwpx_lib import (COMPOSE_CHAR, HWPUNIT_PER_MM, INVISIBLE_RE, KEYCAP_RE, T, HeaderEdit, Package, Styles, cell_paras, clean_chars, drop_linesegs, etree, insert_marker_gap,  # noqa: E402
                      clear_print_method, edit_run_text, fake_label, head_length, is_blank, is_table_title, label_colon, label_content, marker_level,
                      page_info, para_pics, para_runs, para_tables, para_text, plain_run, run_tabs, run_text, set_run_text,
                      split_marker, table_grid, text_marks, pct_range, is_num_char, same_path, tight_marker_end)
from layout import FIT_FLOOR, FW_EM, Layout, Metrics, spacing_after  # noqa: E402
from spaces import compact_fw, lead_to_margin  # noqa: E402
from build_base import DATE_LINE_RE, SKILL_VERSION, read_doc_meta  # noqa: E402
from fit_base import CONNECTORS, fill_last_line  # noqa: E402
from fit_tables import TableFit  # noqa: E402 — 제목 걸친 상자 찾기(_caption_content)를 작성 모드와 같게

FW = "⎵"  # 고정폭 빈칸(1/4 글자, 양쪽 정렬 때 늘어나지 않음)
O_GAP_DEFAULT = 600  # ○ 위 간격 기본(6pt) — 문서에 ○ 위 간격을 쓴 곳이 없을 때(기본 양식 값)
O_GAP_FALLBACK = (400, 300, 200)  # 쪽이 늘면 줄여 볼 ○ 위 간격(4·3·2pt)
HANG_MAX = 0.4  # 내어쓰기가 본문 폭의 이 비율을 넘으면(이름표가 너무 김) 하지 않음
CELL_HANG_MAX = 0.10  # 표 칸은 둘째 줄을 이름표·쌍점 뒤에 맞추는 폭이 칸 안쪽 폭의 이 비율을 넘으면 머리 기호 뒤에 — 깊이 들이면 줄이 늘어남(사용자 표 안 보고서 139mm 칸: '- .env :' 13.5mm는 쌍점 뒤, '○ 받기 :' 16mm는 머리 기호 뒤)
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
REPORT_CELL_EM = 25  # 칸 안쪽 폭이 글자 이만큼은 돼야 보고서 칸으로 보고 양쪽 맞춤 — 좁은 칸은 낱말 사이가 크게 벌어짐
CELL_LOOSE_EM = 0.5  # 칸 보고글 윗줄이 양쪽 맞춤으로 빈칸마다 글자 이만큼 넘게 벌어지면 그 문단은 왼쪽 맞춤(사용자 표 안 보고서 시험 65줄: 대부분 0.3 아래, 긴 낱말이 넘어간 4줄만 0.6~1.2)
CELL_MIN_EM = 15  # 칸 안쪽 폭이 글자 이만큼은 돼야 본문 규칙을 씀 — 더 좁은 칸은 한두 낱말씩 끊겨 자간으로 맞출 거리가 아님
CELL_GAP_EM = 0.4  # 표 칸 ○ 위 간격의 상한(글자 크기의 배수) — 본문 6pt가 15pt 글의 0.4배
CELL_GAP_MIN = 200  # 이보다 작은 위 간격(0.5pt 등)은 표 칸에서 '간격을 둔 것'으로 보지 않음
CELL_LINE_MIN = 120  # 표 칸 줄 간격이 이보다 좁으면(%) 줄이 붙어 보임 — 칸 높이 안에서 넓힘
CELL_LINE_TRIES = (130, 120, 110)  # 넓혀 볼 값(%) — 차례대로, 칸 높이를 넘지 않는 가장 큰 값
LEVEL_EM = {2: 1.0, 3: 2.25, 4: 2.25}  # 표 칸 머리 기호 줄을 □보다 들이는 자리(글자) — 사람이 쓴 보고서 실측: ○ 1.0, - 2.26글자
FLAT_SUB_EM = 1.25  # □ 없는 칸에서 ○·번호 줄 아래 - 줄의 자리(글자) — ○ 글 첫머리(사용자 표 안 보고서 실측 1.32글자)
# 작성 모드가 모르는 머리 기호(전임자 문서에 흔함) — 기호 다음에 빈칸이 있어야 머리 기호로 봄
EXTRA_MARK_RE = re.compile(r"^(?P<lead>[ \t⎵⍽　]*)(?P<mark>[‣▸▹➢➤✓◦])(?P<gap>[ \t⎵⍽　]+)")
FILL_DROP = 0.10  # 정돈 뒤 가장 빈 쪽의 채움이 이만큼 넘게 줄면 되돌림(쪽 수가 같아도 □ 묶음째 다음 쪽으로 밀려 한 쪽이 빈 일 — 평가 2026-11-09)
SIGN_RE = re.compile(r"\((?:서명|날인|인)(?: ?(?:또는|/) ?(?:서명|날인|인))?\)")  # 서명란 '(서명)'·'(인)' 꼴


def own_linesegs(p):
    """문단 자신의 줄 배치 기록(한글이 저장한 실제 줄 나눔). 표 칸 안 문단 것은 빼고."""
    ls = p.find(T("hp:linesegarray"))
    return [] if ls is None else ls.findall(T("hp:lineseg"))


LAST_FILL = 0.97  # 쪽 상한을 맞출 때 마지막 쪽이 이보다 차면 한글에서 넘칠 수 있어 한 단계 더 줄여 봄
# 쪽 상한을 맞출 때 줄여 볼 차례(덜 바꾸는 것부터)
MAX_PAGE_STEPS = [({}, ""), ({"gap_cap": 400}, "○ 위 간격 4pt"), ({"gap_cap": 300}, "○ 위 간격 3pt"), ({"gap_cap": 200}, "○ 위 간격 2pt"),
                  ({"gap_cap": 0}, "○·□ 위 간격 넣지 않음"), ({"gap_cap": 0, "no_lines": True}, "간격 없이 표 칸 줄 간격도 그대로"),
                  ({"gap_cap": 0, "no_lines": True, "no_indent": True}, "간격 없이 표 칸 줄 간격·○ 자리도 그대로")]


def letters(text):
    """보이는 글자 차례만 — 빈칸 종류·줄 바꿈을 모두 뺌(시험 도구용)."""
    return re.sub(r"[ ⎵⍽\n　]+", "", _clean_text(text))


def _clean_text(text):
    """글자 비교 전에 clean_chars가 바꾼 것을 같게 — 보이지 않아야 하는 글자는 없는 셈, 키캡 숫자는 글자 겹치기 자리."""
    return INVISIBLE_RE.sub("", KEYCAP_RE.sub(COMPOSE_CHAR, text))


def flat(text):
    """글자 비교용: 빈칸 **종류**(보통·고정폭·묶음·전각)와 잇단 수, 줄머리 빈칸은 같다고 보되 빈칸이 **있고 없음**과 줄 바꿈은 견준다
    (평가 2026-11-09: 빈칸을 모두 지우고 견줘 줄 바꿈을 풀며 없던 빈칸을 넣은 것을 못 잡았음). 규칙이 빈칸을 더하는 이름표 폭
    ('(현황)' → '(현 황)', '- 교체 :' → '- 교 체 :')만 뺀다. 끝 줄 균형의 빈칸 ↔ 줄 바꿈은 run()이 그 문단만 따로 허용."""
    s = re.sub(r"[ ⎵⍽　]+", " ", _clean_text(text)).strip()
    pre, mark, rest = split_marker(s)
    if mark:  # 기호 뒤 한 칸은 정돈이 넣음(marker_gaps) — 있고 없음을 같게. 이름표 맞춤은 기호 뒤 글에서('(1) (현 황)'의 첫 괄호는 번호)
        s = rest
    s = re.sub(r"\(([^()\n]{1,12})\)", lambda m: "(" + m.group(1).replace(" ", "") + ")", s, count=1)
    s = re.sub(r"(?<=[가-힣]) (?=[가-힣] ?:)", "", s, count=1)
    return mark + " " + s if mark else s


class Tidier:
    def __init__(self, path, keep_o=True, gaps=None, blank_mm=None, all_rules=False, gap_cap=None, no_lines=False, no_indent=False,
                 hang_at=None):
        self.path = path
        # 둘째 줄 기준을 사용자가 밝힘(--hang-at): '기호'(머리 기호 뒤 첫 글자) 또는 '이름표'(이름표·쌍점 뒤, 없으면 기호 뒤).
        # 밝히면 기존 내어쓰기의 0.4글자 허용 없이 그 자리에 정확히, 한 줄 문단에도 같은 값(사용자 2026-11-10)
        self.hang_at = hang_at
        self._hang_log, self._hang_skip = [], {}  # 맞추거나 둔 문단(끝에 다시 대조), 기준을 밝혔을 때 못 맞춘 문단 → 까닭
        # 쪽 상한(--max-pages)을 맞출 때: ○ 위 간격 상한(0이면 넣지 않음), 표 칸 줄 간격 넓히기·○ 들이기 끄기
        self.gap_cap, self.no_lines, self.no_indent = gap_cap, no_lines, no_indent
        self.doc_changes = []  # 문단이 아닌 문서 설정을 바꾼 것
        self._report, self._justified = set(), {}  # 칸 보고글 문단, 그 가운데 왼쪽 → 양쪽으로 바꾼 문단(칸마다)
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
        self.lay.head_of = self.head_len
        self.secs = [self.pkg.xml(n) for n in self.pkg.sections()]
        self.changes = {}  # 문단 → [무엇을 바꿨나]
        self.notes = []
        self.touched = set()  # 줄 배치 기록을 지울 문단(한글이 다시 계산)
        tab = self.secs[0].find(".//" + T("hp:tab")) if self.secs else None
        self.tab_proto = tab
        # 원본 상태(비교용)
        self.body = [p for sec in self.secs for p in sec if p.tag == T("hp:p")]
        # 문단은 요소 자체를 열쇠로(lxml 요소의 id()는 다시 쓰일 수 있어 열쇠로 못 씀 — 첫 시험에서 '글자 바뀜' 오판)
        self.orig_text = {p: para_text(p) for p in self.all_paras()}
        self.orig_marks = {p: text_marks(p) for p in self.all_paras()}
        self.eol_ok = set()  # 끝 줄 균형으로 빈칸 ↔ 줄 바꿈을 바꾼 문단(글자 비교에서 그 바꿈만 허용)
        self.page_of = self._orig_pages()
        # 제목 걸친 상자(조문 발췌 등) 안 인용 글 — 자간·양쪽 정렬만(quote_fit), 줄 바꿈 넣기·빈칸 당기기·끝 줄 내리기는 걸지 않음(작성 모드와 같게)
        self._quote_ps = {cp for tc, _ in self._quote_cells() for cp in cell_paras(tc)}
        self.host = {cp: p for p in self.body if para_tables(p) for cp in p.iter(T("hp:p")) if cp is not p}  # 표 칸 문단 → 표가 든 본문 문단
        self.host_pages = self._host_pages()
        # 이 스킬의 작성 모드로 만든 문서(content.hpf 표시 made=판) — 작성 규칙이 맞춘 내어쓰기(낫표 당김·화살표 줄 포함)·
        # 끝 줄·이름표·칸·간격을 정돈의 어림으로 다시 만지면 되돌리게 된다(평가 2026-11-08: 낫표 줄 내어쓰기 5.4 → 3.1mm,
        # 화살표 줄 61.7 → 35.7mm). 그래서 내어쓰기가 아예 없는 문단(만든 뒤 사람이 더한 줄)·글자 단위 줄 나눔·빈칸만 손봄
        self.made = "" if all_rules else read_doc_meta(self.pkg).get("made", "")

    # ------------------------------------------------------------ 바탕
    def all_paras(self):
        for sec in self.secs:
            yield from sec.iter(T("hp:p"))

    @staticmethod
    def _cells(tbl):
        """표의 칸마다 (칸, 칸 안쪽 폭, 칸 안 위아래 여백)."""
        inm = tbl.find(T("hp:inMargin"))
        dl = int(inm.get("left", "510")) + int(inm.get("right", "510")) if inm is not None else 1020
        dt = int(inm.get("top", "141")) + int(inm.get("bottom", "141")) if inm is not None else 282
        for *_, tc in table_grid(tbl):
            sz = tc.find(T("hp:cellSz"))
            w = int(sz.get("width", "0")) if sz is not None else 0
            ml, mt = dl, dt
            cm = tc.find(T("hp:cellMargin"))
            if tc.get("hasMargin") == "1" and cm is not None:
                ml = int(cm.get("left", "0")) + int(cm.get("right", "0"))
                mt = int(cm.get("top", "0")) + int(cm.get("bottom", "0"))
            yield tc, w - ml, mt

    def _wide(self, tc, w):
        """본문 규칙을 쓸 만큼 넓은 칸인가(글자 CELL_MIN_EM개 폭 이상)."""
        sizes = [self.styles.char.get(r.get("charPrIDRef"), {}).get("size", 10)
                 for cp in cell_paras(tc) if not para_tables(cp) for r in para_runs(cp) if run_text(r).strip()]
        return bool(sizes) and w >= CELL_MIN_EM * max(sizes) * 100

    def blocks(self):
        """글 덩이마다 (문단들, 쓸 수 있는 폭, 범위): 구역 본문과 넓은 표 칸. 범위는 '많이 쓴 값'을 고르는 묶음 — 본문은 문서 전체가
        하나, 표 칸은 칸마다(본문 ○가 13pt이고 칸 ○가 10pt인 문서에서 칸 글을 '한 줄만 다른 크기'로 보지 않게)."""
        for sec in self.secs:
            yield [x for x in sec if x.tag == T("hp:p")], self.box(sec)[0], "본문"
        for sec in self.secs:
            for tbl in sec.iter(T("hp:tbl")):
                for tc, w, _ in self._cells(tbl):
                    if self._wide(tc, w):
                        yield cell_paras(tc), w, tc

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

    def _host_pages(self):
        """표가 든 본문 문단마다 놓인 쪽 글('1쪽'·'1~2쪽') — 표 칸 문단의 '바뀐 곳' 알림용(어림)."""
        out, base = {}, 0
        for sec in self.secs:
            body_w, body_h = self.box(sec)
            paras = [p for p in sec if p.tag == T("hp:p")]
            where, _ = self.lay.paginate(paras, body_w, body_h)
            for p, (s, e) in zip(paras, where):
                if para_tables(p):
                    out[p] = f"{base + s + 1}쪽" if s == e else f"{base + s + 1}~{base + e + 1}쪽"
            base += (max(e for _, e in where) + 1) if where else 0
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
        return re.sub(r"[ ⎵⍽\n]+", " ", text[len(pre):] if mark else text).replace(COMPOSE_CHAR, "").strip()[:10] or "(빈 줄)"

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
        if self.gap_cap is not None:
            tries = [g for g in tries if g <= self.gap_cap]
            if not tries:
                return
        old = [p.get("paraPrIDRef") for p, _ in todo]
        for g in tries:
            for p, cur in todo:
                if cur < g:
                    p.set("paraPrIDRef", self.hedit.para_margin(p.get("paraPrIDRef"), "prev", g))
                if (self.keep_o and self._has_child_line(p)
                        and not self.styles.para.get(p.get("paraPrIDRef"), {}).get("keep_next")):
                    # ○ 줄만(위 간격을 넣으며 ○ 줄 전용 모양이 됨) '다음 문단과 함께' — 한글이 ○ 제목 줄을 쪽 끝에 홀로 두지 않게
                    # (사용자 원고 시험: 어림은 한 줄쯤 어긋나 홀로 남는 ○를 못 잡음 — 한글이 직접 막게 함).
                    # 아래 줄이 그 ○의 -·*·※·표일 때만 — ○끼리 걸면 사슬이 되어 □ 묶음째 다음 쪽으로 밀림(평가 2026-11-09)
                    p.set("paraPrIDRef", self.hedit.para_keep_next(p.get("paraPrIDRef")))
            pages, orphans = self.layout_state()
            if pages <= self.pages0 and orphans <= self.orphans0 and self._fill_ok():
                break
            for (p, _), pid in zip(todo, old):
                p.set("paraPrIDRef", pid)
        else:
            self.notes.append(f"○ 위 간격을 넣으면 쪽이 늘어나거나 한 쪽이 크게 비어 넣지 않았습니다(○ {len(todo)}곳 위 간격 0 — 쪽에 빈 곳이 모자람, "
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
        kept = [p for p, _ in todo if self.keep_o and self._has_child_line(p)]
        for p in kept:
            self.mark(p, "○ 줄을 아래 줄과 같은 쪽에")
        if kept:
            self.notes.append(f"○ 줄 {len(kept)}개는 바로 아래 줄과 같은 쪽에 오게(다음 문단과 함께) 했습니다 — ○ 제목만 쪽 끝에 홀로 남지 않게.")

    def _has_child_line(self, p):
        """바로 아래 문단이 이 ○에 딸린 줄(-·*·※·표)인가."""
        nxt = p.getnext()
        while nxt is not None and nxt.tag != T("hp:p"):
            nxt = nxt.getnext()
        return nxt is not None and (bool(para_tables(nxt)) or self.level(para_text(nxt)) in (3, 4))

    def _min_fill(self):
        """구역마다 마지막 쪽을 뺀 쪽 가운데 가장 빈 쪽의 채움(0~1, 어림)."""
        vals = []
        for sec, used in zip(self.secs, self._page_fill()):
            h = self.box(sec)[1]
            vals += [u / h for u in used[:-1]] if h else []
        return min(vals, default=1.0)

    def _fill_ok(self):
        """가장 빈 쪽이 정돈 전보다 크게 비지 않았는가(쪽 수는 그대로여도 묶음째 다음 쪽으로 밀리면 앞쪽이 빔)."""
        return self._min_fill() >= self.fill0 - FILL_DROP

    def blank_heights(self):
        """□ 바로 앞 빈 줄(묶음 사이 빈 줄)을 가장 많이 쓴 모양 하나로 — 본문은 문서 전체에서, 표 칸은 칸마다."""
        self._blank_heights(self.body, self.box(self.secs[0])[0])
        for paras, w, scope in self.blocks():
            if scope != "본문":
                self._blank_heights(paras, w, in_cell=True)

    def _blank_heights(self, paras, body_w, in_cell=False):
        blanks = []
        for k, p in enumerate(paras[1:], 1):
            prev = paras[k - 1]
            # ■ 표 제목 위 좁은 빈 줄은 □ 앞 빈 줄과 다른 자리 — 함께 세면 2.5mm가 7.9mm로 커짐(평가 2026-11-09)
            if marker_level(para_text(p)) == 1 and not para_tables(p) and is_blank(prev) and not is_table_title(p):
                runs = para_runs(prev)
                if all(len(r) <= 1 and (len(r) == 0 or r[0].tag == T("hp:t")) for r in runs) and runs:
                    blanks.append(prev)
        if len(blanks) < 2:
            return
        size = lambda b: self.lay.para_height(b, body_w)[0]  # noqa: E731
        band = lambda b: round(size(b) / (0.5 * HWPUNIT_PER_MM))  # 0.5mm 눈금으로 묶음  # noqa: E731
        # 뚜렷한 다수(60% 이상)인 높이가 있을 때만 그 높이로. 제각각이면 어느 것이 '보통'인지 알 수 없어 그대로 두고 알림
        # (흐트러뜨린 예시 문서 시험: 좁힌 빈 줄이 가장 많아 보통 빈 줄을 좁은 쪽으로 맞춰 버렸음 2026-11-08)
        counts = Counter(band(b) for b in blanks)
        top, cnt = max(counts.items(), key=lambda kv: (kv[1], kv[0]))
        if self.blank_mm and not in_cell:
            # 사용자가 높이를 정해 준 때: 문서에 있는 □ 앞 빈 줄 가운데 그 높이에 가장 가까운 모양으로 모두 맞춤
            want = self.blank_mm * HWPUNIT_PER_MM
            top = band(min(blanks, key=lambda b: abs(size(b) - want)))
        elif len(counts) > 1 and cnt < 0.6 * len(blanks):
            if in_cell:
                return  # 칸마다 알리면 길어짐 — 표 칸은 뚜렷한 다수가 있을 때만 맞춤
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
        if self.pages() > self.pages0 or not self._fill_ok():  # 쪽이 늘거나 크게 비면 되돌림(쪽 수 지키기)
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

    def head_len(self, text):
        """자간을 바꾸지 않을 머리 글자 수 — 전임자 문서의 더한 기호(‣▸✓)도 머리로(head_length는 작성 모드가 아는 기호만 봄)."""
        return head_length(self.split(text)[2])

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
        return (0 if self._fake(t, pre) else label_content(t)) or label_colon(t) or len(pre)

    @staticmethod
    def _fake(t, pre):
        m = LABEL_RE.match(t[len(pre):])
        return bool(m) and fake_label(m.group("core"), t[len(pre) + m.end():])

    def _cell_head_at(self, p, text, box_w):
        """표 칸의 둘째 줄 자리 — 이름표·쌍점 뒤가 칸 폭에 비해 깊으면 머리 기호 뒤."""
        k = self.head_at(text)
        pre = self.split(text)[0]
        if k > len(pre) and sum(c[1] for c in self.lay.chars(p)[:k]) > box_w * CELL_HANG_MAX:
            return len(pre)
        return k

    def head_kind(self, text):
        pre, _, t = self.split(text)
        return "이름표" if label_content(t) and not self._fake(t, pre) else ("쌍점" if label_colon(t) else "머리 기호")

    def aligned_spots(self, text):
        """작성자가 둘째 줄을 맞춰 두었을 만한 자리(글자 위치): 머리 기호 뒤·괄호 이름표 뒤·'항목 : ' 쌍점 뒤.
        지금 내어쓰기가 이 가운데 하나와 맞으면 작성자의 맞춤으로 보고 그대로 둔다(사람이 쓴 15쪽 계획서 첫 시험: 쌍점 뒤에 맞춘
        28.8mm 내어쓰기를 머리 기호 뒤 13.8mm로 줄여 버렸음)."""
        pre, mark, t = self.split(text)
        return {k for k in (len(pre) if mark else 0, 0 if self._fake(t, pre) else label_content(t), label_colon(t)) if k}

    @staticmethod
    def _em_at(chs, k):
        """허용치를 잴 글자 폭: k번째 글자부터 폭이 있는 첫 글자(줄 바꿈은 폭 0이라 건너뜀 — '·↵안전PC'에서 허용치가 0이 되어 0.01mm 차이로도
        두 번째 정돈마다 다시 맞추던 것, 2026-11-10). 없으면 1000."""
        return next((c[1] for c in chs[k:] if c[1] > 0), 1000)

    def _hang_at(self, p, box_w, in_cell):
        """둘째 줄을 맞출 글자 위치를 재는 함수 — 기준을 '기호'로 밝히면 머리 기호 뒤 첫 글자만(이름표·쌍점 뒤를 대신 인정하지 않음)."""
        if self.hang_at == "기호":
            return lambda x: len(self.split(x)[0])
        return (lambda x: self._cell_head_at(p, x, box_w)) if in_cell else self.head_at

    def _hang_one(self, p, box_w, in_cell=False):
        """문단 하나의 둘째 줄을 맞춘다. 돌려주는 것: 'done'·'indent'(첫 줄 들여쓰기를 바꿔 맞춤)·'fw'(머리 빈칸만 고정폭으로, 내어쓰기는 그대로)·
        'break'(줄 바꿈 문단)·'tab'·'grew'·None. 기준을 밝히면(self.hang_at) 0.4글자 허용 없이 그 자리에 정확히, 한 줄 문단에도 걸어 두고
        (나중에 글이 늘어도 맞게), 맞추지 못한 문단은 까닭을 _hang_skip에 남긴다(사용자 2026-11-10)."""
        text = para_text(p)
        lv = self.level(text)
        strict = self.hang_at
        at = self._hang_at(p, box_w, in_cell)
        k = at(text)
        if not k or (lv == 1 and not in_cell and not self._is_number(text)) or k >= len(text):
            return None  # 본문 □ 제목은 양식이 맡음 — 표 칸의 □·■(체크 칸 항목 등)와 로마자 번호 줄은 둘째 줄을 글자 첫머리에
        pp = self.styles.para.get(p.get("paraPrIDRef"), {})
        if pp.get("align") in ("CENTER", "RIGHT"):
            return None
        indent = max(0, pp.get("intent", 0))  # 첫 줄 들여쓰기(양수)
        cur = -pp.get("intent", 0) if not indent else 0
        chs, lines0 = self.lay.para_lines(p, box_w)

        def near(cs, j):
            """지금 내어쓰기가 글자 위치 j(머리 폭)와 0.4글자 안인가 — 작성자가 한글에서 눈으로 맞춘 값은 어림과 1mm쯤 다를 수 있다
            (사용자 원고: 23.2~23.7mm, 어림 22.7mm)."""
            return cur > 0 and abs(cur - sum(c[1] for c in cs[:j])) <= 0.4 * self._em_at(cs, j)

        if self.made and pp.get("intent", 0) < 0:
            # 작성 모드가 이미 내어쓰기를 맞춘 문단(낫표 당김·화살표 줄 등 작성 규칙의 자리) — 그대로. 기준을 밝히면 기호·이름표·쌍점 자리에
            # 맞춰 둔 문단만 그 기준으로 다시 맞추고, 그 밖의 자리(화살표 뒤 등)는 작성 규칙이라 그대로 두고 알림
            if not strict:
                return None
            if not any(near(chs, j) for j in self.aligned_spots(text)):
                self._hang_skip[p] = "작성 규칙이 맞춘 자리(화살표 뒤 등)"
                return None
        if re.search(r"\n[ ⎵⍽　]+", text):
            # 줄 바꿈(Shift+Enter) 뒤 빈칸으로 둘째 줄을 맞춘 문단 — 내어쓰기를 걸면 빈칸만큼 두 번 들어감. 글을 바꿔야 해서 그대로.
            # (줄 바꿈 뒤가 바로 글이면 한글은 그 줄도 둘째 줄로 내어쓰므로 아래에서 보통대로 맞춤 — 실험: 작성 도구가 끝 줄
            # 균형으로 넣은 줄 바꿈을 건너뛰어 '보강, 산책로 정비'가 왼쪽 끝에 남았음)
            if strict:
                self._hang_skip[p] = "줄 바꿈(Shift+Enter) 뒤 빈칸으로 둘째 줄을 맞춘 문단(글을 바꿔야 함)"
            return "break"
        if not strict and self.lines_of(p, box_w) < 2 and not self.near_wrap(p, box_w):
            return None
        if "\t" in text[:k]:
            # 머리 기호 뒤를 탭으로 띄운 문단 — 탭이 닿는 자리는 문서의 기본 탭 간격·내어쓰기 자동 탭에 따라 달라 어림하면
            # 오히려 어긋남(실험: 둘째 줄이 2~7mm 어긋나거나 쌍점 항목은 내어쓰기를 못 함). 그대로 두고 알림
            if strict:
                self._hang_skip[p] = "머리 기호 뒤를 탭으로 띄운 문단(탭 자리는 문서 설정마다 달라 어림하지 않음)"
            return "tab"
        n0 = len(lines0)
        # 양쪽 정렬이면 머리(기호·이름표 앞뒤)의 보통 빈칸이 늘어나 첫 줄 글 시작이 밀린다 — 그런 빈칸이 남아 있으면 내어쓰기가 허용치 안이어도
        # '이미 맞춤'으로 보지 않고 먼저 고정폭 빈칸으로 바꾼 뒤 판단(사용자 2026-11-10 구동안내서: ○ 13.20pt·- 7.60pt 내어쓰기가 계산 폭
        # 14.55·8.83pt와 허용치 안이라 건너뛰어, 기호 뒤 보통 빈칸이 양쪽 정렬로 늘어남)
        stretchy = " " in text[:k] and pp.get("align") in ("JUSTIFY", "DISTRIBUTE", None)
        if not strict and not stretchy and any(near(chs, j) for j in self.aligned_spots(text)):
            return None  # 작성자가 이미 머리 기호·이름표·쌍점 뒤에 맞춰 둔 문단
        if sum(c[1] for c in chs[:k]) + indent > box_w * HANG_MAX:
            if strict:
                self._hang_skip[p] = f"머리(이름표)가 본문 폭의 {HANG_MAX:.0%}를 넘어 내어쓰면 글 자리가 너무 좁음"
            return None
        pid0 = p.get("paraPrIDRef")
        state0 = self._runs_state(p)

        def grew():
            """맞췄더니 줄이 늘었으면 되돌림 — 2줄이 3줄이 되어 1쪽 문서가 2쪽이 됨(평가 2026-11-09). 표 칸은 먼저 내용 자간으로 줄 수를 지켜 본다
            (왼쪽 끝으로 나온 둘째 줄이 ○와 같은 자리에 있으면 수준이 흐려짐 — 사용자 표 안 보고서)."""
            if len(self.lay.para_lines(p, box_w)[1]) <= n0:
                return False
            if in_cell:
                got = self._keep_lines(p, box_w, n0)
                if got is not None:
                    self.mark(p, f"줄이 늘지 않게 내용 자간 {got[0]:+d}%")
                    return False
            p.set("paraPrIDRef", pid0)
            self._restore_runs(p, state0)
            self._hang_retry.append((p, box_w, in_cell))
            return True

        # 머리 기호 앞뒤 보통 빈칸을 고정폭 빈칸으로(첫 줄이 양쪽 정렬로 늘어나도 내용 시작 자리가 그대로)
        text0 = text
        pos = 0
        for r in para_runs(p):
            t = run_text(r)
            start, pos = pos, pos + len(t)
            if start >= k:
                break
            cut = min(len(t), k - start)
            new = t[:cut].replace(" ", FW * self._fw_per_space(r)) + t[cut:]
            if new != t and plain_run(r):
                edit_run_text(r, new, self.tab_proto)
        text = para_text(p)
        k = at(text)
        if stretchy and " " in text[:k]:
            # 형광펜 등 표시가 있는 조각이라 바꾸지 못한 빈칸 — 양쪽 정렬에서 늘어날 수 있어 '맞춤'으로 볼 수 없음
            self._restore_runs(p, state0)
            self._hang_skip[p] = "머리 빈칸이 표시(형광펜 등) 조각 안이라 고정폭으로 바꾸지 못함 — 양쪽 정렬에서 늘어날 수 있음"
            return None
        converted = text != text0
        kind = "머리 기호" if k == len(self.split(text)[0]) else self.head_kind(text)
        chs, _ = self.lay.para_lines(p, box_w)
        hang = sum(c[1] for c in chs[:k])
        em = self._em_at(chs, k)
        fw_note = "머리 기호 뒤 빈칸을 고정폭으로(양쪽 정렬에서 늘어나지 않게"
        if not strict and not indent and converted and any(near(chs, j) for j in self.aligned_spots(text)):
            # 빈칸을 고정폭으로 바꾼 뒤에도 작성자 내어쓰기가 허용치 안 — 내어쓰기는 그대로(작성자 서식), 빈칸만 바꿈
            if grew():
                return "grew"
            self.mark(p, fw_note + ", 내어쓰기는 그대로)")
            self._hang_log.append((p, box_w, in_cell, "kept"))
            return "fw"
        if indent:
            # 첫 줄 들여쓰기 Y → 왼쪽 여백을 Y만큼 늘리고 내어쓰기로(첫 줄 자리는 그대로, 둘째 줄은 내용 첫 글자 밑)
            pid = self.hedit.para_margin(p.get("paraPrIDRef"), "left", pp.get("left", 0) + indent)
            p.set("paraPrIDRef", self.hedit.para_hang(pid, hang))
            if grew():
                return "grew"
            self._hang_log.append((p, box_w, in_cell, "set"))
            if p in getattr(self, "_lead_moved", ()):
                # 줄머리 빈칸을 옮기며 생긴 첫 줄 들여쓰기 — 작성자가 둔 들여쓰기가 아님
                self.mark(p, f"둘째 줄을 {kind} 뒤 첫 글자에(내어쓰기 {hang / HWPUNIT_PER_MM:.1f}mm)")
                return "done"
            self.mark(p, f"첫 줄 들여쓰기 {indent / HWPUNIT_PER_MM:.1f}mm를 왼쪽 여백으로 옮기고 둘째 줄을 {kind} 뒤에"
                         f"(내어쓰기 {hang / HWPUNIT_PER_MM:.1f}mm)")
            return "indent"
        if abs(cur - hang) <= 0.05 * em:
            self._hang_log.append((p, box_w, in_cell, "set"))
            if not converted:
                return None
            if grew():
                return "grew"
            self.mark(p, fw_note + ")")
            return "fw"
        p.set("paraPrIDRef", self.hedit.para_hang(p.get("paraPrIDRef"), hang))
        if grew():
            return "grew"
        self._hang_log.append((p, box_w, in_cell, "set"))
        self.mark(p, f"둘째 줄을 {kind} 뒤 첫 글자에"
                     f"(내어쓰기 {cur / HWPUNIT_PER_MM:.1f} → {hang / HWPUNIT_PER_MM:.1f}mm)")
        return "done"

    def _where(self, p):
        """문단 자리 글('3쪽'·'2쪽 표 칸') — 알림용(쪽은 원본 기준)."""
        host = self.host.get(p)
        return f"{self.host_pages.get(host, '?쪽')} 표 칸" if host is not None else f"{self.page_of.get(p) or '?'}쪽"

    def hang_verify(self):
        """정돈 끝(빈칸 정리·폭 손질 뒤 최종 상태)에 둘째 줄을 맞춘 문단의 내어쓰기를 기준 자리와 다시 대조한다 — 어긋나면 다시 맞추고,
        그러면 줄이 늘어나는 문단은 그대로 두고 알린다(사용자 2026-11-10). 작성자 내어쓰기를 허용치 안이라 둔 문단('kept')은 대조하지 않음."""
        fixed, stuck, checked = [], [], 0
        seen = set()
        for p, w, in_cell, how in self._hang_log:
            if p in seen or how != "set" or p.getparent() is None:
                continue
            seen.add(p)
            text = para_text(p)
            k = self._hang_at(p, w, in_cell)(text)
            if not k or k >= len(text):
                continue
            chs = self.lay.chars(p)
            hang = sum(c[1] for c in chs[:k])
            em = self._em_at(chs, k)
            pid0 = p.get("paraPrIDRef")
            cur = -self.styles.para.get(pid0, {}).get("intent", 0)
            checked += 1
            if abs(cur - hang) <= 0.05 * em:
                continue
            n0 = len(self.lay.para_lines(p, w)[1])
            p.set("paraPrIDRef", self.hedit.para_hang(pid0, hang))
            if len(self.lay.para_lines(p, w)[1]) > n0:
                p.set("paraPrIDRef", pid0)
                stuck.append(p)
                continue
            self.mark(p, f"끝에 다시 대조해 내어쓰기 {cur / HWPUNIT_PER_MM:.1f} → {hang / HWPUNIT_PER_MM:.1f}mm")
            fixed.append(p)
        if fixed:
            self.notes.append(f"정돈 끝에 둘째 줄 자리를 다시 대조해 어긋난 문단 {len(fixed)}개를 다시 맞췄습니다(앞 단계의 빈칸·폭 손질로 머리 폭이 바뀜).")
        if stuck:
            self.notes.append(f"정돈 끝에 다시 대조했더니 둘째 줄 자리가 어긋난 문단 {len(stuck)}개 — 다시 맞추면 줄이 늘어나 그대로 두었습니다: "
                              + ", ".join(f"‘{self.name(p)}…’({self._where(p)})" for p in stuck[:5]))
        if self.hang_at and checked and not fixed and not stuck:
            self.notes.append(f"정돈 끝에 둘째 줄을 맞춘 문단 {checked}개를 다시 대조했습니다 — 모두 기준 자리와 같음(도구 어림, 한글 화면은 따로 확인).")

    def _quote_cells(self):
        """제목 걸친 상자(조문 발췌 등) 본문 칸마다 (칸, 칸 안쪽 폭) — 작성 모드 fit.quote_boxes와 같은 칸."""
        out = []
        for sec in self.secs:
            for tbl in sec.iter(T("hp:tbl")):
                cap = TableFit._caption_content(tbl, table_grid(tbl))
                w = next((w for tc, w, _ in self._cells(tbl) if tc is cap), 0) if cap is not None else 0
                if w > 0:
                    out.append((cap, w))
        return out

    @staticmethod
    def _quote_orphan(cs, ls):
        """마지막 줄에 짧은 낱말 하나만 남는가(작성 모드 fit_lines._orphan과 같은 셈)."""
        s, e, used, _ = ls[-1]
        return len(ls) > 1 and used < ls[0][3] * 0.25 and len("".join(c[0] for c in cs[s:e]).split()) <= 1

    def _quote_score(self, cs, ls):
        """끝 줄을 뺀 줄 가운데 가장 덜 찬 줄의 채움(한 줄이면 1.0) — 줄 바꿈으로 끝나는 줄은 한글이 벌리지 않아 뺀다."""
        fills = [used / avail for _, e, used, avail in ls[:-1] if avail and self._ends_break(cs, e) is None]
        return min(fills) if fills else 1.0

    def quote_align(self):
        """조문 상자 인용 글의 왼쪽·가운데 정렬을 양쪽 정렬로 — 둘째 줄 맞춤(hangs)보다 먼저 해야 그 단계가 양쪽 정렬에서 늘어나는 머리 빈칸을
        고정폭으로 바꾼다(나중에 바꾸면 두 번째 정돈에서야 바뀜 — 105쪽 예산 문서 시험 2026-11-10). 자간은 quote_fit이 나중에."""
        self._quote_aligned = 0
        for tc, _ in self._quote_cells():
            for p in cell_paras(tc):
                text = para_text(p)
                if para_tables(p) or para_pics(p) or not text.strip() or "\t" in text or not self.fonts_ok(p):
                    continue
                pid = p.get("paraPrIDRef")
                if self.styles.para.get(pid, {}).get("align") in ("LEFT", "CENTER"):
                    p.set("paraPrIDRef", self.hedit.para_align(pid, "JUSTIFY"))
                    self.mark(p, "조문 상자 글을 양쪽 정렬로(끝선은 자간으로)")
                    self._quote_aligned += 1

    def quote_fit(self):
        """제목 걸친 상자(조문 발췌 등) 안 인용 글은 양쪽 정렬로 두고 자간만 바꿔 줄마다 끝선까지 고르게 — 작성 모드 fit_quotes와 같은 셈
        (사용자 2026-11-10 '조문 상자 안의 끝도 양끝이 맞아야 한다. 글자 간격을 줄이거나 늘려서', 정돈에도 같은 규칙 — 답 '1').
        자간을 -18~+5%로 바꿔 보며 끝 줄을 뺀 줄 가운데 가장 덜 찬 줄이 97%(PULL)에 닿는 값 가운데 가장 덜 바꾸는 값, 못 닿으면 가장 많이 차는 값.
        줄 수는 늘리지 않고, 끝 줄에 외톨이 낱말이 새로 생기는 값은 뺀다. 인용 글이라 줄 바꿈 넣기·빈칸 당기기·끝 줄 내리기는 걸지 않는다
        (sparse_lines·short_lines·connector_lines·fill_broken에서 뺌). 낱말 사이가 조금 벌어지는 줄도 양쪽 정렬 그대로(사용자 2026-11-10 '이대로 두기')."""
        aligned, spaced = getattr(self, "_quote_aligned", 0), []
        for tc, w in self._quote_cells():
            for p in cell_paras(tc):
                text = para_text(p)
                if para_tables(p) or para_pics(p) or not text.strip() or "\t" in text or not self.fonts_ok(p):
                    continue
                if self.styles.para.get(p.get("paraPrIDRef"), {}).get("align") not in ("JUSTIFY", "DISTRIBUTE"):
                    continue
                chs, lines = self.lay.para_lines(p, w)
                if not lines:
                    continue
                n0, was = len(lines), self._quote_orphan(chs, lines)
                cur = self._content_spacing(p)
                head = self.head_len(text)
                q = copy.deepcopy(p)  # '② '·'1. '까지 한 조각인 조문은 머리를 떼야 자간이 바뀜 — 사본으로 재고, 바꿀 때만 원본을 뗌
                if head and not self._split_at(q, head):
                    continue
                scored = []
                for d in range(FIT_FLOOR - cur, WIDEN_MAX - cur + 1):
                    c2, l2 = self.lay.para_lines(q, w, delta=d, shrink=SLACK)
                    if not l2 or len(l2) > n0 or (self._quote_orphan(c2, l2) and not was):
                        continue
                    scored.append((self._quote_score(c2, l2), d))
                if not scored:
                    continue
                top = max(s for s, _ in scored)
                d = min((d for s, d in scored if s >= min(top, PULL) - 0.005), key=lambda v: (abs(v), v))
                if not d:
                    continue
                state = self._runs_state(p)
                if head and not self._split_at(p, head):
                    continue
                old = self._set_delta(self._content_runs(p, head, len(para_text(p))), d)
                if not old or len(self.lay.para_lines(p, w)[1]) > n0:
                    self._undo(old)
                    self._restore_runs(p, state)
                    continue
                spaced.append(d)
                self.mark(p, f"조문 상자 글 자간 {d:+d}%로 줄마다 끝선까지 고르게")
        if aligned or spaced:
            span = f"자간을 바꿔({pct_range(spaced) if min(spaced) * max(spaced) >= 0 else f'{min(spaced):+d}~{max(spaced):+d}%'}) " if spaced else ""
            self.notes.append(f"제목 걸친 상자(조문 발췌 등) 안 글을 양쪽 정렬로 두고({aligned}문단 바꿈) {span}줄마다 끝선까지 고르게 채웠습니다"
                              f"{f'({len(spaced)}문단)' if spaced else ''} — 인용 글·줄 바꿈은 그대로.")

    def hangs(self):
        got = Counter()
        cells = Counter()
        self._hang_retry = []
        for sec in self.secs:
            body_w, _ = self.box(sec)
            for p in [x for x in sec if x.tag == T("hp:p")]:
                if para_tables(p) or para_pics(p):
                    continue
                got[self._hang_one(p, body_w)] += 1
            # 표 칸 안 문단(· 항목 등) — 칸 안쪽 폭 = 칸 너비 − 칸 안 여백
            for tbl in sec.iter(T("hp:tbl")):
                for tc, w, _ in self._cells(tbl):
                    for cp in cell_paras(tc):
                        if para_tables(cp) or para_pics(cp) or w <= 0:
                            continue
                        cells[self._hang_one(cp, w, in_cell=True)] += 1
        n = got["done"] + got["indent"]
        spot = {"기호": "머리 기호 뒤", "이름표": "이름표·쌍점(없으면 머리 기호) 뒤"}.get(self.hang_at, "이름표·쌍점·머리 기호 뒤")
        lines = "머리 기호 문단(한 줄 문단 포함 — 고르신 기준)" if self.hang_at else "두 줄 이상인 머리 기호 문단"
        if n:
            self.notes.append(f"{lines} {n}개의 둘째 줄을 {spot} 첫 글자에 맞췄습니다"
                              + (f"(첫 줄 들여쓰기를 왼쪽 여백으로 옮긴 것 {got['indent']}개)" if got["indent"] else "") + ".")
        c = cells["done"] + cells["indent"]
        if c:
            self.notes.append(f"표 칸 안 {'' if self.hang_at else '두 줄 이상인 '}항목 {c}개의 둘째 줄을 {spot if self.hang_at else '머리 기호 뒤'} 첫 글자에 맞췄습니다.")
        f = got["fw"] + cells["fw"]
        if f:
            self.notes.append(f"양쪽 정렬 문단 {f}개는 머리 기호 뒤 보통 빈칸을 고정폭 빈칸으로 바꿨습니다(줄마다 늘어나 첫 줄 글 시작이 밀리지 않게 — "
                              "내어쓰기가 이미 맞던 문단은 내어쓰기 그대로).")
        skip = [p for p in self._hang_skip if self._hang_skip[p]]
        if skip:
            self.notes.append(f"둘째 줄을 맞추지 못한 문단 {len(skip)}개 — 자리와 까닭: "
                              + "; ".join(f"‘{self.name(p)}…’({self._where(p)}) {self._hang_skip[p]}" for p in skip[:6])
                              + (f" 외 {len(skip) - 6}개" if len(skip) > 6 else ""))
            for p in skip:
                self._hang_skip[p] = ""  # 두 번째 hangs()에서 같은 알림을 되풀이하지 않게
        tb = got["tab"] + cells["tab"]
        if tb and not self.hang_at:  # 기준을 밝혔으면 위 '맞추지 못한 문단'에 자리와 함께 적음
            self.notes.append(f"머리 기호 뒤를 탭으로 띄운 문단 {tb}개는 둘째 줄을 맞추지 않았습니다 — 탭이 닿는 자리는 문서 설정마다 달라 "
                              "어림하지 않음(한글에서 확인).")
        b = got["break"] + cells["break"]
        if b:
            self.notes.append(f"줄 바꿈(Shift+Enter)과 빈칸으로 둘째 줄을 맞춘 문단 {b}개는 그대로 두었습니다 — 고치려면 글을 바꿔야 함"
                              "(줄 바꿈을 지우고 한 문단으로 이으면 정돈이 맞춤).")

    # ------------------------------------------------------------ 0. 이름표 폭(사용자 원칙 — 네 글자가 기준)
    def _no_hang(self, text):
        """둘째 줄 맞춤을 건너뛰는 꼴(줄 바꿈 + 빈칸 흉내, 머리 기호 뒤 탭)인가 — 이름표 폭·머리 자간도 건드리지 않음:
        윗줄 내용만 밀려 둘째 줄이 약 10mm 어긋남(평가 2026-11-09)."""
        return bool(re.search(r"\n[ ⎵⍽　]+", text)) or "\t" in text[:self.head_at(text)]

    def labels(self):
        """두세 글자 괄호 이름표 '(대 상)'·'(사 업 비)'는 네 글자 폭으로, 작대기 줄의 두 글자 항목명 '- 교체 : …'은 세 글자 폭으로
        고정폭 빈칸을 고르게 넣어 맞춘다(style-guide 1절 '이름표 폭 맞추기' — 작성 모드와 같은 규칙). 보이는 글자는 그대로
        (이름표 안 빈칸 수만). 네 글자 넘는 이름표·네 글자 이름표는 그대로(붙여 쓰기는 글을 바꾸므로 하지 않음)."""
        self._label_n0, self._widened, self._head_changed, self._fit_note, self._box_group = {}, {}, {}, {}, {}
        self._label_slack = {}
        group = 0
        for paras, body_w, scope in self.blocks():
            group += scope != "본문"  # 표 칸은 칸마다 새 묶음
            for p in paras:
                if para_tables(p) or para_pics(p):
                    continue
                text = para_text(p)
                if self.level(text) == 1:
                    group += 1
                    continue
                pre, mark, _ = self.split(text)
                if not mark or self._no_hang(text):
                    continue
                self._box_group[p] = group
                self._label_n0[p] = (len(self.lay.para_lines(p, body_w)[1]), body_w)
                self._label_slack[p] = (len(self.lay.para_lines(p, body_w, shrink=SLACK)[1]), sum(c[1] for c in self.lay.chars(p)))
                body = text[len(pre):]
                m = LABEL_RE.match(body)
                want = 4
                if m and fake_label(m.group("core"), body[m.end():]):
                    continue
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
        lo, hi = len(self.split(text)[0]), self.head_len(text)
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
            now = len(self.lay.para_lines(p, w, shrink=SLACK)[1])
            # 처음부터 끝선에 걸쳐 조금 좁힌 폭으로만 넘치던 문단은, 글 폭이 그대로면 이름표 때문이 아님 — 건드리지 않음(안 그러면 정돈할 때마다 자간이 줆, 검토)
            slack0, wide0 = self._label_slack[p]
            if now <= n0 or (now <= slack0 and sum(c[1] for c in self.lay.chars(p)) <= wide0 and len(self.lay.para_lines(p, w)[1]) <= n0):
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
                    for r in self._content_runs(p, 0, self.head_len(para_text(p))):
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
        for paras, body_w, scope in self.blocks():
            for p in paras:
                if para_tables(p) or para_pics(p):
                    continue
                text = para_text(p)
                lv = self.level(text)
                k = self.head_len(text)
                if lv not in (2, 3, 4) or not k or k >= len(text) or self._no_hang(text) or not self._split_at(p, k):
                    continue
                runs = self._content_runs(p, 0, k)
                if runs:
                    heads.setdefault((scope, lv), []).append((p, runs, body_w))
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
                    keep = set(self._content_runs(p, lo, self.head_len(para_text(p))))
                    todo = [r for r in todo if r not in keep]
                if not todo:
                    continue
                was = sp(todo[0])
                old = [(r, r.get("charPrIDRef")) for r in todo]
                for r in todo:
                    r.set("charPrIDRef", self.hedit.char_spacing(r.get("charPrIDRef"), mode))
                self._head_changed[p] = (was, mode, old)  # 줄이 늘면 _fit_heads가 맞추거나 되돌림, 알림은 labels()가

    def _is_number(self, text):
        """번호 머리 기호 줄(1) 가. (1) ① 등)인가 — 작대기·가운데점 같은 기호 줄과 가름."""
        mark = self.split(text)[1]
        return bool(mark) and (mark[0].isalnum() or mark[0] in "(<〈《【[" or is_num_char(mark[0]))

    def _start_x(self, p):
        """문단 첫 줄이 시작하는 자리(왼쪽 여백 + 첫 줄 들여쓰기 + 줄머리 빈칸)."""
        pp = self.styles.para.get(p.get("paraPrIDRef"), {})
        lead = re.match(r"[ \t⎵⍽　]*", para_text(p)).end()
        return pp.get("left", 0) + max(0, pp.get("intent", 0)) + sum(c[1] for c in self.lay.chars(p)[:lead])

    def cell_justify(self):
        """표 칸 보고서 글은 양쪽 맞춤으로 — 왼쪽 맞춤이면 윗줄이 끝선에 닿지 않는다(사용자 2026-11-09 '앞의 끝선이 맞으면 뒤의 끝선도', 시안에서
        끝선 0.5mm 안 줄 3 → 51, 쪽 그대로). 넓은 칸에 □·○·번호 줄이 둘 이상인 칸만. 표 칸만 — 본문 정렬은 양식의 몫."""
        for paras, w, scope in self.blocks():
            if scope == "본문":
                continue
            rows = [p for p in paras if not (para_tables(p) or para_pics(p)) and para_text(p).strip()]
            tops = [p for p in rows if self.level(para_text(p)) in (1, 2) or self._is_number(para_text(p))]
            if len(tops) < 2 or w < REPORT_CELL_EM * max(self._para_size(p) or 10 for p in tops) * 100:
                continue
            for p in rows:
                text = para_text(p)
                if "\t" in text or re.search(r"\n[ ⎵⍽　]+", text) or not self.fonts_ok(p):
                    continue
                self._report.add(p)
                pid = p.get("paraPrIDRef")
                if self.styles.para.get(pid, {}).get("align") == "LEFT":
                    p.set("paraPrIDRef", self.hedit.para_align(pid, "JUSTIFY"))
                    self._justified[p] = scope

    @staticmethod
    def _ends_break(chs, e):
        """줄 끝 e가 줄 바꿈인가 — '글 ↵다음'처럼 줄 바꿈 앞 빈칸은 줄 끝에 걸려 e가 빈칸을 가리킴. 줄 바꿈 자리(없으면 None)."""
        while e < len(chs) and chs[e][0] == " ":
            e += 1
        return e if e < len(chs) and chs[e][0] == "\n" else None

    def _too_loose(self, p, w, delta=0):
        """양쪽 맞춤이면 윗줄 낱말 사이가 크게 벌어지는가(자간 delta를 더해 본 값으로) — 다음 낱말이 길어 넘어간 줄."""
        chs, lines = self.lay.para_lines(p, w, delta=delta, floor=-30)
        for s, e, used, avail in lines[:-1]:
            if self._ends_break(chs, e) is not None:
                continue  # 줄 바꿈 앞 줄은 한글이 벌리지 않음
            gaps = sum(1 for c in chs[s:e - 1] if c[0] == " ")
            if avail - used > CELL_LOOSE_EM * chs[s][2] * max(1, gaps):
                return True
        return False

    def _justify_notes(self):
        cells = set()
        for p, tc in self._justified.items():
            self.mark(p, "왼쪽 맞춤 → 양쪽 맞춤")
            cells.add(tc)
        if cells:
            self.notes.append(f"표 칸 {len(cells)}개의 보고서 글을 양쪽 맞춤으로 바꿨습니다(왼쪽 맞춤이면 윗줄이 끝선에 닿지 않음).")

    def fill_ends(self):
        """끝선에 조금 못 미친 한 줄·끝 줄을 자간으로 끝선에(fill_last_line, 작성 모드와 같음). □ 제목·줄 바꿈·탭 문단, 칸의 머리 기호 없는 글은 그대로(로마자 번호 줄은 채움)."""
        got = []
        for paras, w, scope in self.blocks():
            for p in paras:
                text = para_text(p)
                if para_tables(p) or para_pics(p) or not text.strip() or "\n" in text or "\t" in text:
                    continue
                lv = self.level(text)
                if (lv == 1 and not self._is_number(text)) or (scope != "본문" and not lv and p not in self._quote_ps):
                    continue  # 칸의 머리 기호 없는 글은 그대로 — 조문 상자 인용 글은 끝 줄도 끝선에(작성 모드와 같게)
                if self.styles.para.get(p.get("paraPrIDRef"), {}).get("align") not in ("JUSTIFY", "DISTRIBUTE", None) or not self.fonts_ok(p):
                    continue
                res = fill_last_line(self.lay, self.styles, self.hedit, p, w, self.head_len(text), self._split_at)
                if res:
                    got.append(res[0])
                    self.mark(p, f"끝선까지 자간 +{res[0]}%(채움 {res[1]:.0%} → {res[2]:.0%})")
        if got:
            self.notes.append(f"끝선에 조금 못 미치던 한 줄·끝 줄 {len(got)}개는 자간을 늘려({pct_range(got, plus=True)}) 끝선에 맞췄습니다.")

    def cell_indent(self):
        """표 칸 보고서 글(□ 제목과 ○ 줄 둘 이상)에서 ○가 □와 같은 자리에서 시작하면 수준이 보이지 않는다(사용자 양식 시험 2026-11-09 '둘 다
        고치기'). 첫 □ 아래 ○는 □보다 한 글자, -·※는 2.25글자 들인다(사람이 쓴 보고서 실측) — 왼쪽 여백만 늘려 내어쓰기는 그대로.
        □ 없는 칸은 ○·번호 줄은 그 자리에 두고 그 아래 - 줄만 ○ 글 첫머리로(사용자 표 안 보고서). 이미 들인 칸은 그대로.
        들여서 줄이 늘면 내용 자간을 줄여(-18%까지) 지키고, 그래도 늘면 칸째 그대로(위아래 자리가 갈리지 않게).
        표 칸만 — 본문 들여쓰기는 양식의 몫이라 바꾸지 않는다."""
        done = stuck = flat = 0
        if self.no_indent:
            return
        for paras, w, scope in self.blocks():
            if scope == "본문":
                continue
            rows = [(p, self.level(para_text(p))) for p in paras
                    if not (para_tables(p) or para_pics(p)) and para_text(p).strip()]
            first = next((k for k, (_, lv) in enumerate(rows) if lv == 1), None)
            if first is None:
                tops = [p for p, lv in rows if lv == 2 or (lv == 3 and self._is_number(para_text(p)))]
                subs, seen = [], False
                for p, lv in rows:
                    if any(p is x for x in tops):
                        seen = True
                    elif seen and lv == 3:
                        subs.append((p, FLAT_SUB_EM))
                if not subs:
                    continue
                moved = self._shift_lines(subs, self._start_x(tops[0]), w)
                if moved is None:
                    stuck += 1
                elif moved:
                    flat += 1
                    for p, a, b in moved:
                        self.mark(p, f"- 자리를 ○ 글 첫머리로 들임(왼쪽 여백 {a / HWPUNIT_PER_MM:.1f} → {b / HWPUNIT_PER_MM:.1f}mm)")
                continue
            has_o = any(lv == 2 for _, lv in rows[first:])
            under, tops, after_num = [], [], False
            for p, lv in rows[first:]:
                if lv == 1:
                    after_num = False
                if lv not in LEVEL_EM:
                    continue
                if lv == 3 and self._is_number(para_text(p)):
                    # □ 아래 '1)'은 ○와 같은 수준, ○ 아래면 -와 같은 수준 — '1)'과 그 아래 -가 같은 자리면 위계가 사라짐(양식 시험 2026-11-09)
                    place, after_num = (2.25 if has_o else 1.0), True
                    if not has_o:
                        tops.append(p)
                elif lv == 2:
                    place, after_num = 1.0, False
                    tops.append(p)
                else:
                    place = 3.5 if has_o and after_num else LEVEL_EM[lv]
                under.append((p, place))
            os_ = tops
            if len(os_) < 2:
                continue
            base = self._start_x(rows[first][0])
            em = lambda p: (self._para_size(p) or 10) * 100  # noqa: E731
            if min(self._start_x(p) for p in os_) - base >= 0.25 * em(os_[0]):
                continue  # 작성자가 이미 들여 둠
            moved = self._shift_lines(under, base, w)
            if moved is None:
                stuck += 1
                continue
            done += 1
            for p, a, b in moved:
                self.mark(p, f"{'○' if self.level(para_text(p)) == 2 else '머리 기호'} 자리를 □보다 들임"
                             f"(왼쪽 여백 {a / HWPUNIT_PER_MM:.1f} → {b / HWPUNIT_PER_MM:.1f}mm)")
        if done:
            self.notes.append(f"표 칸 {done}개의 ○ 줄을 □보다 한 글자(그 아래 수준 줄은 2.25글자) 들였습니다(□와 같은 자리에서 시작하던 칸 — 내어쓰기는 그대로).")
        if flat:
            self.notes.append(f"□ 없는 표 칸 {flat}개의 - 줄을 ○ 글 첫머리로 들였습니다(○와 같은 자리에서 시작하던 줄).")
        if stuck:
            self.notes.append(f"표 칸 {stuck}개는 ○ 줄을 들이면 줄이 늘어 그대로 두었습니다.")

    def _shift_lines(self, under, base, w):
        """줄마다 (문단, 글자 수 자리)를 base + 자리로 들인다(왼쪽 여백만). 이미 그 자리거나 더 들인 줄은 그대로. 들여서 줄이 늘면 내용 자간으로
        지키고, 그래도 늘면 모두 되돌리고 None. 옮긴 줄은 [(문단, 옛 여백, 새 여백)]."""
        undo, spacing, moved = [], [], []
        for p, place in under:
            size = (self._para_size(p) or 10) * 100
            cur, want = self._start_x(p), base + place * size
            if cur >= want - 0.25 * size:
                continue
            n0 = len(self.lay.para_lines(p, w)[1])
            pid = p.get("paraPrIDRef")
            left = self.styles.para.get(pid, {}).get("left", 0)
            undo.append((p, pid))
            p.set("paraPrIDRef", self.hedit.para_margin(pid, "left", left + want - cur))
            moved.append((p, left, left + want - cur))
            if len(self.lay.para_lines(p, w, shrink=SLACK)[1]) > n0:
                got = self._keep_lines(p, w, n0)
                if got is None:
                    self._undo(spacing)
                    for q, qid in undo:
                        q.set("paraPrIDRef", qid)
                    return None
                spacing += got[1]
        return moved

    def cell_lines(self):
        """표 칸의 줄 간격이 120%보다 좁으면 두 줄 글이 붙어 보인다(사용자 양식 시험 2026-11-09 '둘 다 고치기'). 넓은 칸에 글 줄이 둘 이상이면
        칸 높이 안에서 130 → 120 → 110%로 넓힌다. 한 표 안은 같은 값으로 — 칸 하나라도 모자라면 다음 값, 끝내 모자라면 표째 그대로
        (자동 높이 표는 칸에 여유가 없어 그대로). 칸 높이·쪽 배치는 바뀌지 않음. 표 칸만 — 본문 줄 간격은 바꾸지 않는다."""
        done, vals, left, whole = 0, set(), 0, 0
        if self.no_lines:
            return
        pp = lambda p: self.styles.para.get(p.get("paraPrIDRef"), {})  # noqa: E731
        for sec in self.secs:
            for tbl in sec.iter(T("hp:tbl")):
                cells = []
                for tc, w, mt in self._cells(tbl):
                    if not self._wide(tc, w):
                        continue
                    paras = [p for p in cell_paras(tc) if not (para_tables(p) or para_pics(p)) and para_text(p).strip()]
                    tight = [p for p in paras if pp(p).get("line_type", "PERCENT") == "PERCENT"
                             and pp(p).get("line", 160) < CELL_LINE_MIN]
                    if tight and sum(len(self.lay.para_lines(p, w)[1]) for p in paras) >= 2:
                        sz = tc.find(T("hp:cellSz"))
                        need = self.lay.cell_content(tc, w) + mt
                        cells.append((tc, w, mt, tight, max(int(sz.get("height", "0")) if sz is not None else 0, need)))
                if not cells:
                    continue
                old = [(p, p.get("paraPrIDRef")) for *_x, tight, _r in cells for p in tight]
                got = None
                for v in CELL_LINE_TRIES:
                    for p, pid in old:
                        p.set("paraPrIDRef", self.hedit.para_line(pid, v) if self.styles.para.get(pid, {}).get("line", 160) < v else pid)
                    if all(self.lay.cell_content(tc, w) + mt <= room for tc, w, mt, _, room in cells):
                        got = v
                        break
                if got is None:
                    for p, pid in old:
                        p.set("paraPrIDRef", pid)
                    left += 1
                    continue
                vals.add(got)
                whole += 1
                for p, pid in old:
                    if p.get("paraPrIDRef") != pid:
                        self.mark(p, f"줄 간격 {self.styles.para.get(pid, {}).get('line', 160)} → {got}%")
                        done += 1
        if done:
            shown = "·".join(str(v) for v in sorted(vals, reverse=True))
            self.notes.append(f"표 {whole}개에서 줄이 붙어 보이던 칸 글 문단 {done}개의 줄 간격을 {shown}%로 넓혔습니다(칸 높이는 그대로, 한 표 안에서 같은 값).")
        if left:
            self.notes.append(f"표 {left}개는 칸 높이에 여유가 없어 칸 글 줄 간격을 그대로 두었습니다(한 표 안에서 줄 간격이 갈리지 않게).")

    def _page_fill(self):
        """구역마다 쪽별 쓴 높이(어림) — 표 칸을 키웠을 때 줄이 다음 쪽으로 밀렸는지 보는 데 쓴다. 쪽에 갈라진 표 줄 수는 _rows_split에."""
        out = []
        self._rows_split = 0
        for sec in self.secs:
            w, h = self.box(sec)
            out.append(list(self.lay.paginate([x for x in sec if x.tag == T("hp:p")], w, h)[1]))
            self._rows_split += self.lay.split_rows
        return out

    @staticmethod
    def _no_push(before, after):
        """칸을 키워도 표 줄이 다음 쪽으로 밀리지 않았는가 — 쪽 수가 같고 마지막 쪽 앞 쪽들의 쓴 높이가 줄지 않음(밀리면 그 쪽이 빔)."""
        return all(len(a) == len(b) and all(y >= x - 1 for x, y in zip(a[:-1], b[:-1])) for a, b in zip(before, after))

    def cell_gaps(self):
        """표 칸 안 보고서 글(○ 줄 둘 이상인 칸)의 단락 사이 — ○ 위 간격과, 칸 가운데 □ 제목 위 간격(○의 두 배 — □가 앞 줄과 ○보다
        붙어 보이지 않게, 빈 줄은 문단이 늘어 넣지 않음). 칸의 첫 줄과 빈 줄 바로 뒤는 띄우지 않고, 값은 칸에서 많이 쓴 값(없으면 글자
        크기의 0.4배까지 4·3·2pt 차례). 양식의 칸 높이를 지키려고 칸 높이 안에 들어가는 값(위아래 여유로 글자 한 개 높이를 남김)을 먼저
        고르고, 없을 때만 줄이 다음 쪽으로 밀리지 않는 만큼 칸을 키운다. 체크 칸 □만 있는 칸(○ 없음)은 건드리지 않음."""
        fit, grew, stuck = [], 0, 0
        for sec in self.secs:
            body_h = self.box(sec)[1]
            for tbl in sec.iter(T("hp:tbl")):
                for tc, w, mt in self._cells(tbl):
                    if not self._wide(tc, w):
                        continue
                    res = self._cell_gap_one(tc, w, mt, body_h, tbl.get("pageBreak") == "CELL")
                    if res == "stuck":
                        stuck += 1
                    elif res:
                        fit.append(res[0])
                        grew += res[1]
        if fit:
            vals = "·".join(f"{g / 100:g}" for g in sorted(set(fit), reverse=True))
            self.notes.append(f"표 칸 안 보고서 글 {len(fit)}칸의 ○ 위 간격을 {vals}pt로, 칸 가운데 □ 위 간격을 그 두 배로 맞췄습니다"
                              + (f"(칸 높이는 그대로, {grew}칸만 쪽 수가 늘지 않는 만큼 키움)." if grew else "(칸 높이는 그대로)."))
        if stuck:
            self.notes.append(f"표 칸 {stuck}개는 ○ 위 간격을 넣으면 표 줄이 다음 쪽으로 밀리거나 쪽이 늘어 넣지 않았습니다.")

    def cell_keep(self):
        """칸 안에서 쪽을 나누는 표: 보고서 칸의 □ 제목을 아래 줄과 같은 쪽에(다음 문단과 함께) — □만 쪽 끝에 홀로 남던 것(양식 시험 2026-11-09).
        □에만 건다 — 위 ※ 줄까지 걸면 □가 다시 쪽 끝에 남았음."""
        n = 0
        for sec in self.secs:
            for tbl in sec.iter(T("hp:tbl")):
                if tbl.get("pageBreak") != "CELL":
                    continue
                for tc, w, _ in self._cells(tbl):
                    if not self._wide(tc, w):
                        continue
                    paras = [p for p in cell_paras(tc) if para_tables(p) or para_pics(p) or para_text(p).strip()]
                    if sum(marker_level(para_text(p)) == 2 for p in paras) + sum(self._is_number(para_text(p)) for p in paras) < 2:
                        continue
                    for p in paras[:-1]:
                        pid = p.get("paraPrIDRef")
                        if (not para_tables(p) and not para_pics(p) and marker_level(para_text(p)) == 1
                                and not self.styles.para.get(pid, {}).get("keep_next")):
                            p.set("paraPrIDRef", self.hedit.para_keep_next(pid))
                            self.mark(p, "□ 제목을 아래 줄과 같은 쪽에")
                            n += 1
        if n:
            self.notes.append(f"쪽을 넘는 표 칸의 □ 제목 {n}개는 아래 줄과 같은 쪽에 오게 했습니다.")

    def _cell_gap_one(self, tc, w, mt, body_h, flows=False):
        """칸 하나의 ○·□ 위 간격. 돌려주는 것: None(할 일 없음)·'stuck'(넣지 못함)·(넣은 값, 칸을 키웠으면 1)."""
        paras = cell_paras(tc)
        texts = [para_text(p) if not (para_tables(p) or para_pics(p)) else "표" for p in paras]
        filled = [k for k, t in enumerate(texts) if t.strip()]
        os_ = [k for k in filled if marker_level(texts[k]) == 2] or [k for k in filled if marker_level(texts[k]) == 3 and self._is_number(texts[k])]
        if len(os_) < 2:
            return None
        prev = lambda p: self.styles.para.get(p.get("paraPrIDRef"), {}).get("prev", 0)  # noqa: E731
        apart = lambda k: k != filled[0] and texts[k - 1].strip()  # 칸 첫 줄·빈 줄 뒤는 띄우지 않음  # noqa: E731
        o_todo = [k for k in os_ if apart(k)]
        box_todo = [k for i, k in enumerate(filled[:-1]) if marker_level(texts[k]) == 1 and apart(k)
                    and filled[i + 1] in os_]
        cur = [v for v in (prev(paras[k]) for k in o_todo) if v >= CELL_GAP_MIN]
        size = max(self.styles.char.get(r.get("charPrIDRef"), {}).get("size", 10) for k in os_ for r in para_runs(paras[k]))
        cap = size * 100 * CELL_GAP_EM
        tries = [g for g in (600, 400, 300, 200) if g <= cap] or [200]
        if cur:
            target = Counter(cur).most_common(1)[0][0]
            tries = [target] + [g for g in tries if g < target]
        if self.gap_cap is not None:
            tries = [g for g in tries if g <= self.gap_cap]
            if not tries:
                return None
        old = [(k, paras[k].get("paraPrIDRef")) for k in o_todo + box_todo]
        need0 = self.lay.cell_content(tc, w) + mt
        sz = tc.find(T("hp:cellSz"))
        # 칸 높이 안에서 — 위아래에 합쳐 글자 한 개 높이는 남긴다(다 쓰면 첫 줄·끝 줄이 칸 선에 붙음: 양식 시험 3pt)
        room = max(int(sz.get("height", "0")) if sz is not None else 0, need0) - size * 100

        def apply(g):
            for k, pid in old:
                paras[k].set("paraPrIDRef", pid)
            for k, want in [(k, g) for k in o_todo] + [(k, 2 * g) for k in box_todo]:
                if prev(paras[k]) < want:
                    paras[k].set("paraPrIDRef", self.hedit.para_margin(paras[k].get("paraPrIDRef"), "prev", want))

        def undo():
            for k, pid in old:
                paras[k].set("paraPrIDRef", pid)

        apply(tries[0])
        if all(paras[k].get("paraPrIDRef") == pid for k, pid in old):
            return None  # 이미 맞음
        undo()
        got, grew = None, 0
        for g in tries:  # 칸 높이 안에 들어가는 값부터
            apply(g)
            if self.lay.cell_content(tc, w) + mt <= room:
                got = g
                break
        if got is None:  # 칸에 여유가 없으면 쪽 배치가 그대로인 만큼만 키움
            undo()
            before = self._page_fill()
            split0 = self._rows_split
            for g in tries:
                apply(g)
                now = self._page_fill()
                if flows and split0:
                    # 이미 칸 글이 쪽을 넘어 흐르는 표(표 안 보고서)는 쪽 수만 본다 — 조각 자리까지 따지면 한 표 안에서 ○ 간격이 있는 칸과
                    # 없는 칸이 갈림(사용자 견본은 모두 같은 값)
                    ok = sum(map(len, now)) <= sum(map(len, before))
                else:
                    after = self.lay.cell_content(tc, w) + mt
                    tall = after > body_h and (after // body_h) != (need0 // body_h)  # 한 쪽보다 긴 칸이 한 쪽 더 넘어감
                    # 칸 안에서 나누는 표는 키워도 줄이 통째로 밀리지 않으니, 쪽에 새로 갈라지는 줄이 생기는지도 본다
                    ok = not tall and self._no_push(before, now) and self._rows_split <= split0
                if ok:
                    got, grew = g, 1
                    break
        if got is None:
            undo()
            return "stuck"
        for (k, pid) in old:
            if paras[k].get("paraPrIDRef") != pid:
                was = self.styles.para.get(pid, {}).get("prev", 0)
                self.mark(paras[k], f"{'○' if k in os_ else '□'} 위 간격 {was / 100:g} → {prev(paras[k]) / 100:g}pt")
        return got, grew

    # ------------------------------------------------------------ 2-1. 같은 머리 기호 줄의 글자 크기(사용자 2026-11-08 '둘 다 고치기')
    def _para_size(self, p):
        """문단 글자 크기 — 머리 기호·이름표 뒤 내용 첫 글자의 크기. 글자 수로 세면 2pt 작게 쓴 긴 괄호 부연설명
        '(daegu.sharedata.go.kr)' 때문에 문단 전체가 작은 글자로 잡혀 그 괄호까지 키워 버렸음(사람이 쓴 15쪽 계획서)."""
        text = para_text(p)
        k = self.head_len(text)
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
        by_mark = {}
        for paras, _, scope in self.blocks():
            group += scope != "본문"
            for p in paras:
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
                    by_mark.setdefault((scope, mark.strip()), []).append((p, mark.strip(), size, group))
        todo, left = [], []
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

    def hangs_again(self):
        """둘째 줄을 맞추면 줄이 늘어 되돌린 문단을 한 번 더 — 빈칸 맞춤이 자간을 줄여 자리가 났으면 맞춘다(안 그러면 두 번째 정돈에서야 맞춰짐)."""
        retry, self._hang_retry = self._hang_retry, []
        n = 0
        for p, w, in_cell in retry:
            n += self._hang_one(p, w, in_cell=in_cell) in ("done", "indent")
        if n:
            self.notes.append(f"자간을 줄여 자리가 난 문단 {n}개도 둘째 줄을 맞췄습니다.")
        stuck = [x[0] for x in self._hang_retry]
        if stuck:
            where = ", ".join(f"‘{self.name(p)}…’({self._where(p)})" for p in stuck[:5]) if self.hang_at else f"예: ‘{self.name(stuck[0])}…’"
            self.notes.append(f"둘째 줄을 맞추면 줄이 늘어나(쪽 수를 지키려고) 맞추지 않고 되돌린 문단 {len(stuck)}개({where}) — 낱말을 줄이면 맞출 수 있음.")

    @staticmethod
    def _runs_state(p):
        """문단 조각의 지금 상태(되돌리기용): 조각·글자 모양·글."""
        return [(r, r.get("charPrIDRef"), [copy.deepcopy(t) for t in r.findall(T("hp:t"))]) for r in para_runs(p)]

    @staticmethod
    def _restore_runs(p, state):
        """_runs_state 때로 되돌린다 — 그 뒤 나눠진 조각은 빼고 글을 되살린다. 조각이 나뉜 뒤 앞 조각만 되쓰면 글이 겹치거나 뒷글을 잃음(검토)."""
        for r in para_runs(p):
            if not any(r is x[0] for x in state):
                p.remove(r)
        for r, cid, ts in state:
            r.set("charPrIDRef", cid)
            now = r.findall(T("hp:t"))
            if [etree.tostring(t) for t in now] != [etree.tostring(t) for t in ts]:
                for t in now:
                    r.remove(t)
                r.extend(ts)

    def _keep_lines(self, p, w, n0):
        """머리(이름표)를 넓혀 줄이 n0보다 늘었을 때 내용 글자 자간을 1%씩 줄여(-18%까지) 줄 수를 n0로 지킨다(어림 오차 대비 폭을
        조금 줄여 봄). 지키면 (쓴 값, 되돌릴 목록), 못 지키면 None(바꾼 것 없음 — 나눈 조각도 되돌림)."""
        text = para_text(p)
        head = self.head_len(text)
        state = self._runs_state(p)
        if head and not self._split_at(p, head):
            return None
        content = self._content_runs(p, head, len(text))
        for d in range(-1, FIT_FLOOR - 1, -1):
            if len(self.lay.para_lines(p, w, delta=d, shrink=SLACK)[1]) <= n0:
                old = self._set_delta(content, d)
                if old and len(self.lay.para_lines(p, w, shrink=SLACK)[1]) <= n0:
                    return d, old
                self._undo(old)  # -18%에 걸린 조각이 있어 실제로는 덜 줄었음 — 더 줄여 봄
        self._restore_runs(p, state)
        return None

    def _replace_span(self, p, a, b, new):
        """글자 위치 [a, b)를 new로(한 조각 안에 있고 그 조각이 글 하나뿐일 때만)."""
        pos = 0
        for r in para_runs(p):
            t = run_text(r)
            if pos <= a and b <= pos + len(t):
                if not (plain_run(r)):
                    return False
                edit_run_text(r, t[:a - pos] + new + t[b - pos:], self.tab_proto)
                return True
            pos += len(t)
        return False

    # ------------------------------------------------------------ 3-2. 빈칸이 벌어지는 줄(사용자 원칙 — 다음 낱말 당기기)
    def _sparse(self, chs, lines, limit):
        """끝 줄을 빼고 limit보다 덜 찬 줄이 있는가(줄 바꿈으로 끝나는 줄은 한글이 벌리지 않으므로 뺌)."""
        return any(a and u / a < limit and self._ends_break(chs, e) is None for _, e, u, a in lines[:-1])

    def _pull_sparse(self, p, w, head, mark=True, report=False):
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
        wide = self._sparse(chs, lines, SPARSE)
        starts = [x[0] for x in lines]
        best = 0
        # 실제 값 +5%까지 한 번에 — +5%p씩 늘리면 정돈할 때마다 또 늘어남(-10 → -5 → 0 → +5, 검토. fill_broken과 같음)
        low = min([v for v in (self.styles.char.get(r.get("charPrIDRef"), {}).get("spacing", 0) for r in content) if v >= -30] + [0])
        for d in range(1, (WIDEN_MAX - low if wide else 0) + 1):
            _, l2 = self.lay.para_lines(p, w, delta=d, shrink=SLACK, floor=-30)  # 늘릴 때 그대로 두는 조각은 -30% 밑(_shift) — 어림도 같게
            if [x[0] for x in l2] != starts:
                break
            best = d
        if report and self._too_loose(p, w, best):
            return "left"  # 칸 보고글: 늘려도 낱말 사이가 크게 벌어짐 — 자간을 늘리지 않고 왼쪽 맞춤으로
        if not wide:
            return False
        if best and mark and self._set_delta(content, best):  # 이미 늘린 문단은 바뀌는 것이 없음
            self.mark(p, f"빈칸이 벌어지던 줄 — 당길 수 없어 자간을 +{best}%p 늘려 덜 벌어지게")
        return False

    def sparse_lines(self):
        n_ok = n_left = n_plain = 0
        for paras, body_w, _ in self.blocks():
            for p in paras:
                text = para_text(p)
                if para_tables(p) or para_pics(p) or re.search(r"\n[ ⎵⍽　]+", text) or "\t" in text or not text.strip():
                    continue
                if p in self._quote_ps:
                    continue  # 조문 상자 인용 글은 quote_fit이 자간으로만
                if self.styles.para.get(p.get("paraPrIDRef"), {}).get("align") not in ("JUSTIFY", "DISTRIBUTE", None):
                    continue
                if not self.fonts_ok(p):
                    continue
                chs, lines = self.lay.para_lines(p, body_w)
                if len(lines) < 2 or not self._sparse(chs, lines, PULL):
                    continue
                got = self._pull_sparse(p, body_w, self.head_len(text), report=p in self._report)
                if got == "left":
                    p.set("paraPrIDRef", self.hedit.para_align(p.get("paraPrIDRef"), "LEFT"))
                    if self._justified.pop(p, None) is None:  # 원래 양쪽 맞춤이던 문단만 바뀐 곳에(원래 왼쪽이면 그대로인 것)
                        self.mark(p, "낱말 사이가 크게 벌어져 왼쪽 맞춤으로")
                        n_plain += 1
                elif got:
                    n_ok += 1
                else:
                    n_left += 1
        self._justify_notes()
        if n_plain:
            self.notes.append(f"표 칸 보고서 글 {n_plain}개는 다음 낱말이 길어 낱말 사이가 크게 벌어져 왼쪽 맞춤으로 바꿨습니다.")
        if n_ok:
            self.notes.append(f"다음 낱말이 넘어가 빈칸이 벌어지던 문단 {n_ok}개는 자간을 줄여(-18%까지) 그 낱말을 당겼습니다.")
        if n_left:
            self.notes.append(f"빈칸이 벌어지는 줄이 남은 문단 {n_left}개 — 긴 낱말이 넘어가 자간으로는 못 당김(자간을 +5%까지 늘려 덜 벌어지게 한 것 포함).")

    # ------------------------------------------------------------ 4. 끝 줄 두세 글자 올리기(사용자 원칙 — 자간으로만)
    def _split_at(self, p, k):
        """글자 위치 k에서 조각을 나눠(같은 글자 모양) k 뒤 글만 자간을 바꿀 수 있게. 나누지 못하면 False."""
        pos = 0
        for r in para_runs(p):
            t = run_text(r)
            if pos < k < pos + len(t):
                if not (plain_run(r)):
                    return False
                tabs = run_tabs(r)
                twin = copy.deepcopy(r)
                set_run_text(r, t[:k - pos], self.tab_proto, tabs)
                set_run_text(twin, t[k - pos:], self.tab_proto, tabs)
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
                if t[i - pos] != " " or not (plain_run(r)):
                    return False
                edit_run_text(r, t[:i - pos] + "\n" + t[i - pos + 1:], self.tab_proto)
                self.eol_ok.add(p)
                return True
            pos += len(t)
        return False

    @staticmethod
    def _tail_len(chs, line):
        # 낱자만 센다 — ‘번만 허용’’·‘기간 → 확인’도 두서너 자(문장 부호·화살표를 세면 다섯 자로 보여 남았음, 양식 시험 2026-11-09)
        return len(re.sub(r"[^\w]|_", "", "".join(c[0] for c in chs[line[0]:line[1]])))

    def short_lines(self):
        """끝 줄에 두세 글자(빈칸 빼고 SHORT_LAST자 이하)만 남은 글 문단 — 사용자 원칙(style-guide 1절):
        ① 내용 글자의 자간을 1%씩 줄여(본문 -18%까지, 겹칠 만큼은 안 됨) 그 글자를 윗줄로 올린다.
        ② 올리면 겹칠 만큼 줄여야 하면, 문단 자간을 1%씩 늘려(+5%까지) 윗줄 낱말이 끝 줄로 자연스럽게 내려와 끝 줄이
           PUSH_LO자를 넘게 한다 — 윗줄은 양쪽 정렬로 꽉 찬 채(빈 곳이 남지 않음).
        ③ 그래도 안 되면 윗줄 낱말 경계의 빈칸을 줄 바꿈으로 바꿔 끝 줄을 PUSH_LO~PUSH_HI자로 내리고, 짧아진 윗줄의 자간을
           늘려(+5%까지) 빈 곳을 줄인다(한글은 줄 바꿈 바로 앞 줄을 벌리지 않아 그대로 두면 윗줄 끝이 빔).
        머리 기호·이름표는 자간을 바꾸지 않는다(둘째 줄 맞춤 그대로). 맞대어 보지 않은 글꼴은 건드리지 않음."""
        pulled, lowered, broke, cannot, unsure = [], [], [], [], 0
        self._lowered = {}
        for paras, body_w, _ in self.blocks():
            for p in paras:
                if para_tables(p) or para_pics(p) or "\n" in para_text(p) or "\t" in para_text(p) or p in self._quote_ps:
                    continue  # 조문 상자 인용 글은 끝 줄을 내리지 않음(줄 바꿈 넣기 없음 — quote_fit)
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
                head = self.head_len(text)
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
        k = self.head_len(text)
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
        for paras, _, scope in self.blocks():
            group += scope != "본문"
            for p in paras:
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

    def connector_lines(self):
        """줄 끝에 화살표·연결어(+·및·또는·= 등)만 남으면 그 앞에서 줄을 바꿔 다음 줄 첫머리로 — 작성 모드와 같은 사용자 원칙, 표 칸에도(양식 시험 2026-11-09
        '… → 범위 → / 기간 → 확인'). 줄 수가 늘면 그대로. 윗줄 빈 곳은 다음 단계(fill_broken)가 자간으로 채운다."""
        n = 0
        for paras, w, _ in self.blocks():
            for p in paras:
                text = para_text(p)
                if para_tables(p) or para_pics(p) or "\t" in text or not text.strip() or re.search(r"\n[ ⎵⍽　]+", text):
                    continue
                if p in self._quote_ps:
                    continue  # 조문 상자 인용 글에는 줄 바꿈을 넣지 않음
                if self.styles.para.get(p.get("paraPrIDRef"), {}).get("align") not in ("JUSTIFY", "DISTRIBUTE", "LEFT", None):
                    continue
                for _try in range(4):
                    chs, lines = self.lay.para_lines(p, w)
                    if len(lines) < 2:
                        break
                    hit = None
                    for s0, e0, _u, _a in lines[:-1]:
                        seg = "".join(c[0] for c in chs[s0:e0]).rstrip()
                        words = seg.split(" ")
                        if len(words) >= 3 and words[-1] in CONNECTORS and (e0 >= len(chs) or chs[e0][0] != "\n"):
                            hit = s0 + len(seg) - len(words[-1])
                            break
                    if hit is None or chs[hit - 1][0] != " " or not self._break_at(p, hit - 1):
                        break
                    if len(self.lay.para_lines(p, w)[1]) > len(lines):
                        self._swap_char(p, hit - 1, "\n", " ")
                        break
                    self.mark(p, "줄 끝 화살표·연결어를 다음 줄 첫머리로")
                    n += 1
        if n:
            self.notes.append(f"줄 끝에 남던 화살표·연결어 {n}곳을 다음 줄 첫머리로 내렸습니다.")

    def fill_broken(self):
        """줄 바꿈(Shift+Enter)으로 끝나는 줄은 한글이 양쪽 정렬로 벌리지 않아 줄 끝이 빈다 — 끝 줄 균형을 맞추려고 넣은 줄 바꿈
        (작성 도구의 '함께 내리기' 등)이면 그 줄이 80% 넘게 찬 것 — 자간을 늘려(실제 값 +5%까지) 빈 곳을 채운다
        (사용자: '다섯 글자 넘게 아래로 내리는 경우 위에 어색한 빈 공간이 남지 않게 글자 간격을 조정'). 줄 바꿈 뒤를 빈칸으로
        들인 문단(둘째 줄 흉내)과 맞대어 보지 않은 글꼴은 건드리지 않음."""
        n = unbroken = 0
        for paras, body_w, _ in self.blocks():
            for p in paras:
                text = para_text(p)
                if "\n" not in text or "\t" in text or para_tables(p) or para_pics(p) or re.search(r"\n[ ⎵⍽　]+", text):
                    continue
                if p in self._quote_ps:
                    continue  # 조문 상자 인용 글은 quote_fit이 자간으로만
                if not self.fonts_ok(p):
                    continue
                head = self.head_len(text)
                chs, lines = self.lay.para_lines(p, body_w)
                count = len(lines)
                for li in range(len(lines) - 1):
                    chs, lines = self.lay.para_lines(p, body_w)
                    s0, e0, used, avail = lines[li]
                    e0 = self._ends_break(chs, e0)
                    if e0 is None or not avail or not (BROKEN_MIN <= used / avail < FULL):
                        continue
                    # 먼저 그 줄 바꿈을 풀어(빈칸으로) 한글이 저절로 나누게 해 본다 — 정돈으로 내어쓰기가 바뀌어 더는 필요 없는
                    # 줄 바꿈이면 윗줄이 양쪽 정렬로 꽉 차고 끝 줄도 짧지 않음(그러면 푼 채로 둠)
                    # 앞뒤에 빈칸이 없는 줄 바꿈은 풀지 않는다 — 낱말 안 줄 바꿈이면 없던 빈칸이 생김(평가 2026-11-09: 공원안내판↵정비사업)
                    spaced = chs[e0 - 1][0] in " ⎵⍽" or (e0 + 1 < len(chs) and chs[e0 + 1][0] in " ⎵⍽")
                    if spaced and self._swap_char(p, e0, "\n", ""):
                        ok = self._pull_sparse(p, body_w, head, mark=False)
                        c2, l2 = self.lay.para_lines(p, body_w)
                        if ok and len(l2) > 1 and self._tail_len(c2, l2[-1]) <= SHORT_LAST:
                            # 풀면 끝 줄이 두세 글자 — 자간을 줄여 윗줄로(끝 줄 규칙 ①). 안 그러면 첫 정돈은 줄 바꿈을 두고 자간만 늘렸다가
                            # 두 번째 정돈에서야 풀림(표 칸 시험 tables2)
                            self._lift_tail(p, body_w, head)
                            c2, l2 = self.lay.para_lines(p, body_w)
                        if ok and len(l2) <= count and self._tail_len(c2, l2[-1]) > SHORT_LAST:
                            self.mark(p, f"줄 바꿈을 풀어 저절로 나눔(윗줄 채움 {used / avail:.0%} → 꽉 참)")
                            self.eol_ok.add(p)
                            unbroken += 1
                            count = len(l2)
                            break
                        self._insert_char(p, e0, "\n")
                    lo = max(head, s0)
                    if not (self._split_at(p, lo) and self._split_at(p, e0)):
                        continue
                    seg = self._content_runs(p, lo, e0)
                    spacings = [self.styles.char.get(r.get("charPrIDRef"), {}).get("spacing", 0) for r in seg]
                    base = min(spacings, default=0)
                    wide = 0
                    # 실제 값 +5%까지 한 번에 — 차이 +5%p씩만 늘리면 두 번째 정돈이 또 늘림(-4 → +1 → +5, 평가 2026-11-09)
                    for d in range(1, WIDEN_MAX - min([v for v in spacings if v >= -30] + [0]) + 1):
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

    def _lift_tail(self, p, w, head):
        """내용 글자 자간을 줄여(-18%까지) 끝 줄을 윗줄로 올린다. 못 올리면 바꾼 것 없음."""
        n = len(self.lay.para_lines(p, w)[1])
        need = next((d for d in range(-1, FIT_FLOOR - 1, -1)
                     if len(self.lay.para_lines(p, w, delta=d, shrink=SLACK)[1]) < n), None)
        if need is None or (head and not self._split_at(p, head)):
            return
        old = self._set_delta(self._content_runs(p, head, len(para_text(p))), need)
        if len(self.lay.para_lines(p, w)[1]) >= n:
            self._undo(old)

    def _insert_char(self, p, i, ch):
        """글자 위치 i 앞에 글자 하나를 다시 넣는다(_swap_char로 뺀 줄 바꿈 되돌리기)."""
        pos = 0
        for r in para_runs(p):
            t = run_text(r)
            if pos <= i <= pos + len(t) and plain_run(r):
                edit_run_text(r, t[:i - pos] + ch + t[i - pos:], self.tab_proto)
                return
            pos += len(t)

    def _swap_char(self, p, i, a, b):
        """글자 위치 i의 a를 b로(b가 빈 글이면 뺌). 그 조각이 글 하나뿐일 때만."""
        pos = 0
        for r in para_runs(p):
            t = run_text(r)
            if pos <= i < pos + len(t):
                if t[i - pos] != a or not (plain_run(r)):
                    return False
                edit_run_text(r, t[:i - pos] + b + t[i - pos + 1:], self.tab_proto)
                return True
            pos += len(t)
        return False

    def _unbreak(self, p):
        for r in para_runs(p):
            t = run_text(r)
            if "\n" in t and plain_run(r):
                edit_run_text(r, t.replace("\n", " "), self.tab_proto)

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
                    words = [cp for cp in cell_paras(tc) if para_text(cp).strip()]
                    if words:
                        self.mark(words[0], "칸 글을 세로 가운데로")
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

    @staticmethod
    def _keep_gap(left, right):
        """일부러 띄운 자리인가 — 칸 수가 아니라 자리 꼴로 본다(평가 2026-11-09: 표 칸은 세 칸 이상만, 본문은 없음이라 날짜·서명란·공문의
        두 칸을 줄였음). 날짜 틀(년·월·일 사이), (서명)·(인) 앞, 빈 괄호 안, 붙임 뒤, 끝. 앞."""
        return bool((re.search(r"[년월]$", left) and re.match(r"\d{0,2} ?[월일]", right)) or SIGN_RE.match(right)
                    or left.endswith(("(", "붙임")) or right.startswith((")", "끝.")))

    def double_spaces(self):
        """글 가운데 보통 빈칸 두 칸 넘게 잇단 곳을 한 칸으로(사용자: '불필요한 연속 두칸 띄우기는 한칸 띄우기로'). 머리 기호 뒤 두 칸도
        한 칸으로. 머리(이름표 — 작성자가 빈칸으로 폭을 맞춘 '- 대   상 :')와 줄머리, 표 머리 칸처럼 낱자 사이를 벌린 짧은 칸('구  분'·'하  천' —
        style-guide 비교표 꼴)은 그대로. 줄 맞춤 단계보다 먼저 한다(줄 나눔이 바뀔 수 있어서).
        일부러 띄운 자리도 그대로 — _keep_gap(날짜 틀·서명란·빈 괄호·붙임·끝.), 가운데·오른쪽 정렬 줄, 표 칸에서는 ○·-·※ 줄만 손보고
        세 칸 넘게 벌린 칸도 그대로('■ 개인   □ 팀  (팀명:      )'처럼 채울 자리를 비워 둔 양식 칸 — 사용자 양식 시험 2026-11-09)."""
        n = 0
        body = set(self.body)
        for p in self.all_paras():
            text = para_text(p)
            if "  " not in text or re.fullmatch(r"\s*[가-힣](?: +[가-힣]){1,3}\s*", text):
                continue
            if DATE_LINE_RE.match(text):
                continue  # 날짜·부서 줄('’26. 11. 2.(월)  ○○과')은 두 칸으로 갈라 둔 것
            if self.styles.para.get(p.get("paraPrIDRef"), {}).get("align") in ("CENTER", "RIGHT"):
                continue
            if p not in body and self.level(text) not in (2, 3, 4):
                continue
            hit = False
            pre, mark, _ = self.split(text)
            if mark:  # 머리 기호 뒤 두 칸 → 한 칸(고정폭 둘로 남으면 내어쓰기가 이웃 ○와 어긋남 — 평가 2026-11-09)
                a = re.match(r"^[ \t⎵⍽　]*", pre).end() + len(mark)
                if re.fullmatch(" {2,}", text[a:len(pre)]) and self._replace_span(p, a, len(pre), " "):
                    hit = True
                    text = para_text(p)
            if p not in body and re.search(r"\S {3,}\S", text):
                n += hit
                continue
            k = self.head_len(text) if self.split(text)[1] else 0
            m0 = re.match(r"^[ ⎵⍽　]*", text)
            k = max(k, m0.end() if m0 else 0)
            pos = 0
            for r in para_runs(p):
                t = run_text(r)
                st, pos = pos, pos + len(t)
                if pos <= k or not plain_run(r) or "  " not in t:
                    continue
                lo = max(0, k - st)

                def one(m, lo=lo, st=st):
                    keep = self._keep_gap(text[:st + lo + m.start()], text[st + lo + m.end():])
                    return m.group(0) if keep else " "
                new = t[:lo] + re.sub(r"(?<=\S) {2,}(?=\S)", one, t[lo:])
                if new != t:
                    edit_run_text(r, new, self.tab_proto)
                    hit = True
            if hit:
                self.mark(p, "잇단 빈칸을 한 칸으로")
                n += 1
        if n:
            self.notes.append(f"글 가운데 보통 빈칸이 두 칸 넘게 잇단 문단 {n}개를 한 칸으로 줄였습니다"
                              "(이름표 안·표 머리 칸 '구  분' 꼴, 날짜 틀·서명란·빈 괄호·붙임·끝. 앞은 그대로).")

    def leading(self):
        """머리 기호 앞 줄머리 빈칸을 문단 왼쪽 여백(또는 첫 줄 들여쓰기)으로 옮긴다 — 자리는 같고 빈칸 부호는 없음. 줄 맞춤
        단계보다 먼저 해야 줄 채움(%)을 같은 폭으로 잰다(나중에 하면 두 번째 정돈이 다른 줄을 '덜 참'으로 보고 다시 당겼음)."""
        n = 0
        self._lead_moved = set()
        w = self.box(self.secs[0])[0] if self.secs else 0  # 글자 폭만 쓰므로 표 칸 문단도 본문 폭으로 어림해도 같음
        for p in self.all_paras():  # 표 칸 안 '  ○ (평가근거) …'도
            if not (para_tables(p) or para_pics(p)) and self._lead_to_margin(p, w):
                self._lead_moved.add(p)
                self.mark(p, "줄머리 빈칸을 문단 왼쪽 여백으로(자리 그대로)")
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
        """글 문단(본문·넓은 표 칸)마다 어림 줄 수 — 정돈 전후를 견줘 줄이 늘어난 문단을 알린다(이름표·머리 자간을 넓혀 한 줄이 두 줄로
        넘어간 일을 한글 그림을 보기 전에는 몰랐음)."""
        out = {}
        for paras, body_w, _ in self.blocks():
            for p in paras:
                if not (para_tables(p) or para_pics(p)) and para_text(p).strip():
                    out[p] = len(self.lay.para_lines(p, body_w)[1])
        return out

    def split_composes(self):
        """글자 겹치기(네모 숫자 등)를 뒤 글과 다른 조각으로 — 한 조각에 함께 있으면 글을 다시 쓸 수 없어(plain_run) 번호 뒤 빈칸·자간을 못 맞춤.
        보이는 모양은 같음."""
        for sec in self.secs:
            for r in list(sec.iter(T("hp:run"))):
                kids = list(r)
                if len(kids) < 2 or r.find(T("hp:compose")) is None:
                    continue
                at = r
                for k in kids[1:]:
                    r.remove(k)
                    twin = etree.Element(r.tag, dict(r.attrib))
                    twin.append(k)
                    at.addnext(twin)
                    at = twin

    def marker_gaps(self):
        """기호 바로 뒤에 빈칸이 없는 줄(①내용·1.내용·○내용)에 한 칸 — 사용자 '부호 다음에 한칸'. 같은 묶음의 띄운 줄과 글 시작이 어긋나지 않게.
        줄이 늘면 내용 자간으로 지키고, 그래도 늘면 넣지 않음. 잇단 기호(①로그인 ②업로드)·①항·○월 중 같은 글은 그대로."""
        done = left = 0
        boxes = []
        for sec in self.secs:
            boxes += [(x, self.box(sec)[0]) for x in sec if x.tag == T("hp:p")]
            for tbl in sec.iter(T("hp:tbl")):
                for tc, w, _ in self._cells(tbl):
                    boxes += [(x, w) for x in cell_paras(tc)]
        for p, w in boxes:
            if para_tables(p) or para_pics(p) or w <= 0:
                continue
            if tight_marker_end(para_text(p)) is None:
                continue
            state = self._runs_state(p)
            n0 = len(self.lay.para_lines(p, w)[1])
            if not insert_marker_gap(p):
                continue
            if len(self.lay.para_lines(p, w)[1]) > n0 and (not self.fonts_ok(p) or self._keep_lines(p, w, n0) is None):
                self._restore_runs(p, state)
                left += 1
                continue
            self.mark(p, "기호 뒤에 한 칸")
            done += 1
        if done:
            self.notes.append(f"기호 바로 뒤에 빈칸이 없던 줄 {done}개에 한 칸을 넣었습니다.")
        if left:
            self.notes.append(f"기호 뒤에 한 칸을 넣으면 줄이 늘어나는 줄 {left}개는 그대로 두었습니다.")

    def clean_all(self):
        """한글에서 네모·붙임표·빈칸으로 찍히는 보이지 않는 글자를 빼고, 키캡 숫자를 글자 겹치기 네모 숫자로(사용자 그림 '1□공원' 2026-11-09)."""
        cuts = caps = 0
        for sec in self.secs:
            for p in sec.iter(T("hp:p")):
                a, b = clean_chars(p)
                if a:
                    self.mark(p, f"한글에서 네모·붙임표로 찍히는 보이지 않는 글자 {a}개를 뺌")
                if b:
                    self.mark(p, f"키캡 숫자 {b}개를 글자 겹치기 네모 숫자로")
                cuts, caps = cuts + a, caps + b
        if cuts:
            self.notes.append(f"한글에서 네모·붙임표·빈칸으로 찍히는 보이지 않는 글자 {cuts}개를 뺐습니다(이모지 표시 글자 등 — AI가 쓴 글에 잘 섞임).")
        if caps:
            self.notes.append(f"키캡 숫자(1️⃣) {caps}개를 글자 겹치기 네모 숫자로 바꿨습니다(키캡은 네모가 왼쪽으로 삐져나옴).")

    def run(self, out):
        self.split_composes()  # 겹치기와 글을 먼저 나눔 — 한 조각에 함께 있으면 키캡을 못 바꿔 두 번째 정돈에서야 바뀜
        self.clean_all()
        self.pages0, self.orphans0 = self.layout_state()
        self.fill0 = self._min_fill()
        before = self.pages0
        if clear_print_method(self.pkg):
            self.doc_changes.append("문서 설정: 모아찍기 인쇄를 끔(켜 두면 인쇄·PDF가 한 장에 2쪽씩 묶임)")
        lines0 = self.line_counts()
        # 높이가 바뀌지 않는 것 먼저, 높이를 늘릴 수 있는 것(빈 줄·○ 위 간격)은 쪽 수를 재 보며 나중에
        self.word_wrap()
        if not self.made:
            self.double_spaces()  # 작성 문서의 글 속 빈칸은 계획에 적은 그대로(날짜·부서 줄 '…(월)  ○○과' 등)
        if self.made:
            # 작성 모드로 만든 문서: 작성 규칙이 맞춘 것은 그대로, 사람이 더한 줄(내어쓰기 없음)·줄 나눔·빈칸만
            self.leading()
            self.quote_align()  # 옛 판(왼쪽 정렬 조문 상자)으로 만든 문서도 지금 규칙대로 — 지금 판으로 만든 문서는 바뀌는 것 없음
            self.hangs()
            self.hangs_again()
            self.quote_fit()
            self.one_space()
            self.hang_verify()
            self.notes.insert(0, f"이 스킬의 작성 모드로 만든 문서(판 {self.made})라 작성 규칙이 맞춘 끝 줄·이름표·내어쓰기·칸·간격은 "
                                 "그대로 두고, 내어쓰기가 없는 문단(만든 뒤 더한 줄)·글자 단위 줄 나눔·빈칸만 손봤습니다 — "
                                 "글을 크게 고쳤으면 계획을 고쳐 다시 만드는 것이 정확합니다(모두 다시 맞추려면 --all).")
        else:
            self.marker_gaps()
            self.sizes()
            self.labels()
            self.leading()  # 머리 자간을 같은 수준 값으로 맞춘 뒤에 — 그래야 줄머리 폭(여백)도 위아래 같은 값(○ 자리 한 줄로)
            self.cell_justify()  # 빈칸 벌어진 줄 맞춤(양쪽 맞춤 글만 봄)보다 먼저
            self.quote_align()  # 둘째 줄 맞춤보다 먼저(양쪽 정렬이어야 머리 빈칸을 고정폭으로 바꿈)
            self.cell_indent()  # 줄 나눔이 바뀔 수 있어 줄 맞춤 단계보다 먼저
            self.hangs()
            self.sparse_lines()
            self.hangs_again()
            self.quote_fit()  # 둘째 줄 맞춤(내어쓰기)이 정해진 뒤 — 조문 상자 인용 글은 자간으로만
            self.short_lines()
            self.connector_lines()
            self.fill_broken()
            self.harmonize()
            self.fill_ends()  # 줄 나눔이 다 정해진 뒤에
            self.cell_middle()
            self.blank_heights()
            self.o_gaps()
            self.cell_lines()  # 칸 높이의 여유를 쓰는 것은 끝 줄 맞춤 뒤에 — 줄 수가 정해진 다음
            self.cell_gaps()
            self.cell_keep()
            self.one_space()
            self.hang_verify()  # 맨 끝 — 빈칸 정리·폭 손질이 끝난 상태로 둘째 줄 자리를 다시 대조
        now = self.line_counts()
        grown = [p for p, k in lines0.items() if now.get(p, k) > k]
        if grown:
            self.notes.append(f"정돈 뒤 줄 수가 늘어난 문단 {len(grown)}개(예: ‘{self.name(grown[0])}…’) — 둘째 줄 맞춤·글자 크기 맞춤 때문일 수 있음(한글에서 확인).")
        self.grown = grown
        for p in self.touched:
            drop_linesegs(p)
        marked = sum(1 for m in self.orig_marks.values() if any(not k.startswith("tab:") for k in m))
        if marked:
            self.notes.append(f"형광펜 등 표시가 있는 문단 {marked}개는 그 조각의 글·빈칸을 그대로 두었습니다.")
        bad = [p for p in self.all_paras() if not self._same_text(p)]
        if bad:
            bad = self._restore_bad(bad)
        after = self.pages()
        if out and not bad:  # out이 없으면 저장하지 않음(검사만 — '정돈이 고칠 것'). 글자가 바뀐 채로는 저장하지 않음
            self.pkg.save(out)
        return before, after, bad

    def _restore_bad(self, bad):
        """글자가 바뀐 문단(도구 오류)은 원본 그대로 되돌린다 — 글을 잃은 파일을 내보내지 않게. 되돌리지 못한 문단을 돌려준다."""
        src = Package(self.path)
        old = [x for n in src.sections() for x in src.xml(n).iter(T("hp:p"))]
        now = [x for sec in self.secs for x in sec.iter(T("hp:p"))]
        if len(old) != len(now):
            return bad
        at = {x: k for k, x in enumerate(now)}
        for p in bad:
            q = old[at[p]]
            for r in para_runs(p):
                p.remove(r)
            for k, r in enumerate(para_runs(q)):
                p.insert(k, copy.deepcopy(r))
            p.set("paraPrIDRef", q.get("paraPrIDRef"))
            drop_linesegs(p)
            self.changes.pop(p, None)
        self.notes.insert(0, f"**글자가 바뀔 뻔한 문단 {len(bad)}개는 원본 그대로 되돌렸습니다**(정돈하지 않음 — 도구 오류이니 알려 주세요): "
                             + ", ".join(f"‘{self.name(p)}…’" for p in bad[:3]))
        return [p for p in bad if not self._same_text(p)]

    def last_fill(self):
        """마지막 쪽 채움(0~1, 어림)."""
        sec = self.secs[-1]
        h = self.box(sec)[1]
        used = self._page_fill()[-1]
        return used[-1] / h if used and h else 0.0

    def page_holes(self):
        """칸 안 표·그림 때문에 아래가 크게 빈 쪽 [(쪽, 빈 mm)] — 나뉘지 않는 덩어리가 통째로 밀린 자리."""
        out, base = [], 0
        for sec, used in zip(self.secs, self._page_fill()):
            h = self.box(sec)[1]
            inner = any(para_tables(cp) or para_pics(cp) for tbl in sec.iter(T("hp:tbl")) if tbl.get("pageBreak") == "CELL"
                        for tc in tbl.iter(T("hp:tc")) for cp in cell_paras(tc))
            if inner:
                out += [(base + k + 1, (h - u) / HWPUNIT_PER_MM) for k, u in enumerate(used[:-1]) if (h - u) / HWPUNIT_PER_MM > 25]
            base += len(used)
        return out

    def _same_text(self, p):
        """정돈 전후 글·표시가 같은가 — 끝 줄 균형으로 정한 문단만 빈칸 ↔ 줄 바꿈을 같다고 본다."""
        a, b = self.orig_text.get(p), para_text(p)
        if a is None:
            return True
        if p in self.eol_ok:
            a, b = a.replace("\n", " "), b.replace("\n", " ")
        return flat(a) == flat(b) and self.orig_marks.get(p) == text_marks(p)

    def change_lines(self, limit=80):
        """'바뀐 곳' 글 줄 — 정돈 결과와 검사만의 '정돈이 고칠 것'이 같은 글을 쓴다."""
        order = {p: k for k, p in enumerate(self.body)}
        rows = sorted(self.changes.items(), key=lambda x: order.get(self.host.get(x[0], x[0]), 10 ** 6))
        out = list(self.doc_changes)
        for p, whats in rows[:limit]:
            host = self.host.get(p)
            where = f"{self.host_pages.get(host, '?쪽')} 표 칸" if host is not None else f"{self.page_of.get(p) or '?'}쪽"
            out.append(f"{where} ‘{self.name(p)}’: " + ", ".join(dict.fromkeys(whats)))
        if len(rows) > limit:
            out.append(f"… 그 밖 {len(rows) - limit}곳")
        return out

    def report(self, before, after, bad, out):
        print(f"gongyong-hwpx v{SKILL_VERSION}")
        print(f"만듦: {out}  (원본은 그대로)" if not bad else f"만들지 않음: {out}  (원본은 그대로)")
        if bad:
            print("## 문제 있음")
            print(f" - 글자가 바뀐 문단 {len(bad)}개 — 정돈은 글자를 바꾸면 안 되어 파일을 저장하지 않았습니다(도구 오류): "
                  + ", ".join(f"‘{flat(para_text(p))[:12]}…’" for p in bad[:3]))
        print("## 한 일")
        for n in self.notes or ["바꿀 곳이 없었습니다(이미 정돈된 문서)."]:
            print(" - " + n)
        print("## 바뀐 곳(실제로 바뀐 문단만, 쪽은 원본 기준" + (" 어림" if self.page_guess else "") + ")")
        for line in self.change_lines() or ["없음"]:
            print(" - " + line)
        print("## 쪽")
        line = f" - 어림 쪽 수 {before}쪽 → {after}쪽(한글 없이 어림 — 마지막 확인은 한글에서)"
        if after > before:
            line += f" — 쪽이 늘어날 수 있습니다. 정돈은 글·쪽 나눔을 고치지 않으니, 넘치는 쪽을 한글에서 확인해 주세요"
        print(line)
        holes = self.page_holes()
        if holes:
            print(" - 아래가 크게 빈 쪽: " + ", ".join(f"{k}쪽 {mm:.0f}mm" for k, mm in holes)
                  + " — 칸 안 표·그림은 쪽에서 나뉘지 않아 통째로 밀림. ○ 차례를 바꾸거나 그 표를 작게 하면 채울 수 있음")


def tidy_file(path, out, max_pages=None, **base):
    """정돈하고 결과를 찍는다. 돌려주는 것: 끝 번호(0, 쪽 상한을 넘으면 3). max_pages — 덜 바꾸는 안부터 마지막 쪽에 여유까지 있는 첫 안,
    없으면 상한 안에 드는 첫 안, 끝까지 넘으면 가장 많이 줄인 안."""
    pick, how = {}, ""
    if max_pages:
        fits = None
        for pick, how in MAX_PAGE_STEPS:
            t0 = Tidier(path, **base, **pick)
            got = t0.run(None)[1]
            if got < max_pages or (got == max_pages and t0.last_fill() <= LAST_FILL):
                fits = (pick, how)
                break
            if got == max_pages and fits is None:
                fits = (pick, how)
        if fits:
            pick, how = fits
    t = Tidier(path, **base, **pick)
    before, after, bad = t.run(out)
    t.report(before, after, bad, out)
    if bad:
        return 1
    if not max_pages:
        return 0
    print(f"## 쪽 상한 {max_pages}쪽")
    if after > max_pages:
        print(f" - **넘음**: 간격을 모두 줄여도 어림 {after}쪽입니다({how}). 글을 줄이거나 그림을 줄이거나 차례를 바꿔야 합니다"
              " — 칸 안 표·그림은 쪽에서 나뉘지 않아 쪽 끝이 비기 쉬우니 그쪽부터 보세요.")
        return 3
    tight = after == max_pages and t.last_fill() > LAST_FILL
    print(f" - 어림 {after}쪽 — 상한 안" + (f"(맞춘 값: {how})" if how else "")
          + (f". 마지막 쪽이 {t.last_fill():.0%} 차 있어 한글에서 넘칠 수 있음" if tight else "") + ". 어림이므로 한글에서 PDF로 저장해 쪽을 확인할 것")
    return 0


def main():
    ap = argparse.ArgumentParser(description="이미 쓴 한글(hwpx) 파일을 제자리에서 최소로 정돈(글자·차례·문체 그대로)")
    ap.add_argument("path")
    ap.add_argument("--out")
    ap.add_argument("--no-keep-o", action="store_true",
                    help="○ 줄에 '다음 문단과 함께'를 넣지 않음(기본은 넣음 — ○ 제목이 쪽 끝에 홀로 남지 않게)")
    ap.add_argument("--gap", type=float, help="○ 위 간격(pt)을 이 값 하나로")
    ap.add_argument("--max-pages", type=int, help="쪽 상한(양식의 '5쪽 이내' 등) — 넘으면 ○·□ 위 간격부터 줄이고, 그래도 넘으면 분명히 알림")
    ap.add_argument("--blank-mm", type=float, help="□ 앞 빈 줄 높이가 제각각일 때 이 높이(mm)에 가장 가까운 빈 줄로 모두 맞춤")
    ap.add_argument("--all", action="store_true",
                    help="이 스킬의 작성 모드로 만든 문서도 정돈 규칙으로 모두 다시 맞춤(기본은 작성 규칙이 맞춘 것을 그대로 둠)")
    ap.add_argument("--hang-at", choices=("기호", "이름표"),
                    help="사용자가 둘째 줄 기준을 밝혔을 때만: 기호(머리 기호 뒤 첫 글자) 또는 이름표(이름표·쌍점 뒤, 없으면 기호 뒤) — "
                         "기존 내어쓰기를 허용치로 두지 않고 그 자리에 정확히, 한 줄 문단에도")
    a = ap.parse_args()
    if not a.path.lower().endswith(".hwpx"):
        raise SystemExit("정돈은 한글(HWPX) 파일만 받습니다. PDF·그림 문서는 '옮겨 쓰기'(내용 그대로 새로 만들기)로 하세요."
                         " 옛 형식(.hwp)이면 한글에서 [다른 이름으로 저장] → 'HWPX'로 저장해 주세요.")
    out = a.out or re.sub(r"\.hwpx$", "", a.path, flags=re.I) + "_정돈.hwpx"
    if same_path(out, a.path):
        raise SystemExit("결과를 원본과 같은 이름으로 저장하지 않습니다 — 다른 이름을 주세요.")
    sys.exit(tidy_file(a.path, out, keep_o=not a.no_keep_o, gaps=[int(round(a.gap * 100))] if a.gap else None, blank_mm=a.blank_mm,
                       all_rules=a.all, max_pages=a.max_pages, hang_at=a.hang_at))


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
