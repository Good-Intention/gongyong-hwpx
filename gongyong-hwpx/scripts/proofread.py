# -*- coding: utf-8 -*-
"""수치·맞춤법 확인 — 고치지 않고 알리기만(사용자 2026-11-15 '수치 검사를 보강해야 합니다 … 합계·소계·증감·비율과 원자료 수치의
일치 여부', '정돈이 끝난 후 파일과 함께 사용자에게 알려줘야겠네요. 수치, 맞춤법 틀린 부분', 맞춤법은 'PC 안에서만').

만들기(build.py)·검사만(review.py)·정돈(tidy.py)이 문서 글을 읽어 '## 수치·맞춤법 확인'으로 낸다:
  ① 표 합계: '계·합계·총계' 줄(또는 열)이 나머지 칸의 합과 같은가, '소계'는 그 묶음의 합과 같은가
  ② 비율·증감: '47건 중 31건(66%)', '38% → 70%(+32%p)', '120 → 150(25% 증가)', '(△3)'처럼 글에 쓴 셈이 맞는가
  ③ 같은 수치: 글에 쓴 '총 29곳'·'계 29곳'이 표의 계와 다른가(같은 단위 표 합계가 있는데 어느 것과도 다를 때만)
  ④ 맞춤법: 자주 틀리는 표기 목록(되요·몇일·금새·~할수 있다 …) — 문서 글을 밖으로 보내지 않는다
원자료(사용자가 준 자료)와의 대조는 도구가 알 수 없으므로 글을 쓴 쪽(AI)이 한다(write.md).
"""
import re

from hwpx_lib import T, cell_paras, para_tables, para_text, table_grid

TOTAL_RE = re.compile(r"^(합계|총계|총합계|계|합|총)$")
SUBTOTAL_RE = re.compile(r"^소계$")
NUM_RE = re.compile(r"^[△▲▽-]?\d{1,3}(?:,\d{3})+(?:\.\d+)?$|^[△▲▽-]?\d+(?:\.\d+)?$")
SKIP_HEAD_RE = re.compile(r"%|율|률|비율|평균|단가|비중|순위|연번|번호|연도|년도|점수|배점|기간|일자|날짜")
UNITS = "건|명|곳|개소|개|가구|세대|대|회|원|천원|만원|백만원|억원|조원|톤|㎡|㎢|km|m|%p|%|점|일|개월|년|시간"
NUMW = r"[\d,]+(?:\.\d+)?"
SNUM = r"(?<![\d,.])[△▲▽-]?[\d,]+(?:\.\d+)?"  # 부호가 붙은 수(앞 글자가 숫자가 아닐 때)


def _num(s):
    """'1,234'·'△40'·'12.5' → 수(△·▲는 음수가 아님 — △ 감소 표시는 음수), 아니면 None."""
    t = re.sub(r"[\s⎵⍽]", "", s or "")
    if not t or not NUM_RE.match(t):
        return None
    neg = t[0] in "△▽-"
    v = float(t.lstrip("△▲▽-").replace(",", ""))
    return -v if neg else v


def _near(got, want, d):
    """쓴 값 want(소수 d자리)가 got을 반올림하거나 버린 값인가."""
    k = 10 ** d
    return any(abs(x - want) < 1e-9 for x in (round(got * k) / k, int(got * k) / k, round(abs(got) * k) / k * (1 if got >= 0 else -1)))


def _dec(*vals):
    return max((len(v.split(".")[1]) if "." in v else 0) for v in vals)


def _cell_text(tc):
    return " ".join(para_text(cp) for cp in cell_paras(tc)).replace("⎵", " ").replace("⍽", " ").strip()


YEAR_RE = re.compile(r"^(?:[’']?\d{2}년?|(?:19|20)\d{2}년?(?:도)?)$")  # 머리 줄의 연도(’25·2025년)는 수가 아님
UNIT_IN_RE = re.compile(rf"\(\s*(?:단위\s*:?\s*)?({UNITS})\s*\)")


def _matrix(tbl):
    """(값 칸 m, 머리 글 h, 머리 칸 표시 hd): 합친 칸은 m에서 빈칸(값을 두 번 세지 않게), h에서는 합친 글을 물려받음
    (‘평균’ 아래 ‘남·여’ 두 열이 모두 평균으로 — Codex 검토 2026-11-15)."""
    grid = table_grid(tbl)
    rows = max((g[0] + g[2] for g in grid), default=0)
    cols = max((g[1] + g[3] for g in grid), default=0)
    m = [[None] * cols for _ in range(rows)]
    h = [[""] * cols for _ in range(rows)]
    hd = [False] * rows
    for r, c, rs, cs, tc in grid:
        txt = _cell_text(tc)
        m[r][c] = txt
        if tc.get("header") == "1":
            hd[r] = True
        for i in range(r, r + rs):
            for j in range(c, c + cs):
                h[i][j] = txt
                if (i, j) != (r, c):
                    m[i][j] = ""
    return m, h, hd


