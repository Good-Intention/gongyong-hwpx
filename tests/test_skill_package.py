# -*- coding: utf-8 -*-
"""스킬 파일 자체 검사: 설명문(불리는 조건), 늘 읽는 분량, 지난 판 약속, 판 표시.

늘 읽는 분량 상한(BUDGET)을 넘으면 규칙을 더하기 전에 겹치는 설명부터 덜어 낸다 — 도구가 하는 일은 auto-fit.md로,
날짜·사용자 말은 history.md로. 꼭 늘려야 하면 상한을 올리되 커밋에 이유를 적는다.
"""
import os
import re
import unittest

from common import ROOT, SCRIPTS, SKILL, read

# SKILL.md + style-guide.md + plan-format.md: 계획 파일을 쓸 때마다 읽는 문서(바이트, UTF-8)
BUDGET = 51_000  # v1.24(51,081B)보다 늘지 않게
# 견본이 없을 때 더 읽는 기본 양식 번호표까지
BUDGET_WITH_MAP = 58_500


def _frontmatter():
    text = read(os.path.join(SKILL, "SKILL.md"))
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md 맨 위에 --- 머리말이 없음"
    fm = {}
    for line in m.group(1).splitlines():
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip().strip('"')
    return fm, text[m.end():]


def _current_version():
    m = re.search(r"지금 판: \*\*v(\d+)\.(\d+)\*\*", read(os.path.join(ROOT, "README.md")))
    assert m, "README.md에 '지금 판: **v1.xx**' 줄이 없음"
    return int(m.group(1)), int(m.group(2))


class Frontmatter(unittest.TestCase):
    def test_name(self):
        fm, _ = _frontmatter()
        self.assertEqual(fm.get("name"), os.path.basename(SKILL))
        self.assertRegex(fm["name"], r"^[a-z0-9]+(-[a-z0-9]+)*$")
        self.assertLessEqual(len(fm["name"]), 64)

    def test_description(self):
        fm, _ = _frontmatter()
        d = fm.get("description", "")
        self.assertTrue(d, "description이 비었음")
        self.assertLessEqual(len(d), 1024, "description은 1,024자 이내(Agent Skills 규격)")
        self.assertNotRegex(d, r"[<>]", "description에 꺾쇠(< >)를 쓰면 올리기가 거부될 수 있음")
        self.assertIn("/gongyong-hwpx", d)

    def test_body_length(self):
        _, body = _frontmatter()
        self.assertLess(body.count("\n"), 500, "SKILL.md 본문은 500줄 아래로(자세한 것은 references/로)")


class ContextBudget(unittest.TestCase):
    def test_always_read_size(self):
        size = lambda rel: os.path.getsize(os.path.join(SKILL, rel))
        core = sum(size(r) for r in ["SKILL.md", "references/style-guide.md", "references/plan-format.md"])
        self.assertLessEqual(core, BUDGET, f"늘 읽는 분량 {core:,}B > 상한 {BUDGET:,}B")
        self.assertLessEqual(core + size("references/basic-report-map.md"), BUDGET_WITH_MAP)

    def test_referenced_files_exist(self):
        _, body = _frontmatter()
        for rel in sorted(set(re.findall(r"`((?:scripts|references|assets)/[^`\s]+)`", body))):
            with self.subTest(path=rel):
                self.assertTrue(os.path.exists(os.path.join(SKILL, rel)), f"SKILL.md가 가리키는 {rel}이 없음")


class StalePromises(unittest.TestCase):
    def test_no_past_version_promises(self):
        """도구 출력·문서에 'v1.22에서 넓힙니다'처럼 이미 지난 판을 약속하는 말이 남지 않게."""
        cur = _current_version()
        pat = re.compile(r"v(\d+)\.(\d+)(?:에서|부터|판에서)\s*(?:넓힙|고칩|합니|됩니|바꿉|더합|나옵)")
        files = [os.path.join(SCRIPTS, f) for f in os.listdir(SCRIPTS) if f.endswith(".py")]
        files += [os.path.join(SKILL, "SKILL.md"), os.path.join(ROOT, "README.md")]
        files += [os.path.join(SKILL, "references", f) for f in os.listdir(os.path.join(SKILL, "references"))
                  if f != "history.md"]
        for path in files:
            for m in pat.finditer(read(path)):
                with self.subTest(file=os.path.relpath(path, ROOT), text=m.group(0)):
                    self.assertGreater((int(m.group(1)), int(m.group(2))), cur, "이미 지난 판을 약속함")


if __name__ == "__main__":
    unittest.main()
