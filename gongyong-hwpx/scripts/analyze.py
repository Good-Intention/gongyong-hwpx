# -*- coding: utf-8 -*-
"""견본 한글 파일(.hwpx)을 읽어 '양식 지도'를 보인다.

쓰는 법:
    python analyze.py 견본.hwpx            # 짧은 양식 지도(여백 → 기호로 쓰면 고르는 문단 → 번호로 쓰는 문단)
    python analyze.py 견본.hwpx --all      # 문단마다 조각·표 칸의 서식까지(번호·조각 모양을 직접 고를 때)
    python analyze.py 견본.hwpx --text     # 글만 처음부터 끝까지(문체 익히기)
    python analyze.py 견본.hwpx --json 지도.json   # 기계가 읽는 지도도 저장

지도의 [번호]가 계획 파일(plan.json)의 "like" 값이다.
"""
import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hwpx_lib import (STRUCT_CTRLS, UNIT_RE, Package, Styles, T, cell_paras, cell_text, indexed_runs, local,  # noqa: E402
                      marker_kind, page_info, para_pics, para_runs, para_tables, para_text, run_objects, run_text, split_marker,
                      table_grid)

SHOW = 60  # 글 미리 보기 글자 수
BRIEF_MAX = 30  # 짧은 지도의 '번호로 쓰는 문단' 줄 수 상한


def short(s, n=SHOW):
    s = s.replace("\n", "↵").replace("\t", "⇥")
    return s if len(s) <= n else s[: n - 1] + "…"


def describe_runs(p, styles):
    out = []
    for i, r in enumerate(indexed_runs(p)):
        objs = [o for o in run_objects(r) if o != "secPr" and not (o.startswith("ctrl:") and o[5:] in STRUCT_CTRLS)]
        out.append({"index": i, "charPr": r.get("charPrIDRef"), "char": styles.char_desc(r.get("charPrIDRef")),
                    "text": run_text(r), "objects": objs})
    return out


def guess_role(p, styles, idx, text, tables):
    if tables:
        tbl = tables[0]
        rows, cols = tbl.get("rowCnt"), tbl.get("colCnt")
        grid = table_grid(tbl)
        if rows == "1" and cols == "1":
            return "제목 상자" if idx <= 2 else "글 상자(1칸 표)"
        first = cell_text(grid[0][4]).strip() if grid else ""
        if rows == "1" and first.replace(" ", "")[:2] in ("참고", "붙임", "별첨", "첨부"):
            return "참고 머리표"
        return "표"
    if para_pics(p) and not text.strip():
        return "그림(표지 슬로건·마크 등)"
    pre, mark, body = split_marker(text)
    if mark == "■":  # ■ 표 제목 줄 — 머리 기호 수준은 □와 같지만 큰 항목이 아니다(이 문단을 □ 자리에 고르지 않게, 2026-11-07)
        return "표 제목(■)"
    if mark:
        return marker_kind(mark)
    if not text.strip():
        return "빈 줄"
    if UNIT_RE.match(text):
        return "표 위 기준·단위 줄"
    para = styles.para.get(p.get("paraPrIDRef"), {})
    sizes = [styles.char.get(r.get("charPrIDRef"), {}).get("size", 10) for r in para_runs(p) if run_text(r).strip()]
    if para.get("align") == "CENTER" and sizes and max(sizes) >= 16:
        return "제목"
    if para.get("align") == "RIGHT":
        return "오른쪽 정렬 줄(날짜·부서 등)"
    if para.get("align") == "CENTER":
        return "가운데 줄"
    return "본문"


def describe_table(tbl, styles):
    grid = table_grid(tbl)
    info = {"rows": int(tbl.get("rowCnt", "0")), "cols": int(tbl.get("colCnt", "0")),
            "border": styles.border_desc(tbl.get("borderFillIDRef")), "cells": [], "merged": False}
    sz = tbl.find(T("hp:sz"))
    if sz is not None:
        info["width_mm"] = round(int(sz.get("width", "0")) / (7200 / 25.4), 1)
    for r, c, rs, cs, tc in grid:
        if rs > 1 or cs > 1:
            info["merged"] = True
        csz = tc.find(T("hp:cellSz"))
        paras = []
        for k, cp in enumerate(cell_paras(tc)):
            paras.append({"index": k, "paraPr": cp.get("paraPrIDRef"), "para": styles.para_desc(cp.get("paraPrIDRef")),
                          "runs": describe_runs(cp, styles), "text": para_text(cp)})
        info["cells"].append({"row": r, "col": c, "rowSpan": rs, "colSpan": cs,
                              "width_mm": round(int(csz.get("width", "0")) / (7200 / 25.4), 1) if csz is not None else None,
                              "border": styles.border_desc(tc.get("borderFillIDRef")), "paras": paras})
    return info