def _fmt(v):
    return f"{v:,.0f}" if abs(v - round(v)) < 1e-9 else f"{v:,.2f}".rstrip("0").rstrip(".")


def _label(row):
    return re.sub(r"\s", "", next((x for x in row if x), "") or "")


def _is_total(lab):
    return bool(TOTAL_RE.match(lab) or SUBTOTAL_RE.match(lab))


def _datum(x):
    """값으로 칠 수인가(머리 줄의 연도는 아님)."""
    return _num(x) is not None and not YEAR_RE.match(re.sub(r"\s", "", x or ""))


def _head_rows(m, hd):
    """머리 줄 수: 한글 머리 칸 표시가 있는 줄, 그다음은 값으로 칠 수가 없는 줄까지."""
    k = 0
    while k < len(m) and (hd[k] or not any(_datum(x) for x in m[k][1:])):
        k += 1
    return k


def _sum_check(cells, tv_text):
    """합해 볼 칸 글 목록과 계 칸 글 → (합, 쓴 계, 소수 자리, 칸 수) 또는 None(수가 아닌 칸이 섞임)."""
    tv = _num(tv_text)
    if tv is None or any(v and _num(v) is None and v not in ("-", "–") for v in cells):
        return None
    nums = [_num(v) or 0 for v in cells if v]
    if not nums:
        return None
    d = _dec((tv_text or "").replace(",", ""), *[v.replace(",", "") for v in cells if v])
    return sum(nums), tv, d, len(nums)


def check_tables(tables):
    notes = []
    for tbl, name in tables:
        m, h, hd = _matrix(tbl)
        if len(m) < 3 or len(m[0]) < 2:
            continue
        head = _head_rows(m, hd)
        heads = [" ".join(dict.fromkeys(h[i][j] for i in range(head) if h[i][j])).strip() for j in range(len(m[0]))]
        data = list(range(head, len(m)))
        if not data:
            continue
        top = _is_total(_label(m[data[0]]))  # 계·소계가 묶음 위에 오는 표(계 → 항목들)
        # ① 계·소계 줄
        for t in data:
            lab = _label(m[t])
            if not _is_total(lab):
                continue
            sub = bool(SUBTOTAL_RE.match(lab))
            if top:  # 아래 줄들: 소계는 다음 계·소계 앞까지, 계는 아래 상세 줄 모두(소계 줄은 빼고)
                parts = []
                for k in range(t + 1, len(m)):
                    if _is_total(_label(m[k])):
                        if sub or TOTAL_RE.match(_label(m[k])):
                            break
                        continue
                    parts.append(k)
            else:
                start = head
                if sub:
                    for k in range(t - 1, head - 1, -1):
                        if SUBTOTAL_RE.match(_label(m[k])):
                            start = k + 1
                            break
                parts = [k for k in range(start, t) if not _is_total(_label(m[k]))]
            if not parts:
                continue
            for j in range(1, len(m[0])):
                if SKIP_HEAD_RE.search(heads[j] or ""):
                    continue
                got = _sum_check([m[k][j] for k in parts], m[t][j])
                if not got:
                    continue
                s, tv, d, n = got
                if abs(s - tv) > 0.5 * 10 ** -d + 1e-9:
                    col = (heads[j] or f"{j + 1}번째 열")[:12]
                    where = "아래" if top else "위"
                    notes.append(f"표 ‘{name}’ {lab} 줄 ‘{col}’ 칸: {lab} {m[t][j]} ≠ {where} 칸의 합 {_fmt(s)}"
                                 + (f"({n}칸)" if n > 1 else "") + " — 줄이 빠졌으면 ‘…’ 줄로 줄였다고 밝히거나 숫자를 맞추세요")
        # ① 계 열(머리 칸이 계·합계): 같은 단위의 나머지 수 칸의 합
        for j in range(1, len(m[0])):
            if not TOTAL_RE.match(re.sub(r"\s|\(.*?\)", "", heads[j] or "")):
                continue
            unit = UNIT_IN_RE.search(heads[j] or "")

            def unit_of(k):
                u = UNIT_IN_RE.search(heads[k] or "")
                return u.group(1) if u else None

            others = [k for k in range(1, len(m[0])) if k != j and not SKIP_HEAD_RE.search(heads[k] or "")
                      and unit_of(k) == (unit.group(1) if unit else None)]
            if len(others) < 2:
                continue
            ok_rows, bad, seen = 0, [], 0
            for i in data:
                got = _sum_check([m[i][k] for k in others], m[i][j])
                if not got:
                    continue
                seen += 1
                s, tv, d, _ = got
                if abs(s - tv) <= 0.5 * 10 ** -d + 1e-9:
                    ok_rows += bool(tv)
                else:
                    bad.append((i, m[i][j], s))
            if bad and (ok_rows or len(bad) == seen):
                for i, tv, s in bad[:3]:
                    notes.append(f"표 ‘{name}’ ‘{_label(m[i])[:10]}’ 줄: {heads[j][:8]} {tv} ≠ 옆 칸의 합 {_fmt(s)}")
    return notes


