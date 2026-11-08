# -*- coding: utf-8 -*-
"""검사만(v1.21): 이미 쓴 한글(hwpx) 문서를 읽어 서식 원칙에 비춰 고칠 곳을 알려 준다. **파일은 바꾸지 않는다.**

    python scripts/review.py 문서.hwpx

읽는 것: 어림 쪽 수·쪽 채움, 쓰인 글꼴(한글과 맞대어 본 글꼴인지), 근거법령 자리·개수, 항목 수, ‘~으로’ 끝맺음,
요약 상자·날짜 줄, 제목 상자 위 빈 공간, 그리고 다듬기(다음 판)가 고칠 수 있는 줄·표 맞춤(지금은 알리기만).
한글 없이 어림한 결과라 마지막 확인은 한글에서. 다른 사람이 만든 문서도 되지만, 견본과 다른 짜임(□○ 기호가 없는
서술식 등)이면 알림이 뜨지 않거나 어긋날 수 있다.
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from hwpx_lib import (T, Package, cell_paras, head_length, is_struct, marker_level, page_info, para_pics,  # noqa: E402
                      para_runs, para_tables, para_text, run_text, split_marker, table_grid, is_table_title)
from build import (BASIS_TITLE_RE, DATE_LINE_RE, FIX_RE, ROMAN, SUMMARY_END_RE, BuildError, Builder,  # noqa: E402
                   basis_exempt, margin_note, read_doc_meta)

# 제목 상자 글이 이 말로 끝나면 근거법령 없이 시작하는 문서로 본다(style-guide 3-2 — 계획의 doc_type을 모를 때)
TITLE_EXEMPT_RE = re.compile(r"(회의\s*자료|보도\s*자료|답변서?|주간\s*업무\s*보고|사업\s*설명서|보도\s*(관련\s*)?대응\s*보고)\s*(\(안\))?\s*$")
from check import check  # noqa: E402
from fit import Fitter, cover_end  # noqa: E402


class Inspector:
    def __init__(self, path, doc_type=None, basis=True, basis_searched=False):
        self.path = path
        self.pkg = Package(path)
        self.b = Builder(self.pkg)
        self.doc_type = doc_type  # 계획의 doc_type과 같은 뜻(--doc-type)
        self.basis_on = basis     # False면 근거법령 검사를 건너뜀(계획의 "basis_first": false와 같음, --no-basis)
        self.basis_searched = basis_searched  # 둘째 근거를 찾아봤지만 없음(계획의 basis_searched, --basis-searched)
        self.paras = [p for p in self.b.sec if p.tag == T("hp:p")]
        self.fix, self.info, self.polish = [], [], []  # 사람이 고칠 것 / 참고 / 다듬기가 할 수 있는 것

    # ------------------------------------------------------------ 읽기만 하는 검사
    def fonts(self):
        used = {}
        for p in self.b.sec.iter(T("hp:p")):
            for r in para_runs(p):
                if r.find(T("hp:t")) is None:
                    continue
                c = self.b.styles.char.get(r.get("charPrIDRef"), {})
                f = c.get("font")
                if f:
                    used[f] = used.get(f, 0) + 1
        checked = [f for f in used if self.b.metrics.checked(f)]
        other = [f for f in used if f not in checked]
        self.info.append("쓰인 글꼴: " + ", ".join(f"{f}({n})" for f, n in sorted(used.items(), key=lambda x: -x[1]))
                         + (f" — 한글과 맞대어 본 글꼴 {', '.join(checked)}" if checked else ""))
        if other:
            self.info.append(f"맞대어 보지 않은 글꼴 {', '.join(other)}: 이 글꼴 문단은 줄 맞춤(자간)을 어림할 수 없어 다듬기가 "
                             "건드리지 않습니다(알림만). 한글과 맞대어 본 글꼴은 판마다 늘려 갑니다.")

    def body_start(self):
        end = cover_end(self.paras)
        return end or 0

    def _basis_skip(self):
        """근거법령 검사를 건너뛸 까닭(없으면 None): --no-basis·--doc-type, 만든 문서에 남긴 표시, 제목 상자 글(3-2 예외 문서)."""
        meta = read_doc_meta(self.pkg)
        if not self.basis_on:
            return "--no-basis"
        if basis_exempt(self.doc_type):
            return f"문서 종류 ‘{self.doc_type}’"
        if meta.get("basis") == "off":
            return "만들 때 근거법령 검사를 끈 문서" + (f"(문서 종류 ‘{meta['doc_type']}’)" if meta.get("doc_type") else "")
        start = self.body_start()
        title = next((p for p in self.paras[start:start + 4] if para_tables(p) and para_tables(p)[0].get("rowCnt") == "1"
                      and para_tables(p)[0].get("colCnt") == "1"), None)
        if title is not None:
            text = " ".join(para_text(cp) for cp in cell_paras(table_grid(para_tables(title)[0])[0][4])).strip()
            if TITLE_EXEMPT_RE.search(text):
                return f"제목 ‘{text[:20]}’"
        return None

    def basis(self):
        """근거법령은 늘 1번: 로마자 장이면 Ⅰ., 아니면 첫 □ 근거법령(○ 둘 이상). 3-2 표의 예외 문서는 건너뜀."""
        why = self._basis_skip()
        if why:
            self.info.append(f"{why} — 근거법령 없이 시작하는 문서라(style-guide 3-2) 근거법령 검사를 건너뜀.")
            return
        start = self.body_start()
        heads = [(i, p) for i, p in enumerate(self.paras[start:], start)
                 if not para_tables(p) and marker_level(para_text(p)) == 1 and not is_table_title(p)]
        if not heads:
            self.info.append("□·Ⅰ. 제목이 없어 근거법령·항목 수 검사를 건너뜀(견본과 다른 짜임).")
            return
        i, first = heads[0]
        mark = split_marker(para_text(first))[1]
        roman = bool(mark) and mark[0] in ROMAN
        if BASIS_TITLE_RE.search(para_text(first)):
            return  # 근거법령 ○ 개수는 rules()의 항목 수 검사(lone_dashes)가 한 번만 알림 — 옛 판은 같은 지적을 두 번 냈음
        where = next((f"{para_text(p).strip()[:14]}" for _, p in heads[1:] if BASIS_TITLE_RE.search(para_text(p))), None)
        if where is None:
            sq = ""
            for p in self.paras[start:]:
                if para_tables(p):
                    continue
                text = para_text(p).replace("⎵", " ").replace("⍽", " ")
                if marker_level(text) == 1:
                    sq = split_marker(text)[2].strip()[:10]
                elif marker_level(text) == 2 and self.b._is_basis(text):
                    where = f"□ ‘{sq}’ 안의 ○ {split_marker(text)[2].strip()[:12]}"
                    break
        if where:
            self.fix.append(f"근거법령이 맨 앞이 아닙니다({where}) — {'Ⅰ. 근거법령 장' if roman else '□ 근거법령'}을 1번으로 "
                            "옮기세요(아래 ○로 법령 하나씩, 둘 이상).")
        else:
            self.fix.append(f"근거법령이 없습니다 — {'Ⅰ. 근거법령 장' if roman else '첫 □ 근거법령'}(○ 「…법」 제○조, 둘 이상)을 "
                            "맨 앞에 두세요. 근거를 모르면 작성자에게 묻습니다.")

    def title_and_summary(self):
        start = self.body_start()
        title = next((i for i, p in enumerate(self.paras[start:], start)
                      if para_tables(p) and para_tables(p)[0].get("rowCnt") == "1" and para_tables(p)[0].get("colCnt") == "1"), None)
        if title is None:
            self.info.append("제목 상자(한 칸 표)를 찾지 못해 제목·요약 상자·날짜 줄 검사를 건너뜀.")
            return
        p = self.paras[title]
        runs = para_runs(p)
        k = next((n for n, r in enumerate(runs) if r.find(T("hp:tbl")) is not None), len(runs))
        if any(r.find(T("hp:secPr")) is None and any(is_struct(ch) for ch in r) for r in runs[:k]):
            self.polish.append("첫 쪽 제목 상자 위에 빈 공간이 생깁니다(제목 표 앞에 쪽 번호 같은 조종 조각이 있어 한글이 한 줄을 줌, "
                               "약 3.5mm) — 다듬기가 그 조각을 날짜 줄로 옮김(36번: 제목 위에는 공간을 두지 않음).")
        if title > start and any(para_text(q).strip() or para_tables(q) for q in self.paras[start:title]):
            self.polish.append("제목 상자 앞에 글·빈 줄이 있어 제목이 쪽 맨 위에 붙지 않습니다(제목 위에는 공간을 두지 않음).")
        summary = next((i for i, q in enumerate(self.paras[title + 1:title + 6], title + 1)
                        if para_tables(q) and para_tables(q)[0].get("rowCnt") == "1" and para_tables(q)[0].get("colCnt") == "1"), None)
        between = self.paras[title + 1:summary] if summary else self.paras[title + 1:title + 3]
        if not any(DATE_LINE_RE.match(para_text(q)) for q in between if not para_tables(q)):
            self.fix.append("제목 상자 아래 날짜·부서 줄이 없습니다 — ‘’26. ○. ○.(○)  ○○○○과 ○○○’ 한 줄을 두세요.")
        if summary is None:
            self.info.append("요약 상자(제목 아래 한 칸 상자)가 없습니다 — 결론 한 문장을 두세 줄로 두는 것이 원칙.")
            return
        tc = table_grid(para_tables(self.paras[summary])[0])[0][4]
        text = "\n".join(para_text(q) for q in cell_paras(tc)).replace("⎵", " ").strip()
        if "\n" in text or re.search(r"[①-⑳]|(^|\n)\s*(\d+[.)]|[-○·])\s", text):
            self.fix.append("요약 상자에 번호·여러 항목이 있습니다 — 한 문장으로 두세 줄(25번, 세부는 아래 □·○로).")
        if text and not SUMMARY_END_RE.search(text):
            self.fix.append(f"요약 상자 끝맺음은 ‘~하고자 함’ 또는 ‘~에 대한 보고임’ — 지금: ‘…{text[-12:]}’.")

    def rules(self):
        """항목 수·‘~으로’ 끝맺음 — build.py의 문단 검사 그대로."""
        before = len(self.b.warnings)
        # 둘째 근거를 찾아봤지만 없음(만들 때 basis_searched, 또는 --basis-searched) → ○ 하나여도 알림만
        self.b.basis_searched = self.basis_searched or read_doc_meta(self.pkg).get("basis_searched") == "yes"
        self.b.lone_dashes(self.paras)
        self.b.basis_notes(self.paras)
        self.b.ref_sole_titles(self.paras, remove=False)
        self.b.table_titles(self.paras)
        self.b.flow_steps(self.paras)
        self.b.check_endings(self.paras)
        for w in self.b.warnings[before:]:  # 등급은 만들기와 같게(FIX_RE) — 알림 등급 문장이 '고쳐야 함'에 섞이지 않게
            (self.fix if FIX_RE.search(w) else self.info).append(w)

    # ------------------------------------------------------------ 다듬기가 할 수 있는 것(한 번 해 보고 버림 — 파일은 안 바꿈)
    def _state(self):
        """서식 값으로 본 문서 상태(서식 번호·조각 나눔은 무시): 글 문단마다 (내어쓰기, 글자마다 (글자, 자간)),
        표마다 칸마다 (너비, 칸 위 여백, 칸 글 (크기, 한 줄로 입력, 정렬, 자간))."""
        st = self.b.styles

        def chars(p):
            out = []
            for r in para_runs(p):
                c = st.char.get(r.get("charPrIDRef"), {})
                out += [(ch, c.get("spacing", 0), c.get("size")) for ch in run_text(r)]
            return out

        sides = {}
        for bf in self.b.pkg.xml("Contents/header.xml").iter(T("hh:borderFill")):
            sides[bf.get("id")] = tuple((bf.find(T("hh:" + k)).get("type") if bf.find(T("hh:" + k)) is not None else None)
                                       for k in ("leftBorder", "rightBorder"))
        paras, tables = [], []
        for p in [x for x in self.b.sec if x.tag == T("hp:p")]:
            if para_tables(p):
                for tbl in para_tables(p):
                    m = tbl.find(T("hp:inMargin"))
                    om = tbl.find(T("hp:outMargin"))
                    cells = []
                    for _, _, _, _, tc in table_grid(tbl):
                        sz = tc.find(T("hp:cellSz"))
                        cm = tc.find(T("hp:cellMargin"))
                        cps = tuple((tuple(chars(cp)), st.para.get(cp.get("paraPrIDRef"), {}).get("squeeze"),
                                     st.para.get(cp.get("paraPrIDRef"), {}).get("align")) for cp in cell_paras(tc))
                        cells.append((sz.get("width"), cm.get("top") if cm is not None else None, cps,
                                      sides.get(tc.get("borderFillIDRef"))))
                    tables.append(((m.get("top") if m is not None else None), cells, cell_text_first(tbl),
                                   om.get("bottom") if om is not None else None))
            else:
                pp = st.para.get(p.get("paraPrIDRef"), {})
                paras.append((para_text(p), pp.get("intent", 0), tuple(chars(p))))
        return paras, tables

    def _changes(self, before, after):
        """다듬기 한 번이 실제로 바꾸는 것만 세어 사람 말로(되풀이해도 같은 문서는 아무것도 안 나옴)."""
        out = []
        (pb, tb), (pa, ta) = before, after
        spacing, hang, breaks, corners = [], [], [], []
        for (tx, ix, cx), (ty, iy, cy) in zip(pb, pa):
            name = tx[head_length(tx):].replace("⎵", " ").strip()[:12]
            if tx.replace("\n", "") != ty.replace("\n", "") or tx.count("\n") != ty.count("\n"):
                breaks.append(name)
            if ix != iy:
                hang.append(name)
            if [c[1] for c in cx] != [c[1] for c in cy] and len(cx) == len(cy):
                k = next((i for i, c in enumerate(cy) if c[0] in "「『"), None)
                head = head_length(tx)
                if k is not None and k <= head + 3 and any(cx[i][1] != cy[i][1] for i in range(min(k, len(cx)))):
                    corners.append(name)
                if any(a[1] != b[1] for a, b in zip(cx[head:], cy[head:])):
                    spacing.append(name)

        def line(n, what, names):
            if names:
                out.append(f"글 문단 {len(names)}개 — {what}: " + ", ".join(f"‘{x}…’" for x in names[:3]) + (" 등" if len(names) > 3 else ""))

        line(0, "자간을 조금 바꿔 끝 줄·빈칸 맞춤", spacing)
        line(0, "둘째 줄 내어쓰기를 이름표·쌍점·화살표 뒤 첫 글자에 맞춤", hang)
        line(0, "줄 바꿈 자리 조정(연결어·화살표·끝 줄 균형)", breaks)
        line(0, "줄 첫머리 낫표(「) 반 칸 당김", corners)
        kinds = {"칸 너비": 0, "칸 글자 크기": 0, "한 줄로 입력": 0, "칸 여백": 0, "칸 글 정렬·자간": 0,
                 "표 아래 띄움(밑 글이 붙지 않게)": 0, "그래프 상자 양옆 선": 0}
        names = []
        for (mx, cx, nx, ox), (my, cy, ny, oy) in zip(tb, ta):
            hit = set()
            if mx != my:
                hit.add("칸 여백")
            if ox != oy:
                hit.add("표 아래 띄움(밑 글이 붙지 않게)")
            for a, b in zip(cx, cy):
                if a[0] != b[0]:
                    hit.add("칸 너비")
                if a[1] != b[1]:
                    hit.add("칸 여백")
                if a[3] != b[3]:
                    hit.add("그래프 상자 양옆 선")
                for pa_, pb_ in zip(a[2], b[2]):
                    if [c[2] for c in pa_[0]] != [c[2] for c in pb_[0]]:
                        hit.add("칸 글자 크기")
                    if pa_[1] != pb_[1]:
                        hit.add("한 줄로 입력")
                    if pa_[2] != pb_[2] or [c[1] for c in pa_[0]] != [c[1] for c in pb_[0]]:
                        hit.add("칸 글 정렬·자간")
            for h in hit:
                kinds[h] += 1
            if hit:
                names.append(nx)
        if names:
            out.append(f"표 {len(names)}개 — " + ", ".join(f"{k} {v}개" for k, v in kinds.items() if v) + ": "
                       + ", ".join(f"‘{x}…’" for x in names[:3]) + (" 등" if len(names) > 3 else ""))
        return out

    def dry_polish(self, tables=True):
        """다듬기를 한 번 걸어 보고(파일은 저장하지 않음) 실제로 바뀌는 것과 어림 쪽 수 변화를 적는다."""
        b = self.b
        before_warn = len(b.warnings)
        before = self._state()
        try:
            b.tighten_quotes()
            b.colon_hang(colons=True, labels=True)
            f = Fitter(b)
            f.lay.move_whole = False  # 다듬기는 쪽 나눔을 박지 않음 — 한글이 하는 대로 셈
            f.push = True
            if tables:
                f.fit_tables()
                f.fit_tables(again=True)
            f.fit_lines()
            if tables:
                f.relieve_pads(refit=False)  # 칸 여백을 넓혀 □ 묶음이 쪽에 걸치면 되돌림(쪽 짜임은 그대로)
            f.pull_corners()
            hard = [w for w in b.warnings[before_warn:] + f.notes if FIX_RE.search(w)]
            fa = Fitter(b)
            fa.lay.move_whole = False
            after_pages = fa.report()
        except Exception as e:  # noqa: BLE001 — 다른 사람 문서라 어떤 짜임이든 올 수 있음
            self.info.append(f"다듬기 어림 중 멈춤({type(e).__name__}: {e}) — 이 문서는 다듬기 전에 짜임을 봐야 합니다.")
            return None
        self.polish += self._changes(before, self._state())
        self.fix += [w for w in hard if w not in self.fix]
        return after_pages

    # ------------------------------------------------------------ 실행
    def run(self, tables=True):
        f = Fitter(self.b)
        f.lay.move_whole = False  # 원본 쪽 수도 한글이 하는 대로
        pages = f.report()  # 바꾸기 전 어림(원본 쪽 수)
        self.fonts()
        self.basis()
        self.title_and_summary()
        self.rules()
        after = self.dry_polish(tables)
        n0, n1 = page_count(pages), page_count(after) if after else None
        if self.polish and n1 is not None:
            self.polish.append(f"다듬으면 어림 쪽 수 {n0}쪽 → {n1}쪽" + (" — 쪽이 늘어나는 고침은 다듬기가 하지 않습니다(원본 쪽 수 지키기)"
                                                              if n1 > n0 else ""))
        errors, notes, _ = check(self.path)
        return pages, errors, notes


def page_count(report):
    m = re.search(r"어림 쪽 수 (\d+)쪽", report or "")
    return int(m.group(1)) if m else None


def cell_text_first(tbl):
    grid = table_grid(tbl)
    return next((para_text(cp).replace("⎵", " ").strip()[:8] for _, _, _, _, tc in grid for cp in cell_paras(tc)
                 if para_text(cp).strip()), "")


def main():
    ap = argparse.ArgumentParser(description="이미 쓴 hwpx를 검사만 한다(파일을 바꾸지 않음)")
    ap.add_argument("hwpx")
    ap.add_argument("--no-tables", action="store_true", help="표 맞춤 어림은 건너뜀(표가 많아 느릴 때)")
    ap.add_argument("--doc-type", default=None, help="문서 종류(회의자료·보도자료·답변서·주간업무 보고·사업설명서 등 — "
                    "근거법령 없이 시작하는 종류면 근거법령 검사를 건너뜀, 계획의 doc_type과 같음)")
    ap.add_argument("--no-basis", action="store_true", help="근거법령 검사를 건너뜀(계획의 \"basis_first\": false와 같음)")
    ap.add_argument("--basis-searched", action="store_true",
                    help="둘째 근거를 찾아봤지만 없음 — 근거법령 ○ 하나를 알림으로만(계획의 \"basis_searched\": true와 같음)")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        ins = Inspector(a.hwpx, doc_type=a.doc_type, basis=not a.no_basis, basis_searched=a.basis_searched)
        pages, errors, notes = ins.run(tables=not a.no_tables)
    except BuildError as e:
        raise SystemExit(f"검사하지 못함 — {e}")
    print(f"## 검사만: {os.path.basename(a.hwpx)} — 파일은 바꾸지 않았습니다")
    print(" - " + pages)
    tell = margin_note(page_info(ins.b.sec))
    if tell:
        print(" - " + tell)
    print("## 고쳐야 함(글·짜임 — 작성자가 정할 것)")
    for w in ins.fix or ["없음"]:
        print(" - " + w)
    print("## 다듬기가 고칠 것(서식 — 다듬기를 한 번 걸어 본 결과, 파일은 그대로)")
    for w in ins.polish or ["없음"]:
        print(" - " + w)
    print("## 참고")
    for w in ins.info:
        print(" - " + w)
    if errors or notes:
        print("## 파일 검사")
        for w in errors + notes:
            print(" - " + w)
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
