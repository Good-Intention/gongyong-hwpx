# -*- coding: utf-8 -*-
"""빈칸 한 칸 — 작성(build.py)·정돈(tidy.py) 공통.

사용자(2026-11-08, PC 한글 조판 부호 화면): '한칸만 띄워야 하는 곳에 두칸 띄움이 있는 곳이 많다. 동그라미 다음, 작대기 다음 등
불필요한 연속 두칸 띄우기는 한칸 띄우기로 바꾸라. 당연히 지금까지 정한 규칙이 흐트러지면 안되겠지.'
- 머리(머리 기호 뒤·이름표 안·쌍점 앞뒤)는 양쪽 정렬에도 늘지 않게 고정폭 빈칸(글자 크기 1/4)을 두 개씩 써 왔다(보통 빈칸
  한 칸 폭). 보통·묶음·반각(U+2002) 빈칸 한 개는 양쪽 정렬에서 늘고 줄어 둘째 줄이 0.5~1mm 어긋났다(한글 2024 시험).
- 고정폭 빈칸 하나에 장평 200%를 주면 0.498글자(실측) — 보통 빈칸 한 칸 폭, 늘지 않음. 그래서 두 개를 한 개로 줄인다.
- 머리 기호 앞 줄머리 빈칸은 문단 왼쪽 여백(또는 첫 줄 들여쓰기)으로 옮긴다 — 자리는 같고 빈칸 부호는 없다.
폭이 같으므로 둘째 줄 맞춤·이름표 폭·쪽 나눔은 바뀌지 않는다.
"""
import copy
import re

from hwpx_lib import T, head_length, para_runs, para_text, run_text, set_run_text

FW = "⎵"


def compact_fw(p, styles, hedit, split, tab_proto):
    """머리(내용 첫 글자 앞)의 고정폭 빈칸 2n개를 장평을 두 배로 한 고정폭 빈칸 n개로(홀수면 하나는 그대로).
    split(text) → (머리 기호까지 글, 기호, …). 바꾼 묶음 수를 돌려준다."""
    text = para_text(p)
    pre, mark = split(text)[:2]
    if not mark:
        return 0
    k = head_length(text) or len(pre)
    n, pos = 0, 0
    for r in list(para_runs(p)):
        t = run_text(r)
        st, pos = pos, pos + len(t)
        if st >= k or FW * 2 not in t[:k - st] or not (len(r) == 1 and r[0].tag == T("hp:t")):
            continue
        cid = r.get("charPrIDRef")
        ratio = styles.char.get(cid, {}).get("ratio", 100)
        if ratio > 100:
            continue  # 이미 줄인 조각(장평 두 배 — 한글 장평 상한 200%). 자간은 그대로 따라가므로(같은 조각) 폭이 같음
        wide = hedit.char_ratio(cid, 2 * ratio)
        cut = k - st
        pieces = []
        for tok in re.split(r"(⎵{2,})", t[:cut]):
            if not tok:
                continue
            if tok.startswith(FW * 2):
                pieces.append((FW * (len(tok) // 2), wide))
                if len(tok) % 2:
                    pieces.append((FW, cid))
                n += 1
            else:
                pieces.append((tok, cid))
        if t[cut:]:
            pieces.append((t[cut:], cid))
        merged = []
        for s, c2 in pieces:
            if merged and merged[-1][1] == c2:
                merged[-1] = (merged[-1][0] + s, c2)
            else:
                merged.append((s, c2))
        set_run_text(r, merged[0][0], tab_proto)
        r.set("charPrIDRef", merged[0][1])
        last = r
        for s, c2 in merged[1:]:
            twin = copy.deepcopy(r)
            set_run_text(twin, s, tab_proto)
            twin.set("charPrIDRef", c2)
            last.addnext(twin)
            last = twin
    return n


def lead_to_margin(p, styles, hedit, lay, split, fonts_ok, tab_proto, w):
    """머리 기호 앞 줄머리 빈칸(보통·고정폭)을 지우고 그 폭만큼 문단 여백으로 — 첫 줄 자리·둘째 줄 자리 모두 그대로.
    fonts_ok(p): 보통 빈칸 폭을 믿을 수 있는 글꼴인가(고정폭 빈칸만이면 묻지 않음). 옮겼으면 True."""
    text = para_text(p)
    m = re.match(r"^[ ⎵⍽]+", text)
    if not m or not split(text)[1]:
        return False
    pp = styles.para.get(p.get("paraPrIDRef"), {})
    if pp.get("align") in ("CENTER", "RIGHT"):
        return False
    lead = m.group(0)
    if lead.strip(FW) and not fonts_ok(p):
        return False
    chs, _ = lay.para_lines(p, w)
    width = sum(c[1] for c in chs[:len(lead)])
    left_n, todo = len(lead), []
    for r in para_runs(p):
        if not left_n:
            break
        t = run_text(r)
        if not t:
            continue
        if not (len(r) == 1 and r[0].tag == T("hp:t")):
            return False
        cut = min(left_n, len(t))
        todo.append((r, t[cut:]))
        left_n -= cut
    if left_n:
        return False
    for r, t in todo:
        set_run_text(r, t, tab_proto)
    left, intent = pp.get("left", 0), pp.get("intent", 0)
    first = left + max(intent, 0) + width
    rest = left + max(-intent, 0)
    pid = hedit.para_margin(p.get("paraPrIDRef"), "left", min(first, rest))
    pid = hedit.para_hang(pid, rest - first if rest > first else -(first - rest))
    p.set("paraPrIDRef", pid)
    return True
