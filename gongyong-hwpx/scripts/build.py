# -*- coding: utf-8 -*-
"""계획 파일(plan.json)대로 견본 문단을 복사해 새 한글 문서(.hwpx)를 만든다.

쓰는 법:
    python build.py --template 견본.hwpx --plan plan.json --out 결과.hwpx

계획 파일 모양(자세한 것은 references/plan-format.md):
    {"title": "문서 제목(파일 속성)",
     "blocks": [
        {"like": 0, "text": "○○ 추진 계획(안)"},                 # 견본 0번 문단 모양으로 글 넣기
        {"like": 5, "text": "추진 배경"},                        # 머리 기호(□ 등)는 견본 것을 그대로 붙임
        {"like": 6, "text": "**(현황)** 안내판 노후화 심화"},    # **…**는 견본 문단의 굵은 조각 모양
        {"like": 6, "runs": [[" ○ ", 0], ["(현황)", 1], [" 내용", 2]]},  # 조각 모양을 직접 고름
        {"like": 12, "table": [["구분", "현행"], ["대상", "100곳"]]},      # 표: 줄을 늘리거나 줄임
        {"like": 15, "cells": {"0,0": "참고1", "0,2": "세부 현황"}, "page_break": true},
        {"like": 2}                                              # 견본 문단 그대로(빈 줄 등)
     ]}
견본에 없는 서식은 만들지 않는다. 모양은 늘 견본 문단에서 온다.
글 넣기는 build_fill.py, 사용자 원칙은 build_rules.py에 있고 이 파일의 Builder가 둘을 합친다(상수는 build_base.py).
다른 파일은 지금처럼 `from build import Builder, BuildError`로 쓴다.
"""
from build_base import *  # noqa: F401,F403
from hwpx_lib import _base_head  # noqa: E402,F401 — 밑줄 이름은 *로 안 넘어옴
from hwpx_lib import COMPOSE_CHAR, read_plan, same_path  # noqa: E402
from build_fill import FillPart  # noqa: E402
from build_rules import RulesPart  # noqa: E402
from plan_text import expand_plan  # noqa: E402
import proofread  # noqa: E402
from spaces import compact_fw, lead_to_margin  # noqa: E402