def analyze(path):
    pkg = Package(path)
    styles = Styles(pkg.xml("Contents/header.xml"))
    secs = pkg.sections()
    sec = pkg.xml(secs[0])
    result = {"file": os.path.basename(path), "sections": len(secs), "page": page_info(sec), "paragraphs": [],
              "header_footer": []}
    paras = [p for p in sec if p.tag == T("hp:p")]
    for p in sec.iter(T("hp:p")):
        for r in para_runs(p):
            for ctrl in r.findall(T("hp:ctrl")):
                for x in ctrl:
                    if local(x) in ("header", "footer"):
                        txt = " / ".join(t for t in (para_text(q) for q in x.iter(T("hp:p"))) if t.strip())
                        n_pic = len(list(x.iter(T("hp:pic"))))
                        if n_pic:  # 기본 양식 머리말 = 오른쪽 위 시 슬로건 띠 그림(2026-11-11)
                            txt = (txt + " / " if txt else "") + f"그림 {n_pic}개(오른쪽 위 띠 그림 등)"
                        result["header_footer"].append({"kind": "머리말" if local(x) == "header" else "꼬리말",
                                                        "applyTo": x.get("applyPageType"), "text": txt})
                    elif local(x) == "pageNum":
                        result["header_footer"].append({"kind": "쪽 번호", "applyTo": x.get("pos"),
                                                        "text": x.get("formatType", "")})
    for idx, p in enumerate(paras):
        text = para_text(p)
        tables = para_tables(p)
        item = {"index": idx, "role": guess_role(p, styles, idx, text, tables), "paraPr": p.get("paraPrIDRef"),
                "para": styles.para_desc(p.get("paraPrIDRef")), "pageBreak": p.get("pageBreak") == "1",
                "text": text, "runs": describe_runs(p, styles)}
        objs = sorted({o for r in para_runs(p) for o in run_objects(r)
                       if o not in ("secPr", "tbl") and not (o.startswith("ctrl:") and o[5:] in STRUCT_CTRLS)})
        if objs:
            item["objects"] = objs
        if tables:
            item["tables"] = [describe_table(t, styles) for t in tables]
            pp = styles.para.get(p.get("paraPrIDRef"), {})
            item["margin_mm"] = (pp.get("left", 0) + pp.get("right", 0)) / (7200 / 25.4)
        pre, mark, _ = split_marker(text)
        item["marker"] = pre
        result["paragraphs"].append(item)
    return result


def signature(item):
    """모양이 같은 문단끼리 묶는 열쇠."""
    if item.get("tables"):
        t = item["tables"][0]
        return ("표", t["rows"], t["cols"], item["paraPr"], tuple(c["border"] for c in t["cells"][:3]))
    return (item["role"], item["paraPr"], tuple(r["charPr"] for r in item["runs"]), item["marker"].strip())


def _kinds(item):
    """문단에 있는 조각 모양 표시 — 계획의 **굵게**·^^위 첨자^^는 견본 문단에 그 모양 조각이 있어야 먹는다."""
    chars = " ".join(r["char"] for r in item["runs"])
    return ("·굵은 조각" if "굵게" in chars else "") + ("·위 첨자 조각" if "위첨자" in chars else "")


def _table_line(item):
    t = item["tables"][0]
    rows = {}
    for c in t["cells"]:
        rows.setdefault(c["row"], []).append(short(" ".join(p["text"] for p in c["paras"]).strip(), 12))
    head = " | ".join(rows.get(0, []))
    return f"표 {t['rows']}×{t['cols']}{', 합친 칸 있음' if t['merged'] else ''} — 첫 줄: {head}"


