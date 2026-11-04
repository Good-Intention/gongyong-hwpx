# -*- coding: utf-8 -*-
"""사용자 원칙에 따른 자동 맞춤(한글 프로그램 없이 layout.py 어림 계산으로).

1) 줄 맞춤(원칙 1·5): 마지막 줄에 짧은 낱말 하나만 남으면, 그 문단 자간을 겹치지 않는 범위(-10%까지)에서
   1%씩 줄여 보고, 한 줄이 줄어드는 가장 작은 값을 쓴다.
2) 쪽 맞춤(원칙 6·8): 쪽 나눔으로 나뉜 덩어리마다
   - 그대로 / □ 사이 한 줄 빈 줄을 좁은 빈 줄로 / + 줄 간격 150% / + 줄 간격 140%
   를 어림해 보고, 쪽 수가 줄거나 쪽 아래 큰 빈 곳이 줄어드는 것 가운데 가장 덜 바꾼 것을 고른다.
   이득이 없으면 그대로 둔다. 어림 오차에 대비해 쪽 높이를 3mm 덜 쓴다고 보고 계산한다.
"""
import copy
import re

from hwpx_lib import (HWPUNIT_PER_MM, UNIT_RE, T, cell_paras, head_length, is_blank, label_colon, label_content, marker_level,
                      page_info, para_pics, para_runs, para_tables, para_text, run_text, set_run_text, split_marker, table_grid)
from layout import Layout, spacing_after


def split_lines(chs):
    """강제 줄 바꿈(\\n)으로 나눈 글자 묶음들."""
    out, cur = [], []
    for c in chs:
        if c[0] == "\n":
            out.append(cur)
            cur = []
        else:
            cur.append(c)
    out.append(cur)
    return out

SHORT_LAST = 0.25            # 마지막 줄이 쓸 수 있는 폭의 이 비율보다 짧으면 당겨 볼 만함
NL = chr(10)                 # 강제 줄 바꿈 글자
CUT_MAX = 6                  # 이 글자 수 안에서 줄이면 한 줄에 들어가는 두 줄 문단은 '낱말 하나 빼기' 후보로 알림
ARROWS = "⇒→➜"              # 화살표 내용은 한 줄에, 안 되면 화살표부터 통째로 다음 줄(사용자 원칙 2026-11-01)
PUSH_MIN, PUSH_MAX = 7, 10   # 올리기가 안 되면 끝 줄이 이만큼(빈칸 뺀 글자 수) 되게 위 줄 낱말을 내림(사용자 원칙 2026-11-01)
FLOOR = -18                  # 본문 자간 하한(사용자 수정본에서 -17~-18까지 씀. 더 좁히면 겹칠 수 있음)
EDGE = 0.95                  # 본문 폭의 이 비율 이상인 표는 본문 폭에 딱 맞춤(끝선 맞추기)
PULL = 0.97                  # 줄을 채운 비율이 이보다 낮으면 자간을 줄여 다음 낱말을 당겨 본다(가급적 한 줄에 — 사용자 지시 2026-10-31)
SPARSE = 0.85                # 당길 수 없고 이보다 낮으면 자간을 조금 늘려 빈칸이 덜 벌어지게
LOOSE = 0.85                 # 맞춘 뒤에도 줄이 이보다 덜 차면 '빈칸이 크게 벌어짐'으로 알림(글을 고치라고)
WIDEN_MAX = 5               # 자간을 늘릴 때 상한(%). +10%는 글자 사이가 넓어 어색하다는 사용자 의견(2026-10-31)
SLACK = 0.995                # 자간을 바꿔 볼 때 쓸 수 있는 폭을 이만큼만 쓴다고 보고 어림(어림 오차 대비)
NUMERIC_RE = re.compile(r"^[△▲▽▼+\-−]?[\d,]+(\.\d+)?\s*(%|대|건|곳|개|명|회|원|천원|만원|백만원|억원|점|일|개사)?$")
# 날짜·시기·기간 칸('26. 11. · '27. 1.~ · 11. 2.~11. 6. · 22:00~02:00 · 4/4분기) — 금액이 아닌 숫자라 가운데 정렬
_ONE_DATE = r"[’']?\d{1,4}(?:\s*[.:/년월일]\s*\d{1,2})*\s*[.년월일]?\s*(?:분기|주차?|주)?\s*(?:\([월화수목금토일]\))?"
DATE_RE = re.compile(r"^" + _ONE_DATE + r"(?:\s*[~∼\-–]\s*(?:" + _ONE_DATE + r")?)?$")
SAFETY = 3 * HWPUNIT_PER_MM  # 쪽 맞춤 여유
BIG_GAP = 0.25               # 쪽 아래 빈 곳이 본문 높이의 이 비율보다 크면 '애매하게 넘어감'
MIN_LINE = 140               # 줄 간격 하한(원칙 6)
SPACER_LINE = 100            # □ 사이 빈 줄을 좁힐 때 그 빈 줄의 줄 간격(더 좁히지 않음)
BLOCK_GAP = 0.20             # □ 블록을 통째로 넘기면 쪽 아래 빈 곳이 본문 높이의 이 비율을 넘을 때는 ○ 묶음 단위로 나눔
                             # (나눌 때 마지막 ○ 하나만 넘어가지 않게 — layout.paginate). 빈 곳은 spread_pages가 줄 간격으로 줄임
SPACER_COST = 10             # 쪽 맞춤에서 □ 사이 빈 줄 좁히기를 줄 간격 몇 %를 낮춘 만큼으로 칠지
ARROW_HANG_AT = 0.55         # 화살표 뒤 글자 밑에 둘째 줄을 맞추는 것은 화살표가 첫 줄의 이 비율 안에 있을 때만(뒤쪽이면 줄이 너무 좁아짐)
FW = "⎵"                     # 고정폭 빈칸(양쪽 정렬 때 늘어나지 않음)
SPREAD_GAP = 0.04            # 다음 쪽으로 이어지는 쪽 아래가 본문 높이의 이 비율보다 비면 '끝선이 애매함' → 그 쪽 줄 간격을 넓힘
SPREAD_ADD = 20              # 그때 쪽 전체 줄 간격을 더하는 상한(%p) — 사용자 수정본: ○ 150→170, 제목 160→180(2026-11-01)
LINE_CAP = 190               # 줄 간격 상한(원칙 6: 140~190%)
# 여는 낫표 표시가 시작하는 자리(글자 칸 대비): 휴먼명조는 칸 오른쪽에 찍혀 왼쪽 반 칸이 빔(글꼴 파일 HMKMM.TTF 실측 2026-11-03,
# 60pt 한글 실측 0.53과 같음). 보통 한글은 0.055~0.12(가·지·조·사·관 …)라 그 어림 KO_INK에 맞춰 당긴다.
CORNER_INK = {"휴먼명조": {"「": 0.535, "『": 0.547}}
KO_INK = 0.07
CORNER_FLOOR = -50           # 낫표 앞 글자 자간 하한(한글 자간 하한, 따옴표 붙이기와 같음)
# 금액 열: 머리 칸에 금액·예산·사업비·○○액·(원)·백만원 등이 있거나, 칸 숫자에 원 단위가 붙은 열(오른쪽 정렬)
AMOUNT_HEAD_RE = re.compile(r"금액|예산|사업비|비용|단가|보조금|지원금|[가-힣]액|\((천|백만|만|억)?원\)|(천|백만|만|억)원")
AMOUNT_CELL_RE = re.compile(r"\d\s*(천|백만|만|억)?원$")
# 표 안 글자는 10~12pt 맑은 고딕, 단어로 끊고, 가급적 다음 줄로 내리지 않는다(사용자 원칙 2026-11-01)
TABLE_MIN_PT = 10            # 줄 바꿈을 줄이려고 표 글자를 줄일 때 하한
NEAR = 1.10                  # 칸 글이 쓸 수 있는 폭을 이 비율 안에서 넘으면 '한 줄로 입력'(한글이 글자 간격을 줄여 한 줄에 —
                             # '셀 안에도 글자 간격을 줄여서 한 줄에', 사용자 원칙 2026-11-01. 10%면 자간 약 -10%로 겹치지 않음)
CUT_COST = 10                # 칸 너비를 정할 때 낱말 가운데 끊김 하나를 줄 몇 개로 칠지('단어로 끊기' — 거의 허용 안 함)
DOTS = "·ㆍ‧"                 # 가운데점: 긴 이름('○○원·△△위원회')은 점 뒤에서 줄을 나눌 수 있음(낱말 끊김 아님)
CELL_COST = 0.25             # 줄 높이를 정하지 않는 칸이라도 다음 줄로 넘어가면 줄 하나를 이만큼으로 침(가급적 내리지 않기)
SHORT_LEN = 10               # 이 글자 수 이하의 짧은 칸 글('평균 3일 이내'·'1%·60%·5%')이 넘어가면 더 보기 나쁨
SHORT_COST = 2               # 짧은 칸 글이 넘어간 줄 하나에 더 얹는 벌점
DOT_COST = 1                 # 가운데점 뒤에서 나누는 것 하나를 줄 몇 개로 칠지(빈칸에서 나누는 것보다는 덜 좋음)
HEAD_COST = 3                # 머리 줄 칸이 다음 줄로 넘어가면(‘남은 두 달 할 / 일’) 줄 몇 개로 칠지 — 머리 줄은 되풀이돼 더 눈에 띔
UNIT_GAP = 2                 # 표 위 기준·단위 줄은 표 글자보다 이만큼(pt) 작게
NOTE_SMALLER = 1             # 표 바로 밑 ※·* 설명은 표 글자보다 이만큼(pt) 작게(사용자 원칙 2026-11-02)
BULLET_RE = re.compile(r"^[ ⎵⍽]*[○●◎◦ㅇ·•\-–※*□■◇◆▶►①-⑳][ ⎵⍽]")  # 칸 안 글머리표 줄('- 내용', '○ 내용', '① 순서')
BULLET_PAD = 1.5 * HWPUNIT_PER_MM  # 칸 안 글머리표 줄은 왼쪽 정렬하되 왼쪽을 약간 띄움(사용자 원칙 2026-11-01)
# 표 열의 '·' 항목(사용자 수정본·결정 2026-11-01): 이름을 늘어놓는 열(머리 칸이 '등록 후보'·'확인 사항'·'평가지표(배점)'처럼
# 끝나는 앞쪽 열)은 '·' 줄 대신 쉼표로 한 줄, 설명 열(칸 글이 문장꼴로 긴 열)은 한 항목이어도 모두 '· '로 통일
NAME_HEAD_RE = re.compile(r"(항목|후보|사항|과제|지표|사업명?|명칭|대상)\s*(\([^()]*\))?$")
DOT_ITEM_RE = re.compile(r"^[ ⎵⍽]*[·ㆍ•][ ⎵⍽]")
CELL_VPAD = 1.2 * HWPUNIT_PER_MM  # 표 칸 안 위·아래 여백 하한(여러 줄 칸 글이 칸 선에 붙지 않게 — 사용자 원칙 2026-11-01)
CELL_HPAD = 1.8 * HWPUNIT_PER_MM  # 표 칸 안 왼쪽·오른쪽 여백 하한
TIGHT = 1.10                 # 옆 열에 폭을 내줄 때 그 칸 글 자간을 줄여(약 -9%, 사용자 수정본) 줄 수를 지킬 수 있는 폭 비율
TIGHT_SP = -9                # 그때 줄이는 자간(%)
CELL_SAFE = 0.97             # 칸 글 줄을 나눌 때 한 줄을 쓸 수 있는 폭의 이 비율 안으로(한 낱말이 넘어가 셋째 줄에 혼자 남는 일 방지)
BORROW_SAFE = 0.97           # 폭을 빌릴 때 칸 글 폭 어림에 더 두는 여유(맑은 고딕 어림이 1~2% 모자라 한 낱말이 넘어간 일, 2026-11-01)
BORROW_STEP = 1 * HWPUNIT_PER_MM  # 옆 열에서 폭을 빌리는 단위
CONNECTORS = {"+", "＋", "및", "또는", "=", "×"}  # 줄 끝에 남으면 다음 줄 첫머리로 내리는 연결어·연결 기호(사용자 원칙 2026-11-01)
UNIT_START = "(+→⇒➜"         # 칸 글을 두 줄로 나눌 때 이 글자로 시작하는 낱말 앞에서 나누면 뜻 단위가 됨
DATE_GAP_RE = re.compile(r"(?<=\d\.)[ ⎵⍽]+(?=\d{1,2}(?:\.|월))")  # 표 안 날짜 숫자 사이 빈칸(’26. 11. 13. → ’26.11.13.)
PAREN_BIND = 10              # 칸 글의 괄호 안 글자가 이만큼 이하이면 괄호 안 빈칸을 묶음 빈칸으로(괄호 가운데서 안 꺾임)
PAREN_RE = re.compile(r"\(([^()]{1,30})\)")
PAREN_SPLIT = 6              # 낱말에 붙은 괄호 안 글자가 이만큼 이상이면 괄호 앞에서도 줄을 나눌 수 있음
INFO_PAREN_RE = re.compile(r"\((?!안\)|가칭\))[^()]+\)")  # 머리 칸의 '(배점)'처럼 정보를 더하는 괄호('(안)'은 아님)
CAPTION_PAD = 4 * HWPUNIT_PER_MM  # 제목 걸친 상자의 제목 양옆(위 선이 끊긴 자리) 여유
NOTE_GAP = 2.0 * HWPUNIT_PER_MM  # 표 바로 뒤 ※와 표 사이(표 바깥 여백 아래) — 너무 붙는다는 사용자 의견(2026-11-01)
MONEY_PAD = 1.5 * HWPUNIT_PER_MM  # 금액 칸은 오른쪽 정렬하되 오른쪽에 약간 띄움(사용자 원칙 2026-11-01)
# 참고 쪽은 가급적 한 장에 꽉 채우고, 표가 작으면 두 개를 한 장에(사용자 원칙 2026-11-01)
REF_RE = re.compile(r"^\s*(참\s*고|붙\s*임|별\s*첨|첨\s*부)")
ROW_PAD = 4.0 * HWPUNIT_PER_MM   # 참고 표 줄 높이를 줄일 때 하한 = 글자 높이 + 이만큼(10pt → 약 7.5mm — 칸 위아래에 약간의 공간, 사용자 원칙 2026-11-01)
ROW_ADD_MAX = 5 * HWPUNIT_PER_MM  # 쪽을 채우려고 줄마다 더하는 높이 상한(더 늘리면 줄이 지나치게 벌어짐)
FILL_MARGIN = 2 * HWPUNIT_PER_MM  # 참고 쪽을 채울 때 SAFETY에 더해 남겨 둘 여유(넘치면 표 한 줄이 다음 쪽으로 감)
# 표지(대구시 문서 표지를 본뜸, 2026-11-01): 제목 띠는 본문 높이의 이 비율쯤에서 시작, 마크·부서명은 쪽 아래에 붙임
COVER_TITLE_AT = 0.22                  # (참고 표지 31% — 가운데 정사각형 개요 상자 자리를 위해 조금 올림)
COVER_BOTTOM_GAP = 8 * HWPUNIT_PER_MM  # 부서명 아래 남길 높이(참고 표지: 약 8mm)
COVER_MIN_GAP = 6 * HWPUNIT_PER_MM     # 묶음 사이 최소 간격
COVER_BOX_MAX = 150 * HWPUNIT_PER_MM   # 표지 개요 상자를 글에 맞춰 넓힐 때 상한(기본 120mm)


def cover_end(paras):
    """첫 쪽이 표지인가: 첫 쪽 나눔 앞 문단들에 그림이 있고 □·○·- 항목이 없으면 표지 — 본문이 시작하는 문단 번호, 아니면 None."""
    end = next((i for i, p in enumerate(paras) if i > 0 and p.get("pageBreak") == "1"), None)
    if end is None:
        return None
    first = paras[:end]
    if not any(para_pics(p) for p in first):
        return None
    if any(marker_level(para_text(p)) in (1, 2, 3) for p in first if not para_tables(p)):
        return None
    return end


