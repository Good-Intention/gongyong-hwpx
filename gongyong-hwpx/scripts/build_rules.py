# -*- coding: utf-8 -*-
"""사용자 원칙(Builder의 일부): 묶음 유지·줄 바꿈, 괄호 이름표 폭, 쌍점·이름표 내어쓰기, □·■ 제목, 항목 수·근거법령·표 제목 검사, 설명글·괄호 작게, 따옴표 붙이기, 번호·빈 줄·단위 줄, 근거법령 1번."""
from build_base import *  # noqa: F401,F403 — 상수·공통 함수·BuildError
from hwpx_lib import _base_head  # noqa: E402,F401 — 밑줄 이름은 *로 안 넘어옴


class RulesPart:
    # ------------------------------------------------------------ 사용자 원칙(줄 나눔·묶음)
    def keep_groups(self, out):
        """□는 바로 아래와 함께, ○와 그 아래 -·*·※·표는 한 쪽에 붙어 있게(다음 문단과 함께)."""
        def lv(k):
            p = out[k]
            tables = para_tables(p)
            if tables:
                return "T1" if tables[0].get("rowCnt") == "1" else "T"
            t = para_text(p)
            if UNIT_RE.match(t) or is_table_title(p, out[k + 1:k + 5]):
                return "U"  # 표 위 ■ 제목·기준·단위 줄: 위 항목·아래 표와 한 쪽에
            return "blank" if not t.strip() else marker_level(t)

        lv_list = [lv(k) for k in range(len(out))]
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
            raise BuildError(f"{where}: title은 표·도표 블록에만(표는 위 ■ 제목 줄, 도표는 < 제목 >), rows는 도표(flow) 블록에만 씁니다.")
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
            text = para_text(p)
            cur = -self.styles.para.get(p.get("paraPrIDRef"), {}).get("intent", 0)
            if k < len(chs) and text[k] in "「『" and -0.02 * chs[k][1] <= cur - hang <= 0.5 * chs[k][1]:
                # 낫표를 반 칸 당긴 줄(fit.pull_corners)은 낫표 칸이 내어쓰기보다 앞에 있다 — 있던 내어쓰기를 그대로 둔다
                # (다시 재면 둘째 줄이 당긴 만큼 앞으로 와 낫표 획과 어긋남, 되풀이해도 같게 2026-11-04)
                continue
            k2 = next((i + 1 for i in range(len(text) - 1, k, -1) if text[i] in ARROWS), 0)
            while k2 and k2 < len(text) and text[k2] in " ⎵⍽":
                k2 += 1
            if k2 and k2 < len(chs) and abs(cur - sum(c[1] for c in chs[:k2])) <= 0.02 * chs[k2][1]:
                # 화살표 뒤 첫 글자 밑에 맞춘 줄(fit.arrow_breaks)은 그 내어쓰기를 그대로 둔다(되풀이해도 같게 2026-11-04)
                continue
            p.set("paraPrIDRef", self.hedit.para_hang(p.get("paraPrIDRef"), hang))
            if by_colon:
                n_colon += 1
            else:
                n_label += 1
        if n_colon:
            self.warn(f"쌍점(:) 뒤 내용이 두 줄 이상인 문단 {n_colon}개는 둘째 줄을 쌍점 뒤 첫 글자에 맞췄습니다.")
        if n_label:
            self.warn(f"괄호 이름표 뒤 내용이 두 줄 이상인 문단 {n_label}개는 둘째 줄을 이름표 뒤 첫 글자에 맞췄습니다.")

    def small_squares(self):
        """□ 큰 항목 기호만 뒤 글자보다 SQUARE_DOWN(2pt) 작게(사용자 2026-11-04 '□도 줄이기' — ■ 표 제목 기호를 2pt 줄인 것과
        같게, ○는 원래 작은 ○). □ 뒤 빈칸은 그대로 두어 글 시작 자리는 바뀌지 않는다. 표지 개요 상자 안 □ 줄도. 바꾼 수."""
        n = 0
        for p in self.sec.iter(T("hp:p")):
            text = para_text(p)
            body = text.lstrip(" " + FW)
            if not body.startswith("□") or para_tables(p):
                continue
            k = text.index("□")
            self._split_run_at(p, k + 1)
            mark, size, pos = None, None, 0
            for r in para_runs(p):
                t = run_text(r)
                if r.find(T("hp:t")) is not None:
                    if mark is None and pos <= k < pos + len(t):
                        mark = r if t.strip() == "□" else False
                    elif mark is not None and mark is not False and size is None and t.strip():
                        size = self.styles.char.get(r.get("charPrIDRef"), {}).get("size")
                pos += len(t)
            if mark is None or mark is False or not size:
                continue
            cid = mark.get("charPrIDRef")
            d = size - SQUARE_DOWN - self.styles.char.get(cid, {}).get("size", size)
            if abs(d) > 0.01:
                mark.set("charPrIDRef", self.hedit.char_size(cid, d))
                n += 1
        if n:
            self.warn(f"□ 기호 {n}개를 뒤 글자보다 {SQUARE_DOWN}pt 작게 했습니다(■ 표 제목 기호와 같게).")

    def _has_image(self, tbl):
        """그림 칸(배경 그림)이 든 표인가 — 만들 때 기록한 칸 또는 칸 모양에 그림 채우기가 든 칸."""
        fills = {bf.get("id"): bf for bf in self.pkg.xml("Contents/header.xml").iter(T("hh:borderFill"))}
        for *_, tc in table_grid(tbl):
            bf = fills.get(tc.get("borderFillIDRef"))
            if tc in self.image_cells or (bf is not None and bf.find(".//" + T("hc:img")) is not None):
                return True
        return False

    def untitled_tables(self):
        """제목 없는 본문 자료 표 문단 목록(table_titles 검사와 같은 기준·차례) — 이미 만든 문서에 ■ 제목을 달 때 쓴다.
        참고 쪽 표도 본다(참고 머리표는 쪽 제목일 뿐). 흐름 표는 뺀다."""
        ps = [x for x in self.sec if x.tag == T("hp:p")]
        found = []
        for k, p in enumerate(ps):
            tables = para_tables(p)
            if not tables:
                continue
            if self._is_ref_head(p):
                continue  # 참고 머리표는 쪽 제목 — 그 아래 표도 저마다 ■ 제목(사용자 2026-11-05)
            tbl = tables[0]
            if tbl in self.flow_tables or not Fitter._is_data_table(tbl) or self._has_image(tbl):
                continue  # 그림 상자(캡처·그래프)는 머리 칸·[그림 N] 줄이 제목 — ■ 제목을 묻지 않음
            j = k - 1
            while j >= 0 and not para_tables(ps[j]) and UNIT_RE.match(para_text(ps[j])):
                j -= 1
            if j >= 0 and is_table_title(ps[j]):
                continue
            found.append(p)
        return found

    def add_table_titles(self, titles):
        """이미 만든 문서의 제목 없는 표 위에 '■ 제목' 줄을 넣는다(사용자 2026-11-04 '여기는 제목을 달아야 하는거 아닌가요?').
        titles: untitled_tables() 차례대로의 제목 목록(빈 값은 건너뜀). 기준·단위 줄이 있으면 그 줄을 복사해 그 위에,
        없으면 문서의 다른 기준·단위 줄(없으면 표 바로 앞 글 문단)을 복사해 표 바로 위에 넣는다. 강제 쪽 나눔은 제목 줄로 옮긴다.
        글꼴·크기·왼쪽 정렬·줄 간격은 Fitter.fit_tables가 표에 맞춘다. 넣은 수."""
        tables = self.untitled_tables()
        if len(titles) != len(tables):
            raise BuildError(f"표 제목 {len(titles)}개를 받았는데 제목 없는 표는 {len(tables)}개입니다.")
        any_unit = next((x for x in self.sec.iter(T("hp:p"))
                         if not para_tables(x) and UNIT_RE.match(para_text(x))), None)
        n = 0
        for p, title in zip(tables, titles):
            title = str(title or "").strip().lstrip(TABLE_TITLE_MARK + " ")
            if not title:
                continue
            top, prev = p, p.getprevious()
            while prev is not None and prev.tag == T("hp:p") and not para_tables(prev) and UNIT_RE.match(para_text(prev)):
                top, prev = prev, prev.getprevious()
            src = top if top is not p else any_unit
            if src is None:
                src = prev
                while src is not None and (src.tag != T("hp:p") or para_tables(src) or not para_text(src).strip()):
                    src = src.getprevious()
            if src is None:
                continue
            q = copy.deepcopy(src)
            drop_linesegs(q)
            runs = [r for r in para_runs(q) if r.find(T("hp:t")) is not None and run_text(r).strip()]
            if not runs:
                continue
            for r in para_runs(q):
                q.remove(r)
            q.insert(0, self._mk(runs[0], f"{TABLE_TITLE_MARK} {title}"))
            for key in ("pageBreak", "columnBreak"):
                if q.get(key) is not None:
                    q.set(key, "0")
            if top.get("pageBreak") == "1":
                top.set("pageBreak", "0")
                q.set("pageBreak", "1")
            top.addprevious(q)
            n += 1
        if n:
            self.warn(f"표 제목 {n}개를 표 위 왼쪽에 ■ 줄로 넣었습니다.")
        return n

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

        for k, p in enumerate(out):
            if para_tables(p):
                if self._is_ref_head(p):
                    break
                continue
            text = para_text(p)
            _, mark, _ = split_marker(text)
            if not mark or is_table_title(p, out[k + 1:k + 5]):
                continue  # ■ 표 제목은 표에 딸린 줄 — 항목으로 세지 않음
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

    def table_titles(self, out):
        """본문 자료 표(머리 줄이 있는 여러 줄·여러 칸 표)는 ■ 제목을 단다(사용자 원칙 2026-11-04 '이 표는 제목이 없군요
        앞으로는 ■ 네모로 제목을 지어줍시다'). 제목 없는 표를 '고쳐야 함'으로 알린다 — 계획의 표 블록에 "title"을 넣으면
        표 위 왼쪽에 ■ 줄이 붙는다. 참고 쪽 표도 본다(참고 머리표는 쪽 제목일 뿐, 사용자 2026-11-05)."""
        missing = []
        for k, p in enumerate(out):
            tables = para_tables(p)
            if not tables:
                continue
            if self._is_ref_head(p):
                continue  # 참고 머리표는 쪽 제목 — 그 아래 표도 저마다 ■ 제목(사용자 2026-11-05)
            tbl = tables[0]
            if tbl in self.flow_tables or not Fitter._is_data_table(tbl) or self._has_image(tbl):
                continue  # 그림 상자(캡처·그래프)는 머리 칸·[그림 N] 줄이 제목 — ■ 제목을 묻지 않음
            j = k - 1
            while j >= 0 and not para_tables(out[j]) and UNIT_RE.match(para_text(out[j])):
                j -= 1
            if j >= 0 and is_table_title(out[j], out[j + 1:j + 5]):
                continue
            g = table_grid(tbl)
            head = next((para_text(cp).replace(FW, " ").strip()[:8] for *_, tc in g for cp in cell_paras(tc)
                         if para_text(cp).strip()), "")
            missing.append(head)
        if missing:
            self.warn(f"표 제목이 없습니다 — 표 {len(missing)}개(" + ", ".join(f"‘{t}…’" for t in missing[:3])
                      + (" 등" if len(missing) > 3 else "") + "): 표 블록에 \"title\": \"○○ 현황\"을 넣으면 표 위 왼쪽에 "
                      "■ 제목이 붙습니다(단위 줄은 그 아래 오른쪽).")

    def basis_notes(self, out):
        """근거법령에는 부연설명을 달지 않는다(사용자 원칙 2026-11-04): Ⅰ. 근거법령 장·□ 근거법령 묶음 안의 -·※·* 줄을
        알린다 — 법령 이름·조항만 ○ 하나씩 쓰고, 설명은 빼거나 그 내용을 쓰는 □(사업개요·추진배경 등)로 옮긴다.
        - 줄이 하위 법령(「…」)이면 ○로 올린다. 참고 쪽(참고 머리표부터)은 보지 않는다."""
        notes, laws, inside, roman = [], [], False, False
        for k, p in enumerate(out):
            if para_tables(p):
                if self._is_ref_head(p):
                    break
                continue
            if is_table_title(p, out[k + 1:k + 5]):
                continue
            text = para_text(p).replace(FW, " ").replace("⍽", " ")
            _, mark, body = split_marker(text)
            if not mark:
                continue
            lv = marker_level(text)
            if lv == 1:
                is_roman = mark[0] in ROMAN
                if inside and (is_roman or not roman):
                    inside = False
                if BASIS_LAW_TITLE_RE.match(body.replace("**", "").strip()):
                    inside, roman = True, is_roman
                continue
            if inside and lv >= 3:
                body = body.replace("**", "").strip()
                (laws if body.startswith("「") else notes).append(body[:16])
        if not notes and not laws:
            return
        msg = "근거법령에는 부연설명을 달지 않습니다(사용자 원칙) — 법령 이름·조항만 ○ 하나씩"
        if notes:
            msg += (f": 설명 줄 {len(notes)}개(" + ", ".join(f"‘{t}…’" for t in notes[:3]) + (" 등" if len(notes) > 3 else "")
                    + ")는 빼거나 그 내용을 쓰는 □(사업개요·추진배경 등)로 옮기세요")
        if laws:
            msg += ("; " if notes else ": ") + f"- 줄의 하위 법령 {len(laws)}개(" + ", ".join(f"‘{t}…’" for t in laws[:3]) + ")는 ○로 올리세요"
        self.warn(msg + ".")

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
        mode = {}  # 문단 → 글자 수가 가장 많은 자간(이 단계가 줄인 조각을 알아보는 기준)
        for r in list(self.sec.iter(T("hp:run"))):
            text = run_text(r)
            if r.find(T("hp:t")) is None or len(r) != 1 or not any(q in text for q in QUOTES + "「」" + MID_DOTS):
                continue
            c = self.styles.char.get(r.get("charPrIDRef"), {})
            base = c.get("spacing", 0)
            deltas = self._tight_deltas(text, c.get("font"))
            if not any(deltas) or base <= -50:
                continue
            p = r.getparent()
            if p not in mode:
                count = {}
                for x in para_runs(p):
                    if x.find(T("hp:t")) is not None:
                        sp = self.styles.char.get(x.get("charPrIDRef"), {}).get("spacing", 0)
                        count[sp] = count.get(sp, 0) + len(run_text(x))
                mode[p] = max(count, key=count.get) if count else base
            # 문단 보통 자간보다 이미 좁은 조각은 이 단계가 줄인 것 — 보통 자간에서 다시 재어 더 줄일 때만(되풀이해도 같게, 2026-11-04)
            ref = max(base, mode[p])
            cids = [self.hedit.char_spacing(r.get("charPrIDRef"), max(-50, ref + dl)) if dl and ref + dl < base else None
                    for dl in deltas]
            if not any(cids):
                continue
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

        out, made, titled = [], 0, 0
        for b in blocks:
            proto = self._proto_of(b)
            if proto is not None and para_tables(proto) and isinstance(b, dict):
                title = str(b.get("title") or "").strip()
                if title and "flow" not in b and (target is not None or fallback is not None):
                    # 표 제목(사용자 원칙 2026-11-04): 표 위 왼쪽 '■ 제목' 줄 — 기준·단위 줄 모양을 빌려 왼쪽 정렬로 넣고,
                    # 글꼴·크기·줄 간격은 fit이 표에 맞춘다(표 글꼴 굵게, 표 글자 크기)
                    title = title.lstrip(TABLE_TITLE_MARK + " ")
                    out.append(dict(unit_block({"_src": b.get("_src")}, f"{TABLE_TITLE_MARK} {title}"), _align="LEFT",
                                    marker=False))
                    titled += 1
                if "flow" not in b:
                    b = {k: v for k, v in b.items() if k != "title"}
                if b.get("unit") and (target is not None or fallback is not None):
                    out.append(unit_block({"_src": b.get("_src")}, b["unit"]))
                    made += 1
                elif out and isinstance(out[-1], dict) and "text" in out[-1] and UNIT_RE.match(out[-1]["text"]) \
                        and out[-1].get("like") not in (target, None) and (target is not None or fallback is not None):
                    out[-1] = unit_block(out[-1], out[-1]["text"])
                    made += 1
                b = {k: v for k, v in b.items() if k != "unit"}
            out.append(b)
        if titled:
            self.warn(f"표 제목 {titled}개를 표 위 왼쪽에 ■ 줄로 넣었습니다(단위 줄은 그 아래 오른쪽).")
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
