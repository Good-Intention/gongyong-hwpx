# -*- coding: utf-8 -*-
"""한글 2024 맞대기 — 관리자 PC의 회귀 시험과 같은 방식(tools/hangul_truth.py).

정답(tests/hangul/이름.json)은 한글 2024가 실제로 그린 PDF에서 한 번 뽑아 둔 것이다: 한글 쪽 수, PDF의 줄마다 글,
문단마다 한글 줄 수, 만들 때 결과(base). 시험은 한글 없이 돈다 — 도구 어림(layout·fit)이 그 정답보다 나빠지지 않았는지
(쪽 수, 줄이 같은 문단 수, 정답 때 맞던 문단이 깨졌는지) 본다. PDF를 읽는 별도 패키지가 필요 없다.

예시 보고서를 새 판으로 다시 만들면 한글 2024에서 PDF도 다시 저장하고 정답을 다시 만든다:
    HANGUL_TRUTH_DIR=tests/hangul python tools/hangul_truth.py make 예시_보고서 예시_보고서/○○.hwpx 예시_보고서/○○.pdf
"""
import glob
import hashlib
import io
import os
import unittest
from contextlib import redirect_stdout

from common import EXAMPLE_DIR, ROOT

TRUTH_DIR = os.path.join(ROOT, "tests", "hangul")
os.environ["HANGUL_TRUTH_DIR"] = TRUTH_DIR   # hangul_truth를 불러오기 전에 정답 폴더를 정함
TOOLS = os.path.join(ROOT, "tools")


def _sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


class HangulMatch(unittest.TestCase):
    def test_truth_files_exist(self):
        names = sorted(os.path.basename(p)[:-5] for p in glob.glob(os.path.join(TRUTH_DIR, "*.json")))
        self.assertIn("예시_보고서", names)
        for n in names:
            self.assertTrue(os.path.exists(os.path.join(TRUTH_DIR, f"{n}.hwpx")), f"{n}.hwpx가 정답 옆에 없음")

    def test_example_is_the_same_file(self):
        """정답 옆 hwpx가 예시_보고서/의 hwpx와 같아야 한다(예시만 바꾸고 정답을 안 만든 경우를 잡음)."""
        shown = glob.glob(os.path.join(EXAMPLE_DIR, "*.hwpx"))
        self.assertEqual(len(shown), 1, shown)
        self.assertEqual(_sha(shown[0]), _sha(os.path.join(TRUTH_DIR, "예시_보고서.hwpx")),
                         "예시 보고서가 바뀌었는데 정답이 그대로 — 한글 2024 PDF로 정답을 다시 만들 것(맨 위 설명)")

    def test_not_worse_than_hangul(self):
        import sys
        if TOOLS not in sys.path:
            sys.path.insert(0, TOOLS)
        import hangul_truth
        self.assertEqual(os.path.normpath(hangul_truth.DIR), os.path.normpath(TRUTH_DIR))
        buf = io.StringIO()
        with redirect_stdout(buf):
            bad = hangul_truth.check()
        self.assertEqual(bad, 0, "한글 2024 정답보다 나빠짐(어림을 고칠 것 — 정답은 한글로만 바꿈):\n" + buf.getvalue())


if __name__ == "__main__":
    unittest.main()
