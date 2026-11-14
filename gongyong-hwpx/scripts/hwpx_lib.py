# -*- coding: utf-8 -*-
"""HWPX(한글 문서) 파일을 열고 읽고 저장하는 공용 함수.

- HWPX는 ZIP 안에 XML 파일이 든 묶음이다.
  - 본문: Contents/section0.xml (구역이 여럿이면 section1.xml …)
  - 글자 모양·문단 모양·테두리 목록: Contents/header.xml
- 이 스킬은 견본(양식)의 서식을 복사해 필요한 성질(자간·내어쓰기 등)만 바꾼 서식을 더한다.
  그래서 결과 문서의 모양이 견본과 같아진다.
"""
import copy
import json
import os
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


_TAGS = {}


def T(name):
    """'hp:p' 같은 이름을 lxml 태그('{주소}p')로 바꾼다(한 번 바꾼 이름은 저장 — 정돈 한 번에 200만 번 넘게 불림, 정돈 속도 2026-11-15)."""
    tag = _TAGS.get(name)
    if tag is None:
        prefix, local = name.split(":")
        tag = _TAGS[name] = "{%s}%s" % (NS[prefix], local)
    return tag


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
        except OSError as e:
            raise SystemExit(f"'{path}' 파일을 열지 못했습니다({e.strerror or e}). 경로를 확인하세요.")
        if "Contents/header.xml" not in self.data:
            raise SystemExit(f"'{path}' 안에 Contents/header.xml이 없습니다. HWPX 문서가 맞는지 확인하세요.")
        self._xml = {}
        if not self.sections():
            raise SystemExit(f"'{path}' 안에 본문(Contents/section0.xml)이 없습니다. HWPX 문서가 맞는지 확인하세요.")

    def xml(self, name):
        if name not in self._xml:
            parser = etree.XMLParser(huge_tree=True, resolve_entities=False, no_network=True)
            try:
                self._xml[name] = etree.fromstring(self.data[name], parser)
            except etree.XMLSyntaxError as e:
                raise SystemExit(f"문서 안 {name}이 깨져 읽지 못했습니다({e}). 한글에서 열어 다시 저장한 뒤 주세요.") from None
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
        try:
            with zipfile.ZipFile(path, "w") as z:
                for n in order:
                    info = zipfile.ZipInfo(n, date_time=(2026, 1, 1, 0, 0, 0))
                    info.compress_type = zipfile.ZIP_STORED if n == "mimetype" else kinds.get(n, zipfile.ZIP_DEFLATED)
                    z.writestr(info, self.data[n])
        except PermissionError:
            raise SystemExit(f"'{path}'에 저장하지 못했습니다 — 한글에서 그 파일을 열어 두었으면 닫고 다시 하세요.") from None
        except OSError as e:
            raise SystemExit(f"'{path}'에 저장하지 못했습니다({e.strerror or e}) — 폴더가 있는지 확인하세요.") from None


def same_path(a, b):
    """같은 파일을 가리키는가 — Windows는 대소문자를 가리지 않아 'Doc.hwpx'와 'DOC.hwpx'가 같은 파일(검토: 원본을 덮어썼음)."""
    try:
        if os.path.exists(a) and os.path.exists(b):
            return os.path.samefile(a, b)
    except OSError:
        pass
    return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def read_plan(path):
    """계획 파일(JSON)을 읽는다. 못 읽으면 쉬운 말로 멈춤."""
    try:
        with open(path, encoding="utf-8-sig") as f:
            return json.load(f)
    except OSError as e:
        raise SystemExit(f"계획 파일을 열지 못했습니다: {path} ({e.strerror or e})") from None
    except UnicodeDecodeError:
        raise SystemExit(f"계획 파일이 UTF-8이 아닙니다: {path} — UTF-8로 저장해 주세요.") from None
    except json.JSONDecodeError as e:
        raise SystemExit(f"계획 파일이 JSON 모양이 아닙니다: {e}") from None


