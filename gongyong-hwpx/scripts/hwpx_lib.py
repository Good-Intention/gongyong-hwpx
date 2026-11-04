# -*- coding: utf-8 -*-
"""HWPX(한글 문서) 파일을 열고 읽고 저장하는 공용 함수.

- HWPX는 ZIP 안에 XML 파일이 든 묶음이다.
  - 본문: Contents/section0.xml (구역이 여럿이면 section1.xml …)
  - 글자 모양·문단 모양·테두리 목록: Contents/header.xml
- 이 스킬은 견본(양식)의 서식 번호를 그대로 다시 쓰고, 새 서식을 만들지 않는다.
  그래서 결과 문서의 모양이 견본과 같아진다.
"""
import copy
import random
import re
import struct
import zipfile
import zlib

try:
    from lxml import etree
except ImportError:  # pragma: no cover
    raise SystemExit("lxml 부품이 필요합니다. 먼저 `pip install lxml`을 실행하세요.")

NS = {
    "hp": "http://www.hancom.co.kr/hwpml/2011/paragraph",
    "hs": "http://www.hancom.co.kr/hwpml/2011/section",
    "hh": "http://www.hancom.co.kr/hwpml/2011/head",
    "hc": "http://www.hancom.co.kr/hwpml/2011/core",
    "ha": "http://www.hancom.co.kr/hwpml/2011/app",
    "opf": "http://www.idpf.org/2007/opf/",
}


def T(name):
    """'hp:p' 같은 이름을 lxml 태그('{주소}p')로 바꾼다."""
    prefix, local = name.split(":")
    return "{%s}%s" % (NS[prefix], local)


def local(el):
    return etree.QName(el).localname


XML_DECL = b'<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>'
HWPUNIT_PER_MM = 7200 / 25.4  # 1인치 = 7200 HWPUNIT
# 표 위 기준·단위 줄 '(기준 : ’26.9월) (단위 : 백만원)' — 표 오른쪽 끝에 맞추고 표 글자보다 2pt 작게(사용자 원칙 2026-11-01)
UNIT_RE = re.compile(r"^\s*\((기준|단위)\s*:")
LANGS =["hangul", "latin", "hanja", "japanese", "other", "symbol", "user"]

# 글 속 특수 문자를 보이는 기호로 바꿔 다룬다(양식 지도·계획 파일 공통).
#   탭 → \t, 줄 바꿈 → \n, 고정폭 빈칸 → ⎵, 묶음 빈칸 → ⍽
ESC = {"tab": "\t", "lineBreak": "\n", "fwSpace": "⎵", "nbSpace": "⍽"}
ESC_REV = {v: k for k, v in ESC.items()}

# 구조를 정하는 조종 문자(쪽 설정·단·머리말·꼬리말·쪽 번호). 첫 문단으로 옮겨 그대로 둔다.
STRUCT_CTRLS = {"colPr", "header", "footer", "pageNum", "pageHiding", "newNum", "pageNumCtrl"}