def print_brief(res, path):
    """짧은 지도(기본): 여백 → 기호로 쓰면 고르는 문단 → 번호로만 쓰는 문단. 30KB가 넘던 지도가 한 번에 읽히지 않아
    견본 하나 읽는 데 가장 오래 걸렸다(시험 2026-11-12) — 조각·칸마다의 서식은 --all로."""
    pg = res["page"]
    items = res["paragraphs"]
    print(f"# 양식 지도: {res['file']}")
    if pg:
        kind = "세로" if pg["width"] < pg["height"] else "가로"
        body_h = pg["height"] - pg.get("top", 0) - pg.get("bottom", 0) - pg.get("header", 0) - pg.get("footer", 0)
        print(f"- 용지 {pg['width']:.0f}×{pg['height']:.0f}mm({kind}), 여백 왼 {pg.get('left', 0):.1f} · 오른 {pg.get('right', 0):.1f} · "
              f"위 {pg.get('top', 0):.1f} · 아래 {pg.get('bottom', 0):.1f}mm → 본문 폭 {pg.get('body_width', 0):.1f}mm, "
              f"높이 {body_h:.1f}mm(머리말 {pg.get('header', 0):.1f}·꼬리말 {pg.get('footer', 0):.1f} 뺌)")
    for hf in res["header_footer"]:
        print(f"- {hf['kind']}: {short(hf['text']) or '(글 없음)'}")
    if not any(hf["kind"] in ("머리말", "꼬리말") for hf in res["header_footer"]):
        print("- 머리말·꼬리말: 없음")
    if res["sections"] > 1:
        print(f"- 주의: 구역이 {res['sections']}개입니다. 첫 구역의 문단만 견본으로 쓰고, 결과 문서는 구역 하나로 만듭니다.")
    wide = []
    for it in items:
        for t in it.get("tables", []):
            diff = t.get("width_mm", 0) - (pg.get("body_width", 0) - it.get("margin_mm", 0)) if pg else 0
            if abs(diff) > 0.3:
                wide.append(f"[{it['index']}] {diff:+.1f}mm")
    if wide:
        print("- 본문 폭과 다른 표(+ 넓음·- 좁음): " + ", ".join(wide[:12]))
    print("- 기호: ⎵ 고정폭 빈칸, ⍽ 묶음 빈칸, ⇥ 탭, ↵ 줄 바꿈")

    # 기호로 쓰면 도구가 고르는 문단 — 만들 때(plan_text)와 같은 방법으로 고른다
    used = {}
    try:
        from build import Builder
        from plan_text import Roles
        roles = Roles(Builder(Package(path)))
    except Exception:  # noqa: BLE001 — 쪽 설정이 없는 파일 등: 번호 목록만 보임
        roles = None
    print()
    print("## 기호로 쓰기 — 계획에 이렇게 쓰면 이 견본 문단 모양으로 들어감")

    def show(how, idx, note=""):
        if idx is None:
            return
        it = items[idx]
        used.setdefault(idx, how)
        if it.get("tables"):
            print(f"- `{how}` → [{idx}] {it['role']} | {_table_line(it)}{note}")
        else:
            print(f"- `{how}` → [{idx}] {it['role']} | {it['para']}{_kinds(it)}{note} | 예) \"{short(it['text'], 34)}\"")

    if roles is not None:
        show("제목: …", roles.title())
        show("날짜: …", roles.date())
        show("요약: …", roles.summary())
        seen_marks = set()
        for it in items:
            mark = split_marker(it["text"])[1]
            if it.get("tables") or not mark or mark == "■" or it["role"] in seen_marks:
                continue
            role = it["role"]
            seen_marks.add(role)
            group = [i for i in roles.of(role)]
            if role in ("주석(*)", "참고(※)"):
                shapes = {}
                for i in group:
                    shapes.setdefault(items[i]["para"], i)
                for i in shapes.values():
                    show(f"{mark} …", i, " — 바로 위 항목의 글 시작 자리에 가까운 모양을 고름" if len(shapes) > 1 else "")
            else:
                lab = [i for i in group if roles.labeled[i]]
                plain = [i for i in group if not roles.labeled[i]]
                if lab and plain:
                    show(f"{mark} (이름표) …", roles.common(lab))
                    show(f"{mark} …", roles.common(plain))
                else:
                    show(f"{mark} …", roles.common(group))
        plain_t = roles.plain_tables()
        seen_cols = set()
        for i in plain_t:  # 칸 수마다 실제로 고르는 표 하나씩(칸 수가 같으면 앞선 표를 고름)
            cols = items[i]["tables"][0]["cols"]
            if cols not in seen_cols:
                seen_cols.add(cols)
                show("{\"table\": [[…], …]}", i)
        if len(plain_t) > 1:
            print("  (표가 여럿 — 칸 수가 같은 표를 먼저, 없으면 첫 표를 고르고 칸 수는 도구가 맞춤. 표 모양을 정하려면 "
                  "{\"like\": 번호, \"table\": …})")
        if plain_t:
            print("- `■ 제목` · `(기준 : …) (단위 : …)` → 바로 다음 표 위의 제목 줄·단위 줄(도구가 표에 맞춰 만듦)")
        elif roles.of("표"):
            print("- (줄·칸을 바꿔 쓸 표가 없는 견본 — 합친 칸 있는 표뿐. 표는 아래 번호로 {\"like\": 번호, \"cells\": …} 칸만 채움)")
        show("[참고1] 제목", roles.ref())
        if not seen_marks:
            print("- (머리 기호로 시작하는 문단이 없는 견본 — 아래 번호로 쓰세요)")
    print("- □ 사이 빈 줄·표 위아래 간격은 도구가 넣는다. 목록에 없는 기호는 이 견본에 없다(있는 기호로 바꾸거나 번호로).")

    # 번호로만 쓰는 문단(상자·그림·모양이 다른 문단) — 같은 모양은 한 줄로
    rest = {}
    for it in items:
        if it["index"] in used:
            continue
        if it.get("tables"):
            key = ("t", it["role"], it["tables"][0]["rows"], it["tables"][0]["cols"], _table_line(it))
        else:
            key = ("p", it["role"], it["para"], it["marker"].strip(), _kinds(it))
        rest.setdefault(key, []).append(it["index"])
    # 기호로 고른 문단과 모양까지 같은 문단은 따로 보이지 않는다 — 기호만 같고 모양(들여쓰기·줄 간격·조각)이 다른 문단은 번호로
    # 골라 쓸 수 있게 보인다(역할·기호만 보고 숨기면 '같은 기호의 다른 모양'을 찾을 길이 없음, 검토 2026-11-12)
    same_as = set()
    for idx in used:
        it = items[idx]
        if not it.get("tables"):
            same_as.add(("p", it["role"], it["para"], it["marker"].strip(), _kinds(it)))
    lines = []
    for key, idxs in rest.items():
        first = items[idxs[0]]
        if key in same_as:
            continue
        what = _table_line(first) if first.get("tables") else f"{first['para']}{_kinds(first)}"
        flag = " [쪽 나눔]" if first["pageBreak"] else ""
        more = f" (같은 모양 {len(idxs) - 1}개 더)" if len(idxs) > 1 else ""
        text = "" if first.get("tables") else f" | \"{short(first['text'], 30)}\""
        lines.append(f"- [{idxs[0]}] {first['role']}{flag} | {what}{text}{more}")
    if lines:
        print()
        print("## 번호로 쓰는 문단 — {\"like\": 번호, \"text\"·\"cells\": …}")
        for ln in lines[:BRIEF_MAX]:
            print(ln)
        if len(lines) > BRIEF_MAX:  # 100쪽 넘는 문서는 모양이 수백 가지 — 지도가 다시 길어지지 않게
            print(f"- … 그 밖 {len(lines) - BRIEF_MAX}가지 모양(모두 보려면 --all)")
    print()
    print(f"- 최상위 문단 {len(items)}개. 조각·표 칸마다의 서식까지 보려면 --all, 글만 읽으려면 --text.")