RATIO_OF_RE = re.compile(rf"({NUMW})\s*({UNITS})?\s*중\s*(?:[가-힣·]+\s+){{0,3}}?({NUMW})\s*({UNITS})?\s*\(\s*({NUMW})\s*%\s*\)")
ARROW_RE = re.compile(rf"({SNUM})\s*({UNITS})?\s*(?:→|->|⇒|에서)\s*({SNUM})\s*({UNITS})?\s*(?:로\s*)?[(（]\s*([+＋△▲▽-]?)\s*({NUMW})\s*(%p|%|{UNITS})?\s*(증가|감소|상승|하락|늘|줄)?")


def check_text(texts):
    notes = []
    for t in texts:
        s = t.replace("⎵", " ").replace("⍽", " ")
        for m in RATIO_OF_RE.finditer(s):
            whole, part, pct = _num(m.group(1)), _num(m.group(3)), m.group(5)
            if not whole or part is None or part > whole:
                continue
            d = _dec(pct)
            got = part / whole * 100
            if _num(pct) is None or not _near(got, _num(pct), d):  # 반올림·버림 모두 허용
                notes.append(f"비율: ‘{m.group(0).strip()}’ — {m.group(3)}/{m.group(1)}은 {got:.{max(d, 1)}f}%")
        for m in ARROW_RE.finditer(s):
            a, b, sign, n, unit, word = _num(m.group(1)), _num(m.group(3)), m.group(5), m.group(6), m.group(7) or "", m.group(8) or ""
            nv = _num(n)
            if a is None or b is None or nv is None:
                continue
            down = (sign != "" and sign in "△▽-") or word in ("감소", "하락", "줄")
            signed = bool(sign or word)  # 부호·증감 낱말이 있으면 방향까지 봄(120명 → 150명(△30명)은 틀림)
            want = -nv if down else nv
            ua, ub = m.group(2) or "", m.group(4) or ""
            if ua and ub and ua != ub:  # 단위가 다르면(1억원 → 120백만원) 셈하지 않음
                continue
            if unit == "%" and "%" not in (ua + ub):  # 증감률
                if not a:
                    continue
                got, d = (b - a) / a * 100, _dec(n)
                if not _near(got, want, d) and (signed or not _near(abs(got), nv, d)):
                    notes.append(f"증감률: ‘{m.group(0).strip()}’ — ({m.group(3)}−{m.group(1)})/{m.group(1)}은 {got:+.{max(d, 1)}f}%")
            else:  # 증감(차)
                got, d = b - a, _dec(m.group(1).replace(",", ""), m.group(3).replace(",", ""), n.replace(",", ""))
                if abs(got - want) > 0.5 * 10 ** -d + 1e-9 and (signed or abs(abs(got) - nv) > 0.5 * 10 ** -d + 1e-9):
                    notes.append(f"증감: ‘{m.group(0).strip()}’ — {m.group(3)}−{m.group(1)}은 {_fmt(got)}")
    return notes


STATED_RE = re.compile(rf"(?:총|계|합계|모두|전체|전부)\s*({NUMW})\s*({UNITS})")
UNIT_HEAD_RE = re.compile(rf"\(\s*({UNITS})\s*\)")


def check_same(texts, tables):
    """글에 쓴 '총·계 N단위'가 같은 단위 표 계와 다르면 — 그 단위의 표 계가 한 곳뿐일 때만(표가 여럿이면 어느 표를 말하는지
    알 수 없어 지적하지 않음, Codex 검토 2026-11-15). 대상이 다를 수 있어 '같은 대상이면'으로 묻는다."""
    totals = {}
    for tbl, _ in tables:
        m, h, hd = _matrix(tbl)
        if len(m) < 3:
            continue
        head = _head_rows(m, hd)
        for row in m[head:]:
            if not TOTAL_RE.match(_label(row)):
                continue
            for j, cell in enumerate(row[1:], 1):
                v = _num(cell)
                u = UNIT_HEAD_RE.search(" ".join(dict.fromkeys(h[i][j] for i in range(head) if h[i][j])))
                if v is not None and u:
                    totals.setdefault(u.group(1), []).append(v)
    notes = []
    for t in texts:
        for mm in STATED_RE.finditer(t.replace("⎵", " ")):
            v, u = _num(mm.group(1)), mm.group(2)
            if v is not None and len(totals.get(u, [])) == 1 and v != totals[u][0]:
                notes.append(f"같은 수치: 글의 ‘{mm.group(0)}’ ≠ 표의 계 {_fmt(totals[u][0])}{u} — 같은 대상이면 맞추세요")
    return notes


