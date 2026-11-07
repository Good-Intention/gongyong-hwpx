# -*- coding: utf-8 -*-
"""스냅숏: 문서 속 계획 예시를 만든 도구 출력(알림·어림 쪽 수·글 차례)을 tests/golden/에 적어 두고 판마다 비교한다.

규칙을 일부러 바꿨으면 출력도 바뀌는 것이 맞다 — 바뀐 곳을 읽어 보고 맞으면 다시 적는다:
    UPDATE_GOLDEN=1 python -m unittest tests/test_snapshots.py
바꾸려던 것이 아닌데 바뀌었으면 예전에 정한 규칙이 되돌아간 것이다(history.md에서 그 규칙을 찾아본다).
"""
import os
import re
import unittest

from common import GOLDEN, build, doc_plans, read


def _slug(name):
    return re.sub(r"[^0-9A-Za-z가-힣]+", "_", name).strip("_") + ".txt"


class Snapshots(unittest.TestCase):
    def test_doc_examples_snapshot(self):
        update = os.environ.get("UPDATE_GOLDEN") == "1"
        os.makedirs(GOLDEN, exist_ok=True)
        for key, name, plan in doc_plans():
            with self.subTest(example=name):
                _, out = build(plan)
                path = os.path.join(GOLDEN, _slug(key))
                if update:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(out)
                    continue
                self.assertTrue(os.path.exists(path), f"{name} 스냅숏이 없음 — UPDATE_GOLDEN=1로 처음 적기")
                want = read(path)
                self.assertEqual(out, want, f"{name} 출력이 바뀜 — 일부러 바꾼 것이면 UPDATE_GOLDEN=1로 다시 적기")


if __name__ == "__main__":
    unittest.main()