def strip_inner_ns(xml_bytes):
    """맨 위 요소에 이미 있는 이름공간 선언이 안쪽 요소에 또 붙으면 지운다(복사한 요소에 생김)."""
    head_end = xml_bytes.find(b">")
    head, body = xml_bytes[: head_end + 1], xml_bytes[head_end + 1 :]
    decls = [b" xmlns:%s=\"%s\"" % (m.group(1), m.group(2)) for m in re.finditer(rb' xmlns:(\w+)="([^"]*)"', head)]
    if not any(d in body for d in decls):
        return xml_bytes

    def clean(m):
        tag = m.group(0)
        for d in decls:
            tag = tag.replace(d, b"")
        return tag

    # 요소 머리(<…>) 안에서만 지운다 — 통째로 바꾸면 본문 글에 같은 글자열이 있을 때 그 글까지 지워짐(검토 2026-11-12)
    return head + re.sub(rb"<[^<>]* xmlns:[^<>]*>", clean, body)


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
            # 숫자·영문은 한글이 '영문' 칸의 글꼴·장평·자간으로 찍음(언어별 값이 다른 견본 — 평가 2026-11-09)
            "latin_font": self.fonts.get("latin", {}).get(ref.get("latin")) if ref is not None else None,
            "latin_ratio": _num(ratio.get("latin"), 100) if ratio is not None else 100,
            "latin_spacing": _num(spacing.get("latin"), 0) if spacing is not None else 0,
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
        info["keep_lines"] = brk is not None and brk.get("keepLines") == "1"  # 문단 보호: 쪽 경계에서 나누지 않음
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
                ls.set("type", "PERCENT")  # 값은 늘 %로 줌 — 고정값 칸(FIXED 16pt)에 값만 쓰면 1.25pt 줄 간격이 됨(검토)
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

    def border_fill(self, bid, color):
        """선은 그대로 두고 바탕을 한 색으로 채운 테두리 모양(칸 안 표의 머리 줄)."""
        key = ("fill", bid, color)
        if key not in self.cache:
            new = self._clone("hh:borderFills", "hh:borderFill", bid)
            if new is None:
                return bid
            for fb in new.findall(T("hc:fillBrush")):
                new.remove(fb)
            brush = etree.SubElement(etree.SubElement(new, T("hc:fillBrush")), T("hc:winBrush"))
            for k, v in (("faceColor", color), ("hatchColor", "#000000"), ("alpha", "0")):
                brush.set(k, v)
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

    def border_sides(self, bid, sides):
        """bid 테두리 모양에서 몇 변만 바꾼 모양. sides = {"leftBorder": (종류, 굵기, 색) 또는 다른 테두리 번호(그 변을 옮겨 옴)}.
        한 열 표의 오른쪽 선을 견본 끝 칸 것으로, 그래프 상자(그림 칸이 든 한 열 표) 양옆을 선으로(사용자 2026-11-04)."""
        key = ("sides", bid, tuple(sorted((k, v if isinstance(v, tuple) else str(v)) for k, v in sides.items())))
        if key not in self.cache:
            new = self._clone("hh:borderFills", "hh:borderFill", bid)
            if new is None:
                return bid
            for side, val in sides.items():
                el = new.find(T("hh:" + side))
                if el is None:
                    continue
                if isinstance(val, tuple):
                    kind, width, color = val
                else:
                    src = next((x for x in self.h.iter(T("hh:borderFill")) if x.get("id") == str(val)), None)
                    s_el = src.find(T("hh:" + side)) if src is not None else None
                    if s_el is None:
                        continue
                    kind, width, color = s_el.get("type"), s_el.get("width"), s_el.get("color")
                el.set("type", kind)
                el.set("width", width)
                el.set("color", color)
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

    def char_bold(self, cid):
        """굵게만 더한 글자 모양(이미 굵으면 그대로). hh:bold는 hh:offset·hh:italic 바로 뒤(한글 저장본과 같은 차례)."""
        if self.styles.char.get(cid, {}).get("bold"):
            return cid
        key = ("bold", cid)
        if key not in self.cache:
            new = self._clone("hh:charProperties", "hh:charPr", cid)
            after = new.find(T("hh:italic"))
            if after is None:
                after = new.find(T("hh:offset"))
            bold = etree.Element(T("hh:bold"))
            if after is not None:
                after.addnext(bold)
            else:
                new.append(bold)
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

    def char_ratio(self, cid, ratio):
        """장평(%)만 바꾼 글자 모양. 고정폭 빈칸(글자 크기 1/4) 하나에 장평 200%를 주면 보통 빈칸 한 칸 폭(0.5글자)이 된다
        (한글 2024 실측 0.498) — 고정폭 빈칸 두 개 대신 한 개로(조판 부호 한 칸, 사용자 2026-11-08)."""
        key = ("ratio", cid, ratio)
        if key not in self.cache:
            new = self._clone("hh:charProperties", "hh:charPr", cid)
            rt = new.find(T("hh:ratio"))
            if rt is not None:
                for k in list(rt.attrib):
                    rt.set(k, str(ratio))
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


