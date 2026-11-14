# -*- coding: utf-8 -*-
"""사용자 원칙에 따른 자동 맞춤(한글 프로그램 없이 layout.py 어림 계산으로).

줄 맞춤은 fit_lines.py, 표 맞춤은 fit_tables.py, 쪽 맞춤·참고 쪽은 fit_pages.py에 있고 이 파일의 Fitter가 셋을 합친다.
상수·공통 함수(cover_end 등)는 fit_base.py. 다른 파일은 지금처럼 `from fit import Fitter, cover_end, ARROWS …`로 쓴다.
"""
from fit_base import *  # noqa: F401,F403
from fit_lines import LineFit  # noqa: E402
from fit_pages import PageFit  # noqa: E402
from fit_tables import TableFit  # noqa: E402


class Fitter(LineFit, TableFit, PageFit):
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
                if para_text(p).strip() and p not in self.b.law_paras:  # 참고 근거법령 조문은 인용 글(quote_boxes)
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

    def quote_boxes(self):
        """제목 걸친 상자(조문 발췌 등) 본문 칸의 글 문단과 그 칸 안쪽 폭. text_boxes와 따로 둔다 — 인용 글이라 화살표·연결어·끝 줄
        내리기 같은 줄 바꿈 넣기와 '낱말 빼기' 알림을 쓰지 않고, 자간으로만 끝선을 맞춘다(fit_quotes, 사용자 2026-11-10)."""
        out = []
        for p in self.paras():
            if p in self.b.law_paras:  # 상자 없이 둔 참고 근거법령 조문 줄(build_rules.law_refs) — 본문 폭에서
                out.append((p, self.body_w))
                continue
            for tbl in para_tables(p):
                tc = self._caption_content(tbl, table_grid(tbl))
                if tc is None:
                    continue
                w = int(tc.find(T("hp:cellSz")).get("width", "0")) - self._cell_margin(tbl, tc)
                for cp in cell_paras(tc):
                    if para_text(cp).strip() and not para_tables(cp):
                        out.append((cp, w))
        return out

    def summary_paras(self):
        """요약 상자(제목 상자 뒤 첫 한 칸 상자) 안 문단 — 줄 바꿈을 넣지 않는 곳(style-guide). 없으면 빈 묶음."""
        paras = self.paras()
        start = cover_end(paras) or 0
        one = lambda p: bool(para_tables(p)) and para_tables(p)[0].get("rowCnt") == "1" and para_tables(p)[0].get("colCnt") == "1"  # noqa: E731
        title = next((i for i, p in enumerate(paras[start:], start) if one(p)), None)
        if title is None:
            return set()
        box = next((p for p in paras[title + 1:title + 6] if one(p)), None)
        return set(cell_paras(table_grid(para_tables(box)[0])[0][4])) if box is not None else set()

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
            self.notes.append(fix_note("표지 글이 길어 한 쪽에 다 들어가지 않을 수 있습니다 — 개요 상자 글을 줄이세요."))
        sets = [(band, y_band - top), (last_pic, gap)]
        if box is not None:
            sets.append((box, gap))
        for i, v in sets:
            p = cover[i]
            p.set("paraPrIDRef", self.b.hedit.para_margin(p.get("paraPrIDRef"), "prev", max(0, v)))
        self.notes.append(f"표지: 제목 띠는 위에서 {y_band / HWPUNIT_PER_MM:.0f}mm, "
                          + ("개요 상자는 제목 띠와 기관 마크 사이 가운데, " if box is not None else "")
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
        self._order_hint = (self.notes[-1], sc[0], sc[1], body0, ref_i)

    def drop_moot_order_hint(self):
        """쪽 맞춤을 끝낸 문서가 이미 '순서를 바꾼 것'만큼 좋으면(걸친 묶음 수·본문 쪽 수가 같거나 적음) 순서 바꾸기 알림을 뺀다 —
        맞춤 전 어림으로 '본문 3→2쪽'이라 알리는데 맞춘 문서가 이미 2쪽이면 할 일이 없는 알림이고, 글 쓰는 쪽은 번번이 따져 본다
        (시험 2026-11-12: 두 주문 모두 이 알림을 읽고 '바꾸지 않음'으로 끝남)."""
        hint = getattr(self, "_order_hint", None)
        if not hint or hint[0] not in self.notes:
            return
        note, splits, pages, body0, ref_i = hint
        paras = self.paras()
        ref_now = next((i for i, p in enumerate(paras) if self._is_ref_head(p)), len(paras))
        if ref_now <= body0:
            return
        try:
            where, used = self.lay.paginate(paras[:ref_now], self.body_w, self.body_h - SAFETY, self.heads(), BLOCK_GAP)
            first, last = where[body0][0], where[ref_now - 1][1]
            now = (len(self.lay.split), last - first)
        finally:
            self.lay.paginate(paras, self.body_w, self.body_h - SAFETY, self.heads(), BLOCK_GAP)
        if now[0] <= splits and now[1] <= pages:
            self.notes.remove(note)

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
        return fix_note(msg) if self.lay.split else msg
