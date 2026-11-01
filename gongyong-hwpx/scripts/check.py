# -*- coding: utf-8 -*-
"""만든 한글 파일(.hwpx)이 깨지지 않았는지 검사하고 글 차례를 보인다.

쓰는 법:
    python check.py 결과.hwpx

검사하는 것:
    - ZIP 묶음 규칙(mimetype이 맨 앞·무압축)과 XML이 모두 읽히는가
    - 본문이 가리키는 글자 모양·문단 모양·테두리·스타일 번호가 header.xml에 모두 있는가
    - 표의 줄·칸 수와 합친 칸이 서로 맞는가
    - 첫 문단에 쪽 설정(secPr)이 있는가
한글 프로그램으로 열어 본 것은 아니다. 모양은 한글에서 열어 확인해야 한다.
"""
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from hwpx_lib import Package, Styles, T, cell_text, para_tables, para_text, table_grid  # noqa: E402

REFS = {"charPrIDRef": "char", "paraPrIDRef": "para", "borderFillIDRef": "border", "styleIDRef": "style"}


def check(path):
    errors, notes = [], []
    with zipfile.ZipFile(path) as z:
        infos = z.infolist()
        if not infos or infos[0].filename != "mimetype":
            errors.append("묶음의 첫 파일이 mimetype이 아닙니다.")
        elif infos[0].compress_type != zipfile.ZIP_STORED:
            errors.append("mimetype이 압축되어 있습니다(무압축이어야 함).")
        elif z.read("mimetype").strip() != b"application/hwp+zip":
            errors.append("mimetype 내용이 application/hwp+zip이 아닙니다.")
        bad = z.testzip()
        if bad:
            errors.append(f"묶음 안 파일이 손상됨: {bad}")
    pkg = Package(path)
    for name in pkg.data:
        if name.endswith((".xml", ".hpf", ".rdf")):
            try:
                pkg.xml(name)
            except Exception as e:  # noqa: BLE001
                errors.append(f"{name}: XML을 읽을 수 없음 ({e})")
    if errors:
        return errors, notes, []
    styles = Styles(pkg.xml("Contents/header.xml"))
    have = {"char": set(styles.char), "para": set(styles.para), "border": set(styles.border),
            "style": styles.style_ids}
    outline = []
    for name in pkg.sections():
        sec = pkg.xml(name)
        missing = {}
        for el in sec.iter():
            for attr, kind in REFS.items():
                v = el.get(attr)
                if v is not None and v not in have[kind]:
                    missing.setdefault(f"{attr}={v}", 0)
                    missing[f"{attr}={v}"] += 1
        for k, n in missing.items():
            errors.append(f"{name}: header.xml에 없는 서식 번호 {k} ({n}곳)")
        paras = [p for p in sec if p.tag == T("hp:p")]
        if not paras:
            errors.append(f"{name}: 문단이 하나도 없습니다.")
            continue
        if name == pkg.sections()[0] and paras[0].find(".//" + T("hp:secPr")) is None:
            errors.append("첫 문단에 쪽 설정(secPr)이 없습니다. 한글이 열지 못할 수 있습니다.")
        for tbl in sec.iter(T("hp:tbl")):
            errors += check_table(tbl)
            for r, c, w, need in narrow_cells(tbl):
                notes.append(f"표 칸({r},{c}) 너비 {w / 283.46:.1f}mm가 칸 안 여백보다 좁아 한글이 {need / 283.46:.1f}mm로 "
                             "넓힙니다 — 표가 본문 밖으로 튀어나올 수 있음")
        for i, p in enumerate(paras):
            tables = para_tables(p)
            if tables:
                for t in tables:
                    rows = {}
                    for r, c, rs, cs, tc in table_grid(t):
                        rows.setdefault(r, []).append(cell_text(tc).replace("\n", " ↵ "))
                    outline.append(f"[{i}] <표 {t.get('rowCnt')}×{t.get('colCnt')}>")
                    for r in sorted(rows):
                        outline.append("     | " + " | ".join(rows[r]) + " |")
            else:
                brk = " [쪽 나눔]" if p.get("pageBreak") == "1" else ""
                outline.append(f"[{i}]{brk} {para_text(p)}")
    return errors, notes, outline


def check_table(tbl):
    errs = []
    try:
        rows, cols = int(tbl.get("rowCnt")), int(tbl.get("colCnt"))
    except (TypeError, ValueError):
        return ["표에 줄·칸 수(rowCnt·colCnt)가 없습니다."]
    trs = [tr for tr in tbl if tr.tag == T("hp:tr")]
    if len(trs) != rows:
        errs.append(f"표 줄 수가 맞지 않음: rowCnt={rows}, 실제 {len(trs)}줄")
    seen = {}
    for r, c, rs, cs, tc in table_grid(tbl):
        for rr in range(r, r + rs):
            for cc in range(c, c + cs):
                if rr >= rows or cc >= cols:
                    errs.append(f"표 칸({r},{c})이 표 밖으로 나감")
                elif (rr, cc) in seen:
                    errs.append(f"표 칸({rr},{cc})이 겹침")
                seen[(rr, cc)] = True
    if not errs and len(seen) != rows * cols:
        errs.append(f"표에 빈 자리가 있음: {rows}×{cols} 중 {len(seen)}칸만 채워짐")
    return errs


MIN_EXTRA = 282  # 칸 너비는 칸 안 좌우 여백 + 약 1mm 이상이어야 한다(아니면 한글이 넓혀 표가 튀어나옴, 실측)


def narrow_cells(tbl):
    """한글이 저절로 넓힐 만큼 좁은 칸 [(줄, 칸, 너비, 최소)]."""
    out = []
    inm = tbl.find(T("hp:inMargin"))
    for r, c, rs, cs, tc in table_grid(tbl):
        cm = tc.find(T("hp:cellMargin")) if tc.get("hasMargin") == "1" else inm
        need = (int(cm.get("left", "510")) + int(cm.get("right", "510")) if cm is not None else 1020) + MIN_EXTRA
        w = int(tc.find(T("hp:cellSz")).get("width", "0"))
        if w < need:
            out.append((r, c, w, need))
    return out


def main():
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    errors, notes, outline = check(sys.argv[1])
    print_report(errors, notes, outline)
    sys.exit(1 if errors else 0)


def print_report(errors, notes, outline):
    if errors:
        print("## 검사 결과: 문제 있음")
        for e in errors:
            print(" - " + e)
    else:
        print("## 검사 결과: 통과(묶음·XML·서식 번호·표 구조)")
    for n in notes:
        print(" - " + n)
    if outline:
        print("\n## 만든 문서의 글 차례")
        for line in outline:
            print(line)


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    main()
