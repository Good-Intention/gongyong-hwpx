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
from spaces import compact_fw, lead_to_margin, protect_lead  # noqa: E402


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
        # 슬로건이 없으면 표지 첫 문단이 제목 띠(표) 문단이 된다 — '감추기' 조각을 거기 두면 한글이 그 조각에 한 줄을 주어 표지 전체가
        # 3.5~6mm 내려감(v2.17 3번). 그때는 표지 쪽의 첫 글 문단(부서명 등)에 둔다(감추기는 그 쪽 어디에 있어도 같음)
        hide_at = paras[0]
        if para_tables(paras[0]) and not para_pics(paras[0]):
            cover_text = next((q for q in paras[1:end] if para_text(q).strip() and not para_tables(q) and not para_pics(q)), None)
            if cover_text is not None:
                hide_at = cover_text
        for p, tag, attrs in ((hide_at, "hp:pageHiding",
                               (("hideHeader", "1"), ("hideFooter", "0"), ("hideMasterPage", "0"), ("hideBorder", "0"),
                                ("hideFill", "0"), ("hidePageNum", "1"))),
                              (first_text if first_text is not None else paras[end], "hp:newNum",
                               (("num", "1"), ("numType", "PAGE")))):
            if p is first_text or p is not paras[0] and tag == "hp:pageHiding":
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
        self.line_pct = opts.get("line_pct")
        if self.line_pct:  # 본문 줄 간격을 정함(의뢰서 190% 등) — 쪽 맞춤은 이 값을 바꾸지 않음
            self.apply_line_pct(int(self.line_pct))
        blocks = [dict(b, _src=b.get("_src", n + 1)) if isinstance(b, dict) else b for n, b in enumerate(blocks)]
        blocks = self.section_blocks(blocks)  # {"section": "가로"} — 그 블록부터 새 구역(가로 쪽 등, v2.17 2번)
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
        # 서술식 문서(계획 "narrative": true — 문장으로 쓰는 문서를 부르는 스킬이 넘김): 이름표 폭·이름표 뒤 둘째 줄·괄호 줄이기 기본 끔
        # (받은 요청 2026-11-22 4·5번. 공용 스킬은 문서 이름을 보고 고르지 않음 — 사용자 '법률자문 스킬은 따로 있다')
        self.narrative = "서술식" if opts.get("narrative") else ""
        off = [name for key, name in (("align_labels", "이름표 폭 맞추기"), ("paren_small", "괄호 글자 줄이기"),
                                      ("opener_breaks", "괄호·낫표 앞 줄 바꿈"), ("connector_breaks", "연결어 앞 줄 바꿈"),
                                      ("push_down", "끝 줄 내리기 줄 바꿈"))
               if self.narrative and key not in opts]
        if off:
            self.warn(f"서술식 문서(계획 narrative)라 {'·'.join(off)}를 기본으로 껐습니다(둘째 줄은 머리 기호 다음 글자 자리에 — "
                      "켜려면 계획에 그 옵션을 true로).")
        if opts.get("align_labels", not self.narrative):
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
        self.data_tbls = set()  # 계획이 줄·칸을 준 표(make_block) — 나머지 여러 칸 표는 견본(양식) 표
        out = [self.make_block(n, b) for n, b in enumerate(blocks)]
        # 판례·해석례 발췌 블록이 펼쳐진 문단(plan_text — '- 머리 줄'·'(판결요지) …' 줄) → case_refs가 인용 모양으로
        self.case_paras = {p: b["_case"] for b, p in zip(blocks, out) if isinstance(b, dict) and b.get("_case")}
        out = self.org_settings(out)  # 기준값 파일의 기관 그림(다른 기관 공용) — 첫 문단(쪽 설정을 받을 문단)을 정하기 전에
        self.flow_gaps(out)
        self.lone_dashes(out)
        self.basis_notes(out)
        self.ref_sole_titles(out)  # 참고 자체가 표 하나면 ■ 제목 줄을 빼고(머리표 제목이 표 제목) 검사
        if "table_title" not in self.omit:
            self.table_titles(out)
        self.table_gaps(out)  # 표 → 다음 표 ■ 제목 사이 빈 줄 하나(사용자 2026-11-26)
        self.flow_steps(out)
        self.check_endings(out)
        out = self.law_refs(out)
        out = self.case_refs(out)  # 판례·해석례 발췌 — 인용 모양(받은 요청 2026-11-22 15번)  # 참고 근거법령은 상자·머리 기호 없이 원문 번호로(사용자 2026-11-15 시안 B) — 법령 이름 ○를 빼므로 아래 알림 앞에
        self.ref_bullets(out)
        self.ref_head_gaps(out)  # 참고 머리표 밑에 글이 바로 오면 반 줄 띄움(밑에 표면 그대로)
        self.law_source_lines(out)  # 참고 근거법령 '※ 출처' 줄은 쓰지 않음 — 알림
        if opts.get("keep_groups", True):
            self.keep_groups(out)
        elif opts.get("keep_heads", True):  # 묶음 유지를 꺼도 머리 문단은 아래 첫 문단과 함께(받은 글 2026-11-26 2번)
            self.keep_heads(out)
        if opts.get("keep_lines", bool(self.narrative)):  # 문단 보호 — 서술식 문서 기본
            self.keep_lines_all(out)
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
        paren = opts.get("paren_small", 0 if self.narrative else PROFILE["paren_smaller_pt"])
        if paren:
            self.small_parens(paren)
        if opts.get("note_small", True):
            self.small_notes()
        if opts.get("square_small", True):
            self.small_squares()
        if opts.get("date_gap", True):
            self.date_gap()
        if opts.get("tighten_quotes", True):
            self.tighten_quotes()
        # 괄호 이름표 뒤 둘째 줄은 늘 '(' 자리(머리 기호 뒤) — 사용자 2026-11-26 '늘 ( 자리로'(11-15 '개조식이면 )에'를 바꿈).
        # 계획 label_hang: true면 옛 방식(개조식은 이름표 ')' 뒤 첫 글자)
        if self.colons or opts.get("label_hang", False):
            self.colon_hang(colons=self.colons, labels=opts.get("label_hang", False))
        self.fit_notes = []
        for p in self.sec.iter(T("hp:p")):
            # 머리(기호·이름표·쌍점과 뒤 빈칸)와 내용을 다른 조각으로 — 줄 맞춤은 내용 조각만 자간을 바꾸고 어림도 그렇게 잼. 이름표 둘째 줄을
            # '(' 자리로 두면서(2026-11-26) colon_hang의 조각 나누기를 거치지 않는 문단이 생겨, 머리와 붙은 내용 조각에 자간이 안 들어갔음
            h = head_length(para_text(p))
            if h and not para_tables(p):
                self._split_run_at(p, h)
        secs = self.split_sections()  # 계획의 "section" 블록에서 새 구역(첫 구역은 self.sec 그대로)
        sec0, reports, pt = self.sec, [], []
        for k, s in enumerate(secs):
            self.sec = s
            self._fit_section(opts, k, reports, pt)
        self.sec = sec0
        if len(secs) > 1:
            self.fit_notes = [n for n in self.fit_notes if not n.startswith("어림 쪽 수")] + [self._join_reports(reports)]
        self.table_pt = min(pt) if pt else None
        self._finish(opts)

    def _fit_section(self, opts, k, reports, pt):
        """구역 하나(self.sec)를 맞춘다 — 구역마다 쪽 크기(가로 쪽 등)가 다르므로 Fitter가 그 구역의 쪽 설정으로 잰다."""
        if opts.get("fit", True):
            f = Fitter(self)
            # 강제 줄 바꿈(끝 줄 내리기·괄호 앞·연결어 앞)은 서술식 문서에서 기본으로 끔 — 한글은 줄 바꿈 앞 줄을 양쪽 정렬하지 않아
            # 오른쪽이 비어 보임(받은 글 2026-11-26 1번, 물음 '서술식만 끔'). 못 고친 끝 줄·벌어진 줄은 '고쳐야 함'으로 문장 고치기를 안내
            f.push = opts.get("push_down", not self.narrative)  # 끝 줄 한두 낱말 내리기(끄면 올리기만)
            f.openers = opts.get("opener_breaks", not self.narrative)
            f.connectors = opts.get("connector_breaks", not self.narrative)
            if self.line_pct:  # 정한 본문 줄 간격은 쪽 맞춤이 줄이지도 넓히지도 않음 — 빈 줄·○ 위 간격도(받은 글 2026-11-26 2번)
                f.min_line = f.line_cap = int(self.line_pct)
                f.fixed_rhythm = True
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
            rep = f.report()
            reports.append((rep, f.pages_used if hasattr(f, "pages_used") else None))
            tag = "" if k == 0 else f"[{k + 1}째 구역] "

            def tagged(n):
                """구역 표시를 붙여도 '고쳐야 함' 등급(Note.level·kind)은 그대로 — 글만 이으면 보통 글이 되어 알림으로 내려갔음."""
                if not tag:
                    return n
                return fix_note(tag + n, getattr(n, "kind", None)) if getattr(n, "level", "info") == "fix" else tag + n
            self.fit_notes += [tagged(n) for n in f.notes] + [rep]
            pt += [f._main_size(t) for t, d in getattr(f, "page_shrink", {}).items() if d]  # 한 장에 넣으려 줄인 표 글자
        elif opts.get("one_space", True):
            self.one_space()

    @staticmethod
    def _join_reports(reports):
        """구역마다 '어림 쪽 수 N쪽(1쪽 …%, …)'을 이어 한 줄로 — 쪽 차례는 이어서 셈."""
        total, parts, fixes = 0, [], []
        for rep, _ in reports:
            m = re.match(r"어림 쪽 수 (\d+)쪽\((.*?)\)(.*)$", str(rep))
            if not m:
                continue
            n = int(m.group(1))
            fill = re.sub(r"(\d+)쪽", lambda x: f"{int(x.group(1)) + total}쪽", m.group(2))
            parts.append(fill)
            total += n
            if m.group(3):
                fixes.append(m.group(3))
        msg = f"어림 쪽 수 {total}쪽({', '.join(parts)})" + "".join(fixes)
        return fix_note(msg) if fixes and any("두 쪽에 걸친" in x for x in fixes) else msg

    SECTION_WORDS = {"가로": "가로", "landscape": "가로", "세로": "세로", "portrait": "세로"}

    def section_blocks(self, blocks):
        """{"section": "가로"}만 있는 블록은 다음 블록에 붙인다(기호로 쓴 계획에서도 쓰게). 값은 가로·세로."""
        out, pending = [], None
        for b in blocks:
            if isinstance(b, dict) and "section" in b:
                v = self.SECTION_WORDS.get(str(b["section"]).strip().lower())
                if v is None:
                    raise BuildError(f"블록 {b.get('_src', '?')}: \"section\"은 \"가로\" 또는 \"세로\"입니다(받은 값: {b['section']!r}).")
                if "like" not in b and set(b) <= {"section", "_src"}:
                    pending = v
                    continue
                b = dict(b, section=v)
            elif pending and isinstance(b, dict):
                b = dict(b, section=pending)
            if isinstance(b, dict) and b.get("section"):
                pending = None
            out.append(b)
        if pending:
            raise BuildError("계획 맨 끝의 {\"section\": …} 뒤에 블록이 없습니다 — 새 구역에 넣을 블록을 그 뒤에 쓰세요.")
        return out

    def split_sections(self):
        """계획의 "section" 블록(make_block이 section_marks에 적음)에서 새 구역을 만든다: 첫 구역의 쪽 설정(secPr)·머리말·꼬리말·쪽 번호
        조각을 복사하고 방향만 바꿈(가로 = landscape NARROWLY — 저장 크기는 그대로, 한글 2024 확인 2026-11-09). 그 구역의 쪽 너비 표는
        새 본문 폭에 맞춰 칸 너비를 비율대로 넓힌다. 쪽 번호는 이어진다. 돌려주는 것: 구역 목록(첫 구역 = self.sec)."""
        marks = getattr(self, "section_marks", {})
        paras = [p for p in self.sec if p.tag == T("hp:p")]
        cuts = []
        for i, p in enumerate(paras):
            if p not in marks or i == 0:
                continue
            k = i
            while k > 1 and not para_tables(paras[k - 1]) and (UNIT_RE.match(para_text(paras[k - 1]))
                                                              or para_text(paras[k - 1]).lstrip().startswith("■")):
                k -= 1  # 표 위 ■ 제목·단위 줄은 표와 같은 구역으로
            if k != i:
                marks[paras[k]] = marks.pop(p)
            cuts.append(k)
        if not cuts:
            return [self.sec]
        secpr = next(self.sec.iter(T("hp:secPr")))
        w0 = page_info(self.sec)["body_width"] * HWPUNIT_PER_MM
        secs = [self.sec]
        bounds = cuts + [len(paras)]
        for a, b in zip(bounds, bounds[1:]):
            root = etree.Element(self.sec.tag, nsmap=self.sec.nsmap)
            for k2, v2 in self.sec.attrib.items():
                root.set(k2, v2)
            for p in paras[a:b]:
                root.append(p)  # 첫 구역에서 옮김
            first = paras[a]
            first.set("pageBreak", "0")  # 구역이 바뀌면 새 쪽 — 쪽 나눔을 겹쳐 두면 빈 쪽이 생길 수 있음
            runs = para_runs(first)
            proto = runs[0] if runs else None
            new_sp = copy.deepcopy(secpr)
            pp = new_sp.find(T("hp:pagePr"))
            if pp is not None:
                pp.set("landscape", "NARROWLY" if marks[first] == "가로" else "WIDELY")
            r = copy.deepcopy(proto) if proto is not None else etree.Element(T("hp:run"))
            for ch in list(r):
                r.remove(ch)
            r.append(new_sp)
            for sr in self.struct_runs:  # 머리말·꼬리말·쪽 번호 넣기 조각(쪽 설정 조각은 위에서 새로)
                for ch in sr:
                    if ch.tag == T("hp:ctrl") and any(etree.QName(x).localname in ("header", "footer", "pageNum") for x in ch):
                        r.append(copy.deepcopy(ch))
            first.insert(list(first).index(runs[0]) if runs else len(first), r)
            drop_linesegs(first)
            w1 = page_info(root)["body_width"] * HWPUNIT_PER_MM
            if abs(w1 - w0) > HWPUNIT_PER_MM:
                for p in root:
                    for tbl in para_tables(p):
                        self._scale_table(tbl, w0, w1)
            secs.append(root)
        self.extra_secs = secs[1:]
        return secs

    @staticmethod
    def _scale_table(tbl, w0, w1):
        """쪽 너비 표(본문 폭과 같은 표)를 새 본문 폭에 맞춰 칸 너비를 비율대로 넓힌다(가로 쪽 구역)."""
        sz = tbl.find(T("hp:sz"))
        if sz is None or abs(int(sz.get("width", "0")) - w0) > 2 * HWPUNIT_PER_MM:
            return
        r = w1 / w0
        sz.set("width", str(int(round(int(sz.get("width")) * r))))
        for tc in tbl.iter(T("hp:tc")):
            cs = tc.find(T("hp:cellSz"))
            if cs is not None:
                cs.set("width", str(int(round(int(cs.get("width", "0")) * r))))

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
            if p in body:  # 기호 없는 줄머리 빈칸은 자간 0(받은 글 2026-11-26 5번) — 본문 문단만(양식 표 칸 글은 그대로)
                protect_lead(p, self.styles, self.hedit, split, self.tab_proto)
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
            self.warn(f"견본의 {name}(둘째 구역부터)은 결과 문서에서 뺐습니다 — 가로 쪽 등 새 구역은 계획에 {{\"section\": \"가로\"}}로.")
        extra = getattr(self, "extra_secs", [])
        for k, root in enumerate(extra, 1):
            for p in root.iter(T("hp:p")):
                p.set("id", new_id(used))
            for tag in ("hp:tbl", "hp:pic", "hp:rect", "hp:line", "hp:ellipse", "hp:container", "hp:equation"):
                for el in root.iter(T(tag)):
                    if el.get("id") is not None:
                        el.set("id", new_id(used))
            self.pkg.add_section(f"Contents/section{k}.xml", root)
        head = self.pkg.xml("Contents/header.xml")
        if head.get("secCnt"):
            head.set("secCnt", str(1 + len(extra)))
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
        if getattr(self, "narrative", ""):
            meta["narr"] = "1"  # 서술식 문서 — 정돈 --all도 이름표 폭·둘째 줄을 작성 때처럼
        # 견본(양식) 표: 계획이 줄·칸을 주지 않은 여러 칸 표(차례:줄x칸) — 정돈 --all이 양식 표 모양(줄 높이·칸 여백)을 바꾸지 않게
        # (받은 요청 2026-11-22 10번: 의뢰서 긴급 사항 칸 줄 높이 19.2 → 11.8mm)
        tables = [t for p in self.sec if p.tag == T("hp:p") for t in para_tables(p)]
        form = [f"{i}:{t.get('rowCnt')}x{t.get('colCnt')}" for i, t in enumerate(tables)
                if t not in getattr(self, "data_tbls", ()) and len(table_grid(t)) > 1]
        if form:
            meta["form"] = ",".join(form)
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
    ap.add_argument("--try", dest="try_file",
                    help="문장 후보 시험(JSON) — 블록 글을 후보마다 바꿔 만들어 보고 줄 수·벌어진 줄·끝 줄을 보임(파일은 만들지 않음). "
                         "꼴: [{\"find\": \"블록 글 일부\" 또는 \"block\": 번호, \"texts\": [\"후보 글\", …]}, …]")
    a = ap.parse_args()
    if same_path(a.template, a.out):
        raise SystemExit("견본 파일에 덮어쓰지 않습니다. --out에 다른 이름을 주세요.")
    plan = read_plan(a.plan)
    if a.try_file:
        sys.exit(try_candidates(a.template, plan, a.try_file, os.path.dirname(os.path.abspath(a.plan))))
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