def print_map(res, show_all=False):
    pg = res["page"]
    print(f"# 양식 지도: {res['file']}")
    if pg:
        kind = "세로" if pg["width"] < pg["height"] else "가로"
        print(f"- 용지 {pg['width']:.0f}×{pg['height']:.0f}mm({kind}), 여백 왼 {pg.get('left', 0):.1f} · 오른 "
              f"{pg.get('right', 0):.1f} · 위 {pg.get('top', 0):.1f} · 아래 {pg.get('bottom', 0):.1f}mm, "
              f"본문 폭 {pg.get('body_width', 0):.1f}mm")
    for hf in res["header_footer"]:
        print(f"- {hf['kind']}: {short(hf['text']) or '(글 없음)'}")
    if pg:
        print()
        print("## 여백 먼저(글과 표는 이 안에 들어가야 함)")
        body_h = pg["height"] - pg.get("top", 0) - pg.get("bottom", 0) - pg.get("header", 0) - pg.get("footer", 0)
        print(f"- 본문 폭 {pg.get('body_width', 0):.1f}mm, 본문 높이 {body_h:.1f}mm "
              f"(위 {pg.get('top', 0):.1f}+머리말 {pg.get('header', 0):.1f}, 아래 {pg.get('bottom', 0):.1f}+꼬리말 {pg.get('footer', 0):.1f})")
        seen = set()
        for it in res["paragraphs"]:
            key = (it["role"], it["para"])
            if it.get("tables") or key in seen or "여백" not in it["para"] and "내어쓰기" not in it["para"]:
                continue
            seen.add(key)
            print(f"- 문단 여백 [{it['index']}] {it['role']}: {it['para']}")
        for it in res["paragraphs"]:
            for t in it.get("tables", []):
                room = pg.get("body_width", 0) - it.get("margin_mm", 0)
                diff = t.get("width_mm", 0) - room
                state = ("끝선 맞음" if abs(diff) <= 0.3 else
                         f"본문보다 {diff:.1f}mm 넓음(튀어나옴)" if diff > 0 else f"본문보다 {-diff:.1f}mm 좁음")
                print(f"- 표 [{it['index']}] {t['rows']}×{t['cols']} 폭 {t.get('width_mm', 0):.1f}mm — {state}")
    if res["sections"] > 1:
        print(f"- 주의: 구역이 {res['sections']}개입니다. 첫 구역의 문단만 견본으로 쓰고, 결과 문서는 구역 하나로 만듭니다.")
    print(f"- 최상위 문단 {len(res['paragraphs'])}개. [번호]가 계획 파일의 \"like\" 값입니다.")
    print("- 기호: ⎵ 고정폭 빈칸, ⍽ 묶음 빈칸, ⇥ 탭, ↵ 줄 바꿈")
    print()

    groups = {}
    for it in res["paragraphs"]:
        groups.setdefault(signature(it), []).append(it["index"])
    first_of = {v[0]: v for v in groups.values()}
    many = len(res["paragraphs"]) > 80 and not show_all

    print("## 문단 목록" + (" (모양이 같은 문단은 첫 것만 자세히)" if many else ""))
    for it in res["paragraphs"]:
        same = first_of.get(it["index"])
        if many and same is None:
            continue
        flag = " [쪽 나눔]" if it["pageBreak"] else ""
        print(f"[{it['index']}] {it['role']}{flag} | 문단모양 p{it['paraPr']}: {it['para']}")
        if same and len(same) > 1:
            print(f"     같은 모양: {', '.join(map(str, same[1:12]))}{' …' if len(same) > 12 else ''}")
        for r in it["runs"]:
            extra = f" (+{','.join(r['objects'])})" if r["objects"] else ""
            print(f"     조각{r['index']} c{r['charPr']} {r['char']}{extra}: \"{short(r['text'])}\"")
        for o in it.get("objects", []):
            if o.startswith("ctrl:") or o in ("pic", "equation", "rect", "line", "container", "fieldBegin"):
                print(f"     (글 아닌 것 포함: {o})")
        for t in it.get("tables", []):
            merged = ", 합친 칸 있음" if t["merged"] else ""
            print(f"     표 {t['rows']}×{t['cols']} 폭 {t.get('width_mm', '?')}mm{merged}")
            for c in t["cells"]:
                if c["row"] > 2 and not show_all:
                    print("       … (넷째 줄부터 생략, --all로 모두 보기)")
                    break
                span = f" 합침{c['rowSpan']}×{c['colSpan']}" if c["rowSpan"] > 1 or c["colSpan"] > 1 else ""
                print(f"       칸({c['row']},{c['col']}){span} 폭{c['width_mm']}mm [{c['border']}]")
                for cp in c["paras"]:
                    for r in cp["runs"]:
                        print(f"          문단{cp['index']} p{cp['paraPr']}({cp['para']}) 조각{r['index']} "
                              f"c{r['charPr']} {r['char']}: \"{short(r['text'], 40)}\"")
    print()
    print("## 같은 모양끼리 묶음")
    for sig, idxs in groups.items():
        first = res["paragraphs"][idxs[0]]
        print(f"- {first['role']}: {', '.join(map(str, idxs[:15]))}{' …' if len(idxs) > 15 else ''}"
              f"  예) \"{short(first['text'], 40)}\"")


def print_text(res):
    for it in res["paragraphs"]:
        if it.get("tables"):
            for t in it["tables"]:
                rows = {}
                for c in t["cells"]:
                    rows.setdefault(c["row"], []).append(" ↵ ".join(p["text"] for p in c["paras"]))
                print(f"[{it['index']}] <표 {t['rows']}×{t['cols']}>")
                for r in sorted(rows):
                    print("    | " + " | ".join(rows[r]) + " |")
        else:
            print(f"[{it['index']}] {it['text']}")


def main():
    ap = argparse.ArgumentParser(description="견본 hwpx의 양식 지도를 보인다")
    ap.add_argument("template")
    ap.add_argument("--text", action="store_true", help="글만 보이기")
    ap.add_argument("--all", action="store_true", help="문단마다 조각·표 칸의 서식까지 모두 보이기(번호·조각 모양을 직접 고를 때)")
    ap.add_argument("--json", help="지도를 JSON 파일로도 저장")
    a = ap.parse_args()
    res = analyze(a.template)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    if a.text:
        print_text(res)
    elif a.all:
        print_map(res, True)
    else:
        print_brief(res, a.template)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
