# -*- coding: utf-8 -*-
"""기호로 쓴 계획 — 블록을 글 한 줄로 써도 되게 한다(문서 만드는 시간 줄이기, 사용자 2026-11-12 '보다 빠르고 정확한 스킬').

머리말·머리 기호를 보고 견본 문단을 도구가 고른다. like 번호를 찾아 적지 않아도 되고, 번호를 잘못 고를 일도 없다:
    "제목: ○○ 추진계획(안)"        제목 상자            "□ 추진배경"      큰 항목(Ⅰ. 장 제목도)
    "날짜: ’26. 11. 13.(금)\\t○○과 홍길동(053-803-○○○○)"   날짜·부서 줄
    "요약: …하고자 함"              요약 상자            "○ (현황) …"     중간 항목
    "[참고1] 세부 현황"             참고 머리표(새 쪽)     "- …"  "· …"     작은 항목
    "■ 표 제목" → 바로 다음 표 블록의 제목              "* …"  "※ …"     바로 위 ○·- 항목에 딸린 설명
    {"table": [[…], …]}             like 없는 표 블록 = 견본의 표(칸 수가 같은 표 먼저)
번호를 쓴 블록({"like": 7, …})은 그대로 둔다 — 섞어 써도 된다. build.Builder.build가 맨 먼저 expand_plan을 부른다.
"""
import os
import re

from analyze import guess_role
from build_base import DATE_LINE_RE, LABEL_RE, BuildError, number_family
from fit_base import cover_end
from hwpx_lib import (UNIT_RE, Package, T, cell_text, fake_label, marker_kind, marker_level, para_tables, para_text,
                      split_marker, table_grid)

HEAD_RE = re.compile(r"^\s*(제목|날짜|요약)\s*[:：]\s*(.*)$", re.S)
REF_RE = re.compile(r"^\s*\[\s*((?:참고|붙임|별첨|첨부)\s*\d*)\s*\]\s*(.*)$", re.S)
REF_WORDS = ("참고", "붙임", "별첨", "첨부")
NOTE_KINDS = ("주석(*)", "참고(※)")
HEAD_NAMES = {"제목": "제목 상자", "날짜": "날짜·부서 줄", "요약": "요약 상자"}


