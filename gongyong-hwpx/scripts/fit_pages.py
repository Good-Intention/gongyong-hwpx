# -*- coding: utf-8 -*-
"""쪽 맞춤(Fitter의 일부): □·○ 묶음 한 쪽에, 줄 간격·빈 줄·그래프 높이, 한 쪽 넘는 표, 빈 쪽 채우기, 참고 쪽 채우기."""
from fit_base import *  # noqa: F401,F403 — 상수·공통 함수(HWPUNIT_PER_MM, T, re, copy …)


class PageFit:
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
            is_head = ((marker_level(para_text(p)) == 1 and not is_table_title(p)) if not tables
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
            figs = [(t, cells) for p in seg for t in para_tables(p) for cells in [self._figure_cells(t)] if cells]
            fig_h = {el: int(el.find(T("hp:cellSz" if el.tag == T("hp:tc") else "hp:sz")).get("height", "0"))
                     for t, cells in figs for el in [t, *cells]}

            def restore():
                for p, (pid, cids) in saved.items():
                    p.set("paraPrIDRef", pid)
                    for r, c in zip(para_runs(p), cids):
                        r.set("charPrIDRef", c)
                for el, h in fig_h.items():
                    el.find(T("hp:cellSz" if el.tag == T("hp:tc") else "hp:sz")).set("height", str(h))

            def shrink_fig(t, cells, pct):
                # 표가 한두 줄 넘쳐 거의 빈 쪽이 생길 때는 그 묶음의 그래프 높이를 줄인다(사용자 2026-11-04
                # '이럴땐 그래프의 높이를 줄이면 되죠') — 그림 칸(크기에 맞춤 채우기)만 낮추고 그래프 제목 칸·너비는 그대로
                cut = 0
                for tc in cells:
                    h = fig_h[tc]
                    new = int(round(h * (100 - pct) / 100))
                    tc.find(T("hp:cellSz")).set("height", str(new))
                    cut += h - new
                t.find(T("hp:sz")).set("height", str(fig_h[t] - cut))

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

            def shrink_spacers2():
                # 그래도 모자라면 □ 사이 빈 줄을 70%까지 — 표 위·아래 여백은 지키고 위쪽을 줄임(사용자 2026-11-05)
                for p in spacers:
                    pid = saved[p][0]
                    if self.st.para.get(pid, {}).get("line_type") == "PERCENT" and \
                            self.st.para.get(pid, {}).get("line", 0) > SPACER_LINE2:
                        p.set("paraPrIDRef", self.b.hedit.para_line(pid, SPACER_LINE2))

            def halve_prev():
                # ○ 위 간격(묶음 구분)을 절반으로 — 표 제목·표 아래 여백보다 먼저 양보
                for p in texts:
                    pid = p.get("paraPrIDRef")
                    pv = self.st.para.get(pid, {}).get("prev", 0)
                    if pv >= 300 and marker_level(para_text(p)) == 2:  # ○ 줄만(날짜 줄·□·■ 제목은 그대로)
                        p.set("paraPrIDRef", self.b.hedit.para_margin(pid, "prev", pv // 2))

            # 덜 바꾸는 것부터: 줄 간격을 5%씩 낮춰 보고(사용자 지시 '줄간 조정'), 그다음 □ 사이 빈 줄 좁히기를 더한다
            top = max((self.st.para.get(saved[p][0], {}).get("line", 0) for p in texts), default=0)
            steps = list(range(top - 5, MIN_LINE - 1, -5)) if top > MIN_LINE else []
            # 바꾸는 정도(덜 바꿀수록 좋음): 줄 간격은 낮춘 %만큼, □ 사이 빈 줄 좁히기는 줄 간격 10%쯤으로 친다
            # — 같은 쪽 수라면 본문 140%보다 '빈 줄 좁힘 + 155%'가 덜 답답하다(2026-10-31)
            plans = [("그대로", 0, lambda: None)]
            plans += [(f"줄 간격 {v}%", top - v, lambda v=v: line_to(v)) for v in steps]
            for k, (t, cells) in enumerate(figs):
                name = "그래프" if len(figs) == 1 else f"그래프({k + 1}번째)"
                plans += [(f"{name} 높이 {v}% 줄임", v * FIG_COST, lambda t=t, cells=cells, v=v: shrink_fig(t, cells, v))
                          for v in FIG_SHRINK]
                # 그래프만으로 모자라면 줄 간격과 함께(가장 많이 줄인 그래프에 줄 간격 단계를 더함)
                v = FIG_SHRINK[-1]
                plans += [(f"{name} 높이 {v}% 줄임 + 줄 간격 {w}%", v * FIG_COST + top - w,
                           lambda t=t, cells=cells, v=v, w=w: (shrink_fig(t, cells, v), line_to(w))) for w in steps]
            if spacers:
                plans.append(("□ 사이 빈 줄 조금 좁힘", SPACER_COST, shrink_spacers))
                plans += [(f"□ 사이 빈 줄 조금 좁힘 + 줄 간격 {v}%", SPACER_COST + top - v,
                           lambda v=v: (shrink_spacers(), line_to(v))) for v in steps]
            low = steps[-1] if steps else None
            extra = []  # 마지막 수단(표 위아래 여백은 지키고 위쪽을 더 줄임 — 사용자 2026-11-05): 쪽 수가 줄 때만 고른다
            if low is not None:
                extra.append((f"□ 사이 빈 줄 조금 좁힘 + 줄 간격 {low}% + ○ 위 간격 절반", SPACER_COST + top - low + PREV_HALF_COST,
                              lambda v=low: (shrink_spacers(), line_to(v), halve_prev())))
                if spacers:
                    extra.append((f"□ 사이 빈 줄 더 좁힘 + 줄 간격 {low}% + ○ 위 간격 절반", SPACER2_COST + top - low + PREV_HALF_COST,
                                  lambda v=low: (shrink_spacers2(), line_to(v), halve_prev())))
            best = None
            for name, cost, act in plans:
                restore()
                act()
                bad, pages = self.badness(seg)
                if best is None or bad < best[0] - 1 or (abs(bad - best[0]) <= 1 and cost < best[4]):
                    best = (bad, name, act, pages, cost)
            for name, cost, act in extra:
                restore()
                act()
                bad, pages = self.badness(seg)
                if pages < best[3] and (bad < best[0] - 1):
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

    def fit_long_tables(self):
        """한 쪽을 조금 넘는 본문 표는 줄 높이를 줄여 한 쪽에 넣는다(사용자 원칙 2026-11-04 — '큰 표가 두 장에 걸치면 차라리
        밑으로 내려서 한 장에 딱 들어가게', '세부사업 예산 현황 행의 줄간격을 줄여야'). 표 + 바로 위 기준·단위·■ 제목 줄 +
        바로 아래 ※·* 줄의 높이가 쪽 높이를 넘으면, 줄마다 같은 만큼(글자 높이 + ROW_TIGHT 밑으로는 안 내림) 줄여 들어가는
        가장 작은 만큼만 줄인다. 그래도 안 들어가는 긴 표는 그대로(쪽 경계에서 줄 사이로 나뉨). 그러면 쪽 맞춤이 묶음째 다음 쪽으로
        넘긴다(layout.paginate). 참고 쪽은 fit_refs가 따로 맞춘다. 줄인 표 수."""
        paras = self.paras()
        lim = self.body_h - SAFETY
        stop = next((i for i, p in enumerate(paras) if self._is_ref_head(p)), len(paras))
        done = []
        for i, p in enumerate(paras[:stop]):
            tbls = [t for t in para_tables(p) if self._is_data_table(t)]
            if not tbls:
                continue
            tbl = tbls[0]
            group = [i]
            k = i - 1
            while k >= 0 and not para_tables(paras[k]) and (UNIT_RE.match(para_text(paras[k]))
                                                            or para_text(paras[k]).lstrip().startswith("■")):
                group.insert(0, k)
                k -= 1
            k = i + 1
            while k < len(paras) and not para_tables(paras[k]) and para_text(paras[k]).lstrip().startswith(("※", "*")):
                group.append(k)
                k += 1

            def height():
                return sum(self.lay.para_height(paras[g], self.body_w)[0] for g in group)

            if height() <= lim:
                continue
            base = self._row_heights(tbl)
            self._set_rows(tbl, [1] * len(base))  # 칸 높이를 아주 작게 두면 글이 차지하는 높이만 남음
            need = self._row_heights(tbl)
            floor = [max(n, self._main_size(tbl) * 100 + ROW_TIGHT) for n in need]
            room = max((b - f for b, f in zip(base, floor)), default=0)

            def rows(d):
                return [max(f, b - d) for b, f in zip(base, floor)]

            self._set_rows(tbl, rows(room))
            if room <= 0 or height() > lim:
                self._set_rows(tbl, base)  # 줄여도 한 쪽보다 긴 표 — 그대로 두고 나눔
                continue
            lo, hi = 0.0, float(room)
            for _ in range(20):
                mid = (lo + hi) / 2
                self._set_rows(tbl, rows(mid))
                if height() <= lim:
                    hi = mid
                else:
                    lo = mid
            self._set_rows(tbl, rows(hi))
            done.append(hi / HWPUNIT_PER_MM)
        if done:
            self.notes.append(f"한 쪽을 조금 넘던 표 {len(done)}개는 줄 높이를 줄여(줄마다 {min(done):.1f}~{max(done):.1f}mm) 한 쪽에 "
                              "들어가게 했습니다(두 쪽에 나뉘지 않고 제목·단위 줄과 함께 다음 쪽에서 시작).")
        return len(done)

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
        heads = [i for i, p in enumerate(region)  # ■ 표 제목은 □와 같은 수준 1이지만 표와 한 몸 — 덩어리 머리가 아님
                 if self._is_ref_head(p) or (not para_tables(p) and marker_level(para_text(p)) == 1 and not is_table_title(p))]
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
            chunks[-1]["open"] = all(self._is_ref_head(p) or (not para_tables(p) and marker_level(para_text(p)) == 1
                                                              and not is_table_title(p)) for p in content)
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
