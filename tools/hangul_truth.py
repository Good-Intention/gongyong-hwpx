# -*- coding: utf-8 -*-
"""한글 맞대기 시험(개발용): 한글 2024가 실제로 그린 결과를 정답으로 저장해 두고, 도구의 줄·쪽 어림이 그 정답과 같은지 본다.
한글 없이 돈다(정답은 한 번 만들어 둔 PDF에서 뽑아 둠).

    python -X utf8 tools/hangul_truth.py make 이름 문서.hwpx 한글.pdf   # 정답 만들기(문서는 tools/regress/hangul/이름.hwpx로 복사)
    python -X utf8 tools/hangul_truth.py check [이름…]                  # 맞대기(regress.py도 부름)

정답 파일(tools/regress/hangul/이름.json):
  pages       한글 쪽 수
  pdf_lines   한글 PDF의 줄마다 글(빈칸 뺌) → 그 줄이 나온 수
  paras       맞대 볼 글 문단마다 [앞 글 20자, 한글 줄 수] — 만들 때 어림 줄이 모두 PDF 줄과 같았던 문단만 줄 수를 적고, 다르면 null
  base        만들 때 결과(맞은 문단 수·전체·어림 쪽 수) — 확인은 '이보다 나빠지지 않았나'로 한다
맞대 보는 문단(위·아래 첨자 글자는 빼고 견줌): 본문·한 칸 상자 안 글 문단 가운데 휴먼명조·맑은 고딕만으로 된 6자 이상 문단.
한양중고딕은 도구가 자간을 맞추는 글꼴이지만 한글 PDF에 글자 대응표가 없어 글자 대부분이 '?'로 나오고 글자 수도 달라져
PDF로는 확인할 수 없다(사람 문서 ※ 줄, 2026-11-05) — 맞대기에서 뺀다. 새 문서는 이 글꼴을 쓰지 않는다(글꼴 세 가지 원칙).
"""
import collections
import json
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
# 정답 폴더 — PC는 tools/regress/hangul, 공개 저장소는 tests/hangul(HANGUL_TRUTH_DIR로 바꿈, 같은 파일을 두 곳에서 씀)
DIR = os.environ.get("HANGUL_TRUTH_DIR") or os.path.join(HERE, "regress", "hangul")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "gongyong-hwpx", "scripts"))
from pdf_glyphs import glyphs  # noqa: E402
from hwpx_lib import T, Package, para_runs, para_text, run_text  # noqa: E402
from build import Builder  # noqa: E402
from fit import Fitter  # noqa: E402

SKIP = re.compile(r"[\s⎵⍽ ]")
FONTS_OK = {"휴먼명조", "맑은 고딕"}  # 한양중고딕은 PDF에서 글자를 읽을 수 없어 뺌(맨 위 설명)


def pdf_lines(path):
    """한글 PDF의 줄 글(빈칸 뺌) → 나온 수, 쪽 수."""
    lines = collections.Counter()
    page = 0
    while True:
        try:
            gl = glyphs(path, page)
        except IndexError:
            break
        page += 1
        gl.sort(key=lambda g: (-g[0], g[1]))
        rows = []
        for y, x, w, ch in gl:
            if rows and abs(rows[-1][0] - y) <= 1.2:
                rows[-1][1].append((x, ch))
            else:
                rows.append([y, [(x, ch)]])
        for _, items in rows:
            s = SKIP.sub("", "".join(ch for _, ch in sorted(items)))
            if s:
                lines[s] += 1
    return lines, page


class Truth:
    """한글 줄 모음과 견주기. PDF 읽기의 한계 두 가지를 너그럽게 본다(사람 문서의 한양중고딕 ※ 줄에서 실측 2026-11-05):
    글자 차례가 뒤섞임('5.0점' → '5.점0') — 글자 모음이 같으면 같은 줄, 글자 대응표가 없어 '?'로 읽힘 — 길이가 같고
    '?'가 아닌 글자가 모두 어림 줄에 있으면 같은 줄."""

    def __init__(self, lines):
        self.real = collections.Counter(lines)
        self.sorted = {"".join(sorted(x)) for x in self.real}
        self.unknown = collections.defaultdict(list)
        for x in self.real:
            if "?" in x:
                self.unknown[len(x)].append(collections.Counter(x.replace("?", "")))

    def has(self, x):
        if self.real[x] > 0 or "".join(sorted(x)) in self.sorted:
            return True
        cx = collections.Counter(x)
        return any(not (c - cx) for c in self.unknown.get(len(x), ()))