class Roles:
    """견본 문단마다 역할(양식 지도와 같은 짐작)을 붙여 두고, 기호에 맞는 문단 번호를 고른다."""

    def __init__(self, b):
        self.b = b
        self.protos = b.protos
        self.role, self.left, self.start, self.labeled = [], [], [], []
        for i, p in enumerate(self.protos):
            text = para_text(p)
            tables = para_tables(p)
            self.role.append(guess_role(p, b.styles, i, text, tables))
            pp = b.styles.para.get(p.get("paraPrIDRef"), {})
            left, intent = pp.get("left", 0), pp.get("intent", 0)
            self.left.append(left)
            self.start.append(left - intent if intent < 0 else left)  # 둘째 줄(글)이 시작하는 자리
            self.labeled.append(not tables and bool(LABEL_RE.match(split_marker(text)[2])))
        self.multi = {}  # 같은 기호 문단이 여럿이던 역할 → 고른 번호들(알림용)
        self.body0 = cover_end(self.protos) or 0  # 견본 첫 쪽이 표지면 본문이 시작하는 문단 번호

    def of(self, *roles):
        return [i for i, r in enumerate(self.role) if r in roles]

    def _note_pick(self, key, cands, idx):
        """고른 번호를 알림용으로 적어 둔다 — 모양(문단 모양·이름표 유무·표 칸 수)이 다른 문단이 섞인 기호만(같은 모양 여럿은 알릴 것 없음)."""
        def shape(i):
            p = self.protos[i]
            tbl = para_tables(p)
            return (self.b.styles.para_desc(p.get("paraPrIDRef")), self.labeled[i], tbl[0].get("colCnt") if tbl else None)

        if len({shape(i) for i in cands}) > 1:
            self.multi.setdefault(key, [])
            if idx not in self.multi[key]:
                self.multi[key].append(idx)
        return idx

    def _boxes(self):
        """한 칸 상자 문단(제목 상자·요약 상자·글 상자) 번호 — 표지가 있는 견본은 표지 쪽(제목 띠·개요 상자)을 뺀 본문부터.
        표지가 있는 만든 문서를 다시 견본으로 쓰면 앞 세 문단의 한 칸 표가 모두 '제목 상자'로 짐작돼 표지 제목 띠를 골랐음(검토 2026-11-12)."""
        return [i for i in self.of("제목 상자", "글 상자(1칸 표)") if i >= self.body0]

    def title(self):
        c = [i for i in self._boxes() if i <= self.body0 + 2]  # 본문 첫머리(쪽 설정 문단·빈 줄 다음까지)의 첫 상자
        return c[0] if c else None

    def date(self):
        for i, p in enumerate(self.protos):
            if i >= self.body0 and not para_tables(p) and DATE_LINE_RE.match(para_text(p)):
                return i
        c = [i for i, r in enumerate(self.role) if i >= self.body0 and r.startswith("오른쪽 정렬 줄")]
        return c[0] if c else None

    def summary(self):
        # 제목 상자 다음의 첫 한 칸 상자 — 날짜 줄이 없는 견본은 요약 상자가 둘째 문단이라 역할 짐작이 '제목 상자'로 나온다
        t = self.title()
        c = [i for i in self._boxes() if t is not None and i > t] or [i for i in self._boxes() if self.role[i] == "글 상자(1칸 표)"]
        return c[0] if c else None

    def item(self, mark, text, ctx):
        """머리 기호 mark로 시작하는 글 text에 맞는 견본 문단 번호(없으면 None). ctx: 바로 위 ○·- 문단 번호 또는 'table'."""
        kind = marker_kind(mark)
        cands = self.of(kind)
        fam = number_family(mark)
        if not cands and fam:
            cands = [i for i, p in enumerate(self.protos)
                     if not para_tables(p) and number_family(split_marker(para_text(p))[1]) == fam]
        if not cands:
            return None
        if kind in NOTE_KINDS:
            return self._note(cands, ctx)  # 위 항목에 따라 정해지는 것이라 '여럿' 알림에 넣지 않음
        body = split_marker(text)[2]
        lm = LABEL_RE.match(body)
        want = bool(lm) and not fake_label(lm.group("core"), body[lm.end():])
        same = [i for i in cands if self.labeled[i] == want]
        idx = self.common(same or cands)
        return self._note_pick(mark + ("(이름표)" if want and same else ""), cands, idx)

    def common(self, cands):
        """같은 기호 문단이 여럿이면 견본에서 가장 많이 쓴 문단 모양의 첫 문단(같으면 앞선 것) — 드문 모양이 먼저 나와도 대표를 고름."""
        desc = {i: self.b.styles.para_desc(self.protos[i].get("paraPrIDRef")) for i in cands}
        count = {}
        for i in cands:
            count[desc[i]] = count.get(desc[i], 0) + 1
        best = max(count.values())
        return next(i for i in cands if count[desc[i]] == best)

    def _note(self, cands, ctx):
        """*·※ 설명 문단: 바로 위 항목의 글 시작 자리에 왼쪽 여백이 가장 가까운 견본 문단(기본 양식 — ○ 아래 8·9번, - 아래 11·12번)."""
        if ctx == "table":
            zero = [i for i in cands if self.left[i] == 0]
            if zero:
                return zero[0]
        if isinstance(ctx, int):
            return min(cands, key=lambda i: (abs(self.left[i] - self.start[ctx]), i))
        inner = [i for i in cands if self.left[i] > 0] or cands
        return min(inner, key=lambda i: (self.left[i], i))

    def _grid(self, i):
        return table_grid(para_tables(self.protos[i])[0])

    def plain_tables(self):
        """줄·칸을 바꿔 쓸 수 있는 견본 표: 합친 칸 없는 두 줄 이상 표(도표·조문 상자·합친 머리 표는 줄을 다시 짤 수 없음)."""
        return [i for i in self.of("표") if len({r for r, *_ in self._grid(i)}) >= 2
                and not any(rs > 1 or cs > 1 for _, _, rs, cs, _ in self._grid(i))]

    def table(self, cols=None, any_table=False):
        """데이터 표로 쓸 견본 표: 합친 칸 없는 두 줄 이상 표 가운데 칸 수가 같은 것 먼저, 없으면 첫 표. 그런 표가 없으면 None
        (any_table — 도표처럼 표를 통째로 다시 짜는 블록 — 이면 아무 표나)."""
        pool = self.plain_tables() or (self.of("표") if any_table else [])
        if not pool:
            return None
        exact = [i for i in pool if cols and int(para_tables(self.protos[i])[0].get("colCnt", "0")) == cols]
        return self._note_pick("표", pool, (exact or pool)[0])

    def ref(self):
        c = self.of("참고 머리표")
        return c[0] if c else None

    def ref_cells(self, i):
        """참고 머리표의 (머리표 칸, 제목 칸) 열쇠 '줄,칸'."""
        cells = [(r, c, cell_text(tc).strip()) for r, c, _, _, tc in self._grid(i)]
        label = next(((r, c) for r, c, t in cells if t.replace(" ", "")[:2] in REF_WORDS), cells[0][:2])
        rest = [(r, c, t) for r, c, t in cells if (r, c) != label]
        title = next(((r, c) for r, c, t in reversed(rest) if t), rest[-1][:2] if rest else label)
        return f"{label[0]},{label[1]}", f"{title[0]},{title[1]}"

    def marks(self):
        """견본에 있는 머리 기호와 그 문단 번호 — 없는 기호를 썼을 때 안내용."""
        seen = {}
        for i, p in enumerate(self.protos):
            if para_tables(p):
                continue
            mark = split_marker(para_text(p))[1]
            if mark and mark != "■" and mark not in seen:
                seen[mark] = i
        return ", ".join(f"{m}({i}번)" for m, i in seen.items()) or "없음"