# ---------------------------------------------------------------- 알림 등급
class Note(str):
    """알림 한 줄 — 등급과 종류를 글과 함께 든다(문장 낱말로 가르면 '두 쪽에 걸친'이 든 참고 문장까지 고쳐야 함이 됨, 평가 2026-11-09)."""
    level = "info"
    kind = None  # 계획 "omit" 키(basis·summary·date·table_title) — 사용자가 뺀다고 한 요소의 지적이면 알림으로 낮춤


def fix_note(msg, kind=None):
    """'고쳐야 함' 등급 알림."""
    n = Note(msg)
    n.level, n.kind = "fix", kind
    return n


def note_is_fix(w, omit=()):
    """고쳐야 함인가(뺀다고 한 요소의 지적은 아님)."""
    return getattr(w, "level", "info") == "fix" and getattr(w, "kind", None) not in omit


def pct_range(vals, plus=False):
    """쓴 값의 범위 글: [-2, -2] → '-2%', [-2, -5] → '-2~-5%'(0에 가까운 값부터)."""
    a, b = min(vals, key=abs), max(vals, key=abs)
    f = (lambda v: f"{v:+d}") if plus or a > 0 or b > 0 else (lambda v: f"{v:d}")
    return f"{f(a)}%" if a == b else f"{f(a)}~{f(b)}%"


# ---------------------------------------------------------------- 글 읽기·쓰기
def t_text(t):
    s = t.text or ""
    for ch in t:
        s += ESC.get(local(ch), "")
        s += ch.tail or ""
    return s


COMPOSE_CHAR = "\uFDD0"  # 글자 겹치기(hp:compose — 네모 숫자 등)가 글 속에서 차지하는 자리(글자 한 칸 폭). 읽을 때만 쓰고 파일에는 쓰지 않음(set_run_text가 뺌). 유니코드 내부용 비문자라 문서에 있을 수 없음(사용자 영역 글자는 한글 문서에 실제로 쓰임)
_XML_BAD_RE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")  # XML에 쓸 수 없는 글자(붙여 넣은 글의 조종 문자 — 그대로 쓰면 저장에서 멈춤)


_HP_T, _HP_COMPOSE, _HP_RUN = "{%s}t" % NS["hp"], "{%s}compose" % NS["hp"], "{%s}run" % NS["hp"]


def run_text(run):
    return "".join(t_text(t) if t.tag == _HP_T else COMPOSE_CHAR for t in run if t.tag == _HP_T or t.tag == _HP_COMPOSE)


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
    return [r for r in p if r.tag == _HP_RUN]


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


TABLE_TITLE_MARK = "■"  # 표 제목(사용자 원칙 2026-11-04 '표는 ■ 네모로 제목') — □ 큰 항목과 다르게 다룬다


def is_table_title(p, after=None):
    """표 제목 줄('■ 세부사업별 예산 현황'): ■로 시작하고, 바로 뒤(기준·단위 줄은 건너뜀)가 표 문단인 글 문단.
    ■는 머리 기호로는 □와 같은 수준 1이라(marker_level) 항목 수 세기·쪽 맞춤 묶음에서 이 함수로 따로 가린다.
    after: 뒤 문단 목록(아직 문서에 넣지 않은 문단을 볼 때). 없으면 문서에서 바로 뒤 문단들을 본다."""
    if p is None or para_tables(p) or not para_text(p).lstrip().startswith(TABLE_TITLE_MARK):
        return False
    if after is None:
        after, nxt = [], p.getnext()
        while nxt is not None and len(after) < 4:
            if nxt.tag == T("hp:p"):
                after.append(nxt)
            nxt = nxt.getnext()
    for q in list(after)[:4]:
        if para_tables(q):
            return True
        if not UNIT_RE.match(para_text(q)):
            return False
    return False


