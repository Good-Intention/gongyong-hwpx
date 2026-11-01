# -*- coding: utf-8 -*-
"""견본 한글 파일(.hwpx)을 읽어 '양식 지도'를 보인다.

쓰는 법:
    python analyze.py 견본.hwpx            # 양식 지도(문단마다 번호·역할·서식·글)
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
                        txt = " / ".join(para_text(q) for q in x.iter(T("hp:p")))
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
    ap.add_argument("--all", action="store_true", help="문단·표 칸을 줄이지 않고 모두 보이기")
    ap.add_argument("--json", help="지도를 JSON 파일로도 저장")
    a = ap.parse_args()
    res = analyze(a.template)
    if a.json:
        with open(a.json, "w", encoding="utf-8") as f:
            json.dump(res, f, ensure_ascii=False, indent=1)
    if a.text:
        print_text(res)
    else:
        print_map(res, a.all)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
