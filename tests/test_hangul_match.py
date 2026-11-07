# -*- coding: utf-8 -*-
"""한글 2024 기준값과 도구 어림 맞대기.

예시_보고서/의 .hwpx는 이 스킬로 만든 파일이고, .pdf는 그 파일을 한글 2024로 연 그대로 PDF로 저장한 것이다.
도구가 어림한 쪽 수와 본문 문단 줄 바꿈이 PDF와 같아야 한다(어림 코드 layout·fit을 고친 뒤 되돌아가지 않게).

예시 보고서를 새 판으로 다시 만들면 PDF도 한글에서 다시 저장해 둘 다 바꾼다.
"""
import glob
import os
import re
import unittest

from common import EXAMPLE_DIR

try:
    import pdfplumber
except ImportError:  # CI에서는 설치함
    pdfplumber = None

NORM = re.compile(r"[\s⎵⍽ ]")


def _files():
    hw = glob.glob(os.path.join(EXAMPLE_DIR, "*.hwpx"))
    pdf = glob.glob(os.path.join(EXAMPLE_DIR, "*.pdf"))
    return (hw[0] if hw else None), (pdf[0] if pdf else None)


@unittest.skipIf(pdfplumber is None, "pdfplumber가 없음(pip install pdfplumber)")
class HangulMatch(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from build import Builder
        from hwpx_lib import HWPUNIT_PER_MM, Package, T, page_info, para_tables
        from layout import Layout

        cls.hwpx, cls.pdf = _files()
        if not cls.hwpx or not cls.pdf:
            raise unittest.SkipTest("예시_보고서에 .hwpx·.pdf가 함께 없음")
        b = Builder(Package(cls.hwpx))
        lay = Layout(b.styles, b.metrics)
        body_w = page_info(b.sec)["body_width"] * HWPUNIT_PER_MM
        cls.est = []  # 본문 문단마다 어림한 줄 글
        for p in b.sec:
            if p.tag != T("hp:p") or para_tables(p):
                continue
            chs, lines = lay.para_lines(p, body_w)
            if chs and lines:
                cls.est.append([NORM.sub("", "".join(c[0] for c in chs[s:e])) for s, e, *_ in lines])
        cls.pdf_lines, cls.pdf_pages = [], 0
        with pdfplumber.open(cls.pdf) as d:
            cls.pdf_pages = len(d.pages)
            for pg in d.pages:
                cls.pdf_lines += [NORM.sub("", ln) for ln in (pg.extract_text() or "").split("\n")]

    def test_page_count(self):
        from review import Inspector
        pages, _, _ = Inspector(self.hwpx).run(tables=True)
        m = re.search(r"어림 쪽 수 (\d+)쪽", pages)
        self.assertIsNotNone(m, pages)
        self.assertEqual(int(m.group(1)), self.pdf_pages, f"어림 {pages} / 한글 2024 PDF {self.pdf_pages}쪽")

    def test_body_line_breaks(self):
        """어림한 줄마다 그 글이 PDF에 한 줄로 그대로 있어야 한다(한글이 줄을 더 나누거나 덜 나누면 어긋남)."""
        pdf = set(self.pdf_lines)
        lines = [ln for para in self.est for ln in para if len(ln) >= 2]
        self.assertGreaterEqual(len(lines), 20, "비교할 줄이 너무 적음 — 예시 보고서가 바뀌었는지 확인")
        miss = [ln for ln in lines if ln not in pdf]
        self.assertEqual(miss, [], f"{len(lines)}줄 중 {len(miss)}줄이 한글 2024 줄 바꿈과 다름")


if __name__ == "__main__":
    unittest.main()