def is_blank(p):
    """글·표·그림이 없는 빈 줄(쪽 설정이 든 첫 문단은 빼고)."""
    return (not para_tables(p) and not para_pics(p) and not para_text(p).strip()
            and p.find(".//" + T("hp:secPr")) is None)


def plain_run(run):
    """글(hp:t) 하나뿐이고 그 안에 줄 바꿈·탭·고정폭·묶음 빈칸만 든 조각인가 — 글을 다시 써도 잃는 것이 없다.
    형광펜(markpenBegin/End) 등 다른 표시가 들면 False(평가 2026-11-09: 정돈이 다시 쓰며 형광펜이 사라졌음)."""
    return len(run) == 1 and run[0].tag == T("hp:t") and all(local(ch) in ESC for ch in run[0])


def run_tabs(run):
    """조각 안 탭 요소를 차례대로 — 글을 다시 쓸 때 set_run_text(tabs=…)로 넘기면 채움 문자·폭이 그대로 간다."""
    return [ch for t in run.findall(T("hp:t")) for ch in t if local(ch) == "tab"]


def text_marks(p):
    """문단 글 속 표시의 수(이름 → 개수) — 글자 비교가 못 보는 형광펜 등 표시와 채움 문자 있는 탭."""
    out = {}
    for r in para_runs(p):
        for t in r.findall(T("hp:t")):
            for ch in t:
                name = local(ch)
                if name == "tab":
                    name = "" if ch.get("leader", "0") == "0" else "tab:" + ch.get("leader")
                elif name in ESC:
                    name = ""
                if name:
                    out[name] = out.get(name, 0) + 1
    return out


# 보이지 않아야 하는 글자인데 한글이 찍는 것(한글 2024 실측 2026-11-09): U+FE0E·FE0F 이모지 표시·U+2060은 네모, U+00AD는 붙임표, U+FEFF는 빈칸. AI가 쓴 글에 잘 섞임('☑️'). U+200B~D는 찍히지 않아 그대로
INVISIBLE_RE = re.compile("[\ufe0e\ufe0f\u2060\ufeff\u00ad]")
KEYCAP_RE = re.compile(r"(\d{1,2})\ufe0f?\u20e3")  # 키캡 숫자(1️⃣) — 한글이 네모를 앞 글자에 겹쳐 왼쪽으로 삐져나오게 찍음 → 글자 겹치기로


def clean_chars(p):
    """문단의 보이지 않아야 하는 글자를 빼고 키캡 숫자를 글자 겹치기 네모 숫자로 바꾼다. 돌려주는 것: (뺀 글자 수, 바꾼 수)."""
    cut = caps = 0
    for r in para_runs(p):
        if r.find(T("hp:t")) is None:
            continue
        text = run_text(r)
        if not INVISIBLE_RE.search(text) and not KEYCAP_RE.search(text):
            continue
        if not plain_run(r):  # 형광펜 등 표시가 든 조각은 글을 다시 쓰지 않고 글자만 뺌
            for t in r.findall(T("hp:t")):
                n0 = len(t_text(t))
                if t.text:
                    t.text = INVISIBLE_RE.sub("", t.text)
                for ch in t:
                    if ch.tail:
                        ch.tail = INVISIBLE_RE.sub("", ch.tail)
                cut += n0 - len(t_text(t))
            continue
        tabs = run_tabs(r)
        parts = KEYCAP_RE.split(text)
        caps += (len(parts) - 1) // 2
        cleaned = [x if k % 2 else INVISIBLE_RE.sub("", x) for k, x in enumerate(parts)]
        cut += sum(len(a) - len(b) for a, b in zip(parts[::2], cleaned[::2]))
        at, used = r, False
        for k, x in enumerate(cleaned):
            if not x:
                continue
            if used:
                twin = etree.Element(r.tag, dict(r.attrib))
                at.addnext(twin)
                at = twin
            used = True
            if k % 2:
                for t in at.findall(T("hp:t")):
                    at.remove(t)
                at.append(compose_el(x))
            else:
                set_run_text(at, x, None, tabs)
        if not used:
            set_run_text(r, "", None, tabs)
    return cut, caps