class Builder(FillPart, RulesPart):
    def __init__(self, pkg, base_dir=None):
        self.pkg = pkg
        self.base_dir = base_dir  # 계획 파일이 있는 폴더(그림 파일의 상대 경로 기준)
        self.image_seq = 0
        self.sample_free = set()  # 올린 견본이 원칙과 다르게 둔 모양·자리(sample_ways)
        self.law_notes = set()  # 참고 근거법령 아래 ※·* 줄(law_refs가 크기·자리를 맞춤 — small_notes는 건너뜀)
        self.law_paras = {}  # 참고 근거법령 조문 줄 → ○ 글자 자리(law_refs) — 인용 글이라 조문 상자처럼 다룸
        self.image_cells = set()  # 배경 그림을 넣은 칸(줄 높이를 늘리지 않음 — 비율 유지)
        self.flow_tables = set()  # 투명 선 도표 표(fit이 칸 너비를 다시 나누지 않음)
        self.flow_bottom = {}  # 도표 표 → 맨 아래 빈 줄 칸 크기(뒤가 글 문단이면 높임)
        self.image_aspect = {}  # 배경 그림 칸 → 그림 가로/세로(fit이 칸 너비·줄 높이를 비율에 맞춤)
        self.image_notes = []
        self.styles = Styles(pkg.xml("Contents/header.xml"))
        self.hedit = HeaderEdit(pkg.xml("Contents/header.xml"), self.styles)
        self.metrics = Metrics()
        self.keep_numbers = True
        self.colons = True
        self.omit = set()  # 계획 "omit"(사용자가 일부러 뺀 요소)
        self.fixed_widths = set()  # 계획 "widths"로 칸 너비를 준 표
        self.sec_names = pkg.sections()
        self.sec = pkg.xml(self.sec_names[0])
        self.protos = [p for p in self.sec if p.tag == T("hp:p")]
        self.warnings = []
        tab = self.sec.find(".//" + T("hp:tab"))
        self.tab_proto = copy.deepcopy(tab) if tab is not None else None
        self.struct_runs = self._collect_struct()
        self.flow_tables |= self._find_flow_tables()  # 이미 만든 문서의 흐름도도(만들 때는 flow_table이 더함)

    def warn(self, msg, level="info", kind=None):
        """알림 한 줄. level="fix"면 '고쳐야 함', kind는 계획 "omit" 키(그 요소를 뺀다고 했으면 알림으로 낮춤)."""
        if msg not in self.warnings:
            self.warnings.append(fix_note(msg, kind) if level == "fix" else msg)

    # ------------------------------------------------------------ 준비
    def _collect_struct(self):
        """쪽 설정·머리말·꼬리말·쪽 번호가 든 run을 모아 둔다(결과 문서 첫 문단에 그대로 넣음)."""
        out = []
        for p in self.protos:
            for r in para_runs(p):
                if any(is_struct(ch) for ch in r):
                    nr = copy.deepcopy(r)
                    for ch in list(nr):
                        if not is_struct(ch):
                            nr.remove(ch)
                    out.append(nr)
        if not out:
            raise BuildError("견본에서 쪽 설정(secPr)을 찾지 못했습니다. 한글에서 저장한 hwpx가 맞는지 확인하세요.")
        return out

    def clone(self, idx, where):
        if not isinstance(idx, int) or not 0 <= idx < len(self.protos):
            raise BuildError(f"{where}: like {idx!r} — 견본에 그 번호의 문단이 없습니다(0~{len(self.protos) - 1}).")
        p = copy.deepcopy(self.protos[idx])
        first_char = None
        for r in para_runs(p):
            first_char = first_char or r.get("charPrIDRef")
            for ch in list(r):
                if is_struct(ch):
                    r.remove(ch)
            if len(r) == 0:
                p.remove(r)
        if not para_runs(p):
            r = copy.deepcopy(self.struct_runs[0])
            for ch in list(r):
                r.remove(ch)
            if first_char:
                r.set("charPrIDRef", first_char)
            set_run_text(r, "")
            p.insert(0, r)
        drop_linesegs(p)
        return p

    # ------------------------------------------------------------ 표지·요약 상자
    def starts_with_cover(self, blocks):
        """계획이 표지로 시작하는가: 본문 첫 문단(쪽 설정이 든 견본) 앞 블록에 그림이 있거나, 첫 블록이 견본 첫 그림 바로 다음 문단(제목 띠)일 때 —
        슬로건을 빼려면 19번을 쓰지 않는다(cover.md)는데 그림으로 시작하는 계획만 표지로 봐 쪽 나눔·쪽 번호 감추기가 빠졌음(평가 2026-11-09)."""
        sec_idx = next((i for i, p in enumerate(self.protos) if p.find(".//" + T("hp:secPr")) is not None), None)
        head = []
        for b in blocks:
            if isinstance(b, dict) and b.get("like") == sec_idx:
                break
            head.append(b)
        else:
            return False
        if not head:
            return False
        protos = [self._proto_of(b) for b in head]
        if any(p is not None and para_pics(p) for p in protos):
            return True
        like = head[0].get("like") if isinstance(head[0], dict) else None
        return isinstance(like, int) and 0 < like < len(self.protos) and bool(para_pics(self.protos[like - 1]))

    def cover_break(self, blocks):
        """계획이 표지(그림이 든 견본 문단)로 시작하면 본문 첫 문단(쪽 설정이 든 견본 = 제목 상자)을 새 쪽에서 시작한다."""
        if not self.starts_with_cover(blocks):
            return
        sec_idx = next((i for i, p in enumerate(self.protos) if p.find(".//" + T("hp:secPr")) is not None), None)
        for b in blocks[1:]:
            if isinstance(b, dict) and b.get("like") == sec_idx:
                b.setdefault("page_break", True)
                return

    @staticmethod
    def _first_text_para(paras):
        """첫 쪽의 첫 글 문단(표·그림 없이 글이 있는 문단 — 날짜 줄 등). 조종 조각(쪽 번호 넣기·새 번호로 시작)을 두는 자리."""
        return next((q for q in paras[:6] if para_text(q).strip() and not para_tables(q) and not para_pics(q)), None)

    def cover_numbers(self, paras):
        """표지에는 쪽 번호와 머리말(머리말 시 슬로건 그림 — 표지는 제 슬로건이 있음, 사용자 2026-11-11 '표지를 뺀 모든 쪽')을
        감추고(감추기), 본문 첫 쪽부터 1로 다시 센다(새 번호로 시작)."""
        end = cover_end(paras)
        if end is None:
            return
        # '새 번호로 시작'을 제목 상자(쪽 너비 표) 앞에 따로 두면 한글이 그 표를 다음 줄로 밀어 제목 위에 빈 줄이 생긴다
        # (한글 확인 2026-11-01) — 같은 쪽의 첫 글 문단(날짜 줄 등) 맨 앞에 둔다
        first_text = next((q for q in paras[end:end + 4] if para_text(q).strip() and not para_tables(q)), None)
        for p, tag, attrs in ((paras[0], "hp:pageHiding",
                               (("hideHeader", "1"), ("hideFooter", "0"), ("hideMasterPage", "0"), ("hideBorder", "0"),
                                ("hideFill", "0"), ("hidePageNum", "1"))),
                              (first_text if first_text is not None else paras[end], "hp:newNum",
                               (("num", "1"), ("numType", "PAGE")))):
            if p is first_text:
                ctrl = etree.Element(T("hp:ctrl"))
                el = etree.SubElement(ctrl, T(tag))
                for k, v in attrs:
                    el.set(k, v)
                para_runs(p)[0].insert(0, ctrl)
                continue
            runs = para_runs(p)
            at = sum(1 for r in runs if any(is_struct(ch) for ch in r))  # 쪽 설정 run 뒤
            r = copy.deepcopy(runs[min(at, len(runs) - 1)])
            for ch in list(r):
                r.remove(ch)
            ctrl = etree.SubElement(r, T("hp:ctrl"))
            el = etree.SubElement(ctrl, T(tag))
            for k, v in attrs:
                el.set(k, v)
            p.insert(list(p).index(runs[at]) if at < len(runs) else len(p), r)

    def check_summary(self, blocks):
        """요약 상자(제목 상자 뒤 첫 한 칸 상자)는 번호·여러 항목 없이 한 문장으로 두세 줄, 끝맺음은 '~하고자 함' 또는
        '~에 대한 보고임'(사용자 원칙 2026-11-01)."""
        seen_title = False
        for b in blocks:
            proto = self._proto_of(b)
            if proto is None:
                continue
            if not para_tables(proto) and marker_level(para_text(proto)) == 1:
                return
            tables = para_tables(proto)
            if not tables or tables[0].get("rowCnt") != "1" or tables[0].get("colCnt") != "1":
                continue
            if proto.find(".//" + T("hp:secPr")) is not None or not seen_title:
                seen_title = seen_title or proto.find(".//" + T("hp:secPr")) is not None
                continue
            text = b.get("text") if isinstance(b.get("text"), str) else ""
            if "\n" in text.strip() or re.search(rf"[{NUM_CHARS}]|(^|\n)\s*(\d+[.)]|[-○·])\s", text):
                self.warn(f"블록 {b.get('_src')}: 요약 상자에는 번호·여러 항목을 넣지 않습니다 — 한 문장으로 두세 줄에 쓰세요"
                          "(세부 항목은 아래 □·○로).", level="fix", kind="summary")
            if text.strip() and not SUMMARY_END_RE.search(text.strip()):
                self.warn(f"블록 {b.get('_src')}: 요약 상자 끝맺음은 ‘~하고자 함’ 또는 ‘~에 대한 보고임’으로 하세요"
                          f"(지금: ‘…{text.strip()[-12:]}’).", level="fix", kind="summary")
            return

    def check_date_line(self, blocks):
        """제목 상자 아래 날짜·부서 줄은 빼지 않는다(사용자 원칙 2026-11-01 — ChatGPT가 날짜·부서를 받지 못하자 줄을
        통째로 뺀 일이 있음). 견본에 날짜 줄 문단이 있는데 계획이 그 줄을 쓰지 않으면 알린다. 모르면 ○로 채운다."""
        dates = [i for i, p in enumerate(self.protos) if not para_tables(p) and DATE_LINE_RE.match(para_text(p))]
        if not dates or not blocks:
            return
        for b in blocks:
            if isinstance(b, dict) and (b.get("like") in dates
                                        or DATE_LINE_RE.match(b.get("text") if isinstance(b.get("text"), str) else "")):
                return
        self.warn(f"날짜·부서 줄이 없습니다 — 제목 상자 바로 아래에 날짜·부서 줄(like {dates[0]})을 넣으세요. 날짜·부서를 "
                  "모르면 줄을 빼지 말고 ‘’26. ○. ○.(○)\\t○○○○과 ○○○’처럼 ○로 채웁니다.", level="fix", kind="date")

    def check_endings(self, out):
        """보고서 문장·항목은 '~으로'로 끝내지 않는다 — '통제 가능한 항목으로 편성'처럼 뒤에 할 일을 붙인다
        (사용자 원칙 2026-11-01). 끝 괄호(보충 설명)는 떼고 본다."""
        hits = []
        for p in out:
            for q in [p] + [c for t in para_tables(p) for _, _, _, _, tc in table_grid(t) for c in cell_paras(tc)]:
                text = para_text(q).replace("⎵", " ").replace("⍽", " ").strip()
                while True:
                    cut = re.sub(r"\s*\([^()]*\)\s*$", "", text).rstrip(" .")
                    if cut == text:
                        break
                    text = cut
                last = text.split(" ")[-1] if text else ""
                if last.endswith("로") and len(last) >= 2 and not last.endswith(LO_WORDS):
                    hits.append(f"‘…{text[-16:]}’")
        if hits:
            self.warn(f"‘~으로’로 끝나는 줄 {len(hits)}곳({', '.join(hits[:6])}{' 등' if len(hits) > 6 else ''}): "
                      "보고서 문장은 ‘~으로’로 끝내지 않습니다 — ‘통제 가능한 항목으로 편성’처럼 뒤에 할 일(편성·배정·전환 등)을 붙이세요.", level="fix")

    def build(self, plan):
        plan = expand_plan(plan, self)  # 기호로 쓴 블록("○ …")·like 없는 표 블록 → 번호 블록(plan_text.py)
        blocks = check_plan(plan)
        if not blocks:
            raise BuildError("계획에 블록이 하나도 없습니다.")
        opts = plan if isinstance(plan, dict) else {}
        self.fit_base = self.made_reset()  # 이 스킬이 만든 문서를 견본으로 쓸 때 앞 판의 맞춤값을 되돌리고, 맞추기 전 기준값을 잼
        blocks = [dict(b, _src=b.get("_src", n + 1)) if isinstance(b, dict) else b for n, b in enumerate(blocks)]
        if opts.get("omit_dots", True):
            self.omit_dots(blocks)  # (중략)·(후략) → ··· — 이름표 맞추기가 (중략)을 이름표로 벌리기 전에
        blocks = self.table_units(blocks)  # 이름표 맞추기 등이 '(기준 : …)'을 괄호 이름표로 다루기 전에
        self.doc_type = str(opts.get("doc_type") or "").strip()
        omit = opts.get("omit") or []
        omit = [omit] if isinstance(omit, str) else omit
        unknown = [x for x in omit if x not in OMIT_KEYS]
        if not isinstance(omit, list) or unknown:
            raise BuildError(f"\"omit\"에는 {', '.join(OMIT_KEYS)} 가운데서만 쓸 수 있습니다(받은 값: {unknown or omit!r}) — "
                             + ", ".join(f"{k} = {v}" for k, v in OMIT_KEYS.items()) + ".")
        self.omit = set(omit)
        self.basis_searched = bool(opts.get("basis_searched"))  # 둘째 근거를 찾아봤지만 없음 → ○ 하나여도 알림만
        self.basis_off = not opts.get("basis_first", True) or basis_exempt(self.doc_type) or "basis" in self.omit
        self.sample_free = self.sample_ways()  # 올린 견본이 원칙과 다르게 둔 모양·자리 — 견본 먼저(사용자 2026-11-15)
        if not self.basis_off and "basis" in self.sample_free:
            self.basis_off = True
            self.warn("견본이 근거를 첫 □가 아닌 곳(다른 □ 안 ○ (근거) 등)에 두어 계획에 쓴 자리를 그대로 두었습니다"
                      "(따르는 차례: 요청 → 견본 → 원칙 — 근거법령 1번으로 옮기지 않음).")
        if "counts" in self.sample_free:
            self.warn("견본에 ○·- 항목이 하나뿐이거나 다섯을 넘는 곳이 있어, 항목 수(2~5개) 지적은 알림으로 낮췄습니다(견본 먼저).")
        if not self.basis_off:
            blocks = self.basis_first(blocks)
        elif basis_exempt(self.doc_type):
            self.warn(f"문서 종류 ‘{self.doc_type}’는 근거법령 없이 시작하는 문서라(doc-types.md) 근거법령 검사를 건너뛰었습니다.")
        self.keep_numbers = opts.get("keep_numbers", True)
        body_pt = opts.get("body_pt")  # 표 글자의 기준 본문 크기(따로 지시가 있을 때만, 없으면 14pt — 사용자 2026-11-05)
        if body_pt is not None and (not isinstance(body_pt, (int, float)) or not 8 <= body_pt <= 30):
            raise BuildError(f"\"body_pt\"는 본문 글자 크기(pt) 숫자여야 합니다(받은 값: {body_pt!r}).")
        self.body_pt = body_pt
        self.colons = opts.get("colons", True)
        if opts.get("join_titles", True):
            self.join_titles(blocks)
        if opts.get("space_blocks", True):
            blocks = self.space_blocks(blocks)
        if opts.get("number_items", True):
            self.number_items(blocks)
        if opts.get("align_labels", True):
            self.align_labels(blocks)
        if opts.get("table_notes", True):
            self.table_notes(blocks)
        self.cover_break(blocks)
        if "summary" not in self.omit:
            self.check_summary(blocks)
        if "date" not in self.omit:
            self.check_date_line(blocks)
        if self.omit:
            self.warn("계획에서 일부러 뺀다고 한 것(omit — " + "·".join(OMIT_KEYS[k] for k in sorted(self.omit))
                      + ")은 검사하지 않고, 그에 대한 지적은 알림으로만 둡니다(만든 문서에 표시가 남아 검사만도 같음).")
        out = [self.make_block(n, b) for n, b in enumerate(blocks)]
        out = self.org_settings(out)  # 기준값 파일의 기관 그림(다른 기관 공용) — 첫 문단(쪽 설정을 받을 문단)을 정하기 전에
        self.flow_gaps(out)
        self.lone_dashes(out)
        self.basis_notes(out)
        self.ref_sole_titles(out)  # 참고 자체가 표 하나면 ■ 제목 줄을 빼고(머리표 제목이 표 제목) 검사
        if "table_title" not in self.omit:
            self.table_titles(out)
        self.flow_steps(out)
        self.check_endings(out)
        out = self.law_refs(out)  # 참고 근거법령은 상자·머리 기호 없이 원문 번호로(사용자 2026-11-15 시안 B) — 법령 이름 ○를 빼므로 아래 알림 앞에
        self.ref_bullets(out)
        if opts.get("keep_groups", True):
            self.keep_groups(out)
        first = out[0]
        k = 0
        for r in self.struct_runs:
            if r.find(T("hp:secPr")) is None and self._first_text_para(out) is not None:
                # 쪽 번호 넣기 같은 조종 조각을 제목 상자(쪽 너비 표) 앞에 두면 한글이 그 조각에 한 줄을 주고 표를
                # 다음 줄로 밀어 제목 위에 빈 공간(10pt 한 줄 ≈ 3.5mm)이 생긴다(한글 확인 2026-11-03, 사용자 원칙 36번:
                # 제목 위에는 공간을 두지 않는다). 쪽 설정(secPr)만 첫 문단에 두고 나머지는 첫 글 문단(날짜 줄) 맨 앞에 둔다.
                self._first_text_para(out).insert(0, r)
                continue
            first.insert(k, r)
            k += 1
        if first.get("pageBreak") == "1":
            first.set("pageBreak", "0")
        self.cover_numbers(out)
        for ch in list(self.sec):
            self.sec.remove(ch)
        for p in out:
            self.sec.append(p)
        cut = caps = 0
        for p in self.sec.iter(T("hp:p")):
            a, b = clean_chars(p)
            cut, caps = cut + a, caps + b
        if cut:
            self.warn(f"한글에서 네모·붙임표·빈칸으로 찍히는 보이지 않는 글자 {cut}개를 뺐습니다(이모지 표시 글자 등).")
        if caps:
            self.warn(f"키캡 숫자(1️⃣) {caps}개를 글자 겹치기 네모 숫자로 바꿨습니다(키캡은 네모가 왼쪽으로 삐져나옴).")
        for p in self.sec.iter(T("hp:p")):  # 기호 뒤 한 칸(표 칸 글 등 — 머리 기호 줄은 견본 기호와 빈칸을 씀)
            insert_marker_gap(p)
        self.org_phone()  # 날짜·부서 줄 전화 앞자리(기준값 파일 — 기본 053-803이면 그대로)
        if opts.get("word_wrap", True):
            self.word_wrap()
        if opts.get("paren_small", PROFILE["paren_smaller_pt"]):
            self.small_parens(opts.get("paren_small", PROFILE["paren_smaller_pt"]))
        if opts.get("note_small", True):
            self.small_notes()
        if opts.get("square_small", True):
            self.small_squares()
        if opts.get("date_gap", True):
            self.date_gap()
        if opts.get("tighten_quotes", True):
            self.tighten_quotes()
        if self.colons or opts.get("label_hang", True):
            self.colon_hang(colons=self.colons, labels=opts.get("label_hang", True))
        self.fit_notes = []
        if opts.get("fit", True):
            f = Fitter(self)
            f.push = opts.get("push_down", True)  # 끝 줄 한두 낱말 내리기(끄면 올리기만)
            f.defer_hints = True  # '한 줄 줄이기 후보'는 맞춤을 다 끝낸 뒤 검사만과 같은 셈으로(fit_lines)
            f.fit_tables()
            f.fit_tables(again=True)  # 한 번 더: 자간·한 줄로 입력·폭 빌리기 뒤 다시 재도 같은 결과가 되게(다듬기의 고정점)
            f.fit_lines()
            f.fit_long_tables()  # 한 쪽을 조금 넘는 표는 줄 높이를 줄여 한 쪽에(쪽 맞춤이 묶음째 다음 쪽으로 넘기게)
            f.order_hints()  # 쪽 나눔을 박기 전, 같은 조건으로 순서 바꾸기를 견줌
            f.fit_pages()
            f.relieve_pads()
            f.spread_pages()
            f.fit_refs()
            f.fit_cover()
            f.drop_moot_order_hint()  # 맞춘 문서가 이미 그만큼 좋으면 순서 바꾸기 알림은 뺌
            if opts.get("one_space", True):
                self.one_space()  # 낫표 당기기 앞에: 당기기가 빈칸 한 개(장평 두 배)의 자간을 줄여 '당김' 표시가 남게
            if opts.get("pull_corner", True):
                f.pull_corners()  # 맨 마지막: 내어쓰기를 다시 재는 단계들 뒤에(아랫줄은 그대로, 낫표만 당김)
            if opts.get("line_fill", True):
                f.fill_ends()  # 낫표 당기기로 줄어든 폭까지 보고 끝선에
            f.rescan_hints = True  # 내린 두 줄 문단의 '한 줄 줄이기 후보'를 다 맞춘 문서에서(검사만과 같게)
            f.report_cut_hints()
            self.fit_notes = f.notes + [f.report()]
            shrunk = [f._main_size(t) for t, d in getattr(f, "page_shrink", {}).items() if d]
            self.table_pt = min(shrunk) if shrunk else None  # 한 장에 넣으려 줄인 표 글자 — 문서에 남겨 검사만이 다시 키우는 것으로 보지 않게
        elif opts.get("one_space", True):
            self.one_space()
        self._finish(opts)

    def one_space(self):
        """빈칸 한 칸(spaces.py — 정돈과 같은 규칙, 사용자 2026-11-08 '작성도 바꾸기'): 맞춤을 다 끝낸 뒤 머리의 고정폭 빈칸
        두 개(보통 빈칸 한 칸 폭)를 장평 두 배 고정폭 빈칸 한 개로, 머리 기호 앞 줄머리 빈칸을 문단 여백으로. 폭이 같아 줄·쪽
        나눔과 둘째 줄 맞춤은 그대로이고, 조판 부호를 켜면 한 칸에 빈칸 부호가 하나만 보인다."""
        lay = Layout(self.styles, self.metrics)
        split = lambda t: split_marker(t)  # noqa: E731
        ham = {"함초롬바탕", "함초롬돋움"}

        def fonts_ok(p):
            fonts = {self.styles.char.get(r.get("charPrIDRef"), {}).get("font") for r in para_runs(p)
                     if r.find(T("hp:t")) is not None and run_text(r).strip()}
            return all(self.metrics.checked(f) or f in ham for f in fonts if f)

        paras = [p for p in self.sec.iter(T("hp:p")) if not (para_tables(p) or para_pics(p))]
        body_w = page_info(self.sec)["body_width"] * HWPUNIT_PER_MM
        body = {p for p in self.sec if p.tag == T("hp:p")}
        for p in paras:
            # 맞춤 뒤에 돌므로 줄 수를 다시 잰다 — 늘면 그 문단은 그대로(옛 판: 40자 붙은 낱말이 1줄 → 2줄, 평가 2026-11-09)
            n0 = len(lay.para_lines(p, body_w)[1]) if p in body else None
            saved = (p.get("paraPrIDRef"), [(r, r.get("charPrIDRef"), copy.deepcopy(list(r))) for r in para_runs(p)], list(p)) if n0 else None
            lead_to_margin(p, self.styles, self.hedit, lay, split, fonts_ok, self.tab_proto, 10 ** 6)
            compact_fw(p, self.styles, self.hedit, split, self.tab_proto)
            if n0 and len(lay.para_lines(p, body_w)[1]) > n0:
                pid, runs, kids = saved
                p.set("paraPrIDRef", pid)
                for r in para_runs(p):
                    if not any(r is x for x in kids):
                        p.remove(r)
                for r, cid, old in runs:
                    for ch in list(r):
                        r.remove(ch)
                    for k in old:
                        r.append(k)
                    r.set("charPrIDRef", cid)

    # ------------------------------------------------------------ 마무리
    def _drop_unused_images(self):
        """결과 문서가 쓰지 않는 견본 그림(표지를 안 쓰면 대구시 마크·슬로건 등)은 묶음에서 뺀다."""
        if "Contents/content.hpf" not in self.pkg.data:
            return
        used = set()
        # 결과에 남는 모든 XML에서 쓰는 그림을 센다 — 머리말·본문만 보면 바탕쪽(masterpage)에서만 쓰는 견본 로고가 지워짐(검토 2026-11-12)
        gone = set(self.sec_names[1:])
        parts = [n for n in self.pkg.data if n.startswith("Contents/") and n.endswith(".xml") and n not in gone]
        for name in parts:
            for el in self.pkg.xml(name).iter():
                v = el.get("binaryItemIDRef")
                if v:
                    used.add(v)
        hpf = self.pkg.xml("Contents/content.hpf")
        for it in list(hpf.iter(T("opf:item"))):
            href = it.get("href", "")
            if href.startswith("BinData/") and it.get("id") not in used:
                it.getparent().remove(it)
                self.pkg.data.pop(href, None)

    def _finish(self, plan):
        used = set()
        for p in self.sec.iter(T("hp:p")):
            p.set("id", new_id(used))
        for tag in ("hp:tbl", "hp:pic", "hp:rect", "hp:line", "hp:ellipse", "hp:container", "hp:equation"):
            for el in self.sec.iter(T(tag)):
                if el.get("id") is not None:
                    el.set("id", new_id(used))
        for name in self.sec_names[1:]:
            self.pkg.drop_section(name)
            self.warn(f"견본의 {name}(둘째 구역부터)은 결과 문서에서 뺐습니다.")
        head = self.pkg.xml("Contents/header.xml")
        if head.get("secCnt"):
            head.set("secCnt", "1")
        self._drop_unused_images()
        if clear_print_method(self.pkg):
            self.warn("견본의 모아찍기 인쇄 설정을 껐습니다 — 켜 두면 인쇄·PDF가 한 장에 2쪽씩 묶입니다.")
        first_id = next(self.sec.iter(T("hp:p"))).get("id")
        if "settings.xml" in self.pkg.data:
            st = self.pkg.xml("settings.xml")
            for el in st.iter():
                if el.tag.endswith("CaretPosition"):
                    el.set("listIDRef", "0")
                    el.set("paraIDRef", first_id)
                    el.set("pos", "0")
        if plan.get("title") and "Contents/content.hpf" in self.pkg.data:
            hpf = self.pkg.xml("Contents/content.hpf")
            t = hpf.find(".//{http://www.idpf.org/2007/opf/}title")
            if t is not None:
                t.text = plan["title"]
        # 검사만(review)·정돈(tidy)이 같은 판단을 하게 표시를 남김 — made=판: 이 스킬의 작성 모드로 만든 문서(정돈이 작성 규칙이
        # 맞춘 내어쓰기·끝 줄·이름표·칸·간격을 다시 만지지 않게, 평가 2026-11-08 '정돈이 작성 결과를 되돌린다')
        meta = {"made": SKILL_VERSION}
        if getattr(self, "omit", None):
            meta["omit"] = ",".join(sorted(self.omit))
        if getattr(self, "basis_off", False):
            meta.update({k: v for k, v in (("doc_type", self.doc_type), ("basis", "off")) if v})
        if getattr(self, "basis_searched", False):
            meta["basis_searched"] = "yes"
        if getattr(self, "sample_free", None):
            meta["sample"] = ",".join(sorted(self.sample_free))  # 견본이 원칙과 달리 둔 것 — 검사만도 같은 판단
        meta.update(getattr(self, "fit_base", None) or {})
        fit_line = self.fit_line_mark()
        if fit_line:
            meta["fit_line"] = fit_line
        if getattr(self, "table_pt", None):
            meta["table_pt"] = str(self.table_pt)
        write_doc_meta(self.pkg, meta)
        text = "\r\n".join(para_text(p).replace(COMPOSE_CHAR, "") for p in self.sec if p.tag == T("hp:p"))
        if "Preview/PrvText.txt" in self.pkg.data:
            self.pkg.data["Preview/PrvText.txt"] = text[:1000].encode("utf-16-le")
        if "Preview/PrvImage.png" in self.pkg.data:
            self.pkg.data["Preview/PrvImage.png"] = blank_png()