class Fitter:
    def __init__(self, builder):
        self.b = builder
        self.st = builder.styles
        self.lay = Layout(builder.styles, builder.metrics)
        pg = page_info(builder.sec)
        self.body_w = pg["body_width"] * HWPUNIT_PER_MM
        self.body_h = (pg["height"] - pg["top"] - pg["bottom"] - pg["header"] - pg["footer"]) * HWPUNIT_PER_MM
        self.forced = set()  # force_breaks가 쪽 나눔을 넣은 문단(묶음째 다음 쪽으로 넘김)
        self.notes = []

    def paras(self):
        return [p for p in self.b.sec if p.tag == T("hp:p")]

    def text_boxes(self):
        """자동 줄 맞춤 대상 글 문단과 그 문단이 쓸 수 있는 폭: 본문 문단 + 한 칸짜리 상자(제목·요약 상자) 안 문단."""
        out = []
        for p in self.paras():
            tables = para_tables(p)
            if not tables:
                if para_text(p).strip():
                    out.append((p, self.body_w))
                continue
            for tbl in tables:
                grid = table_grid(tbl)
                if len(grid) != 1:
                    continue
                tc = grid[0][4]
                w = int(tc.find(T("hp:cellSz")).get("width", "0")) - self._cell_margin(tbl, tc)
                for cp in cell_paras(tc):
                    if para_text(cp).strip():
                        out.append((cp, w))
        return out

    # ------------------------------------------------------------ 줄 맞춤
    def checked(self, p):
        """자간을 바꿔도 되는 문단인가: 한글로 줄 바꿈을 맞대어 본 글꼴(휴먼명조·중고딕)만 쓴 문단.
        다른 글꼴(HY헤드라인M 등)은 어림 오차가 2%를 넘은 적이 있어(2026-10-31 실측) 자간을 건드리지 않는다."""
        faces = {self.st.char.get(r.get("charPrIDRef"), {}).get("font") for r in para_runs(p)
                 if r.find(T("hp:t")) is not None and run_text(r).strip()}
        return bool(faces) and all(self.lay.m.checked(f) for f in faces)

    def set_delta(self, p, d):
        """문단 내용 조각의 자간을 d만큼 바꾼다. 머리 기호·괄호 이름표 조각은 그대로 둔다(줄 맞춤 유지)."""
        head = head_length(para_text(p))
        pos = 0
        for r in para_runs(p):
            if r.find(T("hp:tbl")) is not None:
                continue
            start = pos
            pos += len(run_text(r))
            if r.find(T("hp:t")) is None or start < head:
                continue
            cid = r.get("charPrIDRef")
            base = self.st.char.get(cid, {}).get("spacing", 0)
            new = spacing_after(base, d, FLOOR)
            if new != base:
                r.set("charPrIDRef", self.b.hedit.char_spacing(cid, new))

    def fit_lines(self):
        done = []
        for p, box_w in self.text_boxes():
            if not self.checked(p):
                continue
            chs, lines = self.lay.para_lines(p, box_w)
            if len(lines) < 2:
                continue
            s, e, used, _ = lines[-1]
            full = lines[0][3]  # 첫 줄 폭 기준(이름표 뒤로 내어쓴 둘째 줄은 좁아 비율이 커 보임)
            words = len("".join(c[0] for c in chs[s:e]).split())
            if used > full * SHORT_LAST and words > 1:
                continue
            for d in range(-1, FLOOR - 1, -1):
                _, l2 = self.lay.para_lines(p, box_w, delta=d, shrink=SLACK, floor=FLOOR)
                if len(l2) < len(lines):
                    self.set_delta(p, d)
                    done.append(d)
                    break
        if done:
            self.notes.append(f"마지막 줄에 짧은 낱말만 남던 문단 {len(done)}개는 자간을 조금 줄여"
                              f"({max(done)}~{min(done)}%) 한 줄을 줄였습니다.")
        self.widen_sparse()

    def _content_spacing(self, p):
        """문단 내용(머리 뒤) 글자 수가 가장 많은 자간 — 줄 맞춤이 이미 바꾼 값을 알아보는 기준."""
        head = head_length(para_text(p))
        count, pos = {}, 0
        for r in para_runs(p):
            t = run_text(r)
            if r.find(T("hp:t")) is not None and pos + len(t) > head:
                sp = self.st.char.get(r.get("charPrIDRef"), {}).get("spacing", 0)
                count[sp] = count.get(sp, 0) + len(t) - max(0, head - pos)
            pos += len(t)
        return max(count, key=count.get) if count else 0

    def widen_sparse(self):
        """다음 낱말이 넘어가 양쪽 정렬로 빈칸이 벌어질 줄(쓴 폭 < 97%)이 있으면
        1) 자간을 줄여(-18%까지) 다음 낱말을 그 줄로 당겨 본다(사용자 수정본 규칙: 넘친 글자는 자간을 줄여 한 줄에).
        2) 그래도 안 되면 줄 바꿈 자리는 그대로 두고 자간을 늘려(+5%까지) 덜 벌어지게 한다."""
        pulled, widened = [], []
        for p, box_w in self.text_boxes():
            if not self.checked(p):
                continue
            chs, lines = self.lay.para_lines(p, box_w)
            if len(lines) < 2:
                continue

            def sparse(ls, limit):
                # 강제 줄 바꿈(push_down·연결어 내리기)으로 끝나는 줄은 한글이 벌리지 않으므로 성긴 줄로 치지 않는다
                # (만든 문서를 다시 다듬을 때 그 줄 때문에 자간을 늘리지 않게 — 되풀이해도 같게, 2026-11-04)
                return any(used / avail < limit and "\n" not in (chs[e - 1][0], chs[e][0] if e < len(chs) else "")
                           for _, e, used, avail in ls[:-1])

            def orphan(cs, ls):
                """마지막 줄에 짧은 낱말 하나만 남는가."""
                s, e, used, _ = ls[-1]
                return (len(ls) > 1 and used < ls[0][3] * SHORT_LAST
                        and len("".join(c[0] for c in cs[s:e]).split()) <= 1)

            if not sparse(lines, PULL):
                continue
            done = False
            was_orphan = orphan(chs, lines)
            for d in range(-1, FLOOR - 1, -1):
                c2, l2 = self.lay.para_lines(p, box_w, delta=d, shrink=SLACK, floor=FLOOR)
                if orphan(c2, l2) and not was_orphan:
                    continue  # 당기면 마지막 줄에 외톨이 낱말이 생김 → 이 값은 쓰지 않음
                if len(l2) <= len(lines) and not sparse(l2, PULL):
                    self.set_delta(p, d)
                    pulled.append(d)
                    done = True
                    break
            if done or not sparse(lines, SPARSE):
                continue
            starts = [s for s, _, _, _ in lines]
            best = 0
            # +WIDEN_MAX는 절대 상한 — 이미 늘린 문단을 다시 맞출 때 더 늘리지 않게(되풀이해도 같게, 2026-11-04)
            for d in range(1, WIDEN_MAX - self._content_spacing(p) + 1):
                _, l2 = self.lay.para_lines(p, box_w, delta=d, shrink=SLACK, floor=FLOOR)
                if [s for s, _, _, _ in l2] != starts:
                    break
                best = d
            if best:
                self.set_delta(p, best)
                widened.append(best)
        if pulled:
            self.notes.append(f"다음 낱말이 넘어가 빈칸이 크게 벌어질 문단 {len(pulled)}개는 자간을 줄여"
                              f"({max(pulled)}~{min(pulled)}%) 그 낱말을 앞줄로 당겼습니다.")
        if widened:
            self.notes.append(f"당길 수 없는 문단 {len(widened)}개는 자간을 조금 늘려(+{min(widened)}~+{max(widened)}%) "
                              "빈칸이 덜 벌어지게 했습니다.")
        loose = []
        for p, box_w in self.text_boxes():
            if self.st.para.get(p.get("paraPrIDRef"), {}).get("align") not in ("JUSTIFY", "DISTRIBUTE"):
                continue  # 가운데·왼쪽 정렬 줄은 낱말 사이가 벌어지지 않음
            _, lines = self.lay.para_lines(p, box_w)
            if any(used / avail < LOOSE for _, _, used, avail in lines[:-1]):
                text = para_text(p)
                loose.append(text[head_length(text):].replace("⎵", " ").strip()[:14])
        if loose:
            self.notes.append(f"그래도 빈칸이 크게 벌어지는 줄이 남은 문단 {len(loose)}개 — 긴 낱말이 다음 줄로 넘어감. "
                              "낱말을 줄이거나 순서를 바꾸거나 두 줄로 나누면 좋아집니다: "
                              + ", ".join(f"‘{t}…’" for t in loose))
        self.cut_hints = []
        self.arrow_breaks()
        if getattr(self, "push", True):
            self.push_down()
        self.report_cut_hints()
        # 내리기로도 못 고친(끝 줄 바로 위에 나눌 빈칸이 없는 등) 문단은 글을 고쳐야 하므로 '고쳐야 함'으로 알린다
        short = []
        for p, box_w in self.text_boxes():
            if self.st.para.get(p.get("paraPrIDRef"), {}).get("align") not in ("JUSTIFY", "DISTRIBUTE", "LEFT"):
                continue
            chs, lines = self.lay.para_lines(p, box_w)
            if len(lines) < 2:
                continue
            s, e, used, _ = lines[-1]
            if used < lines[0][3] * SHORT_LAST and len("".join(c[0] for c in chs[s:e]).split()) <= 2:
                text = para_text(p)
                short.append(text[head_length(text):].replace("⎵", " ").strip()[:14])
        if short:
            self.notes.append(f"끝 줄에 한두 낱말만 남은 문단 {len(short)}개 — 자간으로도 당기지 못했습니다. 글을 조금 줄이거나 "
                              "낱말 순서를 바꾸면 한 줄로 들어갑니다: " + ", ".join(f"‘{t}…’" for t in short))

    def _cut_hint(self, p, box_w, lines):
        """두 줄 문단이 몇 자만 줄이면(자간 -18%까지 줄인 상태에서) 한 줄에 들어가는지 재어, 낱말 하나(CUT_MAX자 안)로
        되면 '한 줄 줄이기 후보'로 모은다 — 줄을 내리면 윗줄이 휑해지므로 없어도 되는 낱말 하나를 빼는 편이 낫다
        (사용자 원칙 2026-11-01: '인간은 컨텍스트로 이해할 수 있다'). 낱말을 고르는 것은 글을 쓰는 쪽(Claude)이 한다."""
        if len(lines) != 2:
            return
        chs = self.lay.chars(p, delta=FLOOR, floor=FLOOR)
        head = head_length(para_text(p))
        total = sum(c[1] for c in chs if c[0] != NL)
        need = total - lines[0][3] * SLACK
        body = [c[1] for c in chs[head:] if c[0] not in (" ", NL, "⎵", "⍽")]
        if need <= 0 or not body:
            return
        n = int(need / (sum(body) / len(body))) + 1
        if n <= CUT_MAX:
            body_text = split_marker(para_text(p))[2] or para_text(p)
            self.cut_hints.append((re.sub(r"\s+", " ", body_text.replace("⎵", " ").replace("⍽", " ")).strip()[:22], n))

    def report_cut_hints(self):
        if self.cut_hints:
            self.notes.append(f"한 줄 줄이기 후보 {len(self.cut_hints)}개 — 없어도 되는 낱말 하나(조사·꾸밈말·겹친 말)를 빼면 "
                              "한 줄에 들어갑니다(뜻·숫자·이름은 그대로, 지금은 줄을 내려 둠): "
                              + ", ".join(f"‘{t}…’(약 {n}자)" for t, n in self.cut_hints))

    def arrow_breaks(self):
        """화살표(⇒ → ➜)가 든 두 줄 문단: 한 줄에 있으면 좋고(올리기는 앞 단계에서 해 봄), 그래도 화살표 뒤 내용이 줄 끝에서
        갈라지면 화살표부터 끝까지를 통째로 다음 줄로 내린다(사용자 원칙 2026-11-01). 내린 내용이 한 줄에 다 들어갈 때만
        (아니면 그대로 두고 push_down이 끝 줄을 맞춤). 머리 기호·이름표 안의 화살표는 보지 않는다.
        내린 내용이 한 줄에 안 들어가 화살표 뒤 내용이 둘째 줄로 이어지면 둘째 줄부터를 화살표 뒤 첫 글자 밑에 맞춘다
        (사용자 수정본·결정 2026-11-01 — 화살표가 첫 줄 앞쪽 ARROW_HANG_AT 안에 있고 줄 수가 늘지 않을 때)."""
        done = hung = 0
        for p, box_w in self.text_boxes():
            if not self.checked(p):
                continue
            if self.st.para.get(p.get("paraPrIDRef"), {}).get("align") not in ("JUSTIFY", "DISTRIBUTE", "LEFT"):
                continue
            chs, lines = self.lay.para_lines(p, box_w)
            if len(lines) < 2 or any(c[0] == "\n" for c in chs):
                continue
            s1, e1, _, _ = lines[0]
            head = head_length(para_text(p))
            arrows = [i for i in range(s1, e1) if chs[i][0] in ARROWS and i > head]
            if not arrows:
                continue
            a = arrows[-1]  # 첫 줄의 마지막 화살표 — 그 뒤 내용이 둘째 줄로 갈라짐
            if a == 0 or chs[a - 1][0] != " ":
                continue
            saved = [(r, r.get("charPrIDRef"), copy.deepcopy(list(r))) for r in para_runs(p)]

            def restore(saved=saved):
                for r, cid, kids in saved:
                    for ch in list(r):
                        r.remove(ch)
                    for k in kids:
                        r.append(k)
                    r.set("charPrIDRef", cid)

            if len(lines) == 2:
                self._cut_hint(p, box_w, lines)
                self._insert_breaks(p, [(0, 0, "space", a)])
                _, l2 = self.lay.para_lines(p, box_w)
                if len(l2) == 2:
                    done += 1
                    continue
                restore()  # 화살표 내용이 한 줄에 다 안 들어감 → 되돌리고 화살표 뒤 글자 밑에 맞춰 봄
            hung += self._arrow_hang(p, box_w, a, len(lines), restore)
        if done:
            self.notes.append(f"화살표 뒤 내용이 줄 끝에서 갈라지던 문단 {done}개는 화살표부터 끝까지를 다음 줄로 내렸습니다.")
        if hung:
            self.notes.append(f"화살표 뒤 내용이 다음 줄로 이어지는 문단 {hung}개는 둘째 줄부터를 화살표 뒤 첫 글자 밑에 맞췄습니다.")
        self.connector_breaks()

    def connector_breaks(self):
        """본문 문단의 줄 끝에 연결어·연결 기호('+'·'및'·'또는'·'='·'×')가 남으면 그 앞에서 줄을 바꿔 다음 줄 첫머리로
        내린다(사용자 원칙 2026-11-01: '+나 및 같은 연결어·연결 기호는 아래로 내리는 게 더 이해하기 쉬움'). 줄 수가 늘면
        그대로 둔다. 한글은 줄 바꿈 바로 앞 줄을 벌리지 않으므로 위 줄은 보통 간격으로 조금 짧게 끝난다."""
        done = 0
        for p, box_w in self.text_boxes():
            if self.st.para.get(p.get("paraPrIDRef"), {}).get("align") not in ("JUSTIFY", "DISTRIBUTE", "LEFT"):
                continue
            for _ in range(4):
                chs, lines = self.lay.para_lines(p, box_w)
                if len(lines) < 2:
                    break
                hit = None
                for s0, e0, _, _ in lines[:-1]:
                    seg = "".join(c[0] for c in chs[s0:e0]).rstrip()
                    words = seg.split(" ")
                    if len(words) >= 3 and words[-1] in CONNECTORS:
                        hit = s0 + len(seg) - len(words[-1])  # 연결어 첫 글자 자리
                        break
                if hit is None or chs[hit - 1][0] != " ":
                    break
                saved = [(r, r.get("charPrIDRef"), copy.deepcopy(list(r))) for r in para_runs(p)]
                self._insert_breaks(p, [(0, 0, "space", hit)])
                _, l2 = self.lay.para_lines(p, box_w)
                if len(l2) > len(lines):
                    for r, cid, kids in saved:
                        for ch in list(r):
                            r.remove(ch)
                        for k in kids:
                            r.append(k)
                        r.set("charPrIDRef", cid)
                    break
                done += 1
        if done:
            self.notes.append(f"줄 끝에 남던 연결어·연결 기호(+·및·= 등) {done}곳은 다음 줄 첫머리로 내렸습니다.")

    def _arrow_hang(self, p, box_w, a, n_lines, restore):
        """화살표(글자 위치 a) 뒤 첫 글자 밑에 둘째 줄부터를 맞춘다: 그 앞 보통 빈칸은 고정폭 빈칸으로(첫 줄이 양쪽 정렬로
        늘어나도 화살표 뒤 글자 위치가 변하지 않게 — 쌍점·이름표 맞추기와 같은 방법), 내어쓰기 = 그 글자까지의 폭.
        화살표가 첫 줄 앞쪽 ARROW_HANG_AT 안에 있고 줄 수가 늘지 않을 때만. 맞췄으면 1."""
        chs = self.lay.chars(p)
        k = a + 1
        while k < len(chs) and chs[k][0] in " ⎵⍽":
            k += 1
        if k >= len(chs) or sum(c[1] for c in chs[:k]) > box_w * ARROW_HANG_AT:
            return 0
        pid0 = p.get("paraPrIDRef")
        pos = 0
        for r in para_runs(p):
            t = run_text(r)
            start, pos = pos, pos + len(t)
            if start >= k:
                break
            cut = min(len(t), k - start)
            new = t[:cut].replace(" ", FW * self.b._fw_per_space(r)) + t[cut:]
            if new != t and len(r) == 1:
                set_run_text(r, new, self.b.tab_proto)
        text = para_text(p)
        k2 = next((i + 1 for i in range(len(text) - 1, -1, -1) if text[i] in ARROWS), 0)
        while k2 < len(text) and text[k2] in " ⎵⍽":
            k2 += 1
        hang = sum(c[1] for c in self.lay.chars(p)[:k2])
        p.set("paraPrIDRef", self.b.hedit.para_hang(pid0, hang))
        _, l2 = self.lay.para_lines(p, box_w)
        if len(l2) > n_lines:
            restore()
            p.set("paraPrIDRef", pid0)
            return 0
        return 1

    def push_down(self):
        """끝 줄에 한두 낱말(두서너 자)만 남은 문단: 자간으로 올리기(fit_lines·widen_sparse)가 안 되면, 바로 위 줄의 낱말 경계에
        줄 바꿈을 넣어 끝 줄이 PUSH_MIN~PUSH_MAX자가 되게 '시원하게 내려' 두 줄 균형을 맞춘다(사용자 원칙 2026-11-01:
        '한 단어가 내려올 때는 올려 보고, 글자가 겹칠 것 같으면 7~10자 정도 내려서 균형'). 한글은 양쪽 정렬 문단이라도
        줄 바꿈 바로 앞 줄은 벌리지 않는다(실측) — 위 줄은 보통 간격으로 조금 짧게 끝난다.
        머리 기호·이름표 뒤 고정폭 빈칸·묶음 빈칸에서는 나누지 않는다(둘째 줄은 문단 내어쓰기대로 이름표 뒤 글에 맞춤)."""
        done = []
        for p, box_w in self.text_boxes():
            if not self.checked(p):
                continue
            if self.st.para.get(p.get("paraPrIDRef"), {}).get("align") not in ("JUSTIFY", "DISTRIBUTE", "LEFT"):
                continue
            chs, lines = self.lay.para_lines(p, box_w)
            if len(lines) < 2:
                continue
            s, e, used, _ = lines[-1]
            last = "".join(c[0] for c in chs[s:e])
            if not (used < lines[0][3] * SHORT_LAST and len(last.split()) <= 2):
                continue
            ps, pe, _, _ = lines[-2]
            head = head_length(para_text(p))
            nonspace = len(last.replace(" ", "").replace("⎵", ""))
            best = None
            for i in range(pe - 1, ps, -1):  # 위 줄 안의 보통 빈칸 자리(뒤에서부터)
                if chs[i][0] != " " or i <= head or chs[i - 1][0] in (" ", "⎵", "⍽"):
                    continue
                moved = "".join(c[0] for c in chs[i + 1:pe]).replace(" ", "").replace("⎵", "")
                n = len(moved) + nonspace
                if n > PUSH_MAX + 4:
                    break
                score = 0 if PUSH_MIN <= n <= PUSH_MAX else min(abs(n - PUSH_MIN), abs(n - PUSH_MAX))
                if best is None or score < best[0]:
                    best = (score, i + 1, n)
            if best is None or best[0] > 3:
                continue
            idx = best[1]
            self._cut_hint(p, box_w, lines)
            saved = [(r, r.get("charPrIDRef"), copy.deepcopy(list(r))) for r in para_runs(p)]
            self._insert_breaks(p, [(0, 0, "space", idx)])
            _, l2 = self.lay.para_lines(p, box_w)
            if len(l2) != len(lines):  # 줄 수가 바뀌면(위 줄이 넘침 등) 되돌린다
                for r, cid, kids in saved:
                    for ch in list(r):
                        r.remove(ch)
                    for k in kids:
                        r.append(k)
                    r.set("charPrIDRef", cid)
                continue
            done.append(best[2])
        if done:
            self.notes.append(f"자간으로 올릴 수 없던 짧은 끝 줄(한두 낱말) {len(done)}곳은 위 줄 낱말을 함께 내려 "
                              f"끝 줄을 {min(done)}~{max(done)}자로 균형을 맞췄습니다(줄 바꿈 — 위 줄은 조금 짧게 끝남).")

    # ------------------------------------------------------------ 표 맞춤
    def _cell_margin(self, tbl, tc):
        if tc.get("hasMargin") == "1":
            cm = tc.find(T("hp:cellMargin"))
        else:
            cm = tbl.find(T("hp:inMargin"))
        if cm is None:
            return 1020
        return int(cm.get("left", "510")) + int(cm.get("right", "510"))

    def _natural(self, tbl, tc, fits=None):
        """칸 글을 줄 바꿈 없이 한 줄로 쓸 때 필요한 칸 너비. fits(지금 칸 너비)를 주면 이미 '한 줄로 입력'인 문단이
        그 너비를 NEAR 안에서만 넘을 때는 넘치지 않는 것으로 본다(만든 문서를 다시 다듬을 때 열을 다시 나누지 않게 —
        되풀이해도 같게, 2026-11-04)."""
        need = 0.0
        pad = self._cell_margin(tbl, tc) + 150
        for cp in cell_paras(tc):
            pp = self.st.para.get(cp.get("paraPrIDRef"), {})
            for line in split_lines(self.lay.chars(cp)):
                w = (sum(c[1] for c in line) + pp.get("left", 0) + pp.get("right", 0)) * 1.02 + pad
                if fits is not None and pp.get("squeeze") and fits < w <= fits * NEAR:
                    w = fits
                need = max(need, w)
        # 어림 오차 여유: 글 폭의 2% + 0.5mm(맑은 고딕 칸이 어림과 1~2% 달라 끝에서 줄이 넘어간 실측, 2026-10-31)
        return need

    def _cell_words(self, tbl, tc, where=False):
        """(칸 여백 + 어림 여유, [(조각 목록, 문단 좌우 여백, 한 줄로 입력인가, 글자 수)…]) — 칸 안 줄마다.
        조각 = (폭, 앞 빈칸 폭, 앞 경계 'space'|'dot'|'first'[, 문단 안 글자 번호]). 가운데점(·)으로 이은 긴 이름은
        점 뒤에서도 나눌 수 있는 조각으로 본다('대구정책연구원·성과평가위원회' → 점 뒤에서 줄 바꿈, _balance_breaks)."""
        return self._cell_margin(tbl, tc) + 150, [x for cp in cell_paras(tc) for x in self._para_pieces(cp, where)]

    def _para_pieces(self, cp, where=False):
        """칸 안 문단 하나의 줄마다 (조각 목록, 문단 좌우 여백, 한 줄로 입력인가, 글자 수) — _cell_words 참고."""
        paras = []
        pp = self.st.para.get(cp.get("paraPrIDRef"), {})
        extra = pp.get("left", 0) + pp.get("right", 0) + max(0, -pp.get("intent", 0))  # 내어쓴 둘째 줄은 그만큼 좁음
        pos = 0
        for line in split_lines(self.lay.chars(cp)):
            pieces, cur, gap, kind, start = [], 0.0, 0.0, "first", pos
            for k, ch in enumerate(line):
                if ch[0] in (" ", "　"):
                    if cur:
                        pieces.append((cur, gap, kind, start))
                        cur, gap = 0.0, 0.0
                    gap += ch[1]
                    kind, start = "space", pos + k + 1
                else:
                    if not cur and kind == "space" and ch[0] in UNIT_START:
                        kind = "unit"  # '+ 위법사항'·'⇒ 결론'처럼 뜻 단위로 시작하는 낱말 — 그 앞에서 나누면 보기 좋음
                    if ch[0] == "(" and cur and self._long_paren(line, k):
                        # 낱말에 붙은 긴 괄호 '단축(’25년 19분47초 기준)'은 괄호 앞에서도 나눌 수 있음(뜻 단위, 사용자 수정본 2026-11-01)
                        pieces.append((cur, gap, kind, start))
                        cur, gap, kind, start = 0.0, 0.0, "paren", pos + k
                    cur += ch[1]
                    if ch[0] in DOTS and k + 1 < len(line) and line[k + 1][0] not in (" ", "　"):
                        pieces.append((cur, gap, kind, start))
                        cur, gap, kind, start = 0.0, 0.0, "dot", pos + k + 1
            if cur:
                pieces.append((cur, gap, kind, start))
            pos += len(line) + 1
            if not where:
                pieces = [p[:3] for p in pieces]
            # '· 항목' 줄은 글자 수를 음수로 표시 — _borrow_widths가 짧은 항목이 꺾이지 않게 옆 열 폭을 빌릴 때 씀
            item = bool(DOT_ITEM_RE.match("".join(ch[0] for ch in line[:4])))
            paras.append((pieces, extra, pp.get("squeeze", False), -len(line) if item else len(line)))
        return paras

    @staticmethod
    def _long_paren(line, k):
        """line[k]의 '('부터 닫는 ')'까지 안 글자(빈칸 뺀)가 PAREN_SPLIT자 이상인가."""
        n = 0
        for ch in line[k + 1:]:
            if ch[0] == ")":
                return n >= PAREN_SPLIT
            if ch[0] not in (" ", "　"):
                n += 1
        return False

    @staticmethod
    def _wrap(pieces, avail):
        """조각을 폭 avail에 나눠 쓴 (줄 수, 글자 단위로 끊긴 횟수, 가운데점 뒤에서 나눈 자리[조각],
        새 줄이 시작된 자리[조각])."""
        count, x, cuts, dots, breaks = 1, 0.0, 0, [], []
        for pc in pieces:
            wd, gap, kind = pc[:3]
            if x and x + gap + wd > avail:
                count, x = count + 1, wd
                breaks.append(pc)
                if kind in ("dot", "paren"):
                    dots.append(pc)
            else:
                x = x + gap + wd if x else wd
            while x > avail > 0:  # 칸보다 긴 낱말은 한글이 글자 단위로 끊음
                count, x, cuts = count + 1, x - avail, cuts + 1
        return count, cuts, dots, breaks

    @classmethod
    def _count_lines(cls, margin, paras, w, trust_squeeze=False):
        """칸 너비 w에서 (줄 수, 낱말 가운데서 끊긴 횟수, 가운데점 뒤에서 나눈 횟수, 짧은 글이 넘어간 줄 수).
        한 줄 폭을 NEAR 안에서만 넘는 줄은 '한 줄로 입력'(_squeeze_near)으로 한 줄에 들어가므로 한 줄로 센다.
        trust_squeeze: 이번에 '한 줄로 입력'을 정한 뒤의 마지막 검사에서만 그 표시를 한 줄로 믿는다(칸 너비를 정할 때는
        믿지 않음 — 되풀이해도 같게)."""
        total_lines, cuts, dots, short = 0, 0, 0, 0
        for pieces, extra, squeeze, nchars in paras:
            if trust_squeeze and squeeze and pieces:
                total_lines += 1
                continue
            avail = (w - margin - extra) / 1.02
            one = sum(p[0] + (p[1] if k else 0) for k, p in enumerate(pieces))
            # '한 줄로 입력' 표시는 세지 않는다 — 이 칸 너비에서 NEAR 안일 때만 한 줄(되풀이해도 같게: 표시를 믿고 한 줄로 세면
            # 다시 맞출 때 그 열을 더 좁혀 넘침이 커짐, 2026-11-04 실측)
            if not pieces or one <= avail * NEAR:
                total_lines += 1
                continue
            count, cut, dot, _ = cls._wrap(pieces, avail)
            total_lines += count
            cuts += cut
            dots += len(dot)
            if 0 <= nchars <= SHORT_LEN:  # '· 항목' 줄(음수)은 _borrow_widths가 맡음
                short += count - 1
        return total_lines, cuts, dots, short

    def _balance_breaks(self, tbl):
        """칸 너비를 정한 뒤 두 줄 이상이 되는 칸 글은, 줄 수는 그대로 두고 윗줄·아랫줄 길이가 고르게 되는 자리에서
        줄을 바꾼다(다음 줄에 두어 글자만 내려오는 것보다 균형이 맞는 것이 보기 좋음 — 사용자 원칙 2026-11-01).
        가장 좁은 폭(같은 줄 수로 들어가는)을 찾아 그 폭으로 나눈 자리에 줄 바꿈을 넣는다 — 빈칸 자리면 빈칸을 줄 바꿈으로,
        가운데점 자리면 점 뒤에(한글은 점 뒤에서 스스로 나누지 않고 긴 이름을 글자 단위로 끊음).
        (고르게 나눈 문단 수, 가운데점 뒤에서 나눈 수)."""
        balanced, dots = 0, 0
        grid = table_grid(tbl)
        cap = self._caption_content(tbl, grid)  # 제목 걸친 상자의 인용문(조례 조문 등)은 줄을 채운 채 왼쪽 정렬(_box_left)
        for r, c, rs, cs, tc in grid:
            if tc is cap:
                continue
            w = int(tc.find(T("hp:cellSz")).get("width", "0"))
            margin = self._cell_margin(tbl, tc) + 150
            for cp in cell_paras(tc):
                if self.st.para.get(cp.get("paraPrIDRef"), {}).get("align") in ("JUSTIFY", "DISTRIBUTE"):
                    continue  # 양쪽 정렬 글(요약·개요 상자)은 줄을 고르게 나누면 낱말 사이가 벌어짐 — 줄을 채움
                breaks = []
                for pieces, extra, squeeze, _ in self._para_pieces(cp, where=True):
                    avail = (w - margin - extra) / 1.02
                    one = sum(p[0] + (p[1] if k else 0) for k, p in enumerate(pieces))
                    if not pieces or squeeze or one <= avail * NEAR:
                        continue
                    avail *= CELL_SAFE  # 맑은 고딕 어림이 1~3% 모자라 꽉 찬 줄 끝 낱말이 한글에서 넘어감 — 여유를 둔 폭으로 나눔
                    n, cut, _, brk = self._wrap(pieces, avail)
                    unit = self._unit_break(cp, pieces, avail) if n == 2 and not cut else None
                    if unit is not None:  # 두 줄이면 괄호·'+'·화살표 앞(뜻 단위)에서 나눔(사용자 수정본 2026-11-01)
                        breaks.append(unit)
                        continue
                    if not cut and len(brk) == n - 1:
                        brk = self._connector_down(cp, pieces, brk, avail)
                    if not cut:  # 칸보다 긴 낱말이 없을 때만 폭을 좁혀 고르게(있으면 그 자리 그대로)
                        lo, hi = max(p[0] for p in pieces), avail
                        for _ in range(24):
                            mid = (lo + hi) / 2
                            n2, cut2, _, _ = self._wrap(pieces, mid)
                            if n2 <= n and not cut2:
                                hi = mid
                            else:
                                lo = mid
                        brk = self._connector_down(cp, pieces, self._wrap(pieces, hi)[3], avail)
                    breaks += brk
                if not breaks:
                    continue
                balanced += 1
                dots += sum(1 for pc in breaks if pc[2] == "dot")
                self._insert_breaks(cp, breaks)
        return balanced, dots

    def _connector_down(self, cp, pieces, brk, avail):
        """줄 끝에 연결어·연결 기호('+'·'및'·'또는'·'='·'×')가 남으면 그 앞에서 줄을 바꿔 다음 줄 첫머리로 내린다
        (사용자 원칙 2026-11-01 — 아래로 내리는 것이 읽기 쉬움). 내린 줄이 넘치면 그 자리는 그대로."""
        chs = self.lay.chars(cp)
        text = "".join(c[0] for c in chs)
        idx = {id(pc): k for k, pc in enumerate(pieces)}
        starts = [idx.get(id(pc), -1) for pc in brk] + [len(pieces)]
        out = []
        for n, pc in enumerate(brk):
            k = idx.get(id(pc))
            if k is None or k < 2 or len(pc) < 4:
                out.append(pc)
                continue
            prev = pieces[k - 1]
            word = text[prev[3]:pc[3]].strip()
            line = pieces[k - 1:starts[n + 1]]
            width = sum(q[0] + (q[1] if j else 0) for j, q in enumerate(line))
            if word in CONNECTORS and prev[2] in ("space", "unit") and width <= avail:
                out.append(prev)
            else:
                out.append(pc)
        return out

    def _unit_break(self, cp, pieces, avail):
        """두 줄이 되는 칸 글을 뜻 단위로 나눌 자리: 빈칸 뒤 조각이 괄호·'+'·화살표로 시작하고(‘평균 대기시간 단축 /
        (’25년 19분47초 기준)’, ‘105개 전수 점검 / + 위법사항 조치완료율’) 앞뒤가 각각 한 줄에 들어가는 자리 가운데
        두 줄 길이가 가장 고른 곳의 조각. 없으면 None."""
        return self._unit_split(pieces, avail)

    @staticmethod
    def _unit_split(pieces, avail):
        """앞뒤가 각각 한 줄(avail)에 들어가는 뜻 단위 자리(조각 종류 unit·paren) 가운데 두 줄 길이가 가장 고른 조각."""
        best = None
        for j in range(1, len(pieces)):
            pc = pieces[j]
            if pc[2] not in ("unit", "paren"):
                continue
            a = sum(p[0] + (p[1] if k else 0) for k, p in enumerate(pieces[:j]))
            b = sum(p[0] + (p[1] if k else 0) for k, p in enumerate(pieces[j:]))
            if a > avail or b > avail:
                continue
            if best is None or abs(a - b) < best[0]:
                best = (abs(a - b), pc)
        return best[1] if best else None

    @staticmethod
    def _insert_breaks(cp, breaks):
        """문단 글의 조각 시작 자리마다 줄 바꿈을 넣는다(앞 빈칸은 줄 바꿈으로 바꿈). 조각 = _para_pieces(where=True) 꼴."""
        runs = para_runs(cp)
        texts = [list(run_text(r)) for r in runs]
        where = [(ri, li) for ri, t in enumerate(texts) for li in range(len(t))]
        flat = [ch for t in texts for ch in t]
        changed = set()
        for pc in sorted(breaks, key=lambda p: p[3], reverse=True):
            b = pc[3]
            a = b
            while a > 0 and flat[a - 1] in (" ", "　"):
                a -= 1
            rb, lb = where[b]
            for g in range(b - 1, a - 1, -1):  # 앞 빈칸 지우기(같은 조각 안에서 뒤에서부터)
                ri, li = where[g]
                del texts[ri][li]
                changed.add(ri)
                if ri == rb:
                    lb -= 1
            texts[rb].insert(lb, "\n")
            changed.add(rb)
        for ri in changed:
            set_run_text(runs[ri], "".join(texts[ri]))

    def _balance_widths(self, tbl, grid, n, total):
        """내용이 표 폭보다 길 때 칸 너비를 정한다: 표 전체 줄 수(줄마다 가장 많은 칸의 줄 수의 합)가 가장 적게.
        칸마다 가장 긴 낱말이 들어갈 폭에서 시작해, 남는 폭을 '1mm당 줄이 가장 많이 줄어드는 칸'에 차례로 준다.
        (긴 칸끼리 내용 길이 비율로 나누던 방식은 중간 길이 칸이 지나치게 좁아짐 — 2026-10-31 시험 문서 참고 표)"""
        cells = [(r, c) + self._cell_words(tbl, tc) for r, c, rs, cs, tc in grid if cs == 1]
        if not cells:
            return None
        heads = {r for r, c, rs, cs, tc in grid if tc.get("header") == "1"}
        cache = {}

        def lines(k, w):
            """_count_lines 값(줄 수, 끊김, 가운데점 나눔, 짧은 글 넘김)."""
            key = (k, int(w // 50))
            if key not in cache:
                cache[key] = self._count_lines(cells[k][2], cells[k][3], w)
            return cache[key]

        def score(ws):
            """(표 높이에 해당하는 줄 수 + 낱말 끊김 벌점, 모든 칸 줄 수). 낱말이 글자 단위로 끊기면 세로로 쌓여 보기 나쁨
            (사용자 원칙: 단어로 끊기) — 끊김 하나를 줄 CUT_COST개로 친다."""
            rows, all_lines, extra, cuts, dots, short = {}, 0, 0, 0, 0, 0
            for k, (r, c, _, paras) in enumerate(cells):
                l, cut, dot, sh = lines(k, ws[c])
                rows[r] = max(rows.get(r, 0), l)
                all_lines += l
                extra += l - len(paras)
                cuts += cut
                dots += dot
                short += sh
            return (sum(v * (HEAD_COST if r in heads else 1) for r, v in rows.items()) + CELL_COST * extra
                    + SHORT_COST * short + CUT_COST * cuts + DOT_COST * dots, all_lines)

        mins = [self._cell_margin(tbl, grid[0][4]) + 600] * n  # 아주 짧은 칸도 여백 + 약 2mm
        for r, c, margin, paras in cells:
            longest = max((max(p[0] for p in pcs) for pcs, _, _, _ in paras if pcs), default=0)
            # 가장 긴 낱말이 들어갈 폭에서 시작하되 표 폭의 18%를 넘지 않게(더 긴 낱말은 칸 안에서 끊김)
            mins[c] = max(mins[c], min(longest * 1.02 + margin, total * 0.18))
        if sum(mins) > total:
            mins = [m * total / sum(mins) for m in mins]
        ws, slack, step = list(mins), total - sum(mins), 283.0
        cur = score(ws)
        while slack >= step:
            best = None
            for c in range(n):
                for mult in (1, 2, 4, 8, 16, 32):
                    inc = step * mult
                    if inc > slack:
                        break
                    trial = list(ws)
                    trial[c] += inc
                    sc = score(trial)
                    gain = ((cur[0] - sc[0]) * 1000 + (cur[1] - sc[1])) / mult
                    if gain > 0 and (best is None or gain > best[0]):
                        best = (gain, c, inc, sc)
            if best is None:
                break
            ws[best[1]] += best[2]
            slack -= best[2]
            cur = best[3]
        if slack > 0:  # 더 줄일 수 없으면 남는 폭은 긴 칸(줄이 넘어가는 칸)에 나눠 줌
            need = [0.0] * n
            for k, (r, c, _, _) in enumerate(cells):
                need[c] += max(0, lines(k, ws[c])[0] - 1)
            weight = need if sum(need) else [1.0] * n
            for c in range(n):
                ws[c] += slack * weight[c] / sum(weight)
        return ws

    def _borrow_widths(self, tbl):
        """옆 열의 공간을 줄여 표 전체를 고르게(사용자 원칙 2026-11-01 — 참고5 수정본: '품질평가상 약점' 열을 4mm 줄이고
        자간 -9%로 줄 수를 지킨 뒤 그 폭을 '2027 결과지표 예시' 열에 줘서 '· 지적사항 시정완료율'이 한 줄에 들어감).
        두 열 사이에서 BORROW_STEP씩 폭을 옮겨 보며 (표 전체 줄 수, 꺾인 '· 항목'(뜻 단위 두 줄은 괜찮음)·짧은 값 수,
        모든 칸 줄 수, 자간을 줄인 칸 수 — 한 줄 더 꺾이기보다 자간을 조금 줄이는 쪽)가 좋아질 때만 옮긴다. 폭을 내준 칸은 자간을 TIGHT_SP 줄여야 줄 수가 지켜지면
        그만큼 줄인다. 옮겼으면 1."""
        info = self._borrow_cells(tbl)
        if info is None:
            return 0
        grid, n, cells, heads = info
        ws = [0] * n
        for r, c, rs, cs, tc in grid:
            ws[c] = ws[c] or int(tc.find(T("hp:cellSz")).get("width", "0"))
        if not all(ws):
            return 0

        def score(ws):
            return self._borrow_score(cells, heads, ws)

        mins = [0] * n
        for r, c, tc, margin, paras in cells:
            longest = max((max(p[0] for p in pcs) for pcs, _, _, _ in paras if pcs), default=0)
            mins[c] = max(mins[c], longest * 1.02 + margin, margin + 600)
            for pcs, extra, _, nchars in paras:  # 짧은 값('확보 추정'·'12월')이 든 칸은 한 줄 폭 밑으로 줄이지 않음
                if pcs and 0 <= nchars <= SHORT_LEN:
                    one = sum(p[0] + (p[1] if k else 0) for k, p in enumerate(pcs))
                    mins[c] = max(mins[c], min(one * 1.02 + margin + extra, ws[c]))
        best, how = score(ws)
        start = best
        for _ in range(60):
            move = None
            for a in range(n):
                for b in range(n):
                    if a == b:
                        continue
                    for k in (1, 2, 4, 8, 16):  # 큰 걸음도 — 몇 mm만 옮겨서는 나아지지 않는 곳에 갇히지 않게
                        d = BORROW_STEP * k
                        if ws[b] - d < mins[b]:
                            continue
                        trial = list(ws)
                        trial[a] += d
                        trial[b] -= d
                        sc, h = score(trial)
                        if sc < best and (move is None or sc < move[0]):
                            move = (sc, trial, h)
            if move is None:
                break
            best, ws, how = move
        if best == start:
            return 0
        self._set_widths(tbl, grid, ws, sum(ws))
        for tc, tight in how.items():
            if not tight:
                continue
            for cp in cell_paras(tc):
                for r in para_runs(cp):
                    if r.find(T("hp:t")) is None:
                        continue
                    cid = r.get("charPrIDRef")
                    sp = self.st.char.get(cid, {}).get("spacing", 0)
                    r.set("charPrIDRef", self.b.hedit.char_spacing(cid, max(-50, sp + TIGHT_SP)))
        return 1

    def _borrow_cells(self, tbl):
        """_borrow_widths·_borrow_score가 보는 표: 머리 줄이 있는 자료 표이고 두 열 이상이며 합친 칸이 없을 때
        (칸 표, 열 수, 칸 목록 (줄, 열, 칸, 여백, 조각 줄들), 머리 줄 번호들). 아니면 None."""
        if not self._is_data_table(tbl):
            return None
        grid = table_grid(tbl)
        n = int(tbl.get("colCnt", "1"))
        if n < 2 or any(rs > 1 or cs > 1 for _, _, rs, cs, _ in grid):
            return None
        cells = [(r, c, tc) + self._cell_words(tbl, tc) for r, c, rs, cs, tc in grid]
        heads = {r for r, c, rs, cs, tc in grid if tc.get("header") == "1"}
        return grid, n, cells, heads

    def _borrow_score(self, cells, heads, ws):
        """폭 빌리기의 점수 ((표 전체 줄 수, 꺾인 '· 항목'·짧은 값 수, 모든 칸 줄 수, 자간을 줄인 칸 수), 칸마다 자간을
        줄였는가) — 작을수록 좋다. 열 나누기(_layout_widths)도 '지금 너비를 바꿀 만한가'를 이 점수로 가린다
        (두 단계가 다른 점수를 쓰면 다듬을 때마다 번갈아 바뀜, 2026-11-04)."""
        def cell(margin, paras, w, f):
            lines = bad = 0
            for pieces, extra, squeeze, nchars in paras:
                avail = (w - margin - extra) / 1.02 * f * BORROW_SAFE
                one = sum(p[0] + (p[1] if k else 0) for k, p in enumerate(pieces))
                if not pieces or one <= avail * (NEAR if f == 1.0 else 1.0):  # '한 줄로 입력' 표시는 세지 않음(_count_lines와 같게)
                    lines += 1
                    continue
                cnt, cut, _, _ = self._wrap(pieces, avail)
                lines += cnt + CUT_COST * cut
                # '· 항목'이 꺾이면 나쁨(뜻 단위 자리 — 괄호·'+' 앞 — 에서 두 줄로 나뉘면 괜찮음), 짧은 값('확보 추정')이 꺾여도 나쁨
                if nchars < 0 and not (cnt == 2 and not cut and self._unit_split(pieces, avail) is not None):
                    bad += 1
                elif 0 <= nchars <= SHORT_LEN:
                    bad += 1
            return lines, bad

        rows, bad, tight, total, how = {}, 0, 0, 0, {}
        for r, c, tc, margin, paras in cells:
            plain = cell(margin, paras, ws[c], 1.0)
            tighter = cell(margin, paras, ws[c], TIGHT)
            use = tighter if tighter[:2] < plain[:2] else plain  # 줄 수가 같아도 꺾인 항목이 줄면 자간을 조금 줄임
            how[tc] = use is tighter
            rows[r] = max(rows.get(r, 0), use[0])
            bad += use[1]
            tight += use is tighter
            total += use[0]
        return (sum(v * (HEAD_COST if r in heads else 1) for r, v in rows.items()), bad, total, tight), how

    @staticmethod
    def _fill_widths(nat, total):
        """내용이 표 폭보다 길 때 칸 너비: 짧은 칸부터 내용 너비 그대로(줄 안 넘김) 두고,
        남은 폭은 긴 칸들에 내용 너비 비율로 나눈다(긴 칸만 줄이 넘어감)."""
        width = [0.0] * len(nat)
        remaining, flex = total, list(range(len(nat)))
        for k in sorted(range(len(nat)), key=lambda k: nat[k]):
            if len(flex) > 1 and nat[k] <= remaining / len(flex):
                width[k] = nat[k]
                remaining -= nat[k]
                flex.remove(k)
            else:
                break
        share = sum(nat[k] for k in flex)
        for k in flex:
            width[k] = remaining * nat[k] / share
        return width

    def _layout_widths(self, tbl, grid, n, merged, total, cur):
        """칸 너비 안 (너비 목록 또는 None, 'cols'|'wraps'|None): 칸 글이 모두 한 줄에 들어가면 내용에 맞춰 나누고,
        표 폭보다 길면 줄 수가 가장 적게(_balance_widths). 합친 칸이 있는 표는 그대로 둔다."""
        if merged or n <= 1 or not all(cur):
            return None, None
        scaled = [w * total / sum(cur) for w in cur]
        nat = [0.0] * n
        for r, c, rs, cs, tc in grid:
            nat[c] = max(nat[c], self._natural(tbl, tc, scaled[c]))
        if any(nat[k] > scaled[k] for k in range(n)) and sum(nat) <= total:
            slack = total - sum(nat)
            return [nat[k] + slack * cur[k] / sum(cur) for k in range(n)], "cols"
        if sum(nat) > total:
            ws = self._balance_widths(tbl, grid, n, total) or self._fill_widths(nat, total)
            info = self._borrow_cells(tbl)
            if info is not None:  # 폭 빌리기와 같은 점수로(두 단계가 번갈아 바꾸지 않게)
                now, new = self._borrow_score(info[2], info[3], scaled)[0], self._borrow_score(info[2], info[3], ws)[0]
            else:
                now, new = self._table_score(tbl, grid, scaled), self._table_score(tbl, grid, ws)
            if now <= new:
                return None, None  # 지금 너비가 이미 그만큼 좋으면 그대로(만든 문서를 다시 다듬어도 같게, 2026-11-04)
            return ws, "wraps"
        return None, None

    def _table_score(self, tbl, grid, ws=None, scale=1.0, trust_squeeze=False):
        """다음 줄로 넘어가는 줄 수 + 낱말 끊김 벌점. 줄마다 (가장 많은 칸의 줄 수 − 칸 안 문단 수가 가장 많은 칸의
        문단 수) — 칸에 일부러 나눠 쓴 줄(\\n)은 넘어간 것으로 치지 않는다. ws가 없으면 지금 칸 너비 × scale."""
        rows, base, cuts, dots, extra, short = {}, {}, 0, 0, 0, 0
        heads = {r for r, c, rs, cs, tc in grid if tc.get("header") == "1"}
        for r, c, rs, cs, tc in grid:
            w = sum(ws[c:c + cs]) if ws else int(tc.find(T("hp:cellSz")).get("width", "0")) * scale
            margin, paras = self._cell_words(tbl, tc)
            lines, cut, dot, sh = self._count_lines(margin, paras, w, trust_squeeze)
            if rs == 1:
                rows[r] = max(rows.get(r, 1), lines)
                base[r] = max(base.get(r, 1), len(paras))
            cuts += cut
            dots += dot
            extra += lines - len(paras)
            short += sh
        return (sum((rows[r] - base[r]) * (HEAD_COST if r in heads else 1) for r in rows) + CELL_COST * extra
                + SHORT_COST * short + CUT_COST * cuts + DOT_COST * dots)

    @staticmethod
    def _is_data_table(tbl):
        """글자 크기를 맞출 표: 머리 줄(되풀이 머리 칸)이 있는 여러 줄·여러 칸 표. 제목·요약 상자, 참고 머리표,
        제목 걸친 상자(기본 양식 16번)는 빼고 그 크기를 그대로 둔다."""
        return (int(tbl.get("rowCnt", "1")) > 1 and int(tbl.get("colCnt", "1")) > 1
                and any(tc.get("header") == "1" for tc in tbl.iter(T("hp:tc"))))

    def _table_runs(self, tbl):
        return [r for tc in tbl.iter(T("hp:tc")) for cp in cell_paras(tc) for r in para_runs(cp)
                if r.find(T("hp:t")) is not None]

    def _main_size(self, tbl):
        sizes = [round(self.st.char.get(r.get("charPrIDRef"), {}).get("size", 0)) for r in self._table_runs(tbl)
                 if run_text(r).strip()]
        return max(set(sizes), key=sizes.count) if sizes else 0

    def _fit_font(self, tbl, grid, n, merged, total, cur, width):
        """표 글자 크기: 견본 크기(기본 양식 12pt)에서 1pt씩 TABLE_MIN_PT(10pt)까지 줄여 보며, 다음 줄로 넘어가는 줄이
        가장 적은 크기를 쓴다(같으면 큰 글자). 머리 줄·내용 줄을 같은 만큼 줄인다. (이전 크기, 고른 크기) 또는 None."""
        if not self._is_data_table(tbl):
            return None
        main = self._main_size(tbl)
        if main <= TABLE_MIN_PT:
            return None
        orig = [(r, r.get("charPrIDRef")) for r in self._table_runs(tbl)]

        def resize(d):
            for r, cid in orig:
                r.set("charPrIDRef", cid if d == 0 else self.b.hedit.char_size(cid, d))

        best = None
        for s in range(main, TABLE_MIN_PT - 1, -1):
            resize(s - main)
            ws, _ = self._layout_widths(tbl, grid, n, merged, total, cur)
            sc = self._table_score(tbl, grid, ws, total / width if width else 1.0)
            if best is None or sc < best[0]:
                best = (sc, s)
            if sc == 0:
                break
        resize(best[1] - main)
        return main, best[1]

    def _bullet_cells(self, tbl):
        """칸 안 글머리표 줄('· 항목' — 한 칸에 여러 내용을 넣을 때, 사용자 원칙 2026-11-01): 왼쪽 정렬, 왼쪽을 BULLET_PAD
        띄우고, 둘째 줄은 기호 뒤 글 시작에 맞춘다(내어쓰기 = 기호와 빈칸 폭). 바꾼 문단 수."""
        n = 0
        if tbl.get("rowCnt") == "1" and tbl.get("colCnt") == "1":
            return 0  # 한 칸 상자(요약·표지 개요 상자)의 □·○ 줄은 견본 문단 모양(내어쓰기) 그대로
        for tc in tbl.iter(T("hp:tc")):
            for cp in cell_paras(tc):
                m = BULLET_RE.match(para_text(cp))
                if not m:
                    continue
                hang = sum(c[1] for c in self.lay.chars(cp)[:m.end()])
                pid = self.b.hedit.para_align(cp.get("paraPrIDRef"), "LEFT")
                pid = self.b.hedit.para_margin(pid, "left", BULLET_PAD)
                cp.set("paraPrIDRef", self.b.hedit.para_hang(pid, hang))
                n += 1
        return n

    def _dot_columns(self, tbl):
        """표 열의 '·' 항목을 열 성격에 맞춘다(사용자 수정본·결정 2026-11-01).
        - 이름 열(앞쪽 열, 머리 칸이 NAME_HEAD_RE): 한 칸의 '· 가'·'· 나' 줄 → '가, 나' 한 줄(가운데 정렬 그대로)
        - 그 밖의 열에 '·' 항목이 하나라도 있으면 그 열은 모두 '·': '·'가 없는 칸도 '· '로 시작
          (정렬·내어쓰기는 _bullet_cells가 맞춤)
        (이은 칸 수, '·'를 붙인 칸 수, 한 열에 정보 세 가지인 머리 칸 글 목록)."""
        if not self._is_data_table(tbl):
            return 0, 0, []
        grid = table_grid(tbl)
        heads, cols, three = {}, {}, []
        for r, c, rs, cs, tc in grid:
            if tc.get("header") == "1":
                parts = [l.strip() for cp in cell_paras(tc) for l in para_text(cp).split("\n") if l.strip()]
                if cs == 1:
                    heads[c] = " ".join(parts)
                if len(parts) >= 2 and any(INFO_PAREN_RE.search(l) for l in parts):
                    three.append("/".join(parts))
            elif cs == 1:
                cols.setdefault(c, []).append(tc)
        joined = unified = 0
        for c, tcs in cols.items():
            head = re.sub(r"[\s⎵⍽]+", " ", heads.get(c, "")).strip()
            if c <= 2 and NAME_HEAD_RE.search(head):
                for tc in tcs:
                    items = [cp for cp in cell_paras(tc) if DOT_ITEM_RE.match(para_text(cp))]
                    if len(items) < 2:
                        continue
                    text = ", ".join(DOT_ITEM_RE.sub("", para_text(cp)).replace("\n", " ").strip() for cp in items)
                    runs = [r for r in para_runs(items[0]) if r.find(T("hp:t")) is not None]
                    set_run_text(runs[0], text, self.b.tab_proto)
                    for r in runs[1:]:
                        items[0].remove(r)
                    for cp in items[1:]:
                        cp.getparent().remove(cp)
                    joined += 1
                continue
            texts = [para_text(cp).strip() for tc in tcs for cp in cell_paras(tc) if para_text(cp).strip()]
            if not any(DOT_ITEM_RE.match(t) for t in texts):
                continue  # 그 열에 '·'를 쓰기 시작했으면 그 열은 모두 '·'(사용자 원칙 2026-11-01)
            for tc in tcs:
                cps = [cp for cp in cell_paras(tc) if para_text(cp).strip()]
                if not cps or any(BULLET_RE.match(para_text(cp)) for cp in cps):
                    continue
                if para_text(cps[0]).strip() in ("-", "–", "―", "〃", "″"):
                    continue
                r0 = next((r for r in para_runs(cps[0]) if r.find(T("hp:t")) is not None and run_text(r).strip()), None)
                if r0 is None:
                    continue
                set_run_text(r0, "· " + run_text(r0).lstrip(" "), self.b.tab_proto)
                unified += 1
        return joined, unified, three

    def _cell_pad(self, tbl):
        """표의 각 칸은 위아래·양옆에 약간의 공간을 둔다(사용자 원칙 2026-11-01 — 아주 공간이 없는 경우만 빼고):
        칸 안 여백이 CELL_VPAD·CELL_HPAD보다 작으면 그만큼으로. 한 줄 칸은 줄 높이가 넉넉해 그대로 보이고, 두세 줄 칸
        글이 위아래 칸 선에 붙지 않게 된다. 넓혔으면 1."""
        if not self._is_data_table(tbl):
            return 0
        done = 0
        boxes = [tbl.find(T("hp:inMargin"))] + [tc.find(T("hp:cellMargin")) for tc in tbl.iter(T("hp:tc"))
                                                if tc.get("hasMargin") == "1"]
        for el in boxes:
            if el is None:
                continue
            for k, low in (("top", CELL_VPAD), ("bottom", CELL_VPAD), ("left", CELL_HPAD), ("right", CELL_HPAD)):
                if int(el.get(k, "0")) < low - 1:
                    self.pad_orig.setdefault(tbl, []).append((el, k, el.get(k, "0")))
                    el.set(k, str(int(round(low))))
                    done = 1
        return done

    def relieve_pads(self):
        """칸 여백을 넓혀 □ 묶음이 두 쪽에 걸치게 되면(아주 공간이 없는 경우 — 사용자 원칙 2026-11-01) 그 묶음 안 표의
        칸 여백을 원래대로 되돌리고 쪽 맞춤을 다시 한다."""
        pad = getattr(self, "pad_orig", {})
        if not pad:
            return
        paras = self.paras()
        heads = self.heads()
        self.lay.paginate(paras, self.body_w, self.body_h - SAFETY, heads, BLOCK_GAP)
        if not self.lay.split:
            return
        idx = {p: i for i, p in enumerate(paras)}
        starts = sorted(idx[h] for h in heads)
        undone = 0
        for s0 in self.lay.split:
            e0 = next((h for h in starts if h > s0), len(paras))
            for p in paras[s0:e0]:
                for tbl in para_tables(p):
                    for el, k, v in pad.pop(tbl, []):
                        el.set(k, v)
                        undone += 1
        if undone:
            self.fit_pages()
            self.notes.append("칸 여백을 넓히면 □ 묶음이 두 쪽에 걸치는 곳은 그 묶음 표의 칸 여백을 원래대로 두었습니다(공간이 모자람).")

    def _tight_dates(self, tbl):
        """표 안 날짜는 띄움 없이: ’26. 11. 13. → ’26.11.13., ’26. 11월 → ’26.11월, 11. 2.~11. 6. → 11.2.~11.6.
        (사용자 원칙 2026-11-01 — 본문 날짜 ’26. 12. 11.(금)은 그대로 띄움). 바꾼 조각 수."""
        if not self._is_data_table(tbl):
            return 0
        n = 0
        for tc in tbl.iter(T("hp:tc")):
            for cp in cell_paras(tc):
                for r in para_runs(cp):
                    t = run_text(r)
                    if len(r) != 1 or "." not in t:
                        continue
                    new = DATE_GAP_RE.sub("", t)
                    if new != t:
                        set_run_text(r, new, self.b.tab_proto)
                        n += 1
        return n

    def _bind_parens(self, tbl):
        """칸 글의 짧은 괄호 '(공통 0.5)'·'(가점 0.3)' 안 빈칸은 묶음 빈칸으로 — 괄호 가운데서 줄이 꺾이지 않고
        필요하면 괄호 앞에서 통째로 넘어가게(뜻 단위, 사용자 수정본 2026-11-01). 바꾼 조각 수."""
        n = 0
        for tc in tbl.iter(T("hp:tc")):
            for cp in cell_paras(tc):
                for r in para_runs(cp):
                    t = run_text(r)
                    if "(" not in t or len(r) != 1:
                        continue
                    new = PAREN_RE.sub(lambda m: m.group(0).replace(" ", "⍽")
                                       if len(m.group(1).replace(" ", "")) <= PAREN_BIND else m.group(0), t)
                    if new != t:
                        set_run_text(r, new, self.b.tab_proto)
                        n += 1
        return n

    def _squeeze_near(self, tbl):
        """칸 너비를 정한 뒤, 쓸 수 있는 폭을 NEAR 안에서만 넘는 칸 글은 '한 줄로 입력'으로(다음 줄로 내리지 않게).
        '항목 : 내용' 줄은 쌍점 뒤 글만 자간을 줄인다(_colon_tighten). (한 줄로 입력한 수, 쌍점 뒤만 줄인 수)."""
        if int(tbl.get("rowCnt", "1")) < 2 or int(tbl.get("colCnt", "1")) < 2:
            return 0, 0
        done = colon = 0
        for r, c, rs, cs, tc in table_grid(tbl):
            w = int(tc.find(T("hp:cellSz")).get("width", "0"))
            margin = self._cell_margin(tbl, tc) + 150
            for cp in cell_paras(tc):
                pp = self.st.para.get(cp.get("paraPrIDRef"), {})
                if pp.get("squeeze"):
                    continue
                avail = (w - margin - pp.get("left", 0) - pp.get("right", 0)) / 1.02
                need = max((sum(ch[1] for ch in line) for line in split_lines(self.lay.chars(cp))), default=0)
                if avail * 0.97 < need <= avail * NEAR:  # 어림이 1~3% 모자랄 수 있어(맑은 고딕 굵게) 거의 꽉 찬 칸도
                    if self._colon_tighten(cp, avail):
                        colon += 1
                        continue
                    cp.set("paraPrIDRef", self.b.hedit.para_squeeze(cp.get("paraPrIDRef")))
                    done += 1
        return done, colon

    def _colon_tighten(self, cp, avail):
        """'항목 : 내용' 줄을 '한 줄로 입력'으로 누르면 항목명·쌍점까지 좁아져 위아래 줄과 쌍점이 어긋난다(사용자 지적
        2026-11-02 — 쌍점 뒤 글자 간격을 줄여 위아래 선을 맞출 것). 항목명·쌍점은 그대로 두고 쌍점 뒤 글만 자간을
        줄여(FLOOR까지) 한 줄에 넣어 본다. 넣었으면 True, 안 되면 False(그때는 지금처럼 한 줄로 입력)."""
        if not label_colon(para_text(cp)) or not self.checked(cp):
            return False
        self._split_head(cp)
        for d in range(-1, FLOOR - 1, -1):
            chs = self.lay.chars(cp, delta=d, floor=FLOOR)
            if max((sum(ch[1] for ch in line) for line in split_lines(chs)), default=0) <= avail * 0.97:
                self.set_delta(cp, d)  # 머리(기호·항목명·쌍점)는 그대로, 쌍점 뒤 조각만
                return True
        return False

    def _split_head(self, p):
        """머리(기호·항목명·쌍점)와 내용이 한 조각에 들어 있으면(표 칸 글은 대개 한 조각) 머리 끝에서 조각을 둘로
        나눈다 — 자간은 조각 단위로 주므로, 나눠야 쌍점 뒤 내용에만 줄 수 있다. 보이는 글·모양은 그대로."""
        head = head_length(para_text(p))
        pos = 0
        for r in para_runs(p):
            t = run_text(r)
            if r.find(T("hp:t")) is not None and len(r) == 1 and pos < head < pos + len(t):
                parent = r.getparent()
                at = list(parent).index(r)
                parent.insert(at, self.b._mk(r, t[:head - pos]))
                parent.insert(at + 1, self.b._mk(r, t[head - pos:]))
                parent.remove(r)
                return
            pos += len(t)

    @staticmethod
    def _caption_content(tbl, grid):
        """제목 걸친 상자(3줄×3칸, 가운데 칸이 위 두 줄을 합친 제목)의 본문 칸, 아니면 None."""
        if tbl.get("rowCnt") != "3" or tbl.get("colCnt") != "3":
            return None
        at = {(r, c): (rs, cs, tc) for r, c, rs, cs, tc in grid}
        if at.get((0, 1), (0, 0))[:2] != (2, 1) or at.get((2, 0), (0, 0))[1] != 3:
            return None
        return at[(2, 0)][2]

    def _image_layout(self, tbl, grid, total):
        """배경 그림 칸이 있는 표: 그림 가로세로 비율이 지켜지게 칸 너비와 줄 높이를 맞춘다(사용자 원칙 2026-11-01).
        - 한 줄에 그림 칸이 둘 이상이면 글 칸 너비는 그대로 두고 남은 폭을 그림 비율대로 나눈다 → 그 줄 그림 높이가 같아짐
          (글 기준으로 칸을 나누면 '정비 전' 칸이 좁아져 사진이 눌린 것, 한글 실측)
        - 그다음 그림이 든 줄 높이 = 그 줄 그림 칸의 '너비 ÷ 비율' 가운데 가장 큰 값. 비율이 많이 어긋나는 그림은 알린다."""
        aspect = self.b.image_aspect
        cells = [(r, c, tc) for r, c, rs, cs, tc in grid if tc in aspect and rs == 1 and cs == 1]
        if not cells:
            return 0
        n = int(tbl.get("colCnt", "1"))
        rows = {}
        for r, c, tc in cells:
            rows.setdefault(r, {})[c] = aspect[tc]
        widest = max(rows.values(), key=len)
        if len(widest) >= 2:
            cur = [0] * n
            for r, c, rs, cs, tc in grid:
                if cs == 1 and not cur[c]:
                    cur[c] = int(tc.find(T("hp:cellSz")).get("width", "0"))
            img_cols = sorted({c for row in rows.values() for c in row})
            avg = {c: sum(row[c] for row in rows.values() if c in row) / sum(1 for row in rows.values() if c in row)
                   for c in img_cols}
            rest = total - sum(cur[c] for c in range(n) if c not in img_cols)
            widths = [cur[c] if c not in img_cols else rest * avg[c] / sum(avg.values()) for c in range(n)]
            self._set_widths(tbl, grid, widths, total)
            grid = table_grid(tbl)
        width = {(r, c): int(tc.find(T("hp:cellSz")).get("width", "0")) for r, c, rs, cs, tc in grid}
        for r, row in rows.items():
            h = max(width[(r, c)] / a for c, a in row.items())
            for rr, c, rs, cs, tc in grid:
                if rr == r and rs == 1:
                    tc.find(T("hp:cellSz")).set("height", str(int(round(h))))
            off = max(abs(width[(r, c)] / a / h - 1) for c, a in row.items())
            if off > 0.05:
                self.notes.append(f"표 {r + 1}번째 줄 그림은 비율이 {off * 100:.0f}% 늘어나 보입니다 — 비율이 비슷한 사진끼리 한 줄에 두세요.")
        tbl.find(T("hp:sz")).set("height", str(int(sum(self.lay.table_rows(tbl)))))
        return 1

    def _caption_box(self, tbl, grid, total):
        """제목 걸친 상자(3줄×3칸, 가운데 칸이 위 두 줄을 합친 제목 — 기본 양식 16번)의 제목 칸을 제목 글에 맞춰 넓힌다
        (긴 법령 이름 <대구광역시 성과관리 및 성과평가에 관한 규칙>이 두 줄로 꺾이지 않게). 왼쪽 칸 폭은 그대로."""
        if tbl.get("rowCnt") != "3" or tbl.get("colCnt") != "3":
            return 0
        at = {(r, c): (rs, cs, tc) for r, c, rs, cs, tc in grid}
        if at.get((0, 1), (0, 0))[:2] != (2, 1) or at.get((2, 0), (0, 0))[1] != 3:
            return 0
        cur = [int(at[(0, c)][2].find(T("hp:cellSz")).get("width", "0")) for c in range(3)]
        need = self._natural(tbl, at[(0, 1)][2]) + CAPTION_PAD
        if need <= cur[1] or cur[0] + need > total - 10 * HWPUNIT_PER_MM:
            return 0
        self._set_widths(tbl, grid, [cur[0], need, total - cur[0] - need], total)
        return 1

    def _box_left(self, tbl, grid):
        """제목 걸친 상자 본문 칸 글(법령 조문 등 인용)은 왼쪽 정렬: 글을 고칠 수 없는 인용이라 양쪽 정렬로 낱말 사이가
        벌어지지 않게(맑은 고딕은 어림 폭이 한글과 조금 달라 자간 당기기로는 못 맞춤, 2026-11-01 실측). 바꾼 문단 수."""
        cap = self._caption_content(tbl, grid)
        if cap is None:
            return 0
        n = 0
        for cp in cell_paras(cap):
            pid = cp.get("paraPrIDRef")
            if para_text(cp).strip() and self.st.para.get(pid, {}).get("align") in ("JUSTIFY", "DISTRIBUTE"):
                cp.set("paraPrIDRef", self.b.hedit.para_align(pid, "LEFT"))
                n += 1
        return n

    def _note_gap(self, p, tbl):
        """표 바로 뒤 글 문단과 표 사이를 표 바깥 여백 아래로 띄운다. 글자처럼 취급하지 않은 표 바로 뒤에서는 한글이
        문단 위 간격을 쓰지 않아(실측) 다음 글이 표 아랫선에 붙는다.
        - ※·* 설명: NOTE_GAP(2mm — 표에 딸린 설명이라 가깝게)
        - ○·- 등 글(사용자 지적 2026-11-04 '표 밑에 동그라미가 그대로 붙는 현상 제거'): 글 뒤에 올 때와 같은 간격 =
          그 문단의 위 간격 + 줄 간격 여분(한글은 줄 간격 여분을 앞 줄 아래에 붙임 — 표에는 그 여분이 없음)
        쪽 맨 위에서 시작하는 글(쪽 나눔)·표 위 기준·단위 줄·빈 줄·도표(따로 6mm)는 그대로. 띄웠으면 1(※)·2(글), 아니면 0."""
        nxt = p.getnext()
        while nxt is not None and nxt.tag != T("hp:p"):
            nxt = nxt.getnext()
        if nxt is None or para_tables(nxt) or nxt.get("pageBreak") == "1":
            return 0
        text = para_text(nxt).replace("⎵", " ").strip()
        om = tbl.find(T("hp:outMargin"))
        if not text or om is None:
            return 0
        if text.startswith(("※", "*")):
            kind, gap = 1, NOTE_GAP
        else:
            pos = tbl.find(T("hp:pos"))
            if (UNIT_RE.match(text) or tbl in self.b.flow_tables
                    or (pos is not None and pos.get("treatAsChar") == "1")):
                return 0
            pp = self.st.para.get(nxt.get("paraPrIDRef"), {})
            size = max((self.st.char.get(r.get("charPrIDRef"), {}).get("size", 10) * 100 for r in para_runs(nxt)
                        if run_text(r).strip()), default=1000)
            kind, gap = 2, max(NOTE_GAP, pp.get("prev", 0) + max(0.0, self.lay.line_pitch(nxt, size) - size))
        if int(om.get("bottom", "0")) >= gap - 1:
            return 0
        om.set("bottom", str(int(round(gap))))
        return kind

    def _fit_notes(self, p, tbl):
        """표 바로 밑 ※ 줄(이어지는 ※ 줄 모두)은 표 글꼴(맑은 고딕)로, 크기는 **표 글자보다 1pt 작게**
        (사용자 원칙 2026-11-02 — 표 안 글보다 1pt 작아야 함. 2026-11-01의 '표 글자 크기 그대로'를 바꿈).
        글꼴이 바뀌어 폭이 달라지므로 둘째 줄 내어쓰기(※ 뒤 또는 쌍점 뒤 첫 글자)를 다시 잰다. 바꾼 줄 수."""
        if not self._is_data_table(tbl):
            return 0  # 데이터 표만 — 법령 조문 상자(13pt) 밑 ※ 출처는 작게 그대로
        runs = [r for r in self._table_runs(tbl) if run_text(r).strip()]
        size = self._main_size(tbl)
        src = next((r.get("charPrIDRef") for r in runs
                    if round(self.st.char.get(r.get("charPrIDRef"), {}).get("size", 0)) == size
                    and not self.st.char.get(r.get("charPrIDRef"), {}).get("bold")), None)
        if src is None or not size:
            return 0
        font = self.st.char.get(src, {}).get("font")
        want = size - NOTE_SMALLER
        n = 0
        nxt = p.getnext()
        while nxt is not None and nxt.tag == T("hp:p") and not para_tables(nxt) \
                and para_text(nxt).lstrip(" ⎵⍽").startswith(("※", "*")) and not para_text(nxt).lstrip(" ⎵⍽").startswith("**"):
            changed = False
            for r in para_runs(nxt):
                cid = r.get("charPrIDRef")
                c = self.st.char.get(cid, {})
                if r.find(T("hp:t")) is None or (c.get("font") == font and round(c.get("size", 0)) == want):
                    continue
                r.set("charPrIDRef", self.b.hedit.char_like(cid, src, want))
                changed = True
            if changed:
                text = para_text(nxt)
                pp = self.st.para.get(nxt.get("paraPrIDRef"), {})
                k = label_colon(text) if label_colon(text) and abs(pp.get("intent", 0)) > 0 else 0
                k = k or len(split_marker(text)[0])
                if pp.get("intent", 0):
                    hang = sum(ch[1] for ch in self.lay.chars(nxt)[:k])
                    nxt.set("paraPrIDRef", self.b.hedit.para_hang(nxt.get("paraPrIDRef"), hang))
                n += 1
            nxt = nxt.getnext()
        return n

    def _fit_unit(self, p, size):
        """표 바로 위 기준·단위 줄 '(기준 : ’26.9월) (단위 : 백만원)'을 표 글자보다 UNIT_GAP(2pt) 작게."""
        prev = p.getprevious()
        while prev is not None and prev.tag != T("hp:p"):
            prev = prev.getprevious()
        if prev is None or para_tables(prev) or not UNIT_RE.match(para_text(prev)) or not size:
            return False
        for r in para_runs(prev):
            if r.find(T("hp:t")) is None:
                continue
            cid = r.get("charPrIDRef")
            d = size - UNIT_GAP - self.st.char.get(cid, {}).get("size", 0)
            if abs(d) > 0.01:
                r.set("charPrIDRef", self.b.hedit.char_size(cid, d))
        return True

    def fit_tables(self, again=False):
        """끝선 맞추기·표 글자 크기(10~12pt)·칸 너비를 내용에 맞추기·숫자 칸 자간 자동 줄임·표 위 기준·단위 줄.
        again=True는 같은 문서에 한 번 더 거는 것(자간·한 줄로 입력·폭 빌리기 뒤 다시 재도 같은 결과가 되게 — 만든 문서가
        다듬기의 고정점이 되게, 2026-11-04): 칸 여백 원본은 그대로 두고, 알림은 마지막 상태로 본 '남은 칸'만 다시 적는다."""
        edge, cols, squeezed, wraps, near, units, notes, captions, boxes_left, images = 0, 0, 0, 0, 0, 0, 0, 0, 0, 0
        colon_tight = 0
        shrunk, left, cut_words, dot_breaks, bullets, balanced, note_font = [], [], [], 0, 0, 0, 0
        name_joined, desc_dots, three_info, borrowed, padded = 0, 0, [], 0, 0
        text_gaps = 0
        if not again:
            self.pad_orig = {}
        for p in self.paras():
            for tbl in para_tables(p):
                pp = self.st.para.get(p.get("paraPrIDRef"), {})
                avail = self.body_w - pp.get("left", 0) - pp.get("right", 0)
                width = self.lay.table_width(tbl)
                grid = table_grid(tbl)
                n = int(tbl.get("colCnt", "1"))
                merged = any(rs > 1 or cs > 1 for _, _, rs, cs, _ in grid)
                total = width
                if width > avail + 50 or (width >= avail * EDGE and abs(width - avail) > 50):
                    total = avail
                    edge += 1
                cur = [0] * n
                for r, c, rs, cs, tc in grid:
                    if r == 0 and cs == 1:
                        cur[c] = int(tc.find(T("hp:cellSz")).get("width", "0"))
                if self._is_data_table(tbl) and tbl.get("pageBreak") == "CELL":
                    tbl.set("pageBreak", "TABLE")  # 쪽 경계에서 줄 사이로만 나눔('CELL'은 한 줄이 두 쪽으로 갈라짐, 한글 실측)
                padded += self._cell_pad(tbl)
                self._tight_dates(tbl)
                self._bind_parens(tbl)
                j, u, th = self._dot_columns(tbl)
                name_joined, desc_dots = name_joined + j, desc_dots + u
                three_info += th
                bullets += self._bullet_cells(tbl)
                font = self._fit_font(tbl, grid, n, merged, total, cur, width)
                if font and font[1] != font[0]:
                    shrunk.append(font)
                    self._bullet_cells(tbl)  # 글자가 작아졌으니 둘째 줄 들여쓰기(기호 폭)를 다시 잼
                if tbl in self.b.flow_tables:  # 투명 선 도표: 상자·화살표 칸 비율 그대로(끝선만 맞춤)
                    new, kind = None, None
                else:
                    new, kind = self._layout_widths(tbl, grid, n, merged, total, cur)
                cols += kind == "cols"
                wraps += kind == "wraps"
                if new is None and total != width:
                    new = [w * total / sum(cur) for w in cur] if all(cur) else None
                if new is not None:
                    self._set_widths(tbl, grid, new, total)
                elif total != width and merged:
                    f = total / width
                    for _, _, _, _, tc in grid:
                        sz = tc.find(T("hp:cellSz"))
                        sz.set("width", str(int(round(int(sz.get("width", "0")) * f))))
                    tbl.find(T("hp:sz")).set("width", str(int(total)))
                captions += self._caption_box(tbl, table_grid(tbl), self.lay.table_width(tbl))
                images += self._image_layout(tbl, table_grid(tbl), self.lay.table_width(tbl))
                # 숫자 열(내용 칸 대부분이 숫자·날짜)의 숫자 칸: 금액은 오른쪽 정렬(자릿수가 위아래로 맞게), 금액이 아닌 숫자
                # (쪽 수·건수·대수, 시기·기간 같은 날짜)는 가운데 정렬(사용자 의견 2026-10-31). 글이 섞인 열의 숫자 하나는 그대로.
                cols_cells, heads = {}, {}
                for r, c, rs, cs, tc in grid:
                    if r > 0 and cs == 1:
                        cols_cells.setdefault(c, []).append(tc)
                    elif r == 0:
                        for k in range(c, c + cs):
                            heads[k] = " ".join(para_text(cp) for cp in cell_paras(tc))
                for c, tcs in cols_cells.items():
                    texts = [para_text(cp).strip() for tc in tcs for cp in cell_paras(tc)]
                    filled = [t for t in texts if t and t not in ("-", "–")]
                    nums = [t for t in filled if NUMERIC_RE.match(t) or DATE_RE.match(t)]
                    if not filled or len(nums) < 0.6 * len(filled):
                        continue
                    money = (bool(AMOUNT_HEAD_RE.search(heads.get(c, "").replace(" ", "")))
                             or any(AMOUNT_CELL_RE.search(t) for t in nums))
                    for tc in tcs:
                        for cp in cell_paras(tc):
                            t = para_text(cp).strip()
                            # 숫자 칸의 '-'도 같은 쪽으로. 금액이 아닌 숫자·날짜 열의 짧은 말('상시'·'확인')도 가운데로 맞춰 열을 가지런히
                            if BULLET_RE.match(t):
                                continue  # 글머리표 줄은 왼쪽 정렬 그대로(_bullet_cells)
                            if (NUMERIC_RE.match(t) or DATE_RE.match(t) or t in ("-", "–", "―")
                                    or (not money and t and len(t) <= 6)):
                                pid = self.b.hedit.para_align(cp.get("paraPrIDRef"), "RIGHT" if money else "CENTER")
                                if money:  # 금액은 오른쪽 정렬, 오른쪽 끝에 약간 띄움(사용자 원칙 2026-11-01)
                                    pid = self.b.hedit.para_margin(pid, "right", MONEY_PAD)
                                cp.set("paraPrIDRef", pid)
                for _, _, _, _, tc in grid:
                    for cp in cell_paras(tc):
                        t = para_text(cp).strip()
                        if t and len(t) <= 15 and (NUMERIC_RE.match(t) or DATE_RE.match(t)):
                            new_pid = self.b.hedit.para_squeeze(cp.get("paraPrIDRef"))
                            if new_pid != cp.get("paraPrIDRef"):
                                cp.set("paraPrIDRef", new_pid)
                                squeezed += 1
                if self._borrow_widths(tbl):
                    borrowed += 1
                    self._bullet_cells(tbl)  # 자간을 줄인 칸의 '· ' 폭이 달라졌으니 둘째 줄 들여쓰기를 다시 잼
                    # 자간을 줄인 뒤 다시 재면 열 나누기가 달라질 수 있다 — 지금 한 번 더 맞춰 두어 다듬을 때 바뀌지 않게
                    grid2 = table_grid(tbl)
                    cur2 = [0] * n
                    for r, c, rs, cs, tc in grid2:
                        if r == 0 and cs == 1:
                            cur2[c] = int(tc.find(T("hp:cellSz")).get("width", "0"))
                    new2, _ = self._layout_widths(tbl, grid2, n, merged, total, cur2)
                    if new2 is not None:
                        self._set_widths(tbl, grid2, new2, total)
                        if self._borrow_widths(tbl):
                            self._bullet_cells(tbl)
                n_near, n_colon = self._squeeze_near(tbl)
                near += n_near
                colon_tight += n_colon
                for r, c, rs, cs, tc in table_grid(tbl):
                    margin, words = self._cell_words(tbl, tc)
                    if self._count_lines(margin, words, int(tc.find(T("hp:cellSz")).get("width", "0")), True)[1]:
                        long = max((w for cp in cell_paras(tc) for w in para_text(cp).split()), key=len, default="")
                        cut_words.append(long[:14])
                if self._is_data_table(tbl) and self._table_score(tbl, table_grid(tbl), trust_squeeze=True) > 0:
                    head = next((para_text(cp).strip() for cp in cell_paras(table_grid(tbl)[0][4])), "")
                    left.append(f"{head[:8]}…({self._main_size(tbl)}pt)")
                bal, dot = self._balance_breaks(tbl)
                balanced += bal
                dot_breaks += dot
                boxes_left += self._box_left(tbl, table_grid(tbl))  # 줄 균형(가운데·왼쪽 정렬 글만) 뒤에
                units += self._fit_unit(p, self._main_size(tbl))
                g = self._note_gap(p, tbl)
                notes += g == 1
                text_gaps += g == 2
                note_font += self._fit_notes(p, tbl)
        if again:  # 두 번째 적용: 한 일은 첫 번째 알림에 있고, '남은 칸' 알림만 마지막 상태로 바꿔 적는다
            self.notes[:] = [m for m in self.notes if "줄여도 다음 줄로 넘어가는 칸" not in m and "칸보다 긴 낱말" not in m]
            if shrunk:
                self.notes.append(f"표 {len(shrunk)}개는 다시 재어 표 글자를 한 단계 더 줄였습니다("
                                  + ", ".join(sorted({f"{a}→{b}pt" for a, b in shrunk})) + ").")
            if left:
                self.notes.append(f"표 {len(left)}개는 줄여도 다음 줄로 넘어가는 칸이 남았습니다 — 칸 글을 줄이거나 칸을 합치면 "
                                  "한 줄로 들어갑니다: " + ", ".join(f"‘{t}’" for t in left))
            if cut_words:
                self.notes.append(f"칸보다 긴 낱말 {len(cut_words)}개는 한글이 글자 단위로 끊습니다(단어로 끊기 어긋남) — "
                                  "띄어 쓸 수 있는 말이면 띄우거나 줄이세요: " + ", ".join(f"‘{w}’" for w in cut_words))
            return
        msg = []
        if edge:
            msg.append(f"표 {edge}개의 왼쪽·오른쪽 끝을 본문 폭에 맞췄습니다(끝선 맞추기)")
        if shrunk:
            msg.append(f"표 {len(shrunk)}개는 칸 글이 다음 줄로 덜 넘어가게 표 글자를 줄였습니다("
                       + ", ".join(sorted({f"{a}→{b}pt" for a, b in shrunk})) + f", {TABLE_MIN_PT}pt까지)")
        if cols:
            msg.append(f"표 {cols}개는 칸 글이 줄을 넘지 않게 칸 너비를 내용에 맞춰 나눴습니다")
        if wraps:
            msg.append(f"표 {wraps}개는 내용이 표 폭보다 길어 표 전체 줄 수가 가장 적게 칸 너비를 나눴습니다")
        if near:
            msg.append(f"칸 글이 조금(10% 안) 넘치는 {near}곳은 한 줄로 입력(한글이 글자 간격을 줄여 한 줄에)으로 했습니다")
        if colon_tight:
            msg.append(f"칸 글이 조금 넘치는 '항목 : 내용' 줄 {colon_tight}곳은 쌍점 뒤 글만 자간을 줄여 한 줄에 넣었습니다"
                       "(항목명·쌍점 자리는 위아래 줄과 같게)")
        if squeezed:
            msg.append(f"숫자 칸 {squeezed}곳은 넘칠 때 한글이 자간을 줄이도록(한 줄로 입력) 했습니다")
        if bullets:
            msg.append(f"칸 안 글머리표 줄(· 항목) {bullets}개는 왼쪽 정렬·왼쪽 약간 띄움·둘째 줄을 기호 뒤 글에 맞췄습니다")
        if balanced:
            msg.append(f"두 줄 이상인 칸 글 {balanced}곳은 윗줄·아랫줄 길이가 고르게 줄을 나눴습니다")
        if dot_breaks:
            msg.append(f"칸보다 긴 가운데점 이름 {dot_breaks}곳은 점(·) 뒤에서 줄을 나눴습니다(글자 단위로 끊기지 않게)")
        if units:
            msg.append(f"표 위 기준·단위 줄 {units}개를 표 글자보다 {UNIT_GAP}pt 작게 맞췄습니다")
        if captions:
            msg.append(f"제목 걸친 상자 {captions}개는 제목 칸을 제목 글에 맞춰 넓혔습니다")
        if images:
            msg.append(f"배경 그림이 든 표 {images}개는 칸 너비·줄 높이를 그림 비율에 맞췄습니다(한 줄에 그림이 여럿이면 높이가 같게)")
        if boxes_left:
            msg.append(f"제목 걸친 상자 안 글 {boxes_left}문단은 왼쪽 정렬로 했습니다(인용 글 낱말 사이가 벌어지지 않게)")
        if notes:
            msg.append(f"표 바로 뒤 ※가 붙는 표 {notes}개는 표 아래를 {NOTE_GAP / HWPUNIT_PER_MM:.1f}mm 띄웠습니다")
        if text_gaps:
            msg.append(f"표 바로 밑에 ○·- 글이 붙던 표 {text_gaps}개는 표 아래를 글 사이 간격만큼 띄웠습니다")
        if note_font:
            msg.append(f"표 바로 밑 ※ {note_font}줄은 표 글꼴로, 표 글자보다 {NOTE_SMALLER}pt 작게 맞췄습니다")
        if padded:
            msg.append(f"표 {padded}개는 칸 안 위아래 여백을 {CELL_VPAD / HWPUNIT_PER_MM:.1f}mm로 넓혔습니다(여러 줄 칸 글이 칸 선에 붙지 않게)")
        if borrowed:
            msg.append(f"표 {borrowed}개는 옆 열의 남는 폭을 덜어(필요하면 그 칸 자간 {TIGHT_SP}%) 짧은 '· 항목'이 한 줄에 들어가게 칸 너비를 고르게 했습니다")
        if name_joined:
            msg.append(f"이름을 늘어놓는 열의 '·' 줄 {name_joined}칸은 쉼표로 이어 한 줄로 했습니다")
        if desc_dots:
            msg.append(f"설명 열에서 '·'가 없던 {desc_dots}칸도 '· '로 시작하게 통일했습니다")
        if three_info:
            self.notes.append(f"한 열에 세 가지 정보가 든 머리 칸 {len(three_info)}개({', '.join(sorted(set(three_info))[:4])}): "
                              "내용·배점·부서처럼 세 가지를 한 열에 넣으면 분잡합니다 — 부서는 같은 종류(담당 부서) 열과 합치거나 "
                              "따로 열로 두세요(배점은 '지표(배점)'처럼 이름 뒤 괄호로).")
        if msg:
            self.notes.append("; ".join(msg) + ".")
        if left:
            self.notes.append(f"표 {len(left)}개는 줄여도 다음 줄로 넘어가는 칸이 남았습니다 — 칸 글을 줄이거나 칸을 합치면 "
                              "한 줄로 들어갑니다: " + ", ".join(f"‘{t}’" for t in left))
        if cut_words:
            self.notes.append(f"칸보다 긴 낱말 {len(cut_words)}개는 한글이 글자 단위로 끊습니다(단어로 끊기 어긋남) — "
                              "띄어 쓸 수 있는 말이면 띄우거나 줄이세요: " + ", ".join(f"‘{w}’" for w in cut_words))

    def _set_widths(self, tbl, grid, widths, total):
        ws = [int(round(w)) for w in widths]
        # 칸 안 여백 + 1mm보다 좁은 칸은 한글이 넓혀 표가 튀어나오므로, 모자란 만큼 가장 넓은 칸에서 덜어 온다
        for r, c, rs, cs, tc in grid:
            if r == 0 and cs == 1:
                need = self._cell_margin(tbl, tc) + 282
                if ws[c] < need:
                    big = max(range(len(ws)), key=lambda k: ws[k])
                    ws[big] -= need - ws[c]
                    ws[c] = need
        ws[-1] += int(round(total)) - sum(ws)
        for r, c, rs, cs, tc in grid:
            tc.find(T("hp:cellSz")).set("width", str(sum(ws[c:c + cs])))
        tbl.find(T("hp:sz")).set("width", str(sum(ws)))

    # ------------------------------------------------------------ 쪽 맞춤
    def spacer_kinds(self):
        """견본의 빈 줄 문단 모양: {(문단모양, 글자모양): 높이}."""
        kinds = {}
        for p in self.b.protos:
            if not is_blank(p):
                continue
            runs = para_runs(p)
            if runs:
                kinds[(p.get("paraPrIDRef"), runs[-1].get("charPrIDRef"))] = self.lay.para_height(p, self.body_w)[0]
        return kinds

    def heads(self):
        """큰 묶음의 첫 문단: Ⅰ.·□ 제목(바로 앞도 제목이면 그 앞 제목부터)과 참고 머리표(한 줄짜리 여러 칸 표).
        큰 묶음은 다음 큰 묶음 앞까지 — 가급적 한 쪽에 들어가게 한다(사용자 원칙 9, 2026-10-31)."""
        out, prev_head = set(), False
        for p in self.paras():
            tables = para_tables(p)
            is_head = (marker_level(para_text(p)) == 1 if not tables
                       else tables[0].get("rowCnt") == "1" and tables[0].get("colCnt") != "1")
            if is_head and not prev_head:
                out.add(p)
            prev_head = is_head
        return out

    def badness(self, seg):
        where, used = self.lay.paginate(seg, self.body_w, self.body_h - SAFETY, self.heads(), BLOCK_GAP)
        gaps = sum(self.body_h - u for u in used[:-1] if self.body_h - u > self.body_h * BIG_GAP)
        # 한 쪽에 들어갈 만한 □ 묶음이 두 쪽에 걸치면(끝 ○ 하나만 다음 쪽으로 떨어지는 등) 줄 간격을 줄여서라도
        # 한 쪽에 넣는다 — '(시제품) 줄이 다음 장으로 넘어감' 사용자 지적(2026-10-31). 쪽 수를 늘리는 것보다는 가볍게 친다.
        split = len(self.lay.split) * self.body_h * 2
        return len(used) * self.body_h * 10 + split + gaps, len(used)

    def fit_pages(self):
        kinds = self.spacer_kinds()
        narrow = min(kinds, key=kinds.get) if kinds else None
        segs, cur = [], []
        for p in self.paras():
            if p.get("pageBreak") == "1" and cur:
                segs.append(cur)
                cur = []
            cur.append(p)
        if cur:
            segs.append(cur)
        changed = []
        for seg in segs:
            spacers = []
            if narrow:
                for p in seg:
                    runs = para_runs(p)
                    if not is_blank(p) or not runs:
                        continue
                    k = (p.get("paraPrIDRef"), runs[-1].get("charPrIDRef"))
                    if k in kinds and kinds[k] > kinds[narrow]:
                        spacers.append(p)
            texts = [p for p in seg if not para_tables(p) and para_text(p).strip()
                     and self.st.para.get(p.get("paraPrIDRef"), {}).get("line_type") == "PERCENT"]
            saved = {p: (p.get("paraPrIDRef"), [r.get("charPrIDRef") for r in para_runs(p)]) for p in spacers + texts}

            def restore():
                for p, (pid, cids) in saved.items():
                    p.set("paraPrIDRef", pid)
                    for r, c in zip(para_runs(p), cids):
                        r.set("charPrIDRef", c)

            def shrink_spacers():
                # 한 줄 빈 줄을 좁은 빈 줄(8pt)로 바꾸면 □ 사이가 너무 좁다는 사용자 의견(2026-10-31)
                # → 글자 크기는 두고 줄 간격만 100%로(14pt 기준 약 7.9mm → 4.9mm)
                for p in spacers:
                    pid = saved[p][0]
                    if self.st.para.get(pid, {}).get("line_type") == "PERCENT" and \
                            self.st.para.get(pid, {}).get("line", 0) > SPACER_LINE:
                        p.set("paraPrIDRef", self.b.hedit.para_line(pid, SPACER_LINE))

            def line_to(v):
                for p in texts:
                    pid = saved[p][0]
                    if self.st.para.get(pid, {}).get("line", 0) > v:
                        p.set("paraPrIDRef", self.b.hedit.para_line(pid, v))

            # 덜 바꾸는 것부터: 줄 간격을 5%씩 낮춰 보고(사용자 지시 '줄간 조정'), 그다음 □ 사이 빈 줄 좁히기를 더한다
            top = max((self.st.para.get(saved[p][0], {}).get("line", 0) for p in texts), default=0)
            steps = list(range(top - 5, MIN_LINE - 1, -5)) if top > MIN_LINE else []
            # 바꾸는 정도(덜 바꿀수록 좋음): 줄 간격은 낮춘 %만큼, □ 사이 빈 줄 좁히기는 줄 간격 10%쯤으로 친다
            # — 같은 쪽 수라면 본문 140%보다 '빈 줄 좁힘 + 155%'가 덜 답답하다(2026-10-31)
            plans = [("그대로", 0, lambda: None)]
            plans += [(f"줄 간격 {v}%", top - v, lambda v=v: line_to(v)) for v in steps]
            if spacers:
                plans.append(("□ 사이 빈 줄 조금 좁힘", SPACER_COST, shrink_spacers))
                plans += [(f"□ 사이 빈 줄 조금 좁힘 + 줄 간격 {v}%", SPACER_COST + top - v,
                           lambda v=v: (shrink_spacers(), line_to(v))) for v in steps]
            best = None
            for name, cost, act in plans:
                restore()
                act()
                bad, pages = self.badness(seg)
                if best is None or bad < best[0] - 1 or (abs(bad - best[0]) <= 1 and cost < best[4]):
                    best = (bad, name, act, pages, cost)
            restore()
            best[2]()
            if best[1] != "그대로":
                changed.append(f"{best[1]}(어림 {best[3]}쪽)")
        if changed:
            self.notes.append("쪽이 애매하게 넘어가지 않도록 " + ", ".join(changed) + "으로 맞췄습니다.")
        self.force_breaks()

    def force_breaks(self):
        """묶음(□·○와 그 아래 -·*·※·표)이 쪽 끝에 다 들어가지 않아 다음 쪽으로 넘어갈 자리에는 쪽 나눔을 직접 넣는다.
        한글의 '다음 문단과 함께'는 표가 든 문단에서 묶음을 다 끌고 가지 않을 때가 있어(실측), 계산한 대로 쪽을 나눈다."""
        paras = self.paras()
        heads = self.heads()
        # 쪽 맞춤(badness)과 같은 높이(본문 - SAFETY)로 나눈다 — 높이가 다르면 □ 블록 가운데에 쪽 나눔이 들어감(2026-10-31)
        where, _ = self.lay.paginate(paras, self.body_w, self.body_h - SAFETY, heads, BLOCK_GAP)
        targets = set(self.lay.moved)
        # 어림으로 쪽 맨 위에서 시작하는 □·참고 묶음도 쪽 나눔을 박아 둔다: 한글 쪽 내용이 어림보다 조금 짧으면
        # □ 제목과 표 머리 줄만 앞 쪽 끝에 남는 일이 있었음(2026-10-31 시험 문서 참고1)
        for i, p in enumerate(paras):
            if p in heads and i > 0 and where[i][0] > 0:
                k = i - 1
                while k >= 0 and self._blank(paras[k]):
                    k -= 1
                if k >= 0 and where[k][1] < where[i][0]:
                    targets.add(i)
        n, dropped = 0, 0
        for i in sorted(targets):
            if i > 0 and paras[i].get("pageBreak") != "1":
                paras[i].set("pageBreak", "1")
                self.forced.add(paras[i])
                n += 1
            # 쪽 나눔 바로 앞 빈 줄은 앞 쪽 끝에 남거나 빈 쪽을 만들 뿐이라 뺀다
            k = i - 1
            while k > 0 and self._blank(paras[k]) and paras[k].get("pageBreak") != "1":
                self.b.sec.remove(paras[k])
                dropped += 1
                k -= 1
        if n:
            self.notes.append(f"쪽 끝에 다 들어가지 않는 묶음 {n}곳은 묶음째 다음 쪽에서 시작하게 했습니다.")

    @staticmethod
    def _blank(p):
        return is_blank(p)

    def spread_pages(self):
        """다음 쪽으로 이어지는데 아래 끝선이 애매하게 빈 쪽(SPREAD_GAP 넘게)은 그 쪽 모든 문단(빈 줄 포함)의 줄 간격을
        같은 만큼씩 5%p 단계로(SPREAD_ADD까지, LINE_CAP 넘지 않게) 늘려 빈 곳을 줄인다 — 제목·○·- 사이 차이는 그대로
        (사용자 수정본 2026-11-01: 한 쪽은 ○ 150→170·제목 160→180, 다른 쪽은 +10 — '하단 끝선이 애매하면 페이지 줄간을
        전체로 넓혀도 괜찮다'). 참고 앞 마지막 본문 쪽은 그대로 둔다. 어느 문단이라도 쪽이 바뀌면 그 앞 단계에서 멈춘다."""
        paras = self.paras()
        heads = self.heads()
        lim = self.body_h - SAFETY
        base, used = self.lay.paginate(paras, self.body_w, lim, heads, BLOCK_GAP)
        done = []
        for k in range(len(used) - 1):
            nxt = next((i for i, (s, _) in enumerate(base) if s == k + 1), None)
            if nxt is None or self._is_ref_head(paras[nxt]) or lim - used[k] < self.body_h * SPREAD_GAP:
                continue
            if k == 0 and cover_end(paras) is not None:
                continue  # 표지는 fit_cover가 맡음
            if any(self._is_ref_head(p) for i, p in enumerate(paras) if base[i][0] <= k):
                continue  # 참고 쪽은 fit_refs가 맡음
            # 줄 간격 140% 이상인 글·빈 줄만 — 날짜 줄(100%)·좁힌 빈 줄처럼 일부러 촘촘히 둔 줄은 건드리지 않는다
            texts = [p for i, p in enumerate(paras) if base[i] == (k, k) and not para_tables(p)
                     and self.st.para.get(p.get("paraPrIDRef"), {}).get("line_type") == "PERCENT"
                     and self.st.para.get(p.get("paraPrIDRef"), {}).get("line", 0) >= MIN_LINE]
            saved = {p: p.get("paraPrIDRef") for p in texts}

            def line_add(d):
                for p in texts:
                    pid = saved[p]
                    v = min(LINE_CAP, self.st.para.get(pid, {}).get("line", 0) + d)
                    p.set("paraPrIDRef", self.b.hedit.para_line(pid, v) if d else pid)

            best = 0
            for d in range(5, SPREAD_ADD + 1, 5) if texts else ():
                line_add(d)
                where, u = self.lay.paginate(paras, self.body_w, lim, heads, BLOCK_GAP)
                if where != base or u[k] > lim:
                    break
                best = d
            line_add(best)
            if best:
                done.append(f"{k + 1}쪽 줄 간격 +{best}")
            # 줄 간격으로 다 못 채운 쪽(표가 대부분인 쪽)은 그 쪽에 다 들어간 표의 줄 높이를 늘린다(참고 쪽 채우기와 같은 방법)
            _, u = self.lay.paginate(paras, self.body_w, lim, heads, BLOCK_GAP)
            tbls = [t for i, p in enumerate(paras) if base[i] == (k, k) for t in para_tables(p) if self._is_data_table(t)]
            if lim - u[k] < self.body_h * 0.10 or not tbls:
                continue
            rows0 = {t: self._row_heights(t) for t in tbls}
            add = min((lim - u[k]) / sum(len(h) for h in rows0.values()), ROW_ADD_MAX)
            while add > 0.3 * HWPUNIT_PER_MM:
                for t in tbls:
                    self._set_rows(t, [h + add for h in rows0[t]])
                where, u2 = self.lay.paginate(paras, self.body_w, lim, heads, BLOCK_GAP)
                if where == base and u2[k] <= lim:
                    done.append(f"{k + 1}쪽 표 줄 높이 +{add / HWPUNIT_PER_MM:.1f}mm")
                    break
                add *= 0.8
            else:
                for t in tbls:
                    self._set_rows(t, rows0[t])
        if done:
            self.notes.append("아래 끝선이 애매하게 빈 쪽은 그 쪽 줄 간격을 통째로 같은 만큼(표가 많은 쪽은 표 줄 높이) 늘려 빈 곳을 줄였습니다("
                              + ", ".join(done) + ").")

    # ------------------------------------------------------------ 참고 쪽 채우기
    def _is_ref_head(self, p):
        """참고 머리표: 한 줄짜리 여러 칸 표로 첫 칸이 '참고1'·'붙임' 등."""
        tables = para_tables(p)
        if not tables or tables[0].get("rowCnt") != "1" or tables[0].get("colCnt") == "1":
            return False
        grid = table_grid(tables[0])
        return bool(grid) and bool(REF_RE.match(" ".join(para_text(cp) for cp in cell_paras(grid[0][4]))))

    def _set_rows(self, tbl, heights):
        """줄마다 최소 높이(HWPUNIT)를 칸 높이로 적는다(세로로 합친 칸은 덮은 줄 높이의 합). 한글은 글이 더 길면 늘림."""
        grid = table_grid(tbl)
        heights = list(heights)
        for r, c, rs, cs, tc in grid:  # 배경 그림 줄은 높이를 바꾸지 않는다(가로세로 비율 유지)
            if rs == 1 and tc in self.b.image_cells:
                heights[r] = int(tc.find(T("hp:cellSz")).get("height", "0"))
        for r, c, rs, cs, tc in grid:
            tc.find(T("hp:cellSz")).set("height", str(int(round(sum(heights[r:r + rs])))))
        tbl.find(T("hp:sz")).set("height", str(int(round(sum(heights)))))

    def _row_heights(self, tbl):
        hs = self.lay.table_rows(tbl)
        om = tbl.find(T("hp:outMargin"))
        if om is not None:
            hs[-1] -= int(om.get("top", "0")) + int(om.get("bottom", "0"))
        return hs

    def _block_height(self, ps, lim):
        """문단 묶음만 따로 쪽을 나눠 본 (쪽 수, 마지막 쪽 높이)."""
        _, used = self.lay.paginate(ps, self.body_w, lim)
        return len(used), used[-1]

    def _stretch_rows(self, tbls, seg, lim):
        """seg(첫 문단이 쪽 맨 위에서 시작하는 문단들)의 마지막 쪽 남는 높이를 tbls 표의 줄마다 똑같이 나눠 더한다
        (줄마다 ROW_ADD_MAX까지). 쪽 수가 바뀌면 조금씩 덜 더하고, 끝내 안 되면 되돌린다. 더했으면 True."""
        if not tbls:
            return False
        base = {t: self._row_heights(t) for t in tbls}
        rows = sum(len(h) for h in base.values())
        npg, used = self._block_height(seg, lim)
        add = min((lim - used) / rows, ROW_ADD_MAX)
        while add > 0.3 * HWPUNIT_PER_MM:
            for t in tbls:
                self._set_rows(t, [h + add for h in base[t]])
            if self._block_height(seg, lim)[0] == npg:
                self._last_add = add
                return True
            add *= 0.8
        for t in tbls:
            self._set_rows(t, base[t])
        return False

    def fit_refs(self):
        """참고 쪽(참고 머리표부터 끝까지)은 가급적 한 장에 꽉 채우고, 작은 표는 두 개를 한 장에(사용자 원칙 2026-11-01).
        1) 참고 표 줄 높이를 글에 맞춰 줄인다(글자 높이 + 2.5mm까지) — 한 장에 들어갈 여지를 만든다.
        2) 참고 머리표·□ 제목에서 시작하는 덩어리(제목 + 표 + ※)를 차례로 쪽에 담는다: 앞 덩어리와 한 쪽에 다 들어가면
           쪽 나눔을 빼고 빈 줄 하나를 두어 이어 붙이고(참고가 달라도), 안 들어가면 새 쪽에서 시작한다.
        3) 덩어리가 다 들어간 쪽은 남는 높이를 그 쪽 표의 줄마다 똑같이 나눠 더해(줄마다 5mm까지) 쪽을 채운다."""
        paras = self.paras()
        start = next((i for i, p in enumerate(paras) if self._is_ref_head(p)), None)
        if start is None:
            return
        region = paras[start:]
        lim = self.body_h - SAFETY - FILL_MARGIN
        heads = [i for i, p in enumerate(region)
                 if self._is_ref_head(p) or (not para_tables(p) and marker_level(para_text(p)) == 1)]
        if not heads or heads[0] != 0:
            heads = [0] + heads
        chunks = []
        for k, h in enumerate(heads):
            ps = region[h:heads[k + 1] if k + 1 < len(heads) else len(region)]
            if chunks and chunks[-1]["open"]:  # 제목만 있는 덩어리(참고 머리표 바로 뒤 □ 등)는 다음 덩어리와 한 몸
                chunks[-1]["ps"] += ps
            else:
                chunks.append({"ps": list(ps)})
            content = [p for p in chunks[-1]["ps"] if not self._blank(p)]
            chunks[-1]["open"] = all(self._is_ref_head(p) or (not para_tables(p) and marker_level(para_text(p)) == 1)
                                     for p in content)
        for ch in chunks:
            body = list(ch["ps"])
            tail = []
            while len(body) > 1 and self._blank(body[-1]):
                tail.insert(0, body.pop())
            ch["body"], ch["tail"] = body, tail
        tables = [t for p in region for t in para_tables(p) if self._is_data_table(t)]
        if not tables:
            return
        heads_set = {ch["body"][0] for ch in chunks}
        for p in region:  # 덩어리 안에 force_breaks가 넣은 쪽 나눔은 다시 정한다
            if p in self.forced and p not in heads_set:
                p.set("pageBreak", "0")
                self.forced.discard(p)
        for t in tables:  # 1) 줄 높이 줄이기
            self._set_rows(t, [self._main_size(t) * 100 + ROW_PAD] * int(t.get("rowCnt", "1")))
        sp = self.b._block_spacer()
        sp_h = self.lay.para_height(self.b.protos[sp], self.body_w)[0] if sp is not None else 0
        pages = []  # 2) 쪽에 담기
        for k, ch in enumerate(chunks):
            npg, last = self._block_height(ch["body"], lim)
            if npg == 1 and pages:
                prev_tail = chunks[k - 1]["tail"]
                gap = sum(self.lay.para_height(b, self.body_w)[0] for b in prev_tail) if prev_tail else sp_h
                if pages[-1]["y"] + gap + last <= lim:
                    pages[-1]["chunks"].append(k)
                    pages[-1]["y"] += gap + last
                    continue
            pages.append({"chunks": [k], "y": last, "split": npg > 1})
        joined = []
        for pi, pg in enumerate(pages):
            for j, k in enumerate(pg["chunks"]):
                head = chunks[k]["body"][0]
                if j == 0:
                    if pi > 0 or k > 0:
                        head.set("pageBreak", "1")
                        for b in chunks[k - 1]["tail"]:  # 쪽 나눔 바로 앞 빈 줄은 앞 쪽 끝에 남을 뿐이라 뺀다
                            if b.getparent() is not None:
                                b.getparent().remove(b)
                    continue
                head.set("pageBreak", "0")
                self.forced.discard(head)
                if not chunks[k - 1]["tail"] and sp is not None:
                    head.addprevious(self.b.clone(sp, "참고 쪽 빈 줄"))
                if self._is_ref_head(head):
                    name = para_text(cell_paras(table_grid(para_tables(head)[0])[0][4])[0]).strip()
                else:
                    name = para_text(head).strip()[:10]
                joined.append(name)
        filled = []
        allp = self.paras()
        for pi, pg in enumerate(pages):  # 3) 남는 높이를 표 줄에 나눠 쪽 채우기
            # 앞 쪽에서 넘어온 긴 표(여러 쪽 덩어리)의 꼬리가 있는 쪽은 이 쪽에 다 들어간 덩어리의 표만 늘린다
            own = pg["chunks"][1:] if pg["split"] else pg["chunks"]
            tbls = [t for k in own for p in chunks[k]["body"] for t in para_tables(p) if self._is_data_table(t)]
            first = chunks[pg["chunks"][0]]["body"][0]
            last_p = chunks[pg["chunks"][-1]]["body"][-1]
            seg = allp[allp.index(first):allp.index(last_p) + 1]
            if self._stretch_rows(tbls, seg, lim):
                filled.append(f"{pi + 1}번째 참고 쪽 +{self._last_add / HWPUNIT_PER_MM:.1f}mm")
        msg = []
        if joined:
            msg.append(f"작은 표가 있는 참고 덩어리 {len(joined)}개는 앞 덩어리와 한 쪽에 모았습니다("
                       + ", ".join(f"‘{t}’" for t in joined) + ")")
        if filled:
            msg.append("참고 쪽은 표 줄 높이를 글에 맞춘 뒤 남는 높이를 줄마다 나눠 쪽을 채웠습니다(" + ", ".join(filled) + ")")
        if msg:
            self.notes.append("; ".join(msg) + ".")

    # ------------------------------------------------------------ 표지
    def pull_corners(self):
        """머리 기호(○ - □ …)·괄호 이름표·'항목 : ' 바로 뒤 내용이 여는 낫표(「 『)면, 휴먼명조에서는 표시가 칸 오른쪽에 찍혀
        (왼쪽 반 칸이 빔) 첫 줄만 반 칸 들어가 보이고 아랫줄(내어쓰기)·옆 ○ 줄과 끝선이 안 맞는다(사용자 지적 2026-11-03:
        '꺽쇠 줄은 한 칸 앞으로 당기고 아랫줄은 그대로'). 낫표 앞 빈칸(고정폭 빈칸)과 그 앞 한 글자(머리 기호, 이름표의 닫는
        괄호, 쌍점)의 자간을 줄여(-50%까지) 낫표 표시가 보통 글자 첫 획 자리에 오게 당긴다. 아랫줄 내어쓰기는 그대로 둔다.
        - 내어쓰기를 글자 폭으로 다시 재는 단계들이 앞에 있으므로 맞춤이 모두 끝난 뒤 마지막에 한다.
        - 첫 줄이 넓어져 줄 나눔이 바뀌는 문단은 건드리지 않는다(쪽 맞춤 결과를 지킴).
        - 이어지는 줄이 낫표로 시작하면 그 줄은 당길 수 없다(줄 첫머리는 내어쓰기 자리) — 알린다."""
        pulled = skipped = 0
        lead = []
        for p, box_w in self.text_boxes():
            text = para_text(p)
            pre, mark, _ = split_marker(text)
            k = next((x for x in (label_content(text), len(pre) if mark else 0, label_colon(text))
                      if 0 < x < len(text) and text[x] in "「『"), 0)
            if not k or not self.checked(p):
                continue
            runs = []  # 글자 위치마다 (조각, 글자 모양 번호)
            for r in para_runs(p):
                if r.find(T("hp:tbl")) is None:
                    runs += [(r, r.get("charPrIDRef"))] * len(run_text(r))
            c = self.st.char.get(runs[k][1], {})
            ink = CORNER_INK.get(c.get("font"), {}).get(text[k])
            if ink is None:
                continue
            chs = self.lay.chars(p)

            def w0(i):
                sp = self.st.char.get(runs[i][1], {}).get("spacing", 0)
                return chs[i][1] / (1 + sp / 100) if sp > -100 else 0

            need = (ink - KO_INK) * w0(k)
            j = k
            while j > 0 and text[j - 1] in " ⎵⍽":
                j -= 1
            # 이미 당긴 머리 기호 문단은 건너뜀(되풀이해도 같게, 2026-11-04): ○·-·□ 뒤 고정폭 빈칸은 낫표 붙이기·줄 맞춤이
            # 건드리지 않으므로 그 자간이 하한이면 이 단계가 당긴 것 — 다시 당기면 머리 기호 자간만 더 줄어 낫표가 튀어나옴.
            # 이름표 ')'·쌍점 꼴은 첫 번에 남는 폭을 다 써서 되풀이해도 그대로(쌍점 꼴 빈칸은 낫표 붙이기가 이미 -50%로 둠)
            if mark and k == len(pre) and any(text[i] == "⎵" and self.st.char.get(runs[i][1], {}).get("spacing", 0) <= CORNER_FLOOR
                                              for i in range(j, k)):
                continue
            order = list(range(j, k)) + ([j - 1] if j > 0 and text[j - 1] not in "\n\t" else [])
            new = {}  # 글자 위치 → 새 자간
            for i in order:
                if need <= 0:
                    break
                base = self.st.char.get(runs[i][1], {}).get("spacing", 0)
                full = w0(i)
                room = full * (base - CORNER_FLOOR) / 100
                if full <= 0 or room <= 0:
                    continue
                take = min(room, need)
                new[i] = max(CORNER_FLOOR, round(base - 100 * take / full))
                need -= take
            if not new:
                continue
            pp = self.st.para.get(p.get("paraPrIDRef"), {})
            first, rest = self.lay.widths(p, box_w)

            def breaks(cs):
                if pp.get("squeeze"):
                    return [(s, e) for s, e, *_ in self.lay.wrap(cs, 1e12, 1e12)]
                return [(s, e) for s, e, *_ in self.lay.wrap(cs, first, rest, pp.get("condense", 0))]

            sim = list(chs)
            for i, sp in new.items():
                sim[i] = (sim[i][0], w0(i) * (1 + sp / 100)) + tuple(sim[i][2:])
            lines = breaks(chs)
            if breaks(sim) != lines:
                skipped += 1
                continue
            for i in sorted(new):
                self.b._split_run_at(p, i)
                self.b._split_run_at(p, i + 1)
            pos = 0
            for r in para_runs(p):
                if r.find(T("hp:tbl")) is not None:
                    continue
                n = len(run_text(r))
                if n == 1 and pos in new:
                    r.set("charPrIDRef", self.b.hedit.char_spacing(r.get("charPrIDRef"), new[pos]))
                pos += n
            pulled += 1
            if any(text[s] in "「『" for s, _ in lines[1:] if s < len(text)):
                lead.append(text[k:k + 15].replace("⎵", " "))
        if pulled:
            self.notes.append(f"머리 기호·이름표 바로 뒤가 낫표(「)인 문단 {pulled}개는 낫표 앞 자간을 줄여 낫표를 반 칸 당겼습니다"
                              f"(휴먼명조 「는 왼쪽 반 칸이 비어 첫 줄이 들어가 보임 — 아랫줄·옆 줄과 끝선 맞춤)."
                              + (f" 줄 나눔이 바뀌는 {skipped}개는 그대로 두었습니다." if skipped else ""))
        if lead:
            self.notes.append(f"이어지는 줄이 낫표(「)로 시작하는 문단 {len(lead)}개는 그 줄의 낫표만 반 칸 들어가 보입니다"
                              f"(줄 첫머리는 당길 수 없음 — 법령은 ○ 하나에 하나씩 쓰면 맞음): " + ", ".join(lead))

    def fit_cover(self):
        """표지(첫 쪽: 시 슬로건 그림 + 제목 띠 + 개요 상자 + 대구시 마크·부서명)의 위아래 자리를 문단 위 간격으로 맞춘다
        (대구시 문서 표지를 본뜸, 사용자 2026-11-01): 슬로건은 쪽 맨 위, 제목 띠는 본문 높이의 COVER_TITLE_AT쯤,
        마크·부서명은 쪽 아래(8mm 띄움), 정사각형 개요 상자는 제목 띠와 마크 사이 가운데."""
        paras = self.paras()
        end = cover_end(paras)
        if end is None:
            return
        cover = paras[:end]
        tbls = [i for i, p in enumerate(cover) if para_tables(p)]
        last_pic = max((i for i, p in enumerate(cover) if para_pics(p)), default=None)
        if not tbls or last_pic is None or last_pic < tbls[0]:
            return
        band = tbls[0]
        box = next((i for i in tbls[1:] if i < last_pic), None)
        if box is not None:
            self._widen_cover_box(para_tables(cover[box])[0])

        def own(i):  # 문단 위 간격을 뺀 높이
            h, _, prev, _ = self.lay.para_height(cover[i], self.body_w)
            return h - prev

        top = sum(self.lay.para_height(p, self.body_w)[0] for p in cover[:band])
        band_h = sum(own(i) if i == band else self.lay.para_height(cover[i], self.body_w)[0]
                     for i in range(band, box if box is not None else last_pic))
        box_h = sum(own(i) if i == box else self.lay.para_height(cover[i], self.body_w)[0]
                    for i in range(box, last_pic)) if box is not None else 0
        bottom_h = own(last_pic) + sum(self.lay.para_height(p, self.body_w)[0] for p in cover[last_pic + 1:])
        bottom_top = self.body_h - COVER_BOTTOM_GAP - bottom_h
        y_band = max(top + COVER_MIN_GAP, self.body_h * COVER_TITLE_AT)
        gap = (bottom_top - (y_band + band_h) - box_h) / (2 if box is not None else 1)
        if gap < COVER_MIN_GAP:  # 개요 상자가 커서 모자라면 제목 띠를 올림
            y_band = max(top + COVER_MIN_GAP, y_band - (COVER_MIN_GAP - gap) * (2 if box is not None else 1))
            gap = max(COVER_MIN_GAP, (bottom_top - (y_band + band_h) - box_h) / (2 if box is not None else 1))
        if y_band + band_h + box_h + gap * (2 if box is not None else 1) + bottom_h > self.body_h - SAFETY / 2:
            self.notes.append("표지 글이 길어 한 쪽에 다 들어가지 않을 수 있습니다 — 개요 상자 글을 줄이세요.")
        sets = [(band, y_band - top), (last_pic, gap)]
        if box is not None:
            sets.append((box, gap))
        for i, v in sets:
            p = cover[i]
            p.set("paraPrIDRef", self.b.hedit.para_margin(p.get("paraPrIDRef"), "prev", max(0, v)))
        self.notes.append(f"표지: 제목 띠는 위에서 {y_band / HWPUNIT_PER_MM:.0f}mm, "
                          + ("개요 상자는 제목 띠와 대구시 마크 사이 가운데, " if box is not None else "")
                          + "마크·부서명은 쪽 아래에 두었습니다.")

    def _widen_cover_box(self, tbl):
        """표지 개요 상자: 가장 긴 줄이 칸 폭을 넘으면 상자를 COVER_BOX_MAX까지 넓힌다(○ 줄이 두 줄로 꺾이지 않게)."""
        grid = table_grid(tbl)
        if len(grid) != 1:
            return
        tc = grid[0][4]
        cur = int(tc.find(T("hp:cellSz")).get("width", "0"))
        need = max((self._natural(tbl, tc), cur))
        new = min(need, COVER_BOX_MAX)
        if new <= cur:
            return
        tc.find(T("hp:cellSz")).set("width", str(int(new)))
        tbl.find(T("hp:sz")).set("width", str(int(new)))
        self.notes.append(f"표지 개요 상자를 글에 맞춰 {new / HWPUNIT_PER_MM:.0f}mm로 넓혔습니다"
                          + ("(상한 — 긴 ○ 줄은 줄여 쓰세요)." if need > COVER_BOX_MAX else "."))

    def order_hints(self):
        """□ 묶음마다 줄 수가 달라 쪽 아래가 비거나 묶음이 두 쪽에 걸치면, 이웃한 □ 두 묶음의 순서를 바꿔 보고 쪽이 더
        꽉 차는 바꿈을 알린다(사용자 허락 2026-11-01: 내용을 크게 바꾸지 않는 한 순서를 바꿔도 됨). 순서를 실제로 바꿀지는
        뜻을 아는 글쓴이가 정한다 — 첫 묶음(근거법령)·로마자 장 제목 묶음·참고는 움직이지 않는다. 쪽 맞춤(fit_pages)이
        쪽 나눔을 박기 전에 불러 두 차례를 같은 조건으로 어림한다(어림이므로 숫자는 참고)."""
        paras = self.paras()
        heads = self.heads()
        ref_i = next((i for i, p in enumerate(paras) if self._is_ref_head(p)), len(paras))
        body0 = cover_end(paras) or 0
        starts = sorted(i for i, p in enumerate(paras) if p in heads and body0 <= i < ref_i)
        if len(starts) < 3:
            return
        blocks = [(s, starts[k + 1] if k + 1 < len(starts) else ref_i) for k, s in enumerate(starts)]
        lim = self.body_h - SAFETY

        def score(seq):
            where, used = self.lay.paginate(seq, self.body_w, lim, heads, BLOCK_GAP)
            first, last = where[body0][0], where[len(seq) - 1][1]
            gaps = [max(0.0, lim - used[k]) / self.body_h for k in range(first, last)]
            return len(self.lay.split), last - first, round(sum(g * g for g in gaps), 4), gaps

        def label(s):
            return re.sub(r"^[□\s⎵⍽]+", "", para_text(paras[s])).strip()[:12]

        try:
            base_seq = paras[:ref_i]
            base = score(base_seq)
            best = None
            for k in range(1, len(blocks) - 1):
                (a0, a1), (b0, b1) = blocks[k], blocks[k + 1]
                if any(re.match(r"\s*[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]", para_text(paras[s])) for s in (a0, b0)):
                    continue  # 로마자 장 제목은 움직이지 않음
                seq = paras[:a0] + paras[b0:b1] + paras[a0:a1] + paras[b1:ref_i]
                sc = score(seq)
                if sc[:3] < base[:3] and (best is None or sc[:3] < best[0][:3]):
                    best = (sc, a0, b0)
        finally:
            self.lay.paginate(paras, self.body_w, lim, heads, BLOCK_GAP)  # split 등을 지금 차례로 되돌림
        if best is None:
            return
        sc, a0, b0 = best
        worst = max(base[3], default=0)
        after = max(sc[3], default=0)
        why = []
        if sc[0] < base[0]:
            why.append(f"두 쪽에 걸친 □ 묶음 {base[0]}→{sc[0]}개")
        if sc[1] < base[1]:
            why.append(f"본문 {base[1] + 1}→{sc[1] + 1}쪽")
        if worst - after > 0.02:
            why.append(f"가장 빈 쪽 아래 {worst * 100:.0f}%→{after * 100:.0f}%")
        if not why:
            return
        self.notes.append(f"쪽을 꽉 채우려면 순서 바꾸기를 검토하세요: □ ‘{label(a0)}’와 □ ‘{label(b0)}’를 맞바꾸면 "
                          + ", ".join(why) + "(쪽 맞춤 전 어림) — 뜻이 그대로일 때만 계획에서 순서를 바꿉니다(내용을 크게 바꾸지 않는 한 됨).")

    def report(self):
        """어림 쪽 수와 쪽마다 채운 비율."""
        where, used = self.lay.paginate(self.paras(), self.body_w, self.body_h, self.heads(), BLOCK_GAP)
        fill = ", ".join(f"{k + 1}쪽 {min(100, round(u / self.body_h * 100))}%" for k, u in enumerate(used))
        if cover_end(self.paras()) is not None:  # 쪽 번호는 종이 차례(표지가 1쪽, 본문 쪽 번호는 2쪽부터 1로 찍힘)
            fill = "1쪽 표지" + fill[fill.index(","):] if "," in fill else "1쪽 표지"
        unknown = sorted(self.lay.m.unknown)
        msg = f"어림 쪽 수 {len(used)}쪽({fill})"
        if self.lay.split:
            paras = self.paras()
            names = ", ".join(f"‘{para_text(paras[s]).strip()[:12]}’" for s in self.lay.split)
            msg += (f" — 두 쪽에 걸친 □ 묶음 {len(self.lay.split)}개({names}): 줄 간격으로도 한 쪽에 안 들어가니 "
                    "그 묶음 글을 줄이거나 앞 묶음을 줄이세요")
        if unknown:
            msg += f" — 폭 표에 없는 글꼴({', '.join(unknown)})은 어림값으로 계산함"
        return msg