# ---------------------------------------------------------------- 묶음(ZIP)
class Package:
    """HWPX 파일 하나. XML은 필요할 때 읽고 save()에서 다시 쓴다."""

    def __init__(self, path):
        try:
            with zipfile.ZipFile(path) as z:
                self.infos = z.infolist()
                self.data = {i.filename: z.read(i.filename) for i in self.infos}
        except zipfile.BadZipFile:
            raise SystemExit(
                f"'{path}'는 HWPX 파일이 아닙니다. 옛 형식(.hwp)이면 한글에서 "
                "[다른 이름으로 저장] → 파일 형식 'HWPX'로 저장해 다시 주세요."
            )
        if "Contents/header.xml" not in self.data:
            raise SystemExit(f"'{path}' 안에 Contents/header.xml이 없습니다. HWPX 문서가 맞는지 확인하세요.")
        self._xml = {}

    def xml(self, name):
        if name not in self._xml:
            parser = etree.XMLParser(huge_tree=True, resolve_entities=False, no_network=True)
            self._xml[name] = etree.fromstring(self.data[name], parser)
        return self._xml[name]

    def sections(self):
        """본문 구역 파일 이름(읽는 차례대로)."""
        names = []
        if "Contents/content.hpf" in self.data:
            hpf = self.xml("Contents/content.hpf")
            items = {it.get("id"): it.get("href") for it in hpf.iter(T("opf:item"))}
            for ref in hpf.iter(T("opf:itemref")):
                href = items.get(ref.get("idref"), "")
                if re.match(r"Contents/section\d+\.xml$", href):
                    names.append(href)
        if not names:
            names = sorted(
                (n for n in self.data if re.match(r"Contents/section\d+\.xml$", n)),
                key=lambda n: int(re.findall(r"\d+", n)[-1]),
            )
        return names

    def drop_section(self, name):
        """구역 하나를 묶음과 목차(content.hpf)에서 뺀다."""
        self.data.pop(name, None)
        self._xml.pop(name, None)
        if "Contents/content.hpf" in self.data:
            hpf = self.xml("Contents/content.hpf")
            ids = set()
            for it in list(hpf.iter(T("opf:item"))):
                if it.get("href") == name:
                    ids.add(it.get("id"))
                    it.getparent().remove(it)
            for ref in list(hpf.iter(T("opf:itemref"))):
                if ref.get("idref") in ids:
                    ref.getparent().remove(ref)

    def save(self, path):
        for name, root in self._xml.items():
            self.data[name] = XML_DECL + strip_inner_ns(etree.tostring(root, encoding="UTF-8"))
        kinds = {i.filename: i.compress_type for i in self.infos}
        order = [i.filename for i in self.infos if i.filename in self.data]
        order += [n for n in self.data if n not in order]
        if "mimetype" in order:  # mimetype은 맨 앞, 압축하지 않음(HWPX 규칙)
            order.remove("mimetype")
            order.insert(0, "mimetype")
        with zipfile.ZipFile(path, "w") as z:
            for n in order:
                info = zipfile.ZipInfo(n, date_time=(2026, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_STORED if n == "mimetype" else kinds.get(n, zipfile.ZIP_DEFLATED)
                z.writestr(info, self.data[n])


def strip_inner_ns(xml_bytes):
    """맨 위 요소에 이미 있는 이름공간 선언이 안쪽 요소에 또 붙으면 지운다(복사한 요소에 생김)."""
    head_end = xml_bytes.find(b">")
    head, body = xml_bytes[: head_end + 1], xml_bytes[head_end + 1 :]
    for m in re.finditer(rb' xmlns:(\w+)="([^"]*)"', head):
        body = body.replace(b" xmlns:%s=\"%s\"" % (m.group(1), m.group(2)), b"")
    return head + body


# ---------------------------------------------------------------- 서식 목록(header.xml)
def _num(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


class Styles:
    """header.xml의 글자 모양(charPr)·문단 모양(paraPr)·테두리(borderFill)를 읽기 쉽게 정리한다."""

    def __init__(self, header):
        self.header = header
        self.fonts = {}  # 언어 → {글꼴 번호: 이름}
        for ff in header.iter(T("hh:fontface")):
            lang = (ff.get("lang") or "").lower()
            self.fonts[lang] = {f.get("id"): f.get("face") for f in ff.iter(T("hh:font"))}
        self.char = {c.get("id"): self._char(c) for c in header.iter(T("hh:charPr"))}
        self.para = {p.get("id"): self._para(p) for p in header.iter(T("hh:paraPr"))}
        self.border = {b.get("id"): self._border(b) for b in header.iter(T("hh:borderFill"))}
        self.style_ids = {s.get("id") for s in header.iter(T("hh:style"))}

    def _char(self, c):
        ref = c.find(T("hh:fontRef"))
        ratio = c.find(T("hh:ratio"))
        spacing = c.find(T("hh:spacing"))
        rel = c.find(T("hh:relSz"))
        font = None
        if ref is not None:
            font = self.fonts.get("hangul", {}).get(ref.get("hangul"))
        ul = c.find(T("hh:underline"))
        return {
            "font": font,
            "size": _num(c.get("height"), 1000) / 100,
            "color": c.get("textColor"),
            "shade": c.get("shadeColor"),
            "bold": c.find(T("hh:bold")) is not None,
            "italic": c.find(T("hh:italic")) is not None,
            "underline": ul is not None and ul.get("type") not in (None, "NONE"),
            "ratio": _num(ratio.get("hangul"), 100) if ratio is not None else 100,
            "spacing": _num(spacing.get("hangul"), 0) if spacing is not None else 0,
            # 상대 크기(%): 글자 크기는 그대로 두고 글자만 줄임(작은 ○ 머리 기호 등). 기호는 symbol 칸 값
            "rel": _num(rel.get("symbol", rel.get("hangul")), 100) if rel is not None else 100,
            "superscript": c.find(T("hh:supscript")) is not None,
            "subscript": c.find(T("hh:subscript")) is not None,
        }

    def _para(self, p):
        al = p.find(T("hh:align"))
        info = {"align": al.get("horizontal") if al is not None else "JUSTIFY"}
        # 여백·줄 간격은 hp:switch 안에 두 벌 있다. 한글 2018 이후가 읽는 hp:case(HwpUnitChar) 값이 실제 값이고,
        # hp:default 값은 옛 프로그램용이라 여백이 두 배로 적혀 있다(한글 2024 저장본에서 확인). 그래서 case를 먼저 읽는다.
        case = p.find(".//" + T("hp:case"))
        scope = case if case is not None else p
        margin = scope.find(".//" + T("hh:margin"))
        ls = scope.find(".//" + T("hh:lineSpacing"))
        if margin is None:
            margin = p.find(".//" + T("hh:margin"))
        if ls is None:
            ls = p.find(".//" + T("hh:lineSpacing"))
        for key in ("intent", "left", "right", "prev", "next"):
            el = margin.find(T("hc:" + key)) if margin is not None else None
            info[key] = _num(el.get("value")) if el is not None else 0
        info["line_type"] = ls.get("type") if ls is not None else "PERCENT"
        info["line"] = _num(ls.get("value"), 160) if ls is not None else 160
        brk = p.find(T("hh:breakSetting"))
        info["keep_next"] = brk is not None and brk.get("keepWithNext") == "1"
        info["condense"] = _num(p.get("condense"))
        info["word_break"] = brk.get("breakNonLatinWord") if brk is not None else None
        info["squeeze"] = brk is not None and brk.get("lineWrap") == "SQUEEZE"  # 한 줄로 입력: 넘치면 자간을 줄여 한 줄에
        return info

    def _border(self, b):
        sides = {}
        for side in ("left", "right", "top", "bottom"):
            el = b.find(T("hh:%sBorder" % side))
            if el is not None:
                sides[side] = (el.get("type"), el.get("width"), el.get("color"))
        fill = None
        wb = b.find(".//" + T("hc:winBrush"))
        if wb is not None and wb.get("faceColor") not in (None, "none"):
            fill = wb.get("faceColor")
        return {"sides": sides, "fill": fill}

    # 사람이 읽는 설명 -------------------------------------------------
    def char_desc(self, cid):
        c = self.char.get(cid)
        if not c:
            return f"c{cid}(없음)"
        parts = [c["font"] or "글꼴?", f"{c['size']:g}pt"]
        if c["bold"]:
            parts.append("굵게")
        if c["italic"]:
            parts.append("기울임")
        if c["underline"]:
            parts.append("밑줄")
        if c["superscript"]:
            parts.append("위첨자")
        if c["subscript"]:
            parts.append("아래첨자")
        if c["ratio"] != 100:
            parts.append(f"장평{c['ratio']}")
        if c.get("rel", 100) != 100:
            parts.append(f"상대크기{c['rel']:g}%")
        if c["spacing"]:
            parts.append(f"자간{c['spacing']}")
        if c["color"] and c["color"].upper() != "#000000":
            parts.append(f"색{c['color']}")
        if c["shade"] and c["shade"].lower() != "none":
            parts.append(f"음영{c['shade']}")
        return " ".join(parts)

    def para_desc(self, pid):
        p = self.para.get(pid)
        if not p:
            return f"p{pid}(없음)"
        align = {"JUSTIFY": "양쪽", "LEFT": "왼쪽", "RIGHT": "오른쪽", "CENTER": "가운데",
                 "DISTRIBUTE": "배분", "DISTRIBUTE_SPACE": "나눔"}.get(p["align"], p["align"])
        parts = [align]
        if p["line_type"] == "PERCENT":
            parts.append(f"줄간격{p['line']}%")
        else:
            parts.append(f"줄간격{p['line'] / 100:g}pt({p['line_type']})")
        if p["left"]:
            parts.append(f"왼여백{p['left'] / HWPUNIT_PER_MM:.1f}mm")
        if p["intent"] < 0:
            parts.append(f"내어쓰기{-p['intent'] / HWPUNIT_PER_MM:.1f}mm")
        elif p["intent"] > 0:
            parts.append(f"들여쓰기{p['intent'] / HWPUNIT_PER_MM:.1f}mm")
        if p["prev"]:
            parts.append(f"위{p['prev'] / 100:g}pt")
        if p["next"]:
            parts.append(f"아래{p['next'] / 100:g}pt")
        return " ".join(parts)

    def border_desc(self, bid):
        b = self.border.get(bid)
        if not b:
            return ""
        kinds = {s: v for s, v in b["sides"].items() if v[0] not in (None, "NONE")}
        if not kinds:
            desc = "선 없음"
        elif len({v for v in kinds.values()}) == 1 and len(kinds) == 4:
            t, w, col = next(iter(kinds.values()))
            desc = f"네 변 {t} {w} {col}"
        else:
            name = {"left": "왼", "right": "오른", "top": "위", "bottom": "아래"}
            desc = ", ".join(f"{name[s]} {v[0]} {v[1]} {v[2]}" for s, v in kinds.items())
        if b["fill"]:
            desc += f", 바탕 {b['fill']}"
        return desc

    def is_bold(self, cid):
        return bool(self.char.get(cid, {}).get("bold"))


class HeaderEdit:
    """견본 서식을 바탕으로 '보이는 모양은 같고 성질만 다른' 서식을 더한다.
    (다음 문단과 함께·줄 간격·자간처럼 사용자 원칙에 따라 조정할 때만 쓴다. 글꼴·색은 바꾸지 않고,
    크기는 부연설명 괄호·표 글자(10~12pt)·표 위 기준·단위 줄에서만 바꾼다.)"""

    def __init__(self, header, styles):
        self.h = header
        self.styles = styles
        self.cache = {}

    def _clone(self, list_tag, item_tag, src_id):
        lst = self.h.find(".//" + T(list_tag))
        items = lst.findall(T(item_tag))
        src = next((x for x in items if x.get("id") == src_id), None)
        if src is None:
            return None
        new = copy.deepcopy(src)
        lst.append(new)
        new.set("id", str(max(int(x.get("id")) for x in items) + 1))
        if lst.get("itemCnt") is not None:
            lst.set("itemCnt", str(len(items) + 1))
        return new

    def _para(self, pid):
        return next((x for x in self.h.iter(T("hh:paraPr")) if x.get("id") == pid), None)

    def para_keep_next(self, pid):
        src = self._para(pid)
        if src is None:
            return pid
        brk = src.find(T("hh:breakSetting"))
        if brk is not None and brk.get("keepWithNext") == "1":
            return pid
        key = ("keep", pid)
        if key not in self.cache:
            new = self._clone("hh:paraProperties", "hh:paraPr", pid)
            new.find(T("hh:breakSetting")).set("keepWithNext", "1")
            self.styles.para[new.get("id")] = self.styles._para(new)
            self.cache[key] = new.get("id")
        return self.cache[key]

    def para_line(self, pid, value):
        """줄 간격(%)만 바꾼 문단 모양."""
        key = ("line", pid, value)
        if key not in self.cache:
            new = self._clone("hh:paraProperties", "hh:paraPr", pid)
            for ls in new.iter(T("hh:lineSpacing")):
                ls.set("value", str(value))
            self.styles.para[new.get("id")] = self.styles._para(new)
            self.cache[key] = new.get("id")
        return self.cache[key]

    def para_hang(self, pid, hang):
        """내어쓰기(둘째 줄부터 들어가는 폭, HWPUNIT)만 바꾼 문단 모양. 한글처럼 hp:case에는 실제 값,
        hp:default에는 두 배 값을 적는다(한글 2024 저장본과 같은 꼴)."""
        hang = int(round(hang))
        key = ("hang", pid, hang)
        if key not in self.cache:
            new = self._clone("hh:paraProperties", "hh:paraPr", pid)
            case = new.find(".//" + T("hp:case"))
            for m in new.iter(T("hh:margin")):
                inside_case = case is not None and any(a is case for a in m.iterancestors())
                el = m.find(T("hc:intent"))
                if el is not None:
                    el.set("value", str(-hang if inside_case or case is None else -2 * hang))
            self.styles.para[new.get("id")] = self.styles._para(new)
            self.cache[key] = new.get("id")
        return self.cache[key]

    def para_margin(self, pid, key, value):
        """문단 여백 하나(key: left·right, HWPUNIT)만 바꾼 문단 모양(예: 금액 칸 오른쪽을 약간 띄움).
        para_hang처럼 hp:case에는 실제 값, hp:default에는 두 배 값을 적는다."""
        value = int(round(value))
        key_ = ("margin", pid, key, value)
        if key_ not in self.cache:
            new = self._clone("hh:paraProperties", "hh:paraPr", pid)
            case = new.find(".//" + T("hp:case"))
            for m in new.iter(T("hh:margin")):
                inside_case = case is not None and any(a is case for a in m.iterancestors())
                el = m.find(T("hc:" + key))
                if el is not None:
                    el.set("value", str(value if inside_case or case is None else 2 * value))
            self.styles.para[new.get("id")] = self.styles._para(new)
            self.cache[key_] = new.get("id")
        return self.cache[key_]

    def border_image(self, bid, item_id, mode="TOTAL"):
        """칸 테두리는 그대로 두고 바탕을 그림(binaryItemIDRef)으로 채운 테두리·배경 모양. 표 칸 배경 그림(사용자 원칙 2026-11-01)."""
        key = ("border_image", bid, item_id, mode)
        if key not in self.cache:
            new = self._clone("hh:borderFills", "hh:borderFill", bid)
            if new is None:
                return bid
            for fb in new.findall(T("hc:fillBrush")):
                new.remove(fb)
            fb = etree.SubElement(new, T("hc:fillBrush"))
            ib = etree.SubElement(fb, T("hc:imgBrush"))
            ib.set("mode", mode)
            img = etree.SubElement(ib, T("hc:img"))
            for k, v in (("binaryItemIDRef", item_id), ("bright", "0"), ("contrast", "0"), ("effect", "REAL_PIC"), ("alpha", "0")):
                img.set(k, v)
            self.styles.border[new.get("id")] = self.styles._border(new)
            self.cache[key] = new.get("id")
        return self.cache[key]

    def border_lines(self, bid, kind, width="0.12 mm", color="#000000"):
        """네 변을 모두 kind(NONE·SOLID)로 하고 바탕 채우기를 뺀 테두리 모양. 투명 선 표로 도표를 만들 때
        (표 선은 모두 투명, 상자 칸만 실선 — 사용자 방식 2026-11-01)."""
        key = ("lines", bid, kind, width, color)
        if key not in self.cache:
            new = self._clone("hh:borderFills", "hh:borderFill", bid)
            if new is None:
                return bid
            for side in ("leftBorder", "rightBorder", "topBorder", "bottomBorder"):
                el = new.find(T("hh:" + side))
                if el is not None:
                    el.set("type", kind)
                    el.set("width", width)
                    el.set("color", color)
            for fb in new.findall(T("hc:fillBrush")):
                new.remove(fb)
            self.styles.border[new.get("id")] = self.styles._border(new)
            self.cache[key] = new.get("id")
        return self.cache[key]

    def para_align(self, pid, align):
        """정렬만 바꾼 문단 모양(예: 숫자 칸 오른쪽 정렬)."""
        src = self._para(pid)
        al = src.find(T("hh:align")) if src is not None else None
        if al is None or al.get("horizontal") == align:
            return pid
        key = ("align", pid, align)
        if key not in self.cache:
            new = self._clone("hh:paraProperties", "hh:paraPr", pid)
            new.find(T("hh:align")).set("horizontal", align)
            self.styles.para[new.get("id")] = self.styles._para(new)
            self.cache[key] = new.get("id")
        return self.cache[key]

    def para_squeeze(self, pid):
        """줄이 넘치면 한글이 자간을 줄여 한 줄에 넣는 문단 모양(한글의 '한 줄로 입력', lineWrap=SQUEEZE)."""
        src = self._para(pid)
        brk = src.find(T("hh:breakSetting")) if src is not None else None
        if brk is None or brk.get("lineWrap") == "SQUEEZE":
            return pid
        key = ("squeeze", pid)
        if key not in self.cache:
            new = self._clone("hh:paraProperties", "hh:paraPr", pid)
            new.find(T("hh:breakSetting")).set("lineWrap", "SQUEEZE")
            self.styles.para[new.get("id")] = self.styles._para(new)
            self.cache[key] = new.get("id")
        return self.cache[key]

    def char_size(self, cid, delta_pt):
        """글자 크기만 delta_pt(pt)만큼 바꾼 글자 모양. 부연설명 괄호를 2pt 작게(사용자 원칙, 2026-10-31), 표 글자를
        10~12pt 안에서 줄여 줄 바꿈을 줄일 때와 표 위 기준·단위 줄을 표 글자보다 2pt 작게(2026-11-01) 할 때만 쓴다."""
        key = ("size", cid, delta_pt)
        if key not in self.cache:
            new = self._clone("hh:charProperties", "hh:charPr", cid)
            h = int(new.get("height") or 1000)
            new.set("height", str(max(100, h + int(round(delta_pt * 100)))))
            self.styles.char[new.get("id")] = self.styles._char(new)
            self.cache[key] = new.get("id")
        return self.cache[key]

    def char_like(self, cid, src, size_pt):
        """cid 모양(굵게·위 첨자·자간 등)은 그대로 두고 글꼴은 src 글자 모양 것, 크기는 size_pt로 바꾼 글자 모양.
        표 바로 밑 ※ 줄을 표 글씨(맑은 고딕·표 글자 크기)로 맞출 때 쓴다(사용자 원칙 2026-11-01)."""
        key = ("like", cid, src, size_pt)
        if key not in self.cache:
            new = self._clone("hh:charProperties", "hh:charPr", cid)
            ref = next((x for x in self.h.iter(T("hh:charPr")) if x.get("id") == src), None)
            if ref is not None and ref.find(T("hh:fontRef")) is not None:
                old = new.find(T("hh:fontRef"))
                new.replace(old, copy.deepcopy(ref.find(T("hh:fontRef"))))
            new.set("height", str(int(round(size_pt * 100))))
            self.styles.char[new.get("id")] = self.styles._char(new)
            self.cache[key] = new.get("id")
        return self.cache[key]

    def char_spacing(self, cid, spacing):
        """자간(%)만 바꾼 글자 모양."""
        key = ("spacing", cid, spacing)
        if key not in self.cache:
            new = self._clone("hh:charProperties", "hh:charPr", cid)
            sp = new.find(T("hh:spacing"))
            for k in list(sp.attrib):
                sp.set(k, str(spacing))
            self.styles.char[new.get("id")] = self.styles._char(new)
            self.cache[key] = new.get("id")
        return self.cache[key]

    def word_wrap(self, pid):
        """줄 나눔을 어절(단어) 단위로 맞춘다. 바꿨으면 True.
        한글 단위 어절 = breakNonLatinWord="BREAK_WORD"(이름과 반대 — KEEP_WORD가 글자 단위, 한글 2024 실측).
        영어 단위 단어 = breakLatinWord="KEEP_WORD"."""
        src = self._para(pid)
        brk = src.find(T("hh:breakSetting")) if src is not None else None
        if brk is None:
            return False
        changed = False
        for k, v in (("breakLatinWord", "KEEP_WORD"), ("breakNonLatinWord", "BREAK_WORD")):
            if brk.get(k) != v:
                brk.set(k, v)
                changed = True
        return changed


# ---------------------------------------------------------------- 글 읽기·쓰기
def t_text(t):
    s = t.text or ""
    for ch in t:
        s += ESC.get(local(ch), "")
        s += ch.tail or ""
    return s


def run_text(run):
    return "".join(t_text(t) for t in run if t.tag == T("hp:t"))


def run_objects(run):
    """글이 아닌 것(표·그림·조종 문자 등)의 이름 목록."""
    out = []
    for ch in run:
        if ch.tag == T("hp:t"):
            continue
        if ch.tag == T("hp:ctrl"):
            out += ["ctrl:" + local(x) for x in ch]
        else:
            out.append(local(ch))
    return out


def para_runs(p):
    return [r for r in p if r.tag == T("hp:run")]


def is_struct(ch):
    """쪽 설정(secPr)이나 단·머리말·꼬리말·쪽 번호 조종 문자인가."""
    if ch.tag == T("hp:secPr"):
        return True
    return ch.tag == T("hp:ctrl") and any(local(x) in STRUCT_CTRLS for x in ch)


def indexed_runs(p):
    """양식 지도의 '조각' 번호가 붙는 run 목록(표가 든 run과 구조 조종만 든 run은 뺌).
    analyze.py와 build.py가 같은 번호를 쓰도록 이 함수 하나로 센다."""
    out = []
    for r in para_runs(p):
        if r.find(T("hp:tbl")) is not None:
            continue
        objs = [ch for ch in r if ch.tag != T("hp:t") and not is_struct(ch)]
        if not run_text(r) and not objs:
            continue
        out.append(r)
    return out


def para_text(p):
    return "".join(run_text(r) for r in para_runs(p))


def para_tables(p):
    return [x for r in para_runs(p) for x in r if x.tag == T("hp:tbl")]


def para_pics(p):
    """문단에 바로 든 그림(표 안 그림은 빼고)."""
    return [x for r in para_runs(p) for x in r if x.tag == T("hp:pic")]


def is_blank(p):
    """글·표·그림이 없는 빈 줄(쪽 설정이 든 첫 문단은 빼고)."""
    return (not para_tables(p) and not para_pics(p) and not para_text(p).strip()
            and p.find(".//" + T("hp:secPr")) is None)


def set_run_text(run, text, tab_proto=None):
    """run 안의 글을 text로 바꾼다. \\t·\\n·⎵·⍽는 탭·줄 바꿈·고정폭 빈칸·묶음 빈칸 요소가 된다."""
    for t in run.findall(T("hp:t")):
        run.remove(t)
    t = etree.SubElement(run, T("hp:t"))
    last = None
    buf = []

    def flush():
        s = "".join(buf)
        buf.clear()
        if not s:
            return
        if last is None:
            t.text = (t.text or "") + s
        else:
            last.tail = (last.tail or "") + s

    for ch in text:
        name = ESC_REV.get(ch)
        if name is None:
            buf.append(ch)
            continue
        flush()
        if name == "tab" and tab_proto is not None:
            el = copy.deepcopy(tab_proto)
            el.tail = None
            t.append(el)
        else:
            el = etree.SubElement(t, T("hp:" + name))
            if name == "tab":
                el.set("width", "4000")
                el.set("leader", "0")
                el.set("type", "1")
        last = el
    flush()
    return run


def drop_linesegs(el):
    """줄 배치 정보(linesegarray)를 지운다. 한글이 열 때 새로 계산한다."""
    for ls in list(el.iter(T("hp:linesegarray"))):
        ls.getparent().remove(ls)


# ---------------------------------------------------------------- 머리 기호(□ ○ - * …)
_SYM = "□■◇◆○●◎◦∘•∙·ㆍ▪▫▶▷►☞※＊*ㅇ-–—➜⇒→"
_MARK_RE = re.compile(
    r"^(?P<lead>[ \t⎵⍽　]*)"
    r"(?P<mark>[" + re.escape(_SYM) + r"]|[Ⅰ-Ⅻ]\.|(?:\d{1,2}|[가-하]|[A-Za-z]|[ivxIVX]{1,4})[.)]|\((?:\d{1,2}|[가-하])\)|[①-⑳㉠-㉭㈀-㈍])"
    r"(?P<gap>[ \t⎵⍽　]*)"
)


def split_marker(text):
    """'  ○ 내용' → ('  ○ ', '○', '내용'). 머리 기호가 없으면 ('', '', text)."""
    m = _MARK_RE.match(text)
    if not m:
        return "", "", text
    mark = m.group("mark")
    # '**굵게**' 표시의 별표는 머리 기호가 아니다.
    if mark in "*＊" and text[m.start("mark") + 1: m.start("mark") + 2] in ("*", "＊"):
        return "", "", text
    # 숫자·글자 번호(1. 가. 1))는 뒤에 빈칸이 있어야 번호로 본다('1.5배' 같은 글과 구별).
    if not m.group("gap") and mark[0] not in _SYM and m.end() < len(text):
        return "", "", text
    # '-' 뒤에 바로 숫자가 오면 음수일 수 있어 기호로 보지 않는다.
    if mark in "-–—" and not m.group("gap") and m.end() < len(text):
        return "", "", text
    return text[: m.end()], mark, text[m.end():]


def _base_head(text):
    pre, mark, body = split_marker(text)
    n = len(pre) if mark else 0
    m = re.match(r"\([^()\n]{1,12}\)", body if mark else text)
    return n + (m.end() if m else 0)


COLON_LABEL_MAX = 20  # 쌍점이 첫머리에서 이 글자 수 안에 있어야 '항목명 : 내용'으로 본다


def label_colon(text):
    """'인센티브 : 밤 10시'처럼 첫머리 항목명 뒤 쌍점이 있으면, 쌍점 뒤 내용이 시작하는 글자 위치. 없으면 0.
    괄호 안 쌍점(국:시)과 숫자 사이 쌍점(10:30)은 항목명 쌍점이 아니다."""
    head = _base_head(text)
    depth = 0
    for i in range(head, len(text)):
        ch = text[i]
        if ch in "([「":
            depth += 1
        elif ch in ")]」":
            depth = max(0, depth - 1)
        elif ch == ":" and depth == 0:
            if i - head > COLON_LABEL_MAX:
                return 0
            if i > 0 and text[i - 1].isdigit() and i + 1 < len(text) and text[i + 1].isdigit():
                continue
            if (text[i - 1:i].isalpha() and not text[i - 2:i - 1].strip(":").isalpha()
                    and text[i + 1:i + 2].isalpha() and not text[i + 2:i + 3].strip(":").isalpha()):
                continue  # 비율 표기 국:시
            j = i + 1
            while j < len(text) and text[j] in " ⎵⍽":
                j += 1
            return j if j < len(text) else 0
    return 0


def label_content(text):
    """'○ (근  거) 내용'처럼 괄호 이름표가 있으면 이름표 뒤 내용이 시작하는 글자 위치. 없으면 0."""
    pre, mark, body = split_marker(text)
    if not re.match(r"\([^()\n]{1,12}\)", body if mark else text):
        return 0
    j = _base_head(text)
    while j < len(text) and text[j] in " ⎵⍽":
        j += 1
    return j if j < len(text) else 0


def head_length(text):
    """문단 첫머리(머리 기호·빈칸 + 괄호 이름표, 또는 '항목명 : '까지)의 글자 수. 자간 조정은 이 뒤 내용에만 한다
    (그래야 같은 묶음의 괄호·쌍점과 내용 시작이 위아래로 계속 맞는다)."""
    # 괄호 이름표 뒤 빈칸까지 머리에 넣는다 — 줄 맞춤이 그 빈칸 자간을 줄이면 첫 줄 내용 시작이 둘째 줄 내어쓰기보다
    # 0.1~0.3mm 앞으로 와 위아래가 어긋남(2026-11-04 되풀이 시험에서 찾음). 쌍점 꼴(label_colon)은 원래 빈칸까지 넣음.
    return max(_base_head(text), label_content(text), label_colon(text))


def space_colons(text):
    """쌍점은 앞뒤로 한 칸씩: '항목: 내용' → '항목 : 내용'. 괄호 안(국:시)·숫자 사이(10:30)·'://'는 그대로."""
    out, depth, i = [], 0, 0
    while i < len(text):
        ch = text[i]
        if ch in "([「":
            depth += 1
        elif ch in ")]」":
            depth = max(0, depth - 1)
        if ch == ":" and depth == 0 and not text.startswith("//", i + 1):
            prev = "".join(out).rstrip(" ")
            j = i + 1
            while j < len(text) and text[j] == " ":
                j += 1
            nxt = text[j] if j < len(text) else ""
            # 비율 표기 '국:시', '국:시:구'(한 글자:한 글자)는 띄우지 않는다
            ratio = (text[i - 1:i].isalpha() and not text[i - 2:i - 1].strip(":").isalpha()
                     and text[i + 1:i + 2].isalpha() and not text[i + 2:i + 3].strip(":").isalpha())
            if prev and not (prev[-1].isdigit() and nxt.isdigit()) and nxt and not ratio:
                out = list(prev + " : ")
                i = j
                continue
        out.append(ch)
        i += 1
    return "".join(out)


def marker_level(text):
    """문단 차례 수준: 1 □, 2 ○, 3 -·번호, 4 *·※ 설명, 0 기호 없음."""
    _, mark, _ = split_marker(text)
    if not mark:
        return 0
    if mark in "□■◇◆" or mark[0] in "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ":
        return 1
    if mark in "○●◎◦∘ㅇ":
        return 2
    if mark in "*＊※":
        return 4
    return 3


def marker_kind(mark):
    if not mark:
        return ""
    if mark[0] in "ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩⅪⅫ":
        return "장 제목(Ⅰ.)"
    if mark in "□■◇◆":
        return "큰 항목(□)"
    if mark in "○●◎◦∘ㅇ":
        return "중간 항목(○)"
    if mark in "-–—":
        return "작은 항목(-)"
    if mark in "•∙·ㆍ▪▫":
        return "작은 항목(·)"
    if mark in "*＊":
        return "주석(*)"
    if mark == "※":
        return "참고(※)"
    if mark in "▶▷►☞➜⇒→":
        return f"강조({mark})"
    if re.match(r"\d", mark):
        return f"번호({re.sub(r'[0-9]+', '1', mark)})"
    if re.match(r"[가-하]", mark):
        return f"번호({re.sub(r'[가-하]', '가', mark)})"
    if mark.startswith("("):
        return f"번호({mark})"
    return f"번호({mark})"


# ---------------------------------------------------------------- 표
def table_grid(tbl):
    """표의 칸 목록: [(줄, 칸, 줄 합침, 칸 합침, tc 요소)]."""
    cells = []
    for tc in tbl.iter(T("hp:tc")):
        if tc.getparent().getparent() is not tbl:  # 표 안의 표는 건너뜀
            continue
        addr = tc.find(T("hp:cellAddr"))
        span = tc.find(T("hp:cellSpan"))
        r, c = _num(addr.get("rowAddr")), _num(addr.get("colAddr"))
        rs = _num(span.get("rowSpan"), 1) if span is not None else 1
        cs = _num(span.get("colSpan"), 1) if span is not None else 1
        cells.append((r, c, rs, cs, tc))
    return cells


def cell_paras(tc):
    sub = tc.find(T("hp:subList"))
    return [p for p in sub if p.tag == T("hp:p")] if sub is not None else []


def cell_text(tc):
    return "\n".join(para_text(p) for p in cell_paras(tc))


# ---------------------------------------------------------------- 기타
def new_id(used):
    while True:
        v = str(random.randint(100000000, 2147483646))
        if v not in used:
            used.add(v)
            return v


def blank_png(width=60, height=85):
    """흰 바탕 PNG(미리 보기 그림 자리). 견본 내용이 미리 보기에 남지 않게 한다."""
    raw = b"".join(b"\x00" + b"\xff\xff\xff" * width for _ in range(height))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def page_info(sec_root):
    """첫 구역의 용지·여백(mm)."""
    pp = sec_root.find(".//" + T("hp:pagePr"))
    if pp is None:
        return None
    m = pp.find(T("hp:margin"))
    mm = lambda v: _num(v) / HWPUNIT_PER_MM  # noqa: E731
    w, h = mm(pp.get("width")), mm(pp.get("height"))
    info = {"width": w, "height": h, "landscape": pp.get("landscape")}
    if m is not None:
        for k in ("left", "right", "top", "bottom", "header", "footer"):
            info[k] = mm(m.get(k))
        info["body_width"] = w - info["left"] - info["right"]
    return info
