# -*- coding: utf-8 -*-
"""표 맞춤(Fitter의 일부): 칸 너비·글자 크기·줄 균형·정렬·■ 제목·단위 줄·표 아래 ※·그림 칸."""
from fit_base import *  # noqa: F401,F403 — 상수·공통 함수(HWPUNIT_PER_MM, T, re, copy …)


class TableFit:
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
        info = None if tbl in self.b.fixed_widths else self._borrow_cells(tbl)  # 사용자가 준 너비는 빌리지 않음
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

    def _body_size(self):
        """표 글자의 기준인 본문 글자 크기(pt): 계획의 "body_pt"(사용자가 따로 정했을 때), 없으면 BODY_PT(14pt) — 견본 글자
        크기와 상관없이(사용자 2026-11-05 '별도의 지시가 없을시 기준은 14pt'). 표 글자는 여기서 TABLE_BODY_GAP만큼 작게."""
        return int(getattr(self.b, "body_pt", None) or BODY_PT)

    def _fit_font(self, tbl, grid, n, merged, total, cur, width):
        """표 글자 크기(사용자 원칙 2026-11-05 '표 안의 글씨는 본문보다 3포인트 작다 … 표를 한장에 넣기위해 줄이는 경우말고는
        유지'): 본문 글자(_body_size)보다 TABLE_BODY_GAP(3pt) 작게 고정한다 — 칸 글이 다음 줄로 넘어간다고 줄이지 않고
        칸 너비·한 줄로 입력으로 맞춘다(옛 '10pt까지 줄여 보기'는 없앰). 한 장에 넣으려고 줄이는 만큼은 fit_long_tables가
        page_shrink에 적는다. 머리 줄·내용 줄을 같은 만큼 바꾼다. (이전 크기, 고른 크기) 또는 None."""
        if not self._is_data_table(tbl):
            return None
        main = self._main_size(tbl)
        if not main:
            return None
        want = self._body_size() - TABLE_BODY_GAP - getattr(self, "page_shrink", {}).get(tbl, 0)
        keep = getattr(self, "keep_table_pt", None)
        if keep and keep <= main < want:
            return main, main  # 만들 때 한 장에 넣으려 줄인 표 글자(표시 table_pt) — 다시 재도 키우지 않음(평가 2026-11-09)
        if want != main:
            for r in self._table_runs(tbl):
                r.set("charPrIDRef", self.b.hedit.char_size(r.get("charPrIDRef"), want - main))
        return main, want

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

    def relieve_pads(self, refit=True):
        """칸 여백을 넓혀 □ 묶음이 두 쪽에 걸치게 되면(아주 공간이 없는 경우 — 사용자 원칙 2026-11-01) 그 묶음 안 표의
        칸 여백을 원래대로 되돌리고 쪽 맞춤을 다시 한다. refit=False(다듬기)면 쪽 맞춤은 다시 하지 않는다 — 다듬기는 쪽 짜임
        (쪽 나눔·빈 줄)을 바꾸지 않는다(쪽 맞춤이 빈 줄을 지워 문단 차례가 밀린 일, 2026-11-04)."""
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
        split0 = set(self.lay.split)
        for s0 in sorted(split0):
            e0 = next((h for h in starts if h > s0), len(paras))
            tbls = [t for p in paras[s0:e0] for t in para_tables(p) if t in pad]
            # 넓힌 여백 때문에 걸친 것인지 재 본다 — 되돌려도 그대로 걸치면 여백은 그대로 둠(옛 판은 원인과 상관없이 1.2mm를 되돌렸음, 평가 2026-11-09)
            now = [(el, k, el.get(k)) for t in tbls for el, k, _ in pad[t]]
            for t in tbls:
                for el, k, v in pad[t]:
                    el.set(k, v)
            self.lay.paginate(paras, self.body_w, self.body_h - SAFETY, heads, BLOCK_GAP)
            if s0 in self.lay.split:
                for el, k, v in now:
                    el.set(k, v)
                continue
            for t in tbls:
                undone += len(pad.pop(t))
        if undone and refit:
            self.fit_pages()
            self.notes.append("칸 여백을 넓히면 □ 묶음이 두 쪽에 걸치는 곳은 그 묶음 표의 칸 여백을 원래대로 두었습니다(공간이 모자람).")

    def _neg_triangles(self, tcs):
        """금액 칸의 줄어든 값 '-40,000' → '△40,000'(사용자 2026-11-04 '감소를 삼각형으로 표현한 것은 아주 좋습니다').
        혼자 있는 '-'(값 없음)는 그대로. 바꾼 칸 수."""
        n = 0
        for tc in tcs:
            for cp in cell_paras(tc):
                for r in para_runs(cp):
                    t = run_text(r)
                    if len(r) == 1 and NEG_AMOUNT_RE.match(t.strip()):
                        set_run_text(r, t.replace(t.strip(), NEG_AMOUNT_RE.sub("△", t.strip()), 1), self.b.tab_proto)
                        n += 1
        return n

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

    def _box_blanks(self, tbl, grid):
        """제목 걸친 상자 본문 칸(법령 조문 발췌 등)의 빈 줄을 뺀다(사용자 2026-11-05 참고1 근거법령 사진 '그림에 빈줄도 필요없애자'
        — 조문과 ⑪ 항 사이 빈 줄). 글이 든 문단은 그대로, 문단 하나는 남긴다. 뺀 빈 줄 수."""
        cap = self._caption_content(tbl, grid)
        if cap is None:
            return 0
        paras = cell_paras(cap)
        empty = [cp for cp in paras if not para_text(cp).strip() and not para_tables(cp) and not para_pics(cp)]
        if len(empty) == len(paras):
            empty = empty[1:]
        for cp in empty:
            cp.getparent().remove(cp)
        return len(empty)

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
        if om is None:
            return 0
        if not text:  # 표 뒤 □ 사이 빈 줄: 표 아랫선과 다음 □가 붙지 않게 조금 띄움(사용자 2026-11-05)
            if is_blank(nxt) and tbl not in self.b.flow_tables and int(om.get("bottom", "0")) < TABLE_AFTER - 1:
                om.set("bottom", str(int(round(TABLE_AFTER))))
                return 3
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

    def _fit_title(self, p, tbl, size):
        """표 위 ■ 제목 줄(기준·단위 줄 위, 사용자 원칙 2026-11-04 — '이 표는 제목이 없군요 앞으로는 ■ 네모로 제목을'):
        표 머리 칸 글꼴(맑은 고딕 굵게)로 표 글자보다 1pt 크게, 왼쪽 정렬, 위 6pt, 줄 간격 TITLE_LINE(단위 줄이 제목 쪽으로 붙음 —
        사용자 '단위높이를 살짝 줄이면', '70-80%'). 제목이 길어 오른쪽 끝 단위와 부딪힐 만하면 그 줄만 100%. 맞췄으면 1."""
        prev = p.getprevious()
        while prev is not None and (prev.tag != T("hp:p") or (not para_tables(prev) and UNIT_RE.match(para_text(prev)))):
            prev = prev.getprevious()
        if prev is None or not is_table_title(prev) or not size:
            return 0
        grid = table_grid(tbl)
        head = next((r for *_, tc in grid for cp in cell_paras(tc) for r in para_runs(cp)
                     if r.find(T("hp:t")) is not None and run_text(r).strip()), None)
        if head is None:
            return 0
        cid = head.get("charPrIDRef")
        text = para_text(prev)
        self.b._split_run_at(prev, text.index(TABLE_TITLE_MARK) + 1)  # ■ 기호를 따로 떼어 작게
        pos = 0
        for r in para_runs(prev):
            t = run_text(r)
            if r.find(T("hp:t")) is not None:
                mark = pos <= text.index(TABLE_TITLE_MARK) < pos + len(t) and not t.replace(TABLE_TITLE_MARK, "").strip()
                r.set("charPrIDRef", self.b.hedit.char_like(cid, cid, size + TITLE_UP - (TITLE_MARK_DOWN if mark else 0)))
            pos += len(t)
        width = self.lay.table_width(tbl)
        title_w = sum(c[1] for c in self.lay.chars(prev))
        nxt = prev.getnext()
        while nxt is not None and nxt.tag != T("hp:p"):
            nxt = nxt.getnext()
        has_unit = nxt is not None and not para_tables(nxt) and bool(UNIT_RE.match(para_text(nxt)))
        unit_w = sum(c[1] for c in self.lay.chars(nxt)) if has_unit else 0
        if title_w > width:
            self.long_titles.append(para_text(prev).lstrip(" ■")[:14])
        if not has_unit:
            line = None  # 단위 줄이 없으면 줄 간격을 줄이지 않는다 — 표 윗선이 제목 글자 아래를 가림(한글 실측 2026-11-04)
        else:
            line = TITLE_LINE if title_w + unit_w + 3 * HWPUNIT_PER_MM <= width else 100
        pid = self.b.hedit.para_align(prev.get("paraPrIDRef"), "LEFT")
        above = prev.getprevious()
        while above is not None and above.tag != T("hp:p"):
            above = above.getprevious()
        tight = (above is not None and not para_tables(above) and para_text(above).strip()
                 and prev.get("pageBreak") != "1")  # 바로 위가 글 줄 — 제목이 글에 붙지 않게 조금 더 띄움
        pid = self.b.hedit.para_margin(pid, "prev", TITLE_PREV_TEXT if tight else TITLE_PREV)
        if not has_unit:
            pid = self.b.hedit.para_margin(pid, "next", TITLE_NEXT)  # 단위 줄이 없으면 표에 너무 붙지 않게
        prev.set("paraPrIDRef", self.b.hedit.para_line(pid, line) if line else pid)
        return 1

    def _figure_cells(self, tbl):
        """그림 상자의 그림 칸 목록 — 한 줄의 칸이 모두 그림(배경 그림을 넣은 칸 또는 칸 모양에 그림 채우기가 든 칸)인 줄들의 칸.
        한 열 그래프 상자도, 캡처 두 장을 나란히 둔 두 열 표도 해당(쪽 맞춤에서 높이를 줄여 볼 수 있게 — 2026-11-05). 글 칸이 섞인 줄은 뺀다."""
        hdr = self.b.pkg.xml("Contents/header.xml")
        fills = {bf.get("id"): bf for bf in hdr.iter(T("hh:borderFill"))}

        def is_img(tc):
            bf = fills.get(tc.get("borderFillIDRef"))
            return tc in self.b.image_cells or (bf is not None and bf.find(".//" + T("hc:img")) is not None)

        rows = {}
        for r, c, rs, cs, tc in table_grid(tbl):
            rows.setdefault(r, []).append((rs, tc))
        out = []
        for r in sorted(rows):
            cells = [tc for rs, tc in rows[r] if rs == 1]
            if cells and len(cells) == len(rows[r]) and all(is_img(tc) for tc in cells):
                out.extend(cells)
        return out

    def _figure_sides(self, tbl):
        """그래프 상자(그림 칸이 든 한 열 표)는 양옆에 선을 두른다(사용자 결정 2026-11-04 '2가' — 한 열 표가 견본 첫 열 칸
        모양을 받아 왼쪽 선 없이 오른쪽 선만 남던 것). 선 모양은 그 칸의 위·아래 가는 선과 같게. 바꿨으면 1."""
        if tbl.get("colCnt") != "1":
            return 0
        hdr = self.b.pkg.xml("Contents/header.xml")
        fills = {bf.get("id"): bf for bf in hdr.iter(T("hh:borderFill"))}
        cells = [tc for *_, tc in table_grid(tbl)]
        if not any(fills.get(tc.get("borderFillIDRef")) is not None
                   and fills[tc.get("borderFillIDRef")].find(".//" + T("hc:img")) is not None for tc in cells):
            return 0
        done = 0
        for tc in cells:
            bf = fills.get(tc.get("borderFillIDRef"))
            if bf is None:
                continue
            sides = {k: bf.find(T("hh:" + k)) for k in ("leftBorder", "rightBorder", "bottomBorder", "topBorder")}
            if all(sides[k] is not None and sides[k].get("type") != "NONE" for k in ("leftBorder", "rightBorder")):
                continue
            ref = next((sides[k] for k in ("bottomBorder", "topBorder", "rightBorder")
                        if sides[k] is not None and sides[k].get("type") != "NONE" and sides[k].get("width") == "0.12 mm"), None)
            line = (ref.get("type"), ref.get("width"), ref.get("color")) if ref is not None else ("SOLID", "0.12 mm", "#000000")
            tc.set("borderFillIDRef", self.b.hedit.border_sides(tc.get("borderFillIDRef"),
                                                                {"leftBorder": line, "rightBorder": line}))
            done = 1
        return done

    def _unit_money(self, p):
        """표 문단 p 바로 위 기준·단위 줄이 금액 단위('(단위 : 천원)'·'백만원'·'억원'·'원')인가."""
        prev = p.getprevious()
        while prev is not None and (prev.tag != T("hp:p") or (not para_tables(prev) and UNIT_RE.match(para_text(prev)))):
            if prev.tag == T("hp:p") and MONEY_UNIT_RE.search(para_text(prev)):
                return True
            prev = prev.getprevious()
        return False

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
        text_gaps = titles = figures = box_blanks = 0
        self.long_titles = []
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
                box_blanks += self._box_blanks(tbl, grid)
                grid = table_grid(tbl)
                padded += self._cell_pad(tbl)
                figures += self._figure_sides(tbl)
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
                if tbl in self.b.flow_tables or tbl in self.b.fixed_widths:  # 투명 선 도표·사용자가 준 너비: 칸 비율 그대로(끝선만 맞춤)
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
                self._narrow_cells(tbl, table_grid(tbl), self.lay.table_width(tbl))
                captions += self._caption_box(tbl, table_grid(tbl), self.lay.table_width(tbl))
                images += self._image_layout(tbl, table_grid(tbl), self.lay.table_width(tbl))
                # 숫자 열(내용 칸 대부분이 숫자·날짜)의 숫자 칸: 금액과 수량 숫자(대수·건수·명·%·쪽 수 등)는 오른쪽 정렬 + 오른쪽
                # 1.5mm(자릿수가 위아래로 맞게 — 사용자 2026-11-05 '대수·건수·명·%도 오른쪽', 옛 2026-10-31 '금액 아닌 숫자는 가운데'를
                # 바꿈). 날짜·기간(시기·기한) 열과 연번·연도 같은 번호 열은 가운데. 글이 섞인 열의 숫자 하나는 그대로.
                cols_cells, heads = {}, {}
                for r, c, rs, cs, tc in grid:
                    if r == 0 or tc.get("header") == "1":  # 머리 칸(두 줄 머리면 아랫줄 '국비·시비'도)은 열 이름으로
                        for k in range(c, c + cs):
                            heads[k] = (heads.get(k, "") + " " + " ".join(para_text(cp) for cp in cell_paras(tc))).strip()
                    elif cs == 1:
                        cols_cells.setdefault(c, []).append(tc)
                unit_money = self._unit_money(p)
                money_cols = set()
                for c, tcs in cols_cells.items():
                    texts = [para_text(cp).strip() for tc in tcs for cp in cell_paras(tc)]
                    nums = [t for t in texts if t and (NUMERIC_RE.match(t) or DATE_RE.match(t))]
                    head = re.sub(r"[\s⎵⍽]", "", heads.get(c, ""))
                    bare = [t for t in texts if t and BARE_NUM_RE.match(t)]
                    if (bool(AMOUNT_HEAD_RE.search(head)) or any(AMOUNT_CELL_RE.search(t) for t in nums)
                            or (unit_money and bare and len(bare) >= 0.6 * len(nums) and not ID_HEAD_RE.search(head)
                                and not RATE_HEAD_RE.search(head))):
                        money_cols.add(c)
                for c, tcs in cols_cells.items():
                    texts = [para_text(cp).strip() for tc in tcs for cp in cell_paras(tc)]
                    filled = [t for t in texts if t and t not in ("-", "–")]
                    nums = [t for t in filled if NUMERIC_RE.match(t) or DATE_RE.match(t)]
                    if not filled or len(nums) < 0.6 * len(filled):
                        continue
                    head = re.sub(r"[\s⎵⍽]", "", heads.get(c, ""))
                    money = (c in money_cols
                             or (bool(money_cols) and bool(CHANGE_HEAD_RE.search(head)) and not RATE_HEAD_RE.search(head)))
                    if money:
                        self._neg_triangles(tcs)
                    qty = [t for t in filled if NUMERIC_RE.match(t)]  # 날짜·기간('’26년'·'11월'·'12. 24.')이 아닌 수량 숫자
                    right = money or (len(qty) >= 0.6 * len(filled) and not ID_HEAD_RE.search(head))
                    for tc in tcs:
                        for cp in cell_paras(tc):
                            t = para_text(cp).strip()
                            # 숫자 칸의 '-'도 같은 쪽으로. 가운데 열(날짜·번호)의 짧은 말('상시'·'확인')도 가운데로 맞춰 열을 가지런히
                            if BULLET_RE.match(t):
                                continue  # 글머리표 줄은 왼쪽 정렬 그대로(_bullet_cells)
                            if (NUMERIC_RE.match(t) or DATE_RE.match(t) or t in ("-", "–", "―")
                                    or (not right and t and len(t) <= 6)):
                                pid = self.b.hedit.para_align(cp.get("paraPrIDRef"), "RIGHT" if right else "CENTER")
                                if right:  # 금액·수량은 오른쪽 정렬, 오른쪽 끝에 약간 띄움(사용자 원칙 2026-11-01·2026-11-05)
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
                titles += self._fit_title(p, tbl, self._main_size(tbl))
                g = self._note_gap(p, tbl)
                notes += g == 1
                text_gaps += g == 2
                note_font += self._fit_notes(p, tbl)
        self.notes[:] = [m for m in self.notes if "표 제목이 한 줄을 넘" not in m]
        if self.long_titles:
            self.notes.append(fix_note(f"표 제목이 한 줄을 넘습니다 — {len(self.long_titles)}개(" + ", ".join(f"‘{t}…’" for t in self.long_titles[:3])
                              + "): ■ 제목은 표 폭 안 한 줄로 줄이세요(기준일·출처는 단위 줄이나 표 아래 ※로).", "table_title"))
        if again:  # 두 번째 적용: 한 일은 첫 번째 알림에 있고, '남은 칸' 알림만 마지막 상태로 바꿔 적는다
            self.notes[:] = [m for m in self.notes if "다음 줄로 넘어가는 칸이 남았습니다" not in m and "칸보다 긴 낱말" not in m]
            if left:  # (한 장에 넣으려고 표 글자를 줄인 것은 fit_long_tables가 알림)
                self.notes.append(fix_note(f"표 {len(left)}개는 다음 줄로 넘어가는 칸이 남았습니다(표 글자는 본문보다 {TABLE_BODY_GAP}pt 작게 "
                                  "그대로) — 칸 글을 줄이거나 칸을 합치면 한 줄로 들어갑니다: " + ", ".join(f"‘{t}’" for t in left)))
            if cut_words:
                self.notes.append(fix_note(f"칸보다 긴 낱말 {len(cut_words)}개는 한글이 글자 단위로 끊습니다(단어로 끊기 어긋남) — "
                                  "띄어 쓸 수 있는 말이면 띄우거나 줄이세요: " + ", ".join(f"‘{w}’" for w in cut_words)))
            return
        msg = []
        if edge:
            msg.append(f"표 {edge}개의 왼쪽·오른쪽 끝을 본문 폭에 맞췄습니다(끝선 맞추기)")
        if shrunk:
            msg.append(f"표 {len(shrunk)}개는 표 글자를 본문보다 {TABLE_BODY_GAP}pt 작게 맞췄습니다("
                       + ", ".join(sorted({f"{a}→{b}pt" for a, b in shrunk})) + ")")
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
        if box_blanks:
            msg.append(f"제목 걸친 상자(조문 발췌 등) 안 빈 줄 {box_blanks}개를 뺐습니다")
        if notes:
            msg.append(f"표 바로 뒤 ※가 붙는 표 {notes}개는 표 아래를 {NOTE_GAP / HWPUNIT_PER_MM:.1f}mm 띄웠습니다")
        if titles:
            msg.append(f"■ 표 제목 {titles}줄은 표 글꼴 굵게·표 글자보다 {TITLE_UP}pt 크게, 단위 줄이 제목 쪽으로 붙게 맞췄습니다")
        if figures:
            msg.append(f"그래프 상자(그림 칸이 든 한 열 표) {figures}개는 양옆에 선을 둘렀습니다")
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
            self.notes.append(fix_note(f"한 열에 세 가지 정보가 든 머리 칸 {len(three_info)}개({', '.join(sorted(set(three_info))[:4])}): "
                              "내용·배점·부서처럼 세 가지를 한 열에 넣으면 분잡합니다 — 부서는 같은 종류(담당 부서) 열과 합치거나 "
                              "따로 열로 두세요(배점은 '지표(배점)'처럼 이름 뒤 괄호로)."))
        if msg:
            self.notes.append("; ".join(msg) + ".")
        if left:
            self.notes.append(fix_note(f"표 {len(left)}개는 다음 줄로 넘어가는 칸이 남았습니다(표 글자는 본문보다 {TABLE_BODY_GAP}pt 작게 "
                              "그대로) — 칸 글을 줄이거나 칸을 합치면 한 줄로 들어갑니다: " + ", ".join(f"‘{t}’" for t in left)))
        if cut_words:
            self.notes.append(fix_note(f"칸보다 긴 낱말 {len(cut_words)}개는 한글이 글자 단위로 끊습니다(단어로 끊기 어긋남) — "
                              "띄어 쓸 수 있는 말이면 띄우거나 줄이세요: " + ", ".join(f"‘{w}’" for w in cut_words)))

    def _narrow_cells(self, tbl, grid, total):
        """칸 안 여백 + 1mm보다 좁은 칸은 한글이 넓혀 표가 튀어나온다 — 너비를 어느 길로 정했든 마지막에 잰다(옛 판은 너비를 다시 나눌 때만 재서
        40열 표가 그대로 남음, 평가 2026-11-09). 넓은 칸에서 덜어 오고, 그래도 모자라면 칸 안 여백을 줄여 표 폭에 넣은 뒤 '고쳐야 함'으로
        (표를 나누거나 가로 쪽). 계획의 widths로 준 표는 너비를 바꾸지 않고 알리기만. 도표·합친 칸 표는 뺌."""
        if tbl in self.b.flow_tables or any(rs > 1 or cs > 1 for _, _, rs, cs, _ in grid):
            return
        n = int(tbl.get("colCnt", "1"))
        first = {c: tc for r, c, _, _, tc in grid if r == 0}
        if n <= 1 or len(first) != n:
            return
        ws = [int(first[c].find(T("hp:cellSz")).get("width", "0")) for c in range(n)]
        needs = [self._cell_margin(tbl, first[c]) + 282 for c in range(n)]
        if all(w >= q for w, q in zip(ws, needs)):
            return
        name = (" ".join(para_text(cp) for cp in cell_paras(first[0])) or "표").strip()[:8]
        if tbl in self.b.fixed_widths:
            msg = f"계획의 widths로 준 칸이 칸 안 여백보다 좁아 한글이 넓힙니다(표 ‘{name}…’) — widths를 고치세요."
            if msg not in self.notes:
                self.notes.append(fix_note(msg))
            return
        if sum(needs) > total:
            for _, _, _, _, tc in grid:
                tc.set("hasMargin", "1")
                cm = tc.find(T("hp:cellMargin"))
                if cm is None:
                    cm = etree.SubElement(tc, T("hp:cellMargin"))
                    for k in ("top", "bottom"):
                        cm.set(k, "141")
                cm.set("left", str(CELL_MARGIN_MIN))
                cm.set("right", str(CELL_MARGIN_MIN))
            msg = (f"열이 많아 칸이 좁은 표 ‘{name}…’({n}열) — 칸 안 여백을 줄여 표 폭에 넣었습니다. 글자가 빽빽하니 표를 나누거나 "
                   "가로 쪽 문서로 만드세요.")
            if msg not in self.notes:
                self.notes.append(fix_note(msg))
            needs = [self._cell_margin(tbl, first[c]) + 282 for c in range(n)]
        if sum(needs) <= total:
            self._set_widths(tbl, grid, [max(w, 1) for w in ws], total)

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