def compose_el(text, shape="SHAPE_RECTANGLE"):
    """글자 겹치기 요소(네모 숫자 — 한글 2024가 저장하는 모양 그대로)."""
    el = etree.Element(T("hp:compose"))
    for k, v in (("circleType", shape), ("charSz", "-3"), ("composeType", "SPREAD"), ("charPrCnt", "10"), ("composeText", text)):
        el.set(k, v)
    for _ in range(10):
        etree.SubElement(el, T("hp:charPr")).set("prIDRef", "4294967295")
    return el


def edit_run_text(run, text, tab_proto=None):
    """이미 있는 글을 고칠 때 — 탭은 그 조각의 탭 요소를 차례대로 그대로 옮긴다(목차 줄의 점선 채움 탭이 보통 탭이 되지 않게)."""
    return set_run_text(run, text, tab_proto, run_tabs(run))


def set_run_text(run, text, tab_proto=None, tabs=None):
    """run 안의 글을 text로 바꾼다. \\t·\\n·⎵·⍽는 탭·줄 바꿈·고정폭 빈칸·묶음 빈칸 요소가 된다.
    tabs: 탭 자리에 차례대로 쓸 탭 요소 목록(쓴 것은 빠짐). 다 쓰면 tab_proto."""
    text = _XML_BAD_RE.sub("", text.replace(COMPOSE_CHAR, ""))
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
        if name == "tab" and (tabs or tab_proto is not None):
            el = copy.deepcopy(tabs.pop(0) if tabs else tab_proto)
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
# 한 글자로 된 번호(① ⑴ ⒈ ⒜ ⓐ ⓪ ㉑ ㉠ ㉮ ㈀ ㈎ ㊱ ❶ ➀ ➊ Ⅰ ⅰ) — 글 첫머리에서 다른 뜻으로 쓰이지 않아 뒤에 빈칸이 없어도 머리 기호로 봄
NUM_CHARS = "①-⓿㈀-㈛㉑-㉟㉠-㉻㊱-㊿❶-➓Ⅰ-Ⅻⅰ-ⅻ" + COMPOSE_CHAR  # 네모 숫자는 유니코드에 없어 한글에서 글자 겹치기로 만듦
_NUM_CHAR_RE = re.compile(f"[{NUM_CHARS}]")


def is_num_char(ch):
    return bool(_NUM_CHAR_RE.fullmatch(ch))


_MARK_RE = re.compile(
    "^(?P<lead>[ \t⎵⍽　\u00a0]*)"
    r"(?P<mark>[" + re.escape(_SYM) + r"]|[Ⅰ-Ⅻⅰ-ⅻ]\.|(?:\d{1,2}|[가-하])-\d{1,2}[.)]|(?:\d{1,2}|[가-하]|[ㄱ-ㅎ]|[A-Za-z]|[ivxIVX]{1,4})[.)]"
    r"|\((?:\d{1,2}|[가-하]|[ㄱ-ㅎ]|[A-Za-z]|[ivxIVX]{1,4})\)|[<〈《【\[](?:\d{1,2}|[가-하]|[A-Za-z])[>〉》】\]]|\d{1,2}\ufe0f?\u20e3|[" + NUM_CHARS + r"])"
    "(?P<gap>[ \t⎵⍽　\u00a0]*)"
)


_TIGHT_HANGUL = "가나다라마바사아자차카타파하"


def _number_core(mark):
    return re.sub(r"[.()<>\[\]〈〉《》【】]", "", mark)


def _hangul_number(mark):
    """글자로 된 번호는 가나다 열네 글자만 — '(주) 대구'·'이. 내용'·'끝. 다음'은 글. '(사)'는 사단법인이라 글로 봄(검토: 작성 모드가 '(주)'를 지웠음)."""
    core = _number_core(mark)
    return core.split("-")[0] in _TIGHT_HANGUL and not (mark[0] == "(" and core == "사")


def _tight_number(mark, nxt):
    """빈칸 없이 붙여 쓴 순서 기호인가(nxt는 기호 다음 글자). '1.내용'·'가)내용'·'(1)내용'·'A.내용'·'Ⅰ.개요'는 번호,
    '1.5배'·'3.1운동'·'A.I.'·'U.S.'·'(주)대구'·'(사)협회'·'이.내용'은 글 — 글을 잘못 번호로 읽으면 작성 모드가 그 글자를 뺀다."""
    if is_num_char(mark[0]):
        return True
    if nxt.isdigit():
        return False
    core = _number_core(mark)
    if core[0].isdigit() or "ㄱ" <= core[0] <= "ㅎ":
        return True
    if "가" <= core[0] <= "힣":
        return True  # 가나다 글자인지는 split_marker가 먼저 가림
    return not nxt.isascii()  # 알파벳 기호는 뒤가 한글일 때만