def estimate(hwpx):
    """도구 어림: [(앞 글, 어림 줄 글 목록)], 어림 쪽 수(한글이 하는 대로 — 큰 표 통째 넘기기 없이)."""
    b = Builder(Package(hwpx))
    f = Fitter(b)
    f.lay.move_whole = False
    out = []
    for p, box_w in f.text_boxes():
        runs = para_runs(p)
        if any(r.find(T(x)) is not None for r in runs for x in ("hp:tbl", "hp:pic")):
            continue
        fonts = {b.styles.char.get(r.get("charPrIDRef"), {}).get("font") for r in runs if run_text(r).strip()}
        if not fonts or not fonts <= FONTS_OK:
            continue
        chs, lines = f.lay.para_lines(p, box_w)
        # 위·아래 첨자 글자는 한글이 조금 높은(낮은) 자리에 따로 그려 PDF에서 다른 줄로 읽힌다 — 맞댈 때는 뺀다
        est = [x for x in (SKIP.sub("", "".join(c[0] for c in chs[s:e] if not c[3])) for s, e, _, _ in lines) if x]
        if not est or sum(map(len, est)) < 6:
            continue
        out.append((para_text(p).replace("⎵", " ").strip()[:20], est))
    m = re.search(r"어림 쪽 수 (\d+)쪽", f.report())
    return out, int(m.group(1)) if m else None


def make(name, hwpx, pdf):
    os.makedirs(DIR, exist_ok=True)
    dst = os.path.join(DIR, f"{name}.hwpx")
    if os.path.abspath(hwpx) != os.path.abspath(dst):
        shutil.copy(hwpx, dst)
    real, pages = pdf_lines(pdf)
    truth = Truth(real)
    est, est_pages = estimate(dst)
    paras = [[head, len(lines) if all(truth.has(x) for x in lines) else None] for head, lines in est]
    ok = sum(1 for _, n in paras if n is not None)
    data = {"pages": pages, "pdf_lines": dict(real), "paras": paras,
            "base": {"ok": ok, "total": len(paras), "est_pages": est_pages}}
    with open(os.path.join(DIR, f"{name}.json"), "w", encoding="utf-8") as fp:
        json.dump(data, fp, ensure_ascii=False, separators=(",", ":"))
    print(f"정답 저장 {name}: 한글 {pages}쪽(어림 {est_pages}쪽), 글 문단 {len(paras)}개 중 줄이 같은 문단 {ok}개")


def check(names=None):
    """맞대기 — 나빠진 것이 없으면 0, 있으면 나빠진 수. 줄마다 결과를 찍는다."""
    bad = 0
    for fn in sorted(os.listdir(DIR)) if os.path.isdir(DIR) else []:
        if not fn.endswith(".json"):
            continue
        name = fn[:-5]
        if names and not any(n in name for n in names):
            continue
        with open(os.path.join(DIR, fn), encoding="utf-8") as fp:
            data = json.load(fp)
        truth = Truth(data["pdf_lines"])
        est, est_pages = estimate(os.path.join(DIR, f"{name}.hwpx"))
        base = data["base"]
        ok, broke = 0, []
        for k, (head, lines) in enumerate(est):
            good = all(truth.has(x) for x in lines)
            ok += good
            want = data["paras"][k][1] if k < len(data["paras"]) else None
            if not good and want is not None:
                broke.append(f"‘{head}…’ 한글 {want}줄, 어림 {len(lines)}줄")
        pages_ok = est_pages == data["pages"] or est_pages == base["est_pages"]
        same = len(est) == base["total"] and ok >= base["ok"] and not broke and pages_ok
        bad += not same
        head = (f"{'맞음' if same else '다름'} 한글 맞대기 {name}: 한글 {data['pages']}쪽 / 어림 {est_pages}쪽, "
                f"글 문단 {len(est)}개 중 줄이 같은 문단 {ok}개(정답을 만들 때 {base['ok']}개)")
        print(head)
        if len(est) != base["total"]:
            print(f"    맞대 볼 문단 수가 달라짐 {base['total']}→{len(est)} — 글꼴·문단 판정이 바뀐 것")
        if not pages_ok:
            print(f"    쪽 수 어림이 달라짐: 정답 만들 때 {base['est_pages']}쪽 → 지금 {est_pages}쪽(한글 {data['pages']}쪽)")
        for line in broke[:6]:
            print("    " + line)
        if len(broke) > 6:
            print(f"    … 모두 {len(broke)}문단")
    return bad


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    if len(sys.argv) >= 5 and sys.argv[1] == "make":
        make(sys.argv[2], sys.argv[3], sys.argv[4])
    elif len(sys.argv) >= 2 and sys.argv[1] == "check":
        sys.exit(1 if check(sys.argv[2:]) else 0)
    else:
        print(__doc__)
