# -*- coding: utf-8 -*-
"""검사만(v1.21): 이미 쓴 한글(hwpx) 문서를 읽어 서식 원칙에 비춰 고칠 곳을 알려 준다. **파일은 바꾸지 않는다.**

    python scripts/review.py 문서.hwpx

읽는 것: 어림 쪽 수·쪽 채움, 쓰인 글꼴(한글과 맞대어 본 글꼴인지), 근거법령 자리·개수, 항목 수, ‘~으로’ 끝맺음,
요약 상자·날짜 줄, 제목 상자 위 빈 공간, 그리고 정돈(tidy.py)이 실제로 바꿀 곳(저장 없이 돌린 '바뀐 곳' 그대로).
한글 없이 어림한 결과라 마지막 확인은 한글에서. 다른 사람이 만든 문서도 되지만, 견본과 다른 짜임(□○ 기호가 없는
서술식 등)이면 알림이 뜨지 않거나 어긋날 수 있다.
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from hwpx_lib import (NUM_CHARS, T, Package, cell_paras, fix_note, head_length, is_struct, marker_level, note_is_fix, page_info,  # noqa: E402
                      para_pics, para_runs, para_tables, para_text, run_text, split_marker, table_grid, is_table_title)
from build import (SKILL_VERSION, print_citations, BASIS_MISSING, BASIS_TITLE_RE, DATE_LINE_RE, OMIT_KEYS, ROMAN, SUMMARY_END_MSG, SUMMARY_END_RE, BuildError, Builder,  # noqa: E402
                   basis_exempt, margin_note, read_doc_meta)

# 제목 상자 글이 이 말로 끝나면 근거법령 없이 시작하는 문서로 본다(doc-types.md — 계획의 doc_type을 모를 때)
TITLE_EXEMPT_RE = re.compile(r"(회의\s*자료|보도\s*자료|답변서?|주간\s*업무\s*보고|사업\s*설명서|보도\s*(관련\s*)?대응\s*보고)\s*(\(안\))?\s*$")
from check import check  # noqa: E402
from fit import Fitter, cover_end  # noqa: E402
from tidy import Tidier  # noqa: E402


class Inspector:
    def __init__(self, path, doc_type=None, basis=True, basis_searched=False, omit=()):
        self.path = path
        self.pkg = Package(path)
        self.b = Builder(self.pkg)
        # 일부러 뺀 요소: --omit 또는 만들 때 남긴 표시(omit=date,summary …)
        self.omit = set(omit) | {k for k in read_doc_meta(self.pkg).get("omit", "").split(",") if k in OMIT_KEYS}
        self.doc_type = doc_type  # 계획의 doc_type과 같은 뜻(--doc-type)
        self.basis_on = basis     # False면 근거법령 검사를 건너뜀(계획의 "basis_first": false와 같음, --no-basis)
        self.basis_searched = basis_searched  # 둘째 근거를 찾아봤지만 없음(계획의 basis_searched, --basis-searched)
        self.paras = [p for p in self.b.sec if p.tag == T("hp:p")]
        self.fix, self.info, self.polish = [], [], []  # 사람이 고칠 것 / 참고 / 정돈이 고칠 것

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
            self.info.append(f"맞대어 보지 않은 글꼴 {', '.join(other)}: 이 글꼴 문단은 줄 맞춤(자간)을 어림할 수 없어 도구가 "
                             "건드리지 않습니다(알림만). 한글과 맞대어 본 글꼴은 판마다 늘려 갑니다.")

    def body_start(self):
        end = cover_end(self.paras)
        return end or 0

    def _basis_skip(self):
        """근거법령 검사를 건너뛸 까닭(없으면 None): --no-basis·--doc-type, 만든 문서에 남긴 표시, 제목 상자 글(문서 종류별 차례의 예외 문서)."""
        meta = read_doc_meta(self.pkg)
        if not self.basis_on:
            return "--no-basis"
        if basis_exempt(self.doc_type):
            return f"문서 종류 ‘{self.doc_type}’"
        if "basis" in self.omit:
            return "근거법령을 일부러 뺀 문서(omit)"
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
        """근거법령은 늘 1번: 로마자 장이면 Ⅰ., 아니면 첫 □ 근거법령(○ 둘 이상). 문서 종류별 차례의 예외 문서는 건너뜀."""
        why = self._basis_skip()
        if why:
            self.info.append(f"{why} — 근거법령 없이 시작하는 문서라(doc-types.md) 근거법령 검사를 건너뜀.")
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
        # 로마자 장 문서는 장 제목만 근거 자리로 본다(만들기와 같음) — 장 안의 □ 추진근거는 Ⅰ. 근거법령 장이 아님
        later = [p for _, p in heads[1:] if not roman or split_marker(para_text(p))[1][:1] in ROMAN]
        where = next((f"{para_text(p).strip()[:14]}" for p in later if BASIS_TITLE_RE.search(para_text(p))), None)
        if where is None and not roman:
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
            self.fix.append(fix_note(f"근거법령이 맨 앞이 아닙니다({where}) — {'Ⅰ. 근거법령 장' if roman else '□ 근거법령'}을 1번으로 "
                                     "옮기세요(아래 ○로 법령 하나씩, 둘 이상).", "basis"))
        else:
            first_text = split_marker(para_text(first))[2].replace("⎵", " ").replace("⍽", " ").strip()[:10]
            self.fix.append(fix_note(BASIS_MISSING.format("Ⅰ. 근거법령 장" if roman else f"본문 첫 □ ‘{first_text}’"), "basis"))

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
            self.info.append("첫 쪽 제목 상자 위에 빈 공간이 생깁니다(제목 표 앞에 쪽 번호 같은 조종 조각이 있어 한글이 한 줄을 줌, "
                             "약 3.5mm) — 작성 모드로 새로 만들면 그 조각을 날짜 줄로 옮김(36번: 제목 위에는 공간을 두지 않음).")
        if title > start and any(para_text(q).strip() or para_tables(q) for q in self.paras[start:title]):
            self.info.append("제목 상자 앞에 글·빈 줄이 있어 제목이 쪽 맨 위에 붙지 않습니다(제목 위에는 공간을 두지 않음).")
        summary = next((i for i, q in enumerate(self.paras[title + 1:title + 6], title + 1)
                        if para_tables(q) and para_tables(q)[0].get("rowCnt") == "1" and para_tables(q)[0].get("colCnt") == "1"), None)
        between = self.paras[title + 1:summary] if summary else self.paras[title + 1:title + 3]
        if not any(DATE_LINE_RE.match(para_text(q)) for q in between if not para_tables(q)):
            self.fix.append(fix_note("제목 상자 아래 날짜·부서 줄이 없습니다 — ‘’26. ○. ○.(○)  ○○○○과 ○○○’ 한 줄을 두세요.", "date"))
        if summary is None:
            self.info.append("요약 상자(제목 아래 한 칸 상자)가 없습니다 — 결론 한 문장을 두세 줄로 두는 것이 원칙.")
            return
        tc = table_grid(para_tables(self.paras[summary])[0])[0][4]
        text = "\n".join(para_text(q) for q in cell_paras(tc)).replace("⎵", " ").strip()
        if "\n" in text or re.search(rf"[{NUM_CHARS}]|(^|\n)\s*(\d+[.)]|[-○·])\s", text):
            self.fix.append(fix_note("요약 상자에 번호·여러 항목이 있습니다 — 한 문장으로 두세 줄(25번, 세부는 아래 □·○로).", "summary"))
        if text and not SUMMARY_END_RE.search(text):
            self.fix.append(fix_note(SUMMARY_END_MSG.format(text[-12:]), "summary"))

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
        for w in self.b.warnings[before:]:  # 등급은 만들기와 같게 — 알림 등급 문장이 '고쳐야 함'에 섞이지 않게
            (self.fix if note_is_fix(w) else self.info).append(w)

    # ------------------------------------------------------------ 정돈이 고칠 것(저장 없이 돌린 '바뀐 곳' 그대로)
    def tidy_preview(self):
        """정돈을 한 번 돌려 보고(저장하지 않음) 실제로 바뀌는 문단과 쪽 수를 적는다 — 옛 판은 작성 도구로 어림해 정돈이 하지 않는 일을
        적고 하는 일은 빠뜨렸음(평가 2026-11-09)."""
        try:
            t = Tidier(self.path)
            before, after, _ = t.run(None)
        except Exception as e:  # noqa: BLE001 — 다른 사람 문서라 어떤 짜임이든 올 수 있음
            self.info.append(f"정돈 어림 중 멈춤({type(e).__name__}: {e}) — 이 문서는 정돈 전에 짜임을 봐야 합니다.")
            return
        self.polish += t.change_lines()
        if self.polish:
            self.polish.append(f"정돈하면 어림 쪽 수 {before}쪽 → {after}쪽")

    def dry_fit(self, tables=True):
        """작성 도구의 맞춤을 한 번 걸어 보고(저장하지 않음) 글을 고쳐야 풀리는 것만 '고쳐야 함'으로."""
        b = self.b
        before_warn = len(b.warnings)
        try:
            b.tighten_quotes()
            b.colon_hang(colons=True, labels=True)
            f = Fitter(b)
            f.lay.move_whole = False  # 쪽 나눔을 박지 않음 — 한글이 하는 대로 셈
            f.push = True
            f.keep_table_pt = int(read_doc_meta(self.pkg).get("table_pt", 0)) or None
            f.rescan_hints = True  # 이미 내린 끝 줄도 '한 줄 줄이기 후보'로 봄(만들기와 같은 지적)
            if tables:
                f.fit_tables()
                f.fit_tables(again=True)
            f.fit_lines()
            if tables:
                f.relieve_pads(refit=False)
            f.pull_corners()
            hard = [w for w in b.warnings[before_warn:] + f.notes if note_is_fix(w)]
        except Exception as e:  # noqa: BLE001 — 다른 사람 문서라 어떤 짜임이든 올 수 있음
            self.info.append(f"맞춤 어림 중 멈춤({type(e).__name__}: {e}) — 글·짜임 검사 일부를 건너뜀.")
            return
        self.fix += [w for w in hard if w not in self.fix]

    # ------------------------------------------------------------ 실행
    def run(self, tables=True):
        f = Fitter(self.b)
        f.lay.move_whole = False  # 원본 쪽 수도 한글이 하는 대로
        pages = f.report()  # 바꾸기 전 어림(원본 쪽 수)
        if len(self.b.sec_names) > 1:  # 글·짜임 검사와 위 쪽 수는 첫 구역만 — 말없이 넘어가면 둘째 구역의 문제를 '없음'으로 읽음(검토 2026-11-12)
            self.info.append(f"구역이 {len(self.b.sec_names)}개인 문서입니다 — 위 쪽 수와 '고쳐야 함'(글·짜임)은 첫 구역만 본 것이고, "
                             "'정돈이 고칠 것'은 모든 구역을 봅니다.")
        self.fonts()
        self.basis()
        self.title_and_summary()
        self.rules()
        if read_doc_meta(self.pkg).get("made"):  # 이 스킬이 만든 문서: 두 쪽에 걸친 □ 묶음 지적도 만들 때와 같은 셈으로
            whole = Fitter(self.b).report()
            if note_is_fix(whole):
                self.fix.append(whole)
        self.dry_fit(tables)
        self.tidy_preview()
        # 만들 때(또는 --omit) 일부러 뺀다고 한 요소의 지적은 알림으로 — 근거법령 검사를 끈 문서(--no-basis·문서 종류)의 근거법령 지적도
        off = self.omit | ({"basis"} if self._basis_skip() else set())
        if off:
            moved = [w for w in self.fix if getattr(w, "kind", None) in off]
            self.fix = [w for w in self.fix if w not in moved]
            self.info += [f"(일부러 뺌 — omit) {w}" if getattr(w, "kind", None) in self.omit else f"(근거법령 검사를 끔) {w}" for w in moved]
        errors, notes, _ = check(self.path)
        return pages, errors, notes


def main():
    ap = argparse.ArgumentParser(description="이미 쓴 hwpx를 검사만 한다(파일을 바꾸지 않음)")
    ap.add_argument("hwpx")
    ap.add_argument("--no-tables", action="store_true", help="표 맞춤 어림은 건너뜀(표가 많아 느릴 때)")
    ap.add_argument("--doc-type", default=None, help="문서 종류(회의자료·보도자료·답변서·주간업무 보고·사업설명서 등 — "
                    "근거법령 없이 시작하는 종류면 근거법령 검사를 건너뜀, 계획의 doc_type과 같음)")
    ap.add_argument("--no-basis", action="store_true", help="근거법령 검사를 건너뜀(계획의 \"basis_first\": false와 같음)")
    ap.add_argument("--basis-searched", action="store_true",
                    help="둘째 근거를 찾아봤지만 없음 — 근거법령 ○ 하나를 알림으로만(계획의 \"basis_searched\": true와 같음)")
    ap.add_argument("--omit", default="", help="일부러 뺀 요소(쉼표로: date,summary,basis,table_title — 계획의 \"omit\"과 같음)")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8")
    omit = [k.strip() for k in a.omit.split(",") if k.strip()]
    if any(k not in OMIT_KEYS for k in omit):
        raise SystemExit(f"--omit에는 {', '.join(OMIT_KEYS)} 가운데서만 쓸 수 있습니다(받은 값: {a.omit}).")
    try:
        ins = Inspector(a.hwpx, doc_type=a.doc_type, basis=not a.no_basis, basis_searched=a.basis_searched, omit=omit)
        pages, errors, notes = ins.run(tables=not a.no_tables)
    except BuildError as e:
        raise SystemExit(f"검사하지 못함 — {e}")
    print(f"gongyong-hwpx v{SKILL_VERSION}")
    print(f"## 검사만: {os.path.basename(a.hwpx)} — 파일은 바꾸지 않았습니다")
    print(" - " + pages)
    tell = margin_note(page_info(ins.b.sec))
    if tell:
        print(" - " + tell)
    print("## 고쳐야 함(글·짜임 — 작성자가 정할 것)")
    for w in ins.fix or ["없음"]:
        print(" - " + w)
    print("## 정돈이 고칠 것(서식 — 정돈을 한 번 돌려 본 결과, 파일은 그대로)")
    for w in ins.polish or ["없음"]:
        print(" - " + w)
    print_citations(para_text(p) for p in ins.b.sec.iter(T("hp:p")))
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
