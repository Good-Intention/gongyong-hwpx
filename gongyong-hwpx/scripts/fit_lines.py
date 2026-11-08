# -*- coding: utf-8 -*-
"""줄 맞춤(Fitter의 일부): 자간으로 끝 줄 당기기·빈칸 큰 줄 넓히기·화살표·연결어·끝 줄 내리기."""
from fit_base import *  # noqa: F401,F403 — 상수·공통 함수(HWPUNIT_PER_MM, T, re, copy …)


class LineFit:
    # ------------------------------------------------------------ 줄 맞춤
    def checked(self, p):
        """자간을 바꿔도 되는 문단인가: 한글로 줄 바꿈을 맞대어 본 글꼴(휴먼명조·중고딕)만 쓴 문단.
        다른 글꼴(HY헤드라인M 등)은 어림 오차가 2%를 넘은 적이 있어(2026-10-31 실측) 자간을 건드리지 않는다."""
        faces = {self.st.char.get(r.get("charPrIDRef"), {}).get("font") for r in para_runs(p)
                 if r.find(T("hp:t")) is not None and run_text(r).strip()}
        return bool(faces) and all(self.lay.m.checked(f) for f in faces)

    def set_delta(self, p, d):
        """문단 내용 조각의 자간을 d만큼 바꾼다. 머리 기호·괄호 이름표 조각은 그대로 둔다(줄 맞춤 유지)."""
        head = head_length(para_text(p))
        pos = 0
        for r in para_runs(p):
            if r.find(T("hp:tbl")) is not None:
                continue
            start = pos
            pos += len(run_text(r))
            if r.find(T("hp:t")) is None or start < head:
                continue
            cid = r.get("charPrIDRef")
            base = self.st.char.get(cid, {}).get("spacing", 0)
            new = spacing_after(base, d, FLOOR)
            if new != base:
                r.set("charPrIDRef", self.b.hedit.char_spacing(cid, new))

    def fit_lines(self):
        done = []
        for p, box_w in self.text_boxes():
            if not self.checked(p):
                continue
            chs, lines = self.lay.para_lines(p, box_w)
            if len(lines) < 2:
                continue
            s, e, used, _ = lines[-1]
            full = lines[0][3]  # 첫 줄 폭 기준(이름표 뒤로 내어쓴 둘째 줄은 좁아 비율이 커 보임)
            words = len("".join(c[0] for c in chs[s:e]).split())
            if used > full * SHORT_LAST and words > 1:
                continue
            for d in range(-1, FLOOR - 1, -1):
                _, l2 = self.lay.para_lines(p, box_w, delta=d, shrink=SLACK, floor=FLOOR)
                if len(l2) < len(lines):
                    self.set_delta(p, d)
                    done.append(d)
                    break
        if done:
            self.notes.append(f"마지막 줄에 짧은 낱말만 남던 문단 {len(done)}개는 자간을 조금 줄여"
                              f"({max(done)}~{min(done)}%) 한 줄을 줄였습니다.")
        self.widen_sparse()

    def _content_spacing(self, p):
        """문단 내용(머리 뒤) 글자 수가 가장 많은 자간 — 줄 맞춤이 이미 바꾼 값을 알아보는 기준."""
        head = head_length(para_text(p))
        count, pos = {}, 0
        for r in para_runs(p):
            t = run_text(r)
            if r.find(T("hp:t")) is not None and pos + len(t) > head:
                sp = self.st.char.get(r.get("charPrIDRef"), {}).get("spacing", 0)
                count[sp] = count.get(sp, 0) + len(t) - max(0, head - pos)
            pos += len(t)
        return max(count, key=count.get) if count else 0

    def widen_sparse(self):
        """다음 낱말이 넘어가 양쪽 정렬로 빈칸이 벌어질 줄(쓴 폭 < 97%)이 있으면
        1) 자간을 줄여(-18%까지) 다음 낱말을 그 줄로 당겨 본다(사용자 수정본 규칙: 넘친 글자는 자간을 줄여 한 줄에).
        2) 그래도 안 되면 줄 바꿈 자리는 그대로 두고 자간을 늘려(+5%까지) 덜 벌어지게 한다."""
        pulled, widened = [], []
        for p, box_w in self.text_boxes():
            if not self.checked(p):
                continue
            chs, lines = self.lay.para_lines(p, box_w)
            if len(lines) < 2:
                continue

            def sparse(ls, limit):
                # 강제 줄 바꿈(push_down·연결어 내리기)으로 끝나는 줄은 한글이 벌리지 않으므로 성긴 줄로 치지 않는다
                # (만든 문서를 다시 다듬을 때 그 줄 때문에 자간을 늘리지 않게 — 되풀이해도 같게, 2026-11-04)
                return any(used / avail < limit and "\n" not in (chs[e - 1][0], chs[e][0] if e < len(chs) else "")
                           for _, e, used, avail in ls[:-1])

            def orphan(cs, ls):
                """마지막 줄에 짧은 낱말 하나만 남는가."""
                s, e, used, _ = ls[-1]
                return (len(ls) > 1 and used < ls[0][3] * SHORT_LAST
                        and len("".join(c[0] for c in cs[s:e]).split()) <= 1)

            if not sparse(lines, PULL):
                continue
            done = False
            was_orphan = orphan(chs, lines)
            for d in range(-1, FLOOR - 1, -1):
                c2, l2 = self.lay.para_lines(p, box_w, delta=d, shrink=SLACK, floor=FLOOR)
                if orphan(c2, l2) and not was_orphan:
                    continue  # 당기면 마지막 줄에 외톨이 낱말이 생김 → 이 값은 쓰지 않음
                if len(l2) <= len(lines) and not sparse(l2, PULL):
                    self.set_delta(p, d)
                    pulled.append(d)
                    done = True
                    break
            if done or not sparse(lines, SPARSE):
                continue
            starts = [s for s, _, _, _ in lines]
            best = 0
            # +WIDEN_MAX는 절대 상한 — 이미 늘린 문단을 다시 맞출 때 더 늘리지 않게(되풀이해도 같게, 2026-11-04)
            for d in range(1, WIDEN_MAX - self._content_spacing(p) + 1):
                _, l2 = self.lay.para_lines(p, box_w, delta=d, shrink=SLACK, floor=FLOOR)
                if [s for s, _, _, _ in l2] != starts:
                    break
                best = d
            if best:
                self.set_delta(p, best)
                widened.append(best)
        if pulled:
            self.notes.append(f"다음 낱말이 넘어가 빈칸이 크게 벌어질 문단 {len(pulled)}개는 자간을 줄여"
                              f"({max(pulled)}~{min(pulled)}%) 그 낱말을 앞줄로 당겼습니다.")
        if widened:
            self.notes.append(f"당길 수 없는 문단 {len(widened)}개는 자간을 조금 늘려(+{min(widened)}~+{max(widened)}%) "
                              "빈칸이 덜 벌어지게 했습니다.")
        loose = []
        for p, box_w in self.text_boxes():
            if self.st.para.get(p.get("paraPrIDRef"), {}).get("align") not in ("JUSTIFY", "DISTRIBUTE"):
                continue  # 가운데·왼쪽 정렬 줄은 낱말 사이가 벌어지지 않음
            _, lines = self.lay.para_lines(p, box_w)
            if any(used / avail < LOOSE for _, _, used, avail in lines[:-1]):
                text = para_text(p)
                loose.append(text[head_length(text):].replace("⎵", " ").strip()[:14])
        if loose:
            self.notes.append(f"그래도 빈칸이 크게 벌어지는 줄이 남은 문단 {len(loose)}개 — 긴 낱말이 다음 줄로 넘어감. "
                              "낱말을 줄이거나 순서를 바꾸거나 두 줄로 나누면 좋아집니다: "
                              + ", ".join(f"‘{t}…’" for t in loose))
        self.cut_hints = []
        self.arrow_breaks()
        if getattr(self, "push", True):
            self.push_down()
        self.report_cut_hints()
        # 내리기로도 못 고친(끝 줄 바로 위에 나눌 빈칸이 없는 등) 문단은 글을 고쳐야 하므로 '고쳐야 함'으로 알린다
        short = []
        for p, box_w in self.text_boxes():
            if self.st.para.get(p.get("paraPrIDRef"), {}).get("align") not in ("JUSTIFY", "DISTRIBUTE", "LEFT"):
                continue
            chs, lines = self.lay.para_lines(p, box_w)
            if len(lines) < 2:
                continue
            s, e, used, _ = lines[-1]
            if used < lines[0][3] * SHORT_LAST and len("".join(c[0] for c in chs[s:e]).split()) <= 2:
                text = para_text(p)
                short.append(text[head_length(text):].replace("⎵", " ").strip()[:14])
        if short:
            self.notes.append(f"끝 줄에 한두 낱말만 남은 문단 {len(short)}개 — 자간으로도 당기지 못했습니다. 글을 조금 줄이거나 "
                              "낱말 순서를 바꾸면 한 줄로 들어갑니다: " + ", ".join(f"‘{t}…’" for t in short))

    def _cut_hint(self, p, box_w, lines):
        """두 줄 문단이 몇 자만 줄이면(자간 -18%까지 줄인 상태에서) 한 줄에 들어가는지 재어, 낱말 하나(CUT_MAX자 안)로
        되면 '한 줄 줄이기 후보'로 모은다 — 줄을 내리면 윗줄이 휑해지므로 없어도 되는 낱말 하나를 빼는 편이 낫다
        (사용자 원칙 2026-11-01: '인간은 컨텍스트로 이해할 수 있다'). 낱말을 고르는 것은 글을 쓰는 쪽(Claude)이 한다."""
        if len(lines) != 2:
            return
        chs = self.lay.chars(p, delta=FLOOR, floor=FLOOR)
        head = head_length(para_text(p))
        total = sum(c[1] for c in chs if c[0] != NL)
        need = total - lines[0][3] * SLACK
        body = [c[1] for c in chs[head:] if c[0] not in (" ", NL, "⎵", "⍽")]
        if need <= 0 or not body:
            return
        n = int(need / (sum(body) / len(body))) + 1
        if n <= CUT_MAX:
            body_text = split_marker(para_text(p))[2] or para_text(p)
            self.cut_hints.append((re.sub(r"\s+", " ", body_text.replace("⎵", " ").replace("⍽", " ")).strip()[:22], n))

    def report_cut_hints(self):
        if self.cut_hints:
            self.notes.append(f"한 줄 줄이기 후보 {len(self.cut_hints)}개 — 없어도 되는 낱말 하나(조사·꾸밈말·겹친 말)를 빼면 "
                              "한 줄에 들어갑니다(뜻·숫자·이름은 그대로, 지금은 줄을 내려 둠): "
                              + ", ".join(f"‘{t}…’(약 {n}자)" for t, n in self.cut_hints))

    def arrow_breaks(self):
        """화살표(⇒ → ➜)가 든 두 줄 이상 문단: 글은 한 줄을 채우고 내려온다(사용자 원칙 2026-11-04 — 화살표부터 통째로
        다음 줄로 내리던 2026-11-01 규칙은 그만둠, 줄 끝에 남은 화살표는 connector_breaks가 다음 줄 첫머리로).
        화살표 뒤 내용이 둘째 줄로 이어지면 둘째 줄부터를 화살표 뒤 첫 글자 밑에 맞춘다
        (사용자 수정본·결정 2026-11-01 — 화살표가 첫 줄 앞쪽 ARROW_HANG_AT 안에 있고 줄 수가 늘지 않을 때).
        머리 기호·이름표 안의 화살표는 보지 않는다."""
        done = hung = 0
        for p, box_w in self.text_boxes():
            if not self.checked(p):
                continue
            if self.st.para.get(p.get("paraPrIDRef"), {}).get("align") not in ("JUSTIFY", "DISTRIBUTE", "LEFT"):
                continue
            chs, lines = self.lay.para_lines(p, box_w)
            if len(lines) < 2 or any(c[0] == "\n" for c in chs):
                continue
            s1, e1, _, _ = lines[0]
            head = head_length(para_text(p))
            depth, inside = 0, set()  # 괄호 안 글자 자리 — '(’25년 316대 → ’26년 336대)'처럼 괄호 안 화살표는 범위·변화 표시라
            for i, c in enumerate(chs):  # 글의 갈래가 아니다(둘째 줄을 그 뒤 82mm에 맞추던 것, 사용자 작업 2026-11-06)
                if c[0] in "(（[〔":
                    depth += 1
                elif c[0] in ")）]〕":
                    depth = max(0, depth - 1)
                elif depth:
                    inside.add(i)
            arrows = [i for i in range(s1, e1) if chs[i][0] in ARROWS and i > head and i not in inside]
            if not arrows:
                continue
            a = arrows[-1]  # 첫 줄의 마지막 화살표 — 그 뒤 내용이 둘째 줄로 갈라짐
            if a == 0 or chs[a - 1][0] != " ":
                continue
            saved = [(r, r.get("charPrIDRef"), copy.deepcopy(list(r))) for r in para_runs(p)]

            def restore(saved=saved):
                for r, cid, kids in saved:
                    for ch in list(r):
                        r.remove(ch)
                    for k in kids:
                        r.append(k)
                    r.set("charPrIDRef", cid)

            # 글 문단은 한 줄을 채우고 내려온다(사용자 원칙 2026-11-04 — '표 상자 도표야 균형을 맞추더라도 글로 쓸 때는
            # 한 줄을 채우고 내려오는 게 좋다'): 화살표부터 통째로 다음 줄로 내리던 것(2026-11-01)은 하지 않는다.
            # 줄 끝에 화살표만 남으면 connector_breaks가 그 화살표를 다음 줄 첫머리로 내린다.
            hung += self._arrow_hang(p, box_w, a, len(lines), restore)
        if done:
            self.notes.append(f"화살표 뒤 내용이 줄 끝에서 갈라지던 문단 {done}개는 화살표부터 끝까지를 다음 줄로 내렸습니다.")
        if hung:
            self.notes.append(f"화살표 뒤 내용이 다음 줄로 이어지는 문단 {hung}개는 둘째 줄부터를 화살표 뒤 첫 글자 밑에 맞췄습니다.")
        self.connector_breaks()

    def connector_breaks(self):
        """본문 문단의 줄 끝에 연결어·연결 기호('+'·'및'·'또는'·'='·'×')가 남으면 그 앞에서 줄을 바꿔 다음 줄 첫머리로
        내린다(사용자 원칙 2026-11-01: '+나 및 같은 연결어·연결 기호는 아래로 내리는 게 더 이해하기 쉬움'). 줄 수가 늘면
        그대로 둔다. 한글은 줄 바꿈 바로 앞 줄을 벌리지 않으므로 위 줄은 보통 간격으로 조금 짧게 끝난다."""
        done = 0
        for p, box_w in self.text_boxes():
            if self.st.para.get(p.get("paraPrIDRef"), {}).get("align") not in ("JUSTIFY", "DISTRIBUTE", "LEFT"):
                continue
            for _ in range(4):
                chs, lines = self.lay.para_lines(p, box_w)
                if len(lines) < 2:
                    break
                hit = None
                for s0, e0, _, _ in lines[:-1]:
                    seg = "".join(c[0] for c in chs[s0:e0]).rstrip()
                    words = seg.split(" ")
                    if len(words) >= 3 and words[-1] in CONNECTORS:
                        hit = s0 + len(seg) - len(words[-1])  # 연결어 첫 글자 자리
                        break
                if hit is None or chs[hit - 1][0] != " ":
                    break
                saved = [(r, r.get("charPrIDRef"), copy.deepcopy(list(r))) for r in para_runs(p)]
                self._insert_breaks(p, [(0, 0, "space", hit)])
                _, l2 = self.lay.para_lines(p, box_w)
                if len(l2) > len(lines):
                    for r, cid, kids in saved:
                        for ch in list(r):
                            r.remove(ch)
                        for k in kids:
                            r.append(k)
                        r.set("charPrIDRef", cid)
                    break
                done += 1
        if done:
            self.notes.append(f"줄 끝에 남던 연결어·연결 기호(+·및·= 등) {done}곳은 다음 줄 첫머리로 내렸습니다.")

    def _arrow_hang(self, p, box_w, a, n_lines, restore):
        """화살표(글자 위치 a) 뒤 첫 글자 밑에 둘째 줄부터를 맞춘다: 그 앞 보통 빈칸은 고정폭 빈칸으로(첫 줄이 양쪽 정렬로
        늘어나도 화살표 뒤 글자 위치가 변하지 않게 — 쌍점·이름표 맞추기와 같은 방법), 내어쓰기 = 그 글자까지의 폭.
        화살표가 첫 줄 앞쪽 ARROW_HANG_AT 안에 있고 줄 수가 늘지 않을 때만. 맞췄으면 1."""
        chs = self.lay.chars(p)
        k = a + 1
        while k < len(chs) and chs[k][0] in " ⎵⍽":
            k += 1
        if k >= len(chs) or sum(c[1] for c in chs[:k]) > box_w * ARROW_HANG_AT:
            return 0
        pid0 = p.get("paraPrIDRef")
        pos = 0
        for r in para_runs(p):
            t = run_text(r)
            start, pos = pos, pos + len(t)
            if start >= k:
                break
            cut = min(len(t), k - start)
            new = t[:cut].replace(" ", FW * self.b._fw_per_space(r)) + t[cut:]
            if new != t and len(r) == 1:
                set_run_text(r, new, self.b.tab_proto)
        # 내어쓰기 = 맞춤 기준으로 고른 화살표 a 뒤 첫 글자까지의 폭(옛 판은 문단의 마지막 화살표로 재어, 괄호 안 화살표 등
        # 기준과 다른 화살표에 맞출 수 있었음). 빈칸이 고정폭 빈칸 여럿으로 바뀌어 글자 번호가 밀렸으니 a번째 화살표를 다시 찾는다
        nth = sum(1 for c in chs[:a + 1] if c[0] in ARROWS)
        text = para_text(p)
        seen, k2 = 0, 0
        for i, ch in enumerate(text):
            if ch in ARROWS:
                seen += 1
                if seen == nth:
                    k2 = i + 1
                    break
        while k2 < len(text) and text[k2] in " ⎵⍽":
            k2 += 1
        hang = sum(c[1] for c in self.lay.chars(p)[:k2])
        p.set("paraPrIDRef", self.b.hedit.para_hang(pid0, hang))
        _, l2 = self.lay.para_lines(p, box_w)
        if len(l2) > n_lines:
            restore()
            p.set("paraPrIDRef", pid0)
            return 0
        return 1

    def push_down(self):
        """끝 줄에 한두 낱말(두서너 자)만 남은 문단: 자간으로 올리기(fit_lines·widen_sparse)가 안 되면, 바로 위 줄의 낱말 경계에
        줄 바꿈을 넣어 끝 줄이 PUSH_MIN~PUSH_MAX자가 되게 '시원하게 내려' 두 줄 균형을 맞춘다(사용자 원칙 2026-11-01:
        '한 단어가 내려올 때는 올려 보고, 글자가 겹칠 것 같으면 7~10자 정도 내려서 균형'). 한글은 양쪽 정렬 문단이라도
        줄 바꿈 바로 앞 줄은 벌리지 않는다(실측) — 위 줄은 보통 간격으로 조금 짧게 끝난다.
        머리 기호·이름표 뒤 고정폭 빈칸·묶음 빈칸에서는 나누지 않는다(둘째 줄은 문단 내어쓰기대로 이름표 뒤 글에 맞춤)."""
        done = []
        for p, box_w in self.text_boxes():
            if not self.checked(p):
                continue
            if self.st.para.get(p.get("paraPrIDRef"), {}).get("align") not in ("JUSTIFY", "DISTRIBUTE", "LEFT"):
                continue
            chs, lines = self.lay.para_lines(p, box_w)
            if len(lines) < 2:
                continue
            s, e, used, _ = lines[-1]
            last = "".join(c[0] for c in chs[s:e])
            if not (used < lines[0][3] * SHORT_LAST and len(last.split()) <= 2):
                continue
            ps, pe, _, _ = lines[-2]
            head = head_length(para_text(p))
            nonspace = len(last.replace(" ", "").replace("⎵", ""))
            best = None
            for i in range(pe - 1, ps, -1):  # 위 줄 안의 보통 빈칸 자리(뒤에서부터)
                if chs[i][0] != " " or i <= head or chs[i - 1][0] in (" ", "⎵", "⍽"):
                    continue
                moved = "".join(c[0] for c in chs[i + 1:pe]).replace(" ", "").replace("⎵", "")
                n = len(moved) + nonspace
                if n > PUSH_MAX + 4:
                    break
                score = 0 if PUSH_MIN <= n <= PUSH_MAX else min(abs(n - PUSH_MIN), abs(n - PUSH_MAX))
                if best is None or score < best[0]:
                    best = (score, i + 1, n)
            if best is None or best[0] > 3:
                continue
            idx = best[1]
            self._cut_hint(p, box_w, lines)
            saved = [(r, r.get("charPrIDRef"), copy.deepcopy(list(r))) for r in para_runs(p)]
            self._insert_breaks(p, [(0, 0, "space", idx)])
            _, l2 = self.lay.para_lines(p, box_w)
            if len(l2) != len(lines):  # 줄 수가 바뀌면(위 줄이 넘침 등) 되돌린다
                for r, cid, kids in saved:
                    for ch in list(r):
                        r.remove(ch)
                    for k in kids:
                        r.append(k)
                    r.set("charPrIDRef", cid)
                continue
            done.append(best[2])
        if done:
            self.notes.append(f"자간으로 올릴 수 없던 짧은 끝 줄(한두 낱말) {len(done)}곳은 위 줄 낱말을 함께 내려 "
                              f"끝 줄을 {min(done)}~{max(done)}자로 균형을 맞췄습니다(줄 바꿈 — 위 줄은 조금 짧게 끝남).")