def main():
    ap = argparse.ArgumentParser(description="견본 hwpx의 서식으로 새 문서를 만든다")
    ap.add_argument("--template", required=True, help="견본 hwpx")
    ap.add_argument("--plan", required=True, help="계획 파일(JSON)")
    ap.add_argument("--out", required=True, help="만들 hwpx")
    ap.add_argument("--brief", action="store_true",
                    help="글 차례를 빼고 보임(고쳐야 함을 고치며 다시 만들 때 — 전하기 전 마지막 판은 빼지 않음)")
    a = ap.parse_args()
    if same_path(a.template, a.out):
        raise SystemExit("견본 파일에 덮어쓰지 않습니다. --out에 다른 이름을 주세요.")
    plan = read_plan(a.plan)
    pkg = Package(a.template)
    try:
        b = Builder(pkg, base_dir=os.path.dirname(os.path.abspath(a.plan)))
        b.build(plan)
    except BuildError as e:
        raise SystemExit(f"만들지 못함 — {e}")
    pkg.save(a.out)
    print(f"gongyong-hwpx v{SKILL_VERSION}")
    print(f"만듦: {a.out}")
    if b.image_notes:
        b.warnings.append(f"표 칸 배경 그림 {len(b.image_notes)}개를 넣었습니다({', '.join(b.image_notes)}) — 칸 높이를 그림 비율에 맞춤.")
    errors, notes, outline = check(a.out)
    # 뺀다고 한 요소의 지적은 알림으로 — 근거법령 검사를 끈 문서("basis_first": false·근거법령 없이 시작하는 doc_type)의 근거법령
    # 지적도(설명서는 '끄면 근거법령 검사도 건너뜀'인데 부연설명·○ 하나 지적이 '고쳐야 함'으로 남았음, 검토 2026-11-12)
    off = b.omit | ({"basis"} if getattr(b, "basis_off", False) else set()) | (getattr(b, "sample_free", set()) & {"counts"})
    fix = [w for w in b.warnings + b.fit_notes if note_is_fix(w, off)]
    info = [w for w in b.warnings + b.fit_notes if not note_is_fix(w, off)]
    pages = next((w for w in info if w.startswith("어림 쪽 수")), "")
    print(f"## 한눈에: 고쳐야 함 {len(fix) + len(notes)}건, 구조 검사 {'문제 있음' if errors else '통과'}"
          + (f", {pages}" if pages else ""))
    if fix or errors or notes:
        print("## 고쳐야 함(전하기 전에 계획을 고쳐 다시 만들 것)")
        for w in fix:
            print(" - " + w)
    if info:
        print("## 알림(참고 — 도구가 한 일, 한글 없이 어림한 결과라 마지막 확인은 한글에서)")
        for w in info:
            print(" - " + w)
    tell = margin_note(page_info(b.sec))
    if tell:
        print("## 사용자에게 전할 말(결과를 건넬 때마다 빠짐없이 그대로 옮길 것)")
        print(" - " + tell)
    if not a.brief:  # 전하기 전 마지막 판에서만
        print_citations(para_text(p) for p in b.sec.iter(T("hp:p")))
    proofread.print_report(b.pkg)  # 수치·맞춤법 — 고치지 않고 알림(사용자 2026-11-15)
    print_report(errors, notes, None if a.brief else outline)
    # 끝 번호: 0 = 고칠 것 없음, 1 = 구조 검사 문제(파일을 쓰면 안 됨), 3 = 파일은 만들었고 '고쳐야 함'이 남음
    sys.exit(1 if errors else 3 if (fix or notes) else 0)


