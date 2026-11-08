# -*- coding: utf-8 -*-
"""한글이 만든 PDF에서 글자마다 (y, x 시작, 폭, 글자)를 읽는다(ToUnicode·W 폭·TJ 조정·Tm 장평 반영). 개발용 — 한글 맞대기 시험(hangul_truth.py)이 쓴다.
    python pdf_glyphs.py 문서.pdf [쪽번호(0부터)]  → 줄마다 글자와 x(mm)"""
import re
import sys
import zlib

sys.stdout.reconfigure(encoding="utf-8")
MM = 25.4 / 72  # PDF 사용자 단위(pt) → mm (한글 PDF는 Tm 앞에 cm으로 1/600인치를 쓰는지 아래에서 확인)


def load(path):
    d = open(path, "rb").read()
    objs = {}
    for m in re.finditer(rb"(\d+) 0 obj(.*?)endobj", d, re.S):
        objs[int(m.group(1))] = m.group(2)
    for n, body in list(objs.items()):  # 객체 묶음(ObjStm) 풀기
        if b"/ObjStm" not in body:
            continue
        first = int(re.search(rb"/First\s+(\d+)", body).group(1))
        cnt = int(re.search(rb"/N\s+(\d+)", body).group(1))
        s = stream(body)
        nums = [int(v) for v in s[:first].split()]
        pairs = [(nums[2 * k], nums[2 * k + 1]) for k in range(cnt)]
        for k, (on, off) in enumerate(pairs):
            end = pairs[k + 1][1] if k + 1 < cnt else len(s) - first
            objs[on] = s[first + off:first + end]
    return objs


def stream(body):
    m = re.search(rb"stream\r?\n(.*)endstream", body, re.S)
    if not m:
        return b""
    raw = m.group(1)
    try:
        return zlib.decompress(raw)
    except Exception:  # noqa: BLE001
        return raw


def ref(body, key):
    m = re.search(rb"/" + key + rb"\s+(\d+) 0 R", body)
    return int(m.group(1)) if m else None


def cmap(objs, n):
    s = stream(objs[n]).decode("latin1")
    out = {}
    for blk in re.findall(r"beginbfchar(.*?)endbfchar", s, re.S):
        for a, b in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            out[int(a, 16)] = bytes.fromhex(b).decode("utf-16-be", "replace")
    for blk in re.findall(r"beginbfrange(.*?)endbfrange", s, re.S):
        for a, b, c in re.findall(r"<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>", blk):
            base = int(c, 16)
            for k in range(int(a, 16), int(b, 16) + 1):
                out[k] = chr(base + k - int(a, 16))
    return out


def widths(objs, font):
    desc = re.search(rb"/DescendantFonts\s*\[\s*(\d+) 0 R", objs[font])
    w, dw = {}, 1000
    if not desc:
        return w, dw
    body = objs[int(desc.group(1))]
    m = re.search(rb"/DW\s+(\d+)", body)
    if m:
        dw = int(m.group(1))
    m = re.search(rb"/W\s*(\[.*?\]\s*\])", body, re.S) or re.search(rb"/W\s+(\d+) 0 R", body)
    if not m:
        return w, dw
    arr = m.group(1)
    if not arr.startswith(b"["):
        arr = objs[int(arr)]
    toks = re.findall(rb"\[|\]|[\d.]+", arr)[1:]
    i = 0
    while i < len(toks):
        if toks[i] == b"]":
            break
        c = int(toks[i])
        if toks[i + 1] == b"[":
            j = i + 2
            while toks[j] != b"]":
                w[c] = float(toks[j])
                c += 1
                j += 1
            i = j + 1
        else:
            c2, val = int(toks[i + 1]), float(toks[i + 2])
            for k in range(c, c2 + 1):
                w[k] = val
            i += 3
    return w, dw


def glyphs(path, page=0):
    objs = load(path)
    pages = [n for n, b in sorted(objs.items()) if re.search(rb"/Type\s*/Page[^s]", b)]
    pb = objs[pages[page]]
    res = objs[ref(pb, b"Resources")] if ref(pb, b"Resources") else pb
    fm = re.search(rb"/Font\s*<<(.*?)>>", res, re.S)
    if not fm:
        fr = ref(res, b"Font")
        fm = re.search(rb"<<(.*)>>", objs[fr], re.S)
    fonts = {}
    for name, n in re.findall(rb"/(\w+)\s+(\d+) 0 R", fm.group(1)):
        n = int(n)
        tu = ref(objs[n], b"ToUnicode")
        fonts[name.decode()] = (cmap(objs, tu) if tu else {}, *widths(objs, n))
    cont = re.search(rb"/Contents\s+(\d+) 0 R", pb)
    s = stream(objs[int(cont.group(1))]).decode("latin1")
    unit = 72 / 600  # 한글 PDF의 Tm 좌표는 1/600인치(앞의 cm 0.12와 같음 — 첫 cm이 그림 것일 때가 있어 고정값으로)
    out = []
    f, size, a, d, x, y, lx, ly = None, 10.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0
    # 연산자 차례대로: Tf(글꼴) → Tm(자리)·Td(줄 옮김) → TJ/Tj(글자). Tf 없이 Tm만 되풀이되는 조각도 읽는다
    for m in re.finditer(r"/(\w+) ([\d.]+) Tf|([\d.\-]+) ([\d.\-]+) ([\d.\-]+) ([\d.\-]+) ([\d.\-]+) ([\d.\-]+) Tm"
                         r"|(-?[\d.]+) (-?[\d.]+) T[dD]\b|\[([^\[\]]*)\]\s*TJ|<([0-9A-Fa-f]+)>\s*Tj|\bBT\b", s, re.S):
        if m.group(0) == "BT":
            a, d, x, y, lx, ly = 1.0, 1.0, 0.0, 0.0, 0.0, 0.0
            continue
        if m.group(1):
            f, size = m.group(1), float(m.group(2))
            continue
        if m.group(3):
            a, d = float(m.group(3)), float(m.group(6))
            x, y = float(m.group(7)), float(m.group(8))
            lx, ly = x, y
            continue
        if m.group(9):
            lx, ly = lx + float(m.group(9)) * a, ly + float(m.group(10)) * d
            x, y = lx, ly
            continue
        m_tj, m_hex = m.group(11), m.group(12)
        uni, w, dw = fonts.get(f, ({}, {}, 1000))
        body = m_tj if m_tj is not None else f"<{m_hex}>"
        for tok in re.findall(r"<([0-9A-Fa-f]+)>|(-?[\d.]+)", body):
            if tok[0]:
                hx = tok[0]
                for k in range(0, len(hx), 4):
                    cid = int(hx[k:k + 4], 16)
                    adv = w.get(cid, dw) / 1000 * size * a
                    out.append((round(y * unit * MM, 2), round(x * unit * MM, 2), round(adv * unit * MM, 2), uni.get(cid, "?")))
                    x += adv
            else:
                x -= float(tok[1]) / 1000 * size * a
    return out


if __name__ == "__main__":
    gl = glyphs(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 0)
    lines = {}
    for y, x, w, ch in gl:
        lines.setdefault(y, []).append((x, w, ch))
    for y in sorted(lines, reverse=True):
        row = sorted(lines[y])
        print(f"y={y:.1f}: " + " ".join(f"{ch}{x:.2f}" for x, w, ch in row))