def _core(text):
    """견줄 글 — 머리 기호·이름표·꾸밈 표시·빈칸을 뺀 앞부분."""
    rest = split_marker(text)[2]
    rest = re.sub(r"\*\*|\^\^", "", rest)
    rest = re.sub(r"^[\s⎵⍽]*[(〔［\[][^)〕］\]]{1,14}[)〕］\]]", "", rest)
    return re.sub(r"[\s⎵⍽]", "", rest)[:16]


def try_candidates(template, plan, path, base_dir):
    """--try: 계획 블록 글을 후보로 바꿔 하나씩 만들어 보고(파일은 쓰지 않음) 그 문단의 줄 수·크게 벌어진 줄·끝 줄 길이를 보인다
    (받은 요청 2026-11-22 8번: 레이아웃 함수로 미리 잰 결과와 실제 만들기 결과가 달라 후보마다 만들기를 다시 돌려 봄 — 만들기와
    같은 셈으로). 끝 번호 0(후보 하나라도 통과), 3(모두 남음), 1(후보 파일·블록을 못 찾음)."""
    from fit_lines import loose_hint, loose_line
    try:
        tries = json.load(open(path, encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"후보 파일을 읽지 못함 — {e}")
        return 1
    tries = tries.get("tries", tries) if isinstance(tries, dict) else tries
    blocks = plan.get("blocks") if isinstance(plan, dict) else plan
    if not isinstance(tries, list) or not isinstance(blocks, list):
        print("후보 파일은 [{\"find\": \"블록 글 일부\", \"texts\": [\"후보\", …]}, …] 꼴이어야 합니다.")
        return 1

    def block_text(b):
        return b if isinstance(b, str) else b.get("text", "") if isinstance(b, dict) else ""

    def measure(variant, k, text):
        pl = copy.deepcopy(plan)
        bl = pl["blocks"] if isinstance(pl, dict) else pl
        bl[k] = text if isinstance(bl[k], str) else dict(bl[k], text=text)
        pkg = Package(template)
        b = Builder(pkg, base_dir=base_dir)
        try:
            b.build(pl)
        except BuildError as e:
            return f"만들지 못함 — {e}", False
        f = Fitter(b)
        want = _core(text)
        hit = next(((p, w) for p, w in f.text_boxes() if want and _core(para_text(p)).startswith(want[:12])), None)
        pages = next((w.replace("어림 쪽 수 ", "") for w in b.fit_notes if w.startswith("어림 쪽 수")), "")
        if hit is None:
            return "그 문단을 찾지 못함(글이 크게 바뀌었으면 find를 새 글로)", False
        p, w = hit
        chs, lines = f.lay.para_lines(p, w)
        loose = [n for n, (s, e, u, av) in enumerate(lines[:-1])
                 if loose_line(chs, s, e, u, av) and "\n" not in (chs[e - 1][0], chs[e][0] if e < len(chs) else "")]
        s, e = lines[-1][0], lines[-1][1]
        tail = sum(1 for c in chs[s:e] if c[0] not in (" ", "⎵", "⍽", "\n"))
        short = len(lines) > 1 and tail <= 3
        ok = not loose and not short
        msg = f"{len(lines)}줄, 끝 줄 {tail}자" + (f", {pages}" if pages else "")
        if loose:
            hint = loose_hint(chs, *lines[loose[0]])
            msg += f" — 크게 벌어진 줄 {len(loose)}개({loose[0] + 1}째 줄 끝{': ' + hint if hint else ''})"
        if short:
            msg += " — 끝 줄이 두서너 자"
        return msg, ok

    any_ok, code = False, 3
    for n, t in enumerate(tries, 1):
        if not isinstance(t, dict) or not isinstance(t.get("texts"), list):
            print(f"후보 {n}: \"texts\"(후보 글 목록)가 있어야 합니다.")
            return 1
        if isinstance(t.get("block"), int):
            k = t["block"] - 1
        else:
            find = re.sub(r"\*\*|\^\^", "", str(t.get("find", "")))
            k = next((i for i, b in enumerate(blocks) if find and find in re.sub(r"\*\*|\^\^", "", block_text(b))), None)
        if k is None or not 0 <= k < len(blocks) or not block_text(blocks[k]):
            print(f"후보 {n}: 계획에서 그 블록을 찾지 못함(find는 블록 글의 일부, block은 1부터 센 번호).")
            return 1
        orig = block_text(blocks[k])
        pre, mark, _ = split_marker(orig)
        print(f"## 후보 시험 — 블록 {k + 1} ‘{_core(orig)[:14]}…’")
        msg, _ = measure("지금", k, orig)
        print(f" - 지금 글: {msg}")
        for m, cand in enumerate(t["texts"], 1):
            cand = str(cand)
            if mark and not split_marker(cand)[1]:
                cand = pre + cand  # 머리 기호를 빼고 준 후보는 원래 기호를 붙임
            msg, ok = measure(m, k, cand)
            any_ok |= ok
            print(f" - 후보 {m}: {'통과' if ok else '남음'} — {msg}")
    return 0 if any_ok else code


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