def margin_note(pi):
    """만든 문서의 여백 안내 한 줄(사용자 요청 2026-11-03: 결과를 줄 때마다 여백이 몇 mm인지 알리고, 온나라 공문에
    붙여 넣을 때는 [쪽] → [편집 용지]에서 왼쪽·오른쪽 여백을 맞추라고 — 본문 폭이 같아야 도구가 맞춘 줄 바꿈이 그대로 감).
    한글은 위 여백 다음 머리말 칸, 그 아래부터 본문이므로 본문 칸 위·아래 = 여백 + 머리말·꼬리말."""
    if not pi or "left" not in pi:
        return None
    f = lambda v: f"{v:.0f}" if abs(v - round(v)) < 0.05 else f"{v:.1f}"  # noqa: E731
    paper = "A4" if sorted((round(pi["width"]), round(pi["height"]))) == [210, 297] else f"{f(pi['width'])}×{f(pi['height'])}mm"
    top, bottom = pi["top"] + pi["header"], pi["bottom"] + pi["footer"]
    system = PROFILE.get("org_paste_system") or ""  # 공문 시스템 이름(기준값 파일 — 기본 온나라, 비우면 붙여 넣기 안내를 뺌)
    return (f"여백: {paper}, 본문 칸 위 {f(top)}·아래 {f(bottom)}·왼쪽 {f(pi['left'])}·오른쪽 {f(pi['right'])}mm"
            f"(용지 여백 위 {f(pi['top'])}·아래 {f(pi['bottom'])}mm에 머리말·꼬리말 {f(pi['header'])}·{f(pi['footer'])}mm)."
            + (f" {system} 공문에 붙여 넣으실 때는 [쪽] → [편집 용지]에서 왼쪽·오른쪽 여백을 {f(pi['left'])}·{f(pi['right'])}mm로 "
               "맞춰 주세요(그래야 줄 바꿈이 그대로 갑니다)." if system else ""))


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