# 조문 상자(법령 조문 발췌) 번호 줄의 들임 — 항(①)은 왼쪽 끝, 호(1.)는 두 칸(빈칸 두 개 = 글자 하나 폭), 목(가.)은 네 칸, 그 아래(1)·(1))는 여섯 칸
# (사용자 2026-11-11 '제2항부터는(거의 동그라미 숫자) 좌측에 딱 붙어서 시작할텐데, 제1호 부터는(거의 1. 2. 3.) 두칸 정도 띄어서 … 법률표시니까').
QUOTE_LEVEL_RE = ((re.compile(r"[①-⑳㉑-㉟㊱-㊿]"), 0), (re.compile(r"\d{1,2}\.(?!\d)"), 1), (re.compile(r"[가-하]\."), 2),
                  (re.compile(r"(?:\(\d{1,2}\)|\d{1,2}\))"), 3))


def quote_indent(text):
    """조문 상자 글 한 줄의 들임(글자 수) — 번호 줄이 아니면 None('제○조(…)'·이어진 글은 그대로)."""
    head, mark, _ = split_marker(text.lstrip(" 	⎵⍽　"))
    if not mark:
        return None
    core = mark.strip()
    for rx, em in QUOTE_LEVEL_RE:
        if rx.fullmatch(core):
            return em
    return None


def split_marker(text):
    """' ○ 내용' → (' ○ ', '○', '내용'). 머리 기호가 없으면 ('', '', text)."""
    m = _MARK_RE.match(text)
    if not m:
        return "", "", text
    mark = m.group("mark")
    if "가" <= _number_core(mark)[:1] <= "힣" and not _hangul_number(mark):
        return "", "", text
    if re.fullmatch(r"[A-Za-z]\.", mark) and re.match(r"[A-Za-z]\.", text[m.end():]):
        return "", "", text  # 'U. S. 정부' — 줄임말
    # '○○○ 추진계획(안)'처럼 같은 기호가 빈칸 없이 잇달아 오면 채울 자리를 보인 자리표시이지 머리 기호가 아니다
    # (기본 양식 제목 상자 — 제목 '1. 업무용 차량 운영'의 번호를 견본 기호 '○'와 다르다며 빼던 것, 2026-11-05 사용자 요청).
    if mark in _SYM and not m.group("gap") and text[m.end(): m.end() + 1] == mark:
        return "", "", text
    # '**굵게**' 표시의 별표는 머리 기호가 아니다.
    if mark in "*＊" and text[m.start("mark") + 1: m.start("mark") + 2] in ("*", "＊"):
        return "", "", text
    # 빈칸 없이 붙여 쓴 순서 기호는 다음 글자로 가린다('1.내용'은 번호, '1.5배'는 글).
    if not m.group("gap") and mark[0] not in _SYM and m.end() < len(text) and not _tight_number(mark, text[m.end()]):
        return "", "", text
    # '-' 뒤에 바로 숫자·영문이 오면 음수·기호일 수 있어, 끝도 '-'이면 '-끝-'이라 기호로 보지 않는다('-내용'은 기호).
    if mark in "-–—" and not m.group("gap") and m.end() < len(text) and (text[m.end()].isascii() or text.rstrip().endswith(mark)):
        return "", "", text
    return text[: m.end()], mark, text[m.end():]


