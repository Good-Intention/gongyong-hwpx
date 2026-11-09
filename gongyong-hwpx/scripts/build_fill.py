# -*- coding: utf-8 -*-
"""글 넣기(Builder의 일부): 견본 문단에 글·조각 넣기, 표 칸·줄·칸 수, 칸 배경 그림, 도표(flow)."""
from build_base import *  # noqa: F401,F403 — 상수·공통 함수·BuildError
from hwpx_lib import _base_head  # noqa: E402,F401 — 밑줄 이름은 *로 안 넘어옴


class FillPart:
    # ------------------------------------------------------------ 글 넣기
    def _mk(self, src_run, text):
        r = copy.deepcopy(src_run)
        for ch in list(r):
            r.remove(ch)
        return set_run_text(r, text, self.tab_proto)

    def _nbsp(self, text, where):
        """글 속 U+00A0·U+202F(줄 바꿈 안 되는 빈칸 글자)를 한글 묶음 빈칸(⍽ → hp:nbSpace)으로 바꾼다 — HY헤드라인M 같은
        옛 글꼴에는 그 글자가 없어 한글이 네모로 보인다(사용자 제보 2026-11-05 '번호 뒤에 네모')."""
        n = text.count(" ") + text.count(" ")
        if not n:
            return text
        self.warn(f"{where}: 줄 바꿈 안 되는 빈칸 글자(U+00A0) {n}개는 한글 묶음 빈칸으로 바꿨습니다"
                  "(HY헤드라인M 등에 그 글자가 없어 네모로 보임 — 계획에는 보통 빈칸이나 ⍽를 쓰세요).")
        return text.replace(" ", "⍽").replace(" ", "⍽")

    def fill_text(self, p, text, where, marker=True, cell=False):
        """견본 문단 p(복사본)의 글을 text로 바꾼다. 머리 기호와 조각 모양은 견본 것을 쓴다."""
        if not isinstance(text, str):
            raise BuildError(f"{where}: text는 글(문자열)이어야 합니다.")
        text = self._nbsp(text, where)
        runs = indexed_runs(p)
        lost = sorted({o for r in runs for o in run_objects(r)} - {"tbl"})
        if lost:
            self.warn(f"{where}: 견본 문단의 글 아닌 것({', '.join(lost)})은 빼고 글만 넣었습니다.")
        segs = [(r, run_text(r)) for r in runs]
        full = "".join(t for _, t in segs)
        pre, mark, _ = split_marker(full)
        use_marker = marker and bool(pre)
        body = text
        upre, umark, ubody = split_marker(text)
        swap = None  # 번호(Ⅱ. 2. 나. ②)는 견본 번호 대신 글의 번호를 쓴다
        if use_marker and umark:
            if umark != mark and number_family(umark) and number_family(umark) == number_family(mark):
                swap = (mark, umark)
            elif umark != mark:
                self.warn(f"{where}: 견본 문단은 '{mark}'로 시작하는데 글이 '{umark}'로 시작합니다. "
                          f"견본 기호 '{mark}'를 쓰고 글의 '{umark}'는 뺐습니다. 다른 기호를 원하면 like를 바꾸세요.", level="fix")
            body = ubody
        plen = len(pre) if use_marker else 0

        new_runs = []
        pos = 0
        body_count = {}
        # ○·- 같은 항목 기호 뒤 빈칸은 고정폭 빈칸으로: 양쪽 정렬 때 늘어나지 않아 괄호·내용이 위아래로 맞는다.
        # 고정폭 빈칸은 1/4 글자라, 보통 빈칸 하나를 그 글꼴의 빈칸 폭만큼의 고정폭 빈칸으로 바꾼다.
        # ※·*·· 뒤 빈칸도(두 줄 이상이면 첫 줄이 양쪽 정렬로 늘어나 ※ 뒤 첫 글자가 다른 ※ 줄과 어긋남 — 사용자 지적 2026-11-01)
        fix_gap = use_marker and (marker_level(pre) in (2, 3) or mark in ("※", "*", "＊", "·", "ㆍ"))
        for r, t in segs:
            start, end = pos, pos + len(t)
            if start < plen:
                take = t[: plen - start]
                if fix_gap and start + len(take) == plen:
                    stripped = take.rstrip(" ")
                    take = stripped + FW * (self._fw_per_space(r) * (len(take) - len(stripped)))
                if swap and swap[0] in take:
                    take = take.replace(swap[0], swap[1], 1)
                    swap = None
                if take:
                    new_runs.append(self._mk(r, take))
            if end > plen:
                body_count[id(r)] = (r, end - max(start, plen))
            pos = end
        cand = list(body_count.values())
        if not cand:  # 견본이 기호만 있거나 빈 문단
            cand = [(segs[-1][0], 0)] if segs else [(para_runs(p)[0], 0)]
        def kind(run):
            ch = self.styles.char.get(run.get("charPrIDRef"), {})
            return "sup" if ch.get("superscript") else ("bold" if ch.get("bold") else "plain")

        plain = [c for c in cand if kind(c[0]) == "plain"]
        normal = max(plain or cand, key=lambda c: c[1])[0]
        bold = next((c[0] for c in cand if kind(c[0]) == "bold"), None)
        sup = next((c[0] for c in cand if kind(c[0]) == "sup"), None)

        if self.keep_numbers:
            body = NUMWORD_RE.sub("\\1\u237d", body)
        if self.colons:
            body = space_colons(body)
        if len(re.findall(r"\*\*", body)) % 2 or len(re.findall(r"\^\^", body)) % 2:
            self.warn(f"{where}: 짝이 없는 **(또는 ^^)가 있어 글자 그대로 찍힙니다 — 짝을 맞추거나 지우세요: ‘{body[:24]}…’", level="fix")
        for part in MARKUP_RE.split(body):
            if not part:
                continue
            src = normal
            if part.startswith("**") and part.endswith("**") and len(part) > 4:
                part = part[2:-2]
                if bold is not None:
                    src = bold
                else:
                    self.warn(f"{where}: 견본 문단에 굵은 조각이 없어 **…** 부분을 보통 글씨로 넣었습니다.", level="fix")
            elif part.startswith("^^") and part.endswith("^^") and len(part) > 4:
                part = part[2:-2]
                if sup is not None:
                    src = sup
                else:
                    self.warn(f"{where}: 견본 문단에 위 첨자 조각이 없어 ^^…^^ 부분을 보통 글씨로 넣었습니다.", level="fix")
            new_runs.append(self._mk(src, part))
        if not new_runs:
            new_runs.append(self._mk(normal, ""))
        self._replace_runs(p, new_runs)

    def fill_runs(self, p, spec, proto_idx, where):
        src_runs = indexed_runs(self.protos[proto_idx])
        if not isinstance(spec, list) or not spec:
            raise BuildError(f"{where}: runs는 [[글, 조각 번호], …] 목록이어야 합니다.")
        new_runs = []
        for item in spec:
            if not (isinstance(item, list) and len(item) == 2 and isinstance(item[0], str) and isinstance(item[1], int)):
                raise BuildError(f"{where}: runs의 각 항목은 [글, 조각 번호] 모양이어야 합니다: {item!r}")
            text, k = item
            text = self._nbsp(text, where)
            if not 0 <= k < len(src_runs):
                raise BuildError(f"{where}: 조각 번호 {k}가 없습니다(견본 문단 {proto_idx}의 조각은 0~{len(src_runs) - 1}).")
            new_runs.append(self._mk(src_runs[k], text))
        self._replace_runs(p, new_runs)

    def _replace_runs(self, p, new_runs):
        """p의 글 조각(run)을 new_runs로 바꾼다. 표가 든 run은 그대로 둔다."""
        old = indexed_runs(p)
        at = list(p).index(old[0]) if old else len([x for x in p if x.tag == T("hp:run")])
        for r in old:
            p.remove(r)
        for k, r in enumerate(new_runs):
            p.insert(at + k, r)

    # ------------------------------------------------------------ 표
    def fill_cell(self, tc, value, where, marker=True):
        """칸 글 넣기. marker=False(블록의 "marker": false)면 글의 '1.'·'Ⅰ.'·'○' 등을 머리 기호로 보지 않고 글자 그대로 넣는다."""
        if value is None:  # 견본 글을 그대로 둠
            return
        if isinstance(value, dict):
            if "image" not in value:
                raise BuildError(f"{where}: 칸 값이 사전이면 {{\"image\": \"그림 파일\"}} 모양이어야 합니다.")
            return self.cell_image(tc, value, where)
        lines = value if isinstance(value, list) else str(value).split("\n")
        protos = cell_paras(tc)
        if not protos:
            raise BuildError(f"{where}: 표 칸 안에 문단이 없습니다.")
        sub = tc.find(T("hp:subList"))
        new_ps = []
        use = marker
        for line in lines:
            _, umark, _ = split_marker(line) if use else ("", "", line)
            chosen, marker = None, use
            for cp in protos:
                _, m, _ = split_marker(para_text(cp))
                if umark and m == umark:
                    chosen = cp
                    break
            if chosen is None and not umark:
                chosen = next((cp for cp in protos if not split_marker(para_text(cp))[1]), None)
            if chosen is None:
                chosen, marker = protos[0], use and bool(umark)
            np = copy.deepcopy(chosen)
            drop_linesegs(np)
            self.fill_text(np, line, where, marker=marker, cell=True)
            new_ps.append(np)
        for cp in protos:
            sub.remove(cp)
        for np in new_ps:
            sub.append(np)

    # ------------------------------------------------------------ 표 칸 배경 그림
    def _image_bytes(self, path, where):
        """그림 파일을 읽어 (바이트, 확장자, 화소 가로, 세로). Pillow가 있으면 긴 변 IMAGE_MAX_PX로 줄이고 용량을 줄인다(사용자
        원칙 2026-11-01): 투명 칸은 흰 바탕(종이색)에 합친 뒤 JPEG와 PNG를 둘 다 만들어 작은 쪽을 쓴다 — 사진은 JPEG,
        색이 단순한 로고·도표는 PNG가 대개 작다(투명 채널만 붙은 8MB 사진 PNG가 PNG로 남아 1.9MB가 되던 것, 실측). 없으면 원본 그대로 넣고 알린다."""
        if not path.strip():
            raise BuildError(f"{where}: 그림 파일 이름이 비었습니다(\"image\": \"사진.jpg\" 꼴로 쓰세요).")
        if not os.path.isabs(path) and self.base_dir:
            path = os.path.join(self.base_dir, path)
        if not os.path.isfile(path):
            raise BuildError(f"{where}: 그림 파일을 찾지 못했습니다: {path}")
        try:
            from PIL import Image
        except ImportError:
            Image = None
        if Image is None:
            with open(path, "rb") as f:
                data = f.read()
            w, h = _png_jpeg_size(data)
            self.warn(f"{where}: 그림 라이브러리(Pillow)가 없어 그림을 줄이지 못하고 원본({len(data) // 1024}KB) 그대로 넣었습니다.")
            return data, os.path.splitext(path)[1].lstrip(".").lower() or "png", w, h
        from PIL import ImageOps, UnidentifiedImageError
        try:
            im = Image.open(path)
            im.load()
        except (UnidentifiedImageError, OSError) as e:
            raise BuildError(f"{where}: 그림 파일이 아니거나 깨져 읽지 못했습니다(PNG·JPEG만 됩니다): {path}") from e
        im = ImageOps.exif_transpose(im)  # 휴대전화 사진의 회전 정보대로 세워서(옛 판은 세로 사진이 눕혀 들어감, 평가 2026-11-09)
        return encode_image(im)

    def cell_image(self, tc, value, where):
        """칸 바탕을 그림으로 채운다(글자처럼 넣는 그림이 아니라 '셀 배경' — 사용자 원칙 2026-11-01). 칸 높이를 칸 너비 × 그림
        비율로 맞춰 가로세로 비율을 지킨다(한글은 '크기에 맞추어' 채우므로 칸이 비율과 같아야 늘어나지 않음). 칸 글은 비운다."""
        data, ext, w, h = self._image_bytes(str(value["image"]), where)
        if not w or not h:
            raise BuildError(f"{where}: 그림 크기를 읽지 못했습니다(PNG·JPEG만 됩니다).")
        hpf = self.pkg.xml("Contents/content.hpf")
        man = hpf.find(".//" + T("opf:manifest"))
        have = {it.get("id") for it in man}
        self.image_seq += 1
        while f"cellimg{self.image_seq}" in have:  # 결과 문서를 견본으로 쓸 때 옛 그림 이름을 피함 — 같은 이름이면 새 그림이 옛 그림을 덮음(평가 2026-11-09)
            self.image_seq += 1
        item_id = f"cellimg{self.image_seq}"
        href = f"BinData/{item_id}.{ext}"
        self.pkg.data[href] = data
        it = etree.SubElement(man, T("opf:item"))
        for k, v in (("id", item_id), ("href", href), ("media-type", "image/png" if ext == "png" else "image/jpg"),
                     ("isEmbeded", "1")):
            it.set(k, v)
        tc.set("borderFillIDRef", self.hedit.border_image(tc.get("borderFillIDRef"), item_id))
        sz = tc.find(T("hp:cellSz"))
        cw = int(sz.get("width", "0"))
        if cw:
            sz.set("height", str(int(round(cw * h / w))))
        protos = cell_paras(tc)
        sub_ = tc.find(T("hp:subList"))
        keep = copy.deepcopy(protos[0]) if protos else None
        for cp in protos:
            sub_.remove(cp)
        if keep is not None:
            drop_linesegs(keep)
            self.fill_text(keep, str(value.get("caption", "")), where, marker=False, cell=True)
            sub_.append(keep)
        self.image_cells.add(tc)
        self.image_aspect[tc] = w / h
        self.image_notes.append(f"{len(data) // 1024}KB")

    def fill_table(self, p, block, where):
        tables = para_tables(p)
        if len(tables) != 1:
            raise BuildError(f"{where}: like {block['like']} 문단에는 표가 {len(tables)}개라 표로 채울 수 없습니다.")
        tbl = tables[0]
        grid = table_grid(tbl)
        if "flow" in block:
            self.flow_table(tbl, block, where)
        elif "table" in block:
            self.rebuild_rows(tbl, block, where)
        elif "cells" in block:
            cells = block["cells"]
            if not isinstance(cells, dict):
                raise BuildError(f"{where}: cells는 {{\"줄,칸\": 글}} 모양이어야 합니다.")
            at = {(r, c): tc for r, c, rs, cs, tc in grid}
            for key, val in cells.items():
                try:
                    r, c = (int(x) for x in str(key).split(","))
                except ValueError:
                    raise BuildError(f"{where}: cells의 열쇠 '{key}'는 '줄,칸'(예: \"0,2\") 모양이어야 합니다.")
                if (r, c) not in at:
                    raise BuildError(f"{where}: 칸({r},{c})이 없습니다. 있는 칸: {sorted(at)}")
                self.fill_cell(at[(r, c)], val, f"{where} 칸({r},{c})", marker=block.get("marker", True))
        elif "text" in block:
            if len(grid) != 1:
                raise BuildError(f"{where}: 칸이 {len(grid)}개인 표입니다. \"table\"(줄 목록)이나 "
                                 "\"cells\"({\"줄,칸\": 글})로 채우세요.")
            self.fill_cell(grid[0][4], block["text"], where, marker=block.get("marker", True))

    def flow_table(self, tbl, block, where):
        """도표(단계·흐름)는 그림 도형 대신 표로: 표 선은 모두 투명, 상자 칸만 실선, 상자 사이 칸에 화살표
        (사용자 방식 2026-11-01 — 한글에서 바로 고칠 수 있음). 위·아래 빈 줄은 얇게 두어 앞뒤 글과 띄운다."""
        steps = block["flow"]
        if not isinstance(steps, list) or len(steps) < 2:
            raise BuildError(f"{where}: flow는 상자 글 목록(둘 이상)이어야 합니다: [\"1단계\", \"2단계\", …].")
        arrow = block.get("arrow", "→")
        title = str(block.get("title") or "").strip().strip("<>〈〉 ").strip()
        if title:  # 도표 제목은 '< ○○○ >'로 마감(사용자 의견 2026-11-01)
            title = f"< {title} >"
        n = len(steps)
        forced = block.get("rows")
        if forced not in (None, 1, 2) or (forced == 2 and n < 3):
            raise BuildError(f"{where}: flow의 rows는 1 또는 2(상자 셋 이상일 때)여야 합니다.")
        trs = [tr for tr in tbl if tr.tag == T("hp:tr")]
        total = sum(int(tc.find(T("hp:cellSz")).get("width", "0")) for tc in trs[0] if tc.tag == T("hp:tc"))
        # 상자 모양은 디자인 검토 권고(2026-11-01): 가로로 긴 상자 — 높이는 본문 두 줄(14mm) 공통, 너비는
        # (본문 폭 − 화살표 칸) ÷ 상자 수로 본문 폭에 꽉 채움(한 줄은 42mm까지 — 상자가 셋 이하일 때만 걸려 가운데).
        gap, inner = FLOW_GAP_MM * HWPUNIT_PER_MM, 2 * FLOW_PAD_MM * HWPUNIT_PER_MM
        font = next((self.styles.char.get(r.get("charPrIDRef"), {}).get("font") for tc in trs[-1].iter(T("hp:tc"))
                     for cp in cell_paras(tc) for r in para_runs(cp)), None)

        def text_w(line):  # 상자 글 한 줄의 폭(HWPUNIT, FLOW_PT 어림)
            return sum(self.metrics.em(font, ch) for ch in line) * FLOW_PT * 100

        # 줄 수는 단계 수로 정한다(사용자 2026-11-05 '4, 5 한줄 6,7,8두줄'): 5개까지 한 줄, 6개부터 두 줄 — 좌우를 꽉 채움.
        # (옛 판의 '상자가 좁거나 글이 넘치면 두 줄로'는 없앰 — 상자 글은 상자 안에서 줄을 바꿈)
        lines = 2 if n > FLOW_ROW_MAX else 1
        k0 = (n + 1) // 2 if lines == 2 else n
        if (total - (k0 - 1) * gap) / k0 < FLOW_BOX_MIN_MM * HWPUNIT_PER_MM:
            raise BuildError(f"{where}: 도표 단계가 {n}개라 상자가 너무 좁습니다 — 단계를 묶어 줄이거나 표로 쓰세요(6~8단계는 두 줄로 맞춤).")
        if forced and forced != lines:
            self.warn(f"{where}: 도표 줄 수는 단계 수로 정합니다(4·5단계 한 줄, 6단계부터 두 줄 — 사용자 원칙) — "
                      f"rows {forced} 대신 {lines}줄로 했습니다.")
        k = (n + 1) // 2 if lines == 2 else n  # 첫 줄 상자 수
        if lines == 2 and block.get("widths"):
            raise BuildError(f"{where}: 두 줄 도표에는 widths를 쓸 수 없습니다(칸 너비는 도구가 맞춤).")
        # 두 줄이면 둘째 줄 첫 상자 앞에 →를 두고, 그 →의 왼쪽 끝을 윗줄 첫 상자의 왼쪽 선에 맞춘다(사용자 의견
        # 2026-11-01). 둘째 줄은 '→ 글자 폭 + 다른 화살표 옆 빈 폭'(ind)만큼 들어가, → 뒤 빈 폭이 다른 화살표와 같다.
        # 그래서 칸을 [ind | 상자 − ind | ind | 화살표 칸 − ind]씩 잘게 나누고 상자·화살표는 두 칸씩 합친다
        # (빈 칸은 줄마다 이어 합쳐 좁은 칸이 따로 남지 않게 — 한글은 좁은 칸을 저절로 넓힘).
        glyph = sum(self.metrics.em(font, ch) for ch in arrow) * FLOW_ARROW_PT * 100
        ind = min(gap - HWPUNIT_PER_MM, (gap + glyph) / 2)
        cells2, bounds = None, None
        if block.get("widths"):
            widths, w, pad = list(block["widths"]), None, 0
        elif lines == 2:
            # 두 줄 도표는 두 줄 모두 좌우를 꽉 채운다(사용자 2026-11-05 '좌우가 꽉차게 2단으로' — 옛 판은 상자 너비를 두 줄
            # 같게 두어 윗줄이 아랫줄 첫 → 폭만큼 짧았음). 윗줄 상자 너비 wt, 아랫줄은 첫 →(ind) 뒤라 wb를 따로 정하고, 두 줄의
            # 칸 경계를 모아 잘게 나눈 뒤 상자·화살표 칸을 합친다(좁은 칸은 늘 합친 칸의 일부 — 따로 남지 않음).
            m = n - k
            wt = (total - (k - 1) * gap) / k
            # 아랫줄 상자 수가 윗줄과 같으면(6·8단계) 첫 → 뒤를 꽉 채우는 너비, 하나 적으면(7단계) 윗줄 상자와 같은 너비로 두고
            # 오른쪽 끝을 비운다(사용자 2026-11-05 '2번' — 상자 너비를 위아래 같게)
            wb = (total - ind - (m - 1) * gap) / m if m == k else wt
            cells2 = [[], []]
            for j in range(k):
                x0 = j * (wt + gap)
                cells2[0].append((x0, x0 + wt, steps[j], True))
                if j:
                    cells2[0].append((x0 - gap, x0, arrow, False))
            cells2[1].append((0.0, ind, arrow, False))  # 첫 상자 앞 →: 왼쪽 끝 = 윗줄 첫 상자 왼쪽 선
            for j in range(m):
                x0 = ind + j * (wb + gap)
                cells2[1].append((x0, x0 + wb, steps[k + j], True))
                if j:
                    cells2[1].append((x0 - gap, x0, arrow, False))
            bounds = []
            for x in sorted({x for row in cells2 for c in row for x in c[:2]} | {0.0, float(total)}):
                if not bounds or x - bounds[-1] > 50:  # 0.2mm 안의 경계는 하나로
                    bounds.append(x)
            bounds[-1] = float(total)
            widths = [b1 - b0 for b0, b1 in zip(bounds, bounds[1:])]
            w, pad = min(wt, wb), 0
        else:
            w = min((total - (k - 1) * gap) / k, FLOW_BOX_MAX_MM * HWPUNIT_PER_MM)  # 한 줄은 상한(늘어져 보이지 않게 가운데)
            pad = (total - k * w - (k - 1) * gap) / 2  # 남는 폭은 양옆 빈 칸으로(도표를 가운데에)
            widths = [w if j % 2 == 0 else gap for j in range(2 * k - 1)]
            if pad >= HWPUNIT_PER_MM:
                widths = [pad] + widths + [pad]
            else:
                widths[0] += 2 * pad
                pad = 0
        # 상자 높이: 글 1~2줄이면 14mm, 한 줄 늘 때마다 5mm(3줄 19mm). 한 도표의 상자는 모두 같은 높이.
        width_for_text = (w or total / max(1, 2 * k - 1)) - inner
        n_lines = max(sum(max(1, math.ceil(text_w(line) / width_for_text)) for line in str(s).split("\n"))
                      for s in steps)
        box_h = (FLOW_BOX_H_MM + 5 * max(0, n_lines - 2)) * HWPUNIT_PER_MM
        off = 1 if pad else 0  # 왼쪽 빈 칸이 있으면 도표 칸 번호가 하나씩 밀림
        width_n = len(widths)
        if lines == 1 and width_n != 2 * k - 1 + 2 * off:
            raise BuildError(f"{where}: flow의 widths는 칸 수({2 * k - 1} — 상자·화살표 칸)만큼이어야 합니다.")
        rows, boxes, arrows, spans = [], set(), set(), {}

        def put(r, c, s, is_box, span=1):
            rows[r][c + off] = s
            (boxes if is_box else arrows).add((r, c + off))
            if span > 1:
                spans[(r, c + off)] = span

        if title:
            rows.append([title] + [""] * (width_n - 1))
            spans[(0, 0)] = width_n  # 제목 줄은 한 칸으로 합침
        if not title:  # 위 빈 줄(얇게) — 제목이 있으면 제목 칸 아래 여백이 상자와의 사이(약 3mm)가 됨
            rows.append([""] * width_n)
        rows.append([""] * width_n)
        if lines == 1:
            for j in range(k):
                put(len(rows) - 1, 2 * j, steps[j], True)
                if j:
                    put(len(rows) - 1, 2 * j - 1, arrow, False)
            lead_arrow = None
        else:  # 둘째 줄도 왼쪽 → 오른쪽(아래로 가는 화살표는 쓰지 않음 — 사용자 의견 2026-11-01)
            def col(x):
                return min(range(len(bounds)), key=lambda i: abs(bounds[i] - x))

            for x0, x1, s, is_box in cells2[0]:  # 윗줄: 상자·화살표 칸을 경계에 맞춰 합침
                put(len(rows) - 1, col(x0), s, is_box, col(x1) - col(x0))
            rows.append([""] * width_n)  # 줄 사이
            rows.append([""] * width_n)
            for x0, x1, s, is_box in cells2[1]:  # 아랫줄: 첫 → 칸(왼쪽에 붙임) + 상자·화살표
                put(len(rows) - 1, col(x0), s, is_box, col(x1) - col(x0))
            lead_arrow = (len(rows) - 1, off)
        rows.append([""] * width_n)  # 아래 빈 줄
        for r, row in enumerate(rows):  # 빈 칸은 줄마다 이어 합친다(좁은 칸이 따로 남지 않게)
            c = 0
            while c < width_n:
                if (r, c) in spans:
                    c += spans[(r, c)]
                    continue
                if row[c]:
                    c += 1
                    continue
                e = c
                while e < width_n and not row[e] and (r, e) not in spans:
                    e += 1
                if e - c > 1:
                    spans[(r, c)] = e - c
                c = e
        # 화살표·제목은 굵게: 견본 표 머리 줄의 굵은 글자 모양을 빌려(사용자 의견 2026-11-01)
        bold = next((r.get("charPrIDRef") for tc in trs[0].iter(T("hp:tc")) for cp in cell_paras(tc)
                     for r in para_runs(cp) if self.styles.char.get(r.get("charPrIDRef"), {}).get("bold")), None)
        self.rebuild_rows(tbl, {"table": rows, "header_rows": 0, "widths": widths,
                                "body_like": min(1, len(trs) - 1)}, where)
        none = self.hedit.border_lines(tbl.get("borderFillIDRef"), "NONE")
        box = self.hedit.border_lines(tbl.get("borderFillIDRef"), "SOLID")
        tbl.set("borderFillIDRef", none)
        tbl.set("pageBreak", "NONE")  # 제목·상자가 두 쪽으로 갈라지지 않게
        inm = tbl.find(T("hp:inMargin"))
        if inm is not None:  # 상자 안 글이 선에 붙지 않게 위아래 1.2mm
            for key in ("top", "bottom"):
                inm.set(key, str(max(int(inm.get(key, "0")), int(1.2 * HWPUNIT_PER_MM))))
        trs = [tr for tr in tbl if tr.tag == T("hp:tr")]
        for (r, c), span in spans.items():  # 제목 줄·두 줄 도표의 상자: 칸 합치기
            cells = {int(tc.find(T("hp:cellAddr")).get("colAddr")): tc for tc in trs[r] if tc.tag == T("hp:tc")}
            part = [cells[j] for j in range(c, c + span)]
            part[0].find(T("hp:cellSpan")).set("colSpan", str(span))
            part[0].find(T("hp:cellSz")).set("width", str(sum(int(tc.find(T("hp:cellSz")).get("width")) for tc in part)))
            for tc in part[1:]:
                trs[r].remove(tc)

        def size_runs(tc, want, cid_of=None):
            for cp in cell_paras(tc):
                for run in para_runs(cp):
                    cid = (cid_of or run.get("charPrIDRef"))
                    size = self.styles.char.get(cid, {}).get("size", want)
                    run.set("charPrIDRef", self.hedit.char_size(cid, want - size) if size != want else cid)

        first = None if title else 0
        box_rows = {r for r, _ in boxes}
        for r, c, rs, cs, tc in table_grid(tbl):
            tc.set("header", "0")
            tc.set("borderFillIDRef", box if (r, c) in boxes else none)
            sz = tc.find(T("hp:cellSz"))
            if r in box_rows:  # 상자 줄은 모든 칸을 상자 높이로
                sz.set("height", str(int(box_h)))
            if (r, c) in boxes:  # 상자 글은 FLOW_PT, 가운데, 줄 간격 140%, 좌우 안 여백 2mm·위아래 1mm
                size_runs(tc, FLOW_PT)
                for cp in cell_paras(tc):
                    cp.set("paraPrIDRef", self.hedit.para_line(cp.get("paraPrIDRef"), FLOW_LINE))
                sub = tc.find(T("hp:subList"))
                if sub is not None:
                    sub.set("vertAlign", "CENTER")
                cm = tc.find(T("hp:cellMargin"))
                if cm is not None:
                    tc.set("hasMargin", "1")
                    for key, mm in (("left", FLOW_PAD_MM), ("right", FLOW_PAD_MM), ("top", 1), ("bottom", 1)):
                        cm.set(key, str(int(mm * HWPUNIT_PER_MM)))
            elif (r, c) in arrows:
                size_runs(tc, FLOW_ARROW_PT, bold)
                if (r, c) == lead_arrow:
                    for cp in cell_paras(tc):
                        cp.set("paraPrIDRef", self.hedit.para_align(cp.get("paraPrIDRef"), "LEFT"))
                    cm = tc.find(T("hp:cellMargin"))
                    if cm is not None:
                        tc.set("hasMargin", "1")
                        cm.set("left", "0")
                        cm.set("right", "0")
            elif title and r == 0:
                size_runs(tc, FLOW_TITLE_PT, bold)
            elif r in (first, len(rows) - 1):  # 위·아래 빈 줄(글자 4pt, 1.5mm) — 아래 줄은 뒤가 글이면 flow_gaps가 6mm로
                sz.set("height", str(int(1.5 * HWPUNIT_PER_MM)))
                if r == len(rows) - 1:
                    self.flow_bottom.setdefault(tbl, []).append(sz)
                size_runs(tc, 4)
            elif r in box_rows:  # 상자 줄의 빈 칸
                size_runs(tc, FLOW_PT)
            else:  # 두 줄 도표의 줄 사이(얇게)
                size_runs(tc, 4)
                sz.set("height", str(int(FLOW_ROW_GAP_MM * HWPUNIT_PER_MM)))
        self.flow_tables.add(tbl)

    def _find_flow_tables(self):
        """문서에 이미 있는 투명 선 도표: 화살표(→ ⇒ ➜)만 든 칸이 있고 그 칸의 네 변이 모두 선 없음인 표.
        (만들 때 flow_table이 그리는 모양 — 상자 칸만 실선, 사이 칸에 화살표)"""
        fills = {bf.get("id"): bf for bf in self.pkg.xml("Contents/header.xml").iter(T("hh:borderFill"))}
        found = set()
        for tbl in self.sec.iter(T("hp:tbl")):
            for *_, tc in table_grid(tbl):
                if "".join(para_text(cp) for cp in cell_paras(tc)).strip() not in ("→", "⇒", "➜"):
                    continue
                bf = fills.get(tc.get("borderFillIDRef"))
                sides = [bf.find(T("hh:" + k)) if bf is not None else None
                         for k in ("leftBorder", "rightBorder", "topBorder", "bottomBorder")]
                if all(x is None or x.get("type") in (None, "NONE") for x in sides):
                    found.add(tbl)
                    break
        return found

    def flow_gaps(self, out):
        """도표 바로 뒤가 글 문단(○ 등)이면 도표 아래를 6mm 띄운다(디자인 검토 권고 2026-11-01).
        빈 줄·표가 뒤따르면 그대로 둔다(한글은 빈 줄 칸을 약 4mm보다 낮게 그리지 않음 — 실측)."""
        for p, nxt in zip(out, out[1:]):
            for tbl in para_tables(p):
                if self.flow_bottom.get(tbl) and not para_tables(nxt) and para_text(nxt).strip():
                    for sz in self.flow_bottom[tbl]:
                        sz.set("height", str(int(6 * HWPUNIT_PER_MM)))

    def rebuild_rows(self, tbl, block, where):
        data = block["table"]
        if not isinstance(data, list) or not all(isinstance(r, list) for r in data):
            raise BuildError(f"{where}: table은 [[칸, 칸, …], …] 줄 목록이어야 합니다.")
        tcols = int(tbl.get("colCnt", "0"))
        want = block.get("cols") or max((len(r) for r in data), default=tcols)
        if want != tcols or block.get("widths"):
            self.reshape_cols(tbl, want, block.get("widths"), where)
        if block.get("widths"):
            self.fixed_widths.add(tbl)  # 사용자가 준 칸 너비 — 표 맞춤이 다시 나누지 않음(옛 판: [1,8,1]이 26·102·42mm, 평가 2026-11-09)
        trs = [tr for tr in tbl if tr.tag == T("hp:tr")]
        h = block.get("header_rows", 1 if len(trs) > 1 else 0)
        if not isinstance(h, int) or not 0 <= h <= len(trs):
            raise BuildError(f"{where}: header_rows는 0~{len(trs)} 사이 숫자여야 합니다.")
        # 머리 줄 밖까지 세로로 합친 칸이 있으면 줄을 다시 짜지 못한다 — 파일을 만들기 전에 알림(옛 판은 깨진 표를 만든 뒤 구조 검사에서 걸림)
        for r, tr in enumerate(trs):
            for tc in tr:
                span = tc.find(T("hp:cellSpan")) if tc.tag == T("hp:tc") else None
                if span is not None and r + int(span.get("rowSpan", "1")) > h and span.get("rowSpan", "1") != "1":
                    raise BuildError(f"{where}: 견본 표에 세로로 합친 칸이 있어 줄을 다시 짤 수 없습니다. "
                                     "\"cells\"로 칸만 채우세요.")
        body_like = block.get("body_like", min(h, len(trs) - 1))
        last_like = block.get("last_like")
        for name, v in (("body_like", body_like), ("last_like", last_like)):
            if v is not None and not (isinstance(v, int) and 0 <= v < len(trs)):
                raise BuildError(f"{where}: {name}는 견본 표의 줄 번호(0~{len(trs) - 1})여야 합니다.")
        keep_header = bool(block.get("keep_header"))
        rows_out = []
        if keep_header:
            rows_out = [(copy.deepcopy(trs[i]), None) for i in range(h)]
            body_rows = data
        else:
            body_rows = data[h:]
            for i in range(min(h, len(data))):
                rows_out.append((copy.deepcopy(trs[i]), data[i]))
            if len(data) < h:
                raise BuildError(f"{where}: 머리 줄이 {h}줄인데 table에 {len(data)}줄만 있습니다. "
                                 "머리 줄을 견본 그대로 두려면 \"keep_header\": true를 쓰세요.")
        for k, row in enumerate(body_rows):
            src = trs[last_like] if (last_like is not None and k == len(body_rows) - 1) else trs[body_like]
            rows_out.append((copy.deepcopy(src), row))

        for i, (tr, row) in enumerate(rows_out):
            cells = [tc for tc in tr if tc.tag == T("hp:tc")]
            if row is not None:
                is_header = i < h
                for tc in cells:
                    span = tc.find(T("hp:cellSpan"))
                    if not is_header and span is not None and span.get("rowSpan", "1") != "1":
                        raise BuildError(f"{where}: 견본 표의 본문 줄에 세로로 합친 칸이 있어 줄 수를 바꿀 수 없습니다. "
                                         "\"cells\"로 칸만 채우세요.")
                if len(row) > len(cells):
                    raise BuildError(f"{where}: {i + 1}번째 줄은 칸이 {len(cells)}개인데 글이 {len(row)}개입니다.")
                for k, tc in enumerate(cells):
                    self.fill_cell(tc, row[k] if k < len(row) else "", f"{where} {i + 1}번째 줄 {k + 1}번째 칸")
            for tc in cells:
                drop_linesegs(tc)
                tc.find(T("hp:cellAddr")).set("rowAddr", str(i))
        for tr in trs:
            tbl.remove(tr)
        for tr, _ in rows_out:
            tbl.append(tr)
        tbl.set("rowCnt", str(len(rows_out)))
        total = 0
        for tr, _ in rows_out:
            hs = [int(tc.find(T("hp:cellSz")).get("height", "0")) for tc in tr if tc.tag == T("hp:tc")
                  and (tc.find(T("hp:cellSpan")) is None or tc.find(T("hp:cellSpan")).get("rowSpan", "1") == "1")]
            total += max(hs) if hs else 0
        sz = tbl.find(T("hp:sz"))
        if sz is not None and total:
            sz.set("height", str(total))

    def reshape_cols(self, tbl, n, widths, where):
        """표의 칸 수를 n으로 바꾼다. 첫 칸·끝 칸은 견본의 첫 칸·끝 칸 모양을, 가운데 칸은 견본 가운데 칸 모양을 쓴다
        (그래서 '맨 왼쪽·오른쪽 선 없음' 같은 바깥 선 모양이 그대로 따라간다)."""
        if not isinstance(n, int) or n < 1:
            raise BuildError(f"{where}: cols는 1 이상의 숫자여야 합니다.")
        trs = [tr for tr in tbl if tr.tag == T("hp:tr")]
        if any(rs > 1 or cs > 1 for _, _, rs, cs, _ in table_grid(tbl)):
            raise BuildError(f"{where}: 합친 칸이 있는 표는 칸 수를 바꿀 수 없습니다(견본 {tbl.get('colCnt')}칸). "
                             "칸 수를 견본에 맞추거나 합친 칸이 없는 표를 고르세요.")
        tw = [int(tc.find(T("hp:cellSz")).get("width", "0")) for tc in trs[0] if tc.tag == T("hp:tc")]
        total = sum(tw)
        if widths:
            if (not isinstance(widths, list) or len(widths) != n
                    or any(not isinstance(w, (int, float)) or w <= 0 for w in widths)):
                raise BuildError(f"{where}: widths는 칸 수({n})만큼의 양수 목록이어야 합니다(비율, 예: [1, 2, 2]).")
            ws = [total * w / sum(widths) for w in widths]
        elif n == len(tw):
            ws = tw
        elif n == 1:
            ws = [total]
        else:
            w0 = tw[0] if len(tw) > 1 and tw[0] < total * 0.4 else total / n
            ws = [w0] + [(total - w0) / (n - 1)] * (n - 1)
        ws = [int(round(w)) for w in ws]
        ws[-1] += total - sum(ws)
        for tr in trs:
            cells = [tc for tc in tr if tc.tag == T("hp:tc")]
            m = len(cells)
            if m < 3 and n > 2:
                self.warn(f"{where}: 견본 표에 가운데 칸 모양이 없어 가운데 칸은 끝 칸 모양을 빌렸습니다.")

            def src(j):
                if j == 0:
                    return cells[0]
                if j == n - 1:
                    return cells[-1]
                return cells[1] if m >= 3 else cells[-1]

            new = []
            for j in range(n):
                tc = copy.deepcopy(src(j))
                tc.find(T("hp:cellAddr")).set("colAddr", str(j))
                tc.find(T("hp:cellSz")).set("width", str(ws[j]))
                if n == 1 and m > 1:
                    # 한 칸뿐이면 첫 칸이자 끝 칸 — 오른쪽 선은 견본 끝 칸 것(첫 칸 오른쪽은 칸 사이 선이라 그대로 두면
                    # 오른쪽 선만 남아 그래프 상자 왼쪽 선이 없어 보였음, 사용자 지적 2026-11-04)
                    tc.set("borderFillIDRef", self.hedit.border_sides(
                        tc.get("borderFillIDRef"), {"rightBorder": cells[-1].get("borderFillIDRef")}))
                new.append(tc)
            for tc in cells:
                tr.remove(tc)
            for tc in new:
                tr.append(tc)
        tbl.set("colCnt", str(n))