def _is_table_block(blk):
    return isinstance(blk, dict) and ("table" in blk or "flow" in blk)


_BASIC_SECTION = []


def _is_bundled_basic(pkg):
    """견본이 이 스킬의 기본 양식 그대로인가(본문 XML 바이트가 같음). 기본 양식은 견본이 아니라 사용자 원칙을 따른다
    (따르는 차례: 요청 → 견본 → 원칙 — 사용자 2026-11-12)."""
    if not _BASIC_SECTION:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "assets", "basic_report.hwpx")
        basic = Package(path)
        _BASIC_SECTION.append(basic.data.get(basic.sections()[0]))
    secs = pkg.sections()
    return bool(secs) and pkg.data.get(secs[0]) == _BASIC_SECTION[0]


def _blank_proto(p):
    return not para_tables(p) and not para_text(p).strip() and next(p.iter(T("hp:pic")), None) is None


def expand_plan(plan, b):
    """글로 쓴 블록·like 없는 표 블록을 번호 블록으로 바꾼 계획을 돌려준다(없으면 받은 그대로). b는 Builder."""
    blocks = plan.get("blocks") if isinstance(plan, dict) else plan
    if not isinstance(blocks, list):
        return plan
    if not any(isinstance(x, str) or (_is_table_block(x) and "like" not in x) for x in blocks):
        return plan
    roles = Roles(b)
    how = "{\"like\": 번호, \"text\": …}"
    out, ctx, in_body, pending = [], None, False, {}
    keep_head_blanks = not _is_bundled_basic(b.pkg)  # 올린 견본의 날짜 줄·요약 상자 사이 빈 줄은 견본대로 둔다

    def flush_pending(n, blk=None):
        """■ 제목 줄·(단위 : …) 줄은 바로 다음 표 블록의 title·unit으로."""
        nonlocal pending
        if not pending:
            return blk
        like = blk.get("like") if isinstance(blk, dict) else None
        # 표 블록: table·flow 블록, 또는 번호로 고른 견본 표의 칸만 채우는 블록({"like": 14, "cells": …})
        is_table = _is_table_block(blk) or (isinstance(like, int) and not isinstance(like, bool)
                                           and 0 <= like < len(roles.protos) and roles.role[like] == "표")
        if blk is None or not is_table:
            k, (src, text) = next(iter(pending.items()))
            name = "■ 표 제목 줄" if k == "title" else "표 위 기준·단위 줄"
            raise BuildError(f"블록 {src}: {name}(‘{text[:20]}’) 바로 다음에는 표 블록({{\"table\": [[…], …]}})이 와야 합니다.")
        for k, (src, text) in pending.items():
            if not blk.get(k):
                blk = dict(blk, **{k: text})
        pending = {}
        return blk

    for n, blk in enumerate(blocks, 1):
        where = f"블록 {n}"
        if isinstance(blk, dict):
            if _is_table_block(blk) and "like" not in blk:
                rows = blk.get("table")
                cols = max((len(r) for r in rows if isinstance(r, list)), default=None) if isinstance(rows, list) else None
                i = roles.table(cols, any_table="flow" in blk)
                if i is None:
                    raise BuildError(f"{where}: 견본에 줄·칸을 바꿔 쓸 표(합친 칸 없는 두 줄 이상 표)가 없어 표 블록을 넣을 수 없습니다 — "
                                     "그런 표가 든 견본을 쓰거나 글로 쓰세요(견본 표의 칸만 채우려면 {\"like\": 번호, \"cells\": …}).")
                blk = dict(blk, like=i)
            blk = flush_pending(n, blk)
            out.append(dict(blk, _src=n))
            like = blk.get("like")
            if isinstance(like, int) and not isinstance(like, bool) and 0 <= like < len(roles.protos):
                proto = roles.protos[like]
                if para_tables(proto):
                    ctx = "table" if roles.role[like] == "표" else ctx
                else:  # 글을 주지 않은 블록(견본 문단 그대로 복사)도 그 문단의 기호로 맥락을 잇는다 — 빈 줄(기호 없음)은 그대로
                    lv = marker_level(para_text(proto))
                    in_body = in_body or lv == 1
                    ctx = like if lv in (2, 3) else None if lv == 1 else ctx
            continue
        if not isinstance(blk, str):
            out.append(blk)  # 모양이 틀린 블록 — check_plan이 쉬운 말로 알림
            continue
        s = blk
        if not s.strip():  # 빈 글 = □ 블록 사이 빈 줄(도구가 스스로 넣으므로 보통은 쓸 일이 없음)
            flush_pending(n)
            sp = b._block_spacer()
            if sp is not None:
                out.append({"like": sp, "_src": n})
            continue
        m = None if in_body else HEAD_RE.match(s)
        if m:
            flush_pending(n)
            key, val = m.group(1), m.group(2).strip(" ")
            idx = {"제목": roles.title, "날짜": roles.date, "요약": roles.summary}[key]()
            if idx is None:
                raise BuildError(f"{where}: 견본에서 {HEAD_NAMES[key]} 자리를 찾지 못했습니다 — 양식 지도(analyze.py)에서 "
                                 f"그 문단 번호를 찾아 {how} 꼴로 쓰세요.")
            # 바로 앞 머리 블록(제목·날짜)과 이 머리 블록 사이의 견본 문단이 모두 빈 줄이면 견본처럼 그 빈 줄을 둔다
            # (예: 날짜 줄과 요약 상자 사이 좁은 빈 줄 — 기본 양식은 원칙대로 '사이 빈 줄 없이')
            prev = out[-1].get("like") if out and isinstance(out[-1], dict) and out[-1].get("_head") else None
            if keep_head_blanks and isinstance(prev, int) and prev + 1 < idx \
                    and all(_blank_proto(roles.protos[k]) for k in range(prev + 1, idx)):
                out[-1] = {k: v for k, v in out[-1].items() if k != "_head"}
                out += [{"like": k, "_src": n} for k in range(prev + 1, idx)]
            out.append({"like": idx, "text": val, "_src": n, "_head": True})
            continue
        m = REF_RE.match(s)
        if m:
            flush_pending(n)
            idx = roles.ref()
            if idx is None:
                raise BuildError(f"{where}: 견본에 참고 머리표(‘참고1’ 칸이 든 한 줄 표)가 없습니다 — 참고 쪽 제목은 견본의 "
                                 f"제목 모양 문단을 골라 {how} 꼴로 쓰세요.")
            label, title = roles.ref_cells(idx)
            cells = {label: re.sub(r"\s+", "", m.group(1))}
            if title != label:
                cells[title] = m.group(2).strip()
            out.append({"like": idx, "cells": cells, "page_break": True, "_src": n})
            ctx, in_body = None, True
            continue
        if UNIT_RE.match(s):
            pending["unit"] = (n, s.strip())
            continue
        pre, mark, body = split_marker(s)
        if mark == "■":
            pending["title"] = (n, body.strip())
            continue
        flush_pending(n)
        if not mark:
            raise BuildError(f"{where}: 머리 기호 없는 글(‘{s.strip()[:20]}’)은 어느 견본 문단에 넣을지 알 수 없습니다 — "
                             f"□ ○ - · * ※ 기호(또는 맨 앞의 제목:·날짜:·요약:)로 시작하거나 {how} 꼴로 쓰세요.")
        idx = roles.item(mark, s, ctx)
        if idx is None:
            raise BuildError(f"{where}: 견본에 ‘{mark}’ 기호 문단이 없습니다(견본에 있는 기호: {roles.marks()}) — "
                             f"있는 기호로 바꿔 쓰거나 {how} 꼴로 쓰세요.")
        # 번호(1. 가. ①)는 글의 번호를 살리게 그대로, 기호는 견본 기호를 쓰게 내용만 넘긴다(● → 견본의 ○). 다만 내용이 또 기호·번호로
        # 시작하면('○ 1. 단계별 추진') 견본 문단의 기호를 앞에 붙여 넘긴다 — 내용만 넘기면 글 넣기가 '1.'을 머리 기호로 보고 떼어 냄
        # (검토 2026-11-12). 글 넣기는 견본과 같은 기호를 한 번만 뗀다
        pmark = split_marker(para_text(roles.protos[idx]))[1]
        text = s.strip(" ") if number_family(mark) else (f"{pmark} {body}" if pmark and split_marker(body)[1] else body)
        out.append({"like": idx, "text": text, "_src": n})
        lv = marker_level(s)
        in_body = in_body or lv == 1
        ctx = idx if lv in (2, 3) else None if lv == 1 else ctx
    flush_pending(len(blocks))
    if roles.multi:
        picked = ", ".join(f"{k} → {'·'.join(map(str, v))}번" for k, v in roles.multi.items())
        b.warn(f"기호로 쓴 블록은 견본에서 같은 기호 문단을 골랐습니다(같은 기호 문단이 여럿인 것: {picked}) — "
               "다른 모양을 쓰려면 그 블록만 {\"like\": 번호, …}로.")
    out = [{k: v for k, v in x.items() if k != "_head"} if isinstance(x, dict) else x for x in out]
    return dict(plan, blocks=out) if isinstance(plan, dict) else out