# 기호 바로 뒤가 이런 말이면 띄우지 않는다: 조사('①과 ②', '*은')·조문('①항', '1)호')·자리표시 단위('○월 중', '○과')
_GAP_END = r"(?:[ ⎵⍽,.·)]|$)"
_NO_GAP_WORD = re.compile(r"(?:항|호|번|목|조)(?:[ ⎵⍽,.·)]|$|에|의|을|를|은|는|이|가|과|와|로|도|만|부터|까지)"
                          r"|(?:차|위|과|와|의|을|를|은|는|이|가|에|로|도|만|월|일|년|시|분|곳|개|명|건|대|원|회|층|동|팀|국|실|부|처|청|구|군|읍|면|리)" + _GAP_END +
                          r"|(?:형|급|종|안)(?:에|의|을|를|은|는|이|가|과|와|으로|로|도|만)?" + _GAP_END +  # '(A)형', 'B안으로'
                          r"|(?:에서|에게|에는|에도|부터|까지|으로|로서|로써|처럼|보다|만큼|이나|이며|이고|이다|라고|라는)" + _GAP_END +  # '①에서', '(1)부터'
                          r"|(?:월|일|년|개월|개소|억원|억|천만원|천만|백만원|백만|만원)(?:까지|부터|에는|에서|간|말|초|중|경|도)?" + _GAP_END)  # '○월까지', '○억원'
_NO_SA = _TIGHT_HANGUL.replace("사", "")
_SERIES_RE = re.compile(r"(?:^|\s)(?:\d{1,2}[.)](?!\d)|\(\d{1,2}\)|[" + _TIGHT_HANGUL + r"][.)]|\([" + _NO_SA + r"]\))\S")  # '3.5억원'·'(주)대구'는 번호 아님


def tight_marker_end(text):
    """기호 바로 뒤에 빈칸이 없어 한 칸 넣을 자리(글자 위치). 넣지 않을 글이면 None — '①로그인 ②업로드'·'□개인 □팀'처럼 잇단 기호, '①항'·'○월 중'."""
    pre, mark, rest = split_marker(text)
    if not mark or not rest or pre[-1] in " \t⎵⍽　\u00a0\n" or rest[0] in " \t⎵⍽　\u00a0\n":
        return None
    if not (rest[0].isalnum() or rest[0] in "「『“‘'\"(<[〈《【"):
        return None  # '□·○ 묶음'처럼 뒤가 또 부호면 글
    # 같은 기호가 또 나오면 잇단 기호 — 다만 -·*·ㆍ와 번호는 낱말 사이에도 쓰이므로 빈칸 뒤에 올 때만('-사업계획-안', '·항목·내용', '1.내용 2026.1.1.')
    again = mark in rest if mark in _SYM and mark not in "-–—·ㆍ∙*＊" else re.search(r"\s" + re.escape(mark), rest)
    if again or _NUM_CHAR_RE.search(rest) or _SERIES_RE.search(rest) or _NO_GAP_WORD.match(rest):
        return None
    return len(pre)


def insert_marker_gap(p):
    """붙여 쓴 기호 뒤에 빈칸 한 칸. 넣었으면 (조각, 옛 글) — 되돌릴 때 edit_run_text로. 아니면 None."""
    k = tight_marker_end(para_text(p))
    if k is None:
        return None
    pos = 0
    for r in para_runs(p):
        t = run_text(r)
        at, pos = pos, pos + len(t)
        if at <= k < pos:
            if not plain_run(r):
                return None
            edit_run_text(r, t[:k - at] + " " + t[k - at:])
            return r, t
    return None


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


NOT_LABEL = {"선택", "참고", "예시", "필수", "공통", "비고", "별첨", "주", "사", "재", "유", "합", "학", "의", "복", "가칭", "중략", "전략", "후략", "생략"}  # 괄호로 쓰지만 항목 이름이 아닌 말('(주) 대구상사'를 (   주   )로 벌리면 안 됨)


OMIT_MARK_RE = re.compile(r"[(（〈<]\s*(?:중|전|후|생)\s*략\s*[)）〉>]")  # 괄호 생략 표시 (중략)·(전략)·(후략)·(생략)
OMIT_DOTS = "···"  # 생략은 중점 세 개(사용자 2026-11-15 '중략 전략 후략은 괄호로 하지말고 앞이나 뒤 중점 각 세개씩으로')


_TAIL_RE = re.compile(r"[ ⎵⍽]*(?:\([^()]*\)|···|…|\.{3})[ ⎵⍽]*$")
_NARRATIVE_RE = re.compile(r"(?:다|[어아여해돼세에예죠]요|까|는지|은지|인지|할지|을지)[.?!]?$|\?$")  # '필요·수요·개요'는 개조식(Codex 검토)