SPELL = [  # (틀린 꼴, 바른 꼴) — 거의 늘 틀리는 것만(문맥 따라 맞을 수 있는 것은 넣지 않음)
    (r"되요", "돼요"), (r"됬", "됐"), (r"(?<![가-힣])몇\s?일(?!째)", "며칠"), (r"금새", "금세"), (r"왠만", "웬만"),
    (r"웬지", "왠지"), (r"어의없", "어이없"), (r"오랫만", "오랜만"), (r"역활", "역할"), (r"희안", "희한"),
    (r"설겆이", "설거지"), (r"일일히", "일일이"), (r"깨끗히", "깨끗이"), (r"틈틈히", "틈틈이"), (r"곰곰히", "곰곰이"),
    (r"번번히", "번번이"), (r"갯수", "개수"), (r"댓가", "대가"), (r"촛점", "초점"), (r"할께", "할게"), (r"뵈요", "봬요"),
    (r"설레임", "설렘"), (r"삼가하", "삼가"), (r"읍니다", "습니다"), (r"므로써", "ㅁ으로써"), (r"할려고", "하려고"),
    (r"있슴", "있음"), (r"없슴", "없음"), (r"했슴", "했음"), (r"궂이", "굳이"), (r"어떻해", "어떻게"), (r"익숙치", "익숙지"),
    (r"통채로", "통째로"), (r"알맞는", "알맞은"), (r"걸맞는", "걸맞은"), (r"(?<![가-힣])제작년(?![도월])", "재작년"), (r"내노라", "내로라"),
    (r"일찌기", "일찍이"), (r"더우기", "더욱이"), (r"끼여들", "끼어들"), (r"헤메", "헤매"), (r"애시당초", "애당초"),
    (r"가르키", "가리키"), (r"잠궈", "잠가"), (r"담궈", "담가"), (r"개구장이", "개구쟁이"),
    (r"(할|될|볼|갈|쓸|줄|알|올|살|팔|만들|받을|줄일|늘릴)수\s?(있|없)", r"\1 수 \2"), (r"것같", "것 같"),
    (r"않되", "안 되"),
]


def check_spelling(texts):
    notes, seen = [], set()
    for t in texts:
        s = t.replace("⎵", " ").replace("⍽", " ")
        for pat, fix in SPELL:
            for m in re.finditer(pat, s):
                wrong = m.group(0)
                right = m.expand(fix) if "\\" in fix else fix
                key = (wrong, right)
                if key in seen:
                    continue
                seen.add(key)
                a = max(0, m.start() - 8)
                notes.append(f"맞춤법: ‘{wrong}’ → ‘{right}’ (…{s[a:m.end() + 8].strip()}…)")
    return notes


def proofread(pkg):
    """문서 전체(모든 구역)의 수치·맞춤법 확인 목록(알림 글)."""
    texts, tables = [], []

    def walk(p):
        tbls = para_tables(p)
        if not tbls:
            t = para_text(p)
            if t.strip():
                texts.append(t)
            return
        for tbl in tbls:
            g = table_grid(tbl)
            first = next((_cell_text(tc) for *_, tc in g if _cell_text(tc)), "")
            if len(g) > 1:
                tables.append((tbl, first[:12]))
            for *_, tc in g:
                for cp in cell_paras(tc):
                    walk(cp)

    for name in pkg.sections():
        for p in pkg.xml(name):
            if p.tag == T("hp:p"):
                walk(p)
    notes = check_tables(tables) + check_text(texts) + check_same(texts, tables) + check_spelling(texts)
    return list(dict.fromkeys(notes))


def print_report(pkg):
    notes = proofread(pkg)
    print("## 수치·맞춤법 확인(고치지 않음 — 결과 파일과 함께 사용자에게 그대로 알릴 것, 맞으면 ‘확인함’)")
    for n in notes[:20]:
        print(f" - {n}")
    if len(notes) > 20:
        print(f" - 그 밖에 {len(notes) - 20}곳")
    if not notes:
        print(" - 걸린 곳 없음(표 합계·비율·증감·맞춤법 목록 기준 — 원자료 대조는 글을 쓴 쪽이)")
    return notes
