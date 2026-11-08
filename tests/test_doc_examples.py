# -*- coding: utf-8 -*-
"""문서 속 계획 예시는 모델이 그대로 본떠 쓴다 — 예시가 도구 검사에 걸리면 첫 빌드가 늘 '고쳐야 함'으로 시작한다.
그래서 온전한 계획 예시는 모두 '고쳐야 함 0건'이어야 한다."""
import unittest

from common import build, doc_plans, fix_count


class DocExamples(unittest.TestCase):
    def test_examples_found(self):
        names = [n for _, n, _ in doc_plans()]
        self.assertTrue(any(n.startswith("SKILL.md") for n in names), names)
        self.assertTrue(any(n.startswith("references/basic-report-map.md") for n in names), names)

    def test_examples_pass_checks(self):
        for _, name, plan in doc_plans():
            with self.subTest(example=name):
                code, out = build(plan, brief=True)
                self.assertEqual(fix_count(out), 0, f"{name} 예시가 검사에 걸림:\n{out}")
                self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