def is_narrative(text):
    """글이 서술형(문장)으로 끝나는가 — '~다.'·'~니다.'·'~는지?'·'?'. 끝의 괄호(인용 출처 '(「하천법」 … 관련)')·생략 표시는 빼고 본다.
    개조식(명사형 '~함·~음·~됨', 명사)은 아님. 괄호 이름표 뒤 둘째 줄 자리를 가른다(사용자 2026-11-15 '서술형이면 제목의 (에 맞추는게
    맞다. 개조식이면 )에 맞추는게 맞다')."""
    t = text.rstrip(" ⎵⍽")
    while True:
        t2 = _TAIL_RE.sub("", t)
        if t2 == t or not t2:
            break
        t = t2
    return bool(_NARRATIVE_RE.search(t))


LABEL_LONG = 0.5  # 이름표 뒤로 넘어간 둘째 줄이 줄 폭의 이만큼 이상이면 '(' 자리에(사용자 2026-11-15 '50%이상')


def label_long(chs, lines):
    """이름표 뒤에 맞춰 잰 줄들(Layout.para_lines 결과)에서 둘째 줄이 긴가 — 셋째 줄까지 가거나, 둘째 줄 글이 첫 줄 폭의 절반 이상."""
    if len(lines) >= 3:
        return True
    return len(lines) == 2 and lines[1][2] >= LABEL_LONG * lines[0][3]


def fake_label(core, rest):
    """문장 머리 괄호가 이름표가 아닌 꼴인가: '(선택)'·'(참고)' 같은 말, 또는 괄호 뒤에 또 '항목명 : '이 오는 줄 — '(선택) 자동 시험(약 4분) : …'을
    이름표로 읽어 (선  택)으로 벌리고 내어쓰기를 22.6mm로 만들었음(양식 시험 2026-11-09)."""
    if re.sub(r"[\s⎵⍽]", "", core) in NOT_LABEL:
        return True
    return bool(re.match(r"[^:：,，]{1,20}[ ⎵⍽]:[ ⎵⍽]", rest.lstrip(" ⎵⍽")))


def label_content(text):
    """'○ (근  거) 내용'처럼 괄호 이름표가 있으면 이름표 뒤 내용이 시작하는 글자 위치. 없으면 0."""
    pre, mark, body = split_marker(text)
    if not re.match(r"\([^()\n]{1,12}\)", body if mark else text):
        return 0
    if OMIT_MARK_RE.match(body if mark else text):
        return 0  # (중략)은 이름표가 아님 — 둘째 줄을 그 뒤에 맞추면 붕 뜸(사용자 2026-11-15)
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


def clear_print_method(pkg):
    """모아찍기(settings.xml PrintMethod, 2쪽 모아찍기는 4)를 끈다 — 쪽 그림·쪽 수로는 드러나지 않고 인쇄·PDF에서만 한 장에 2쪽씩 묶인다
    (양식 파일에서 따라옴, 공모전 시험 2026-11-09). 돌려주는 것: 옛 값(꺼져 있었으면 None)."""
    if "settings.xml" not in pkg.data:
        return None
    for el in pkg.xml("settings.xml").iter():
        if el.get("name") == "PrintMethod" and (el.text or "0").strip() not in ("", "0"):
            old, el.text = el.text.strip(), "0"
            return old
    return None


def page_info(sec_root):
    """첫 구역의 용지·여백(mm)."""
    pp = sec_root.find(".//" + T("hp:pagePr"))
    if pp is None:
        return None
    m = pp.find(T("hp:margin"))
    mm = lambda v: _num(v) / HWPUNIT_PER_MM  # noqa: E731
    w, h = mm(pp.get("width")), mm(pp.get("height"))
    if pp.get("landscape") == "NARROWLY":  # 가로 쪽 — 저장값은 세로 그대로(59528×84186)이고 인쇄가 가로(한글 2024 확인 2026-11-09: PDF 841×595)
        w, h = max(w, h), min(w, h)
    info = {"width": w, "height": h, "landscape": pp.get("landscape")}
    if m is not None:
        for k in ("left", "right", "top", "bottom", "header", "footer"):
            info[k] = mm(m.get(k))
        gutter = mm(m.get("gutter"))  # 제본 여백: 위쪽 제본이면 높이에서, 그 밖에는 폭에서 빠짐
        if pp.get("gutterType") == "TOP_BOTTOM":
            info["top"] += gutter
            gutter = 0
        info["body_width"] = w - info["left"] - info["right"] - gutter
    return info
