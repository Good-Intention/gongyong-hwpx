# -*- coding: utf-8 -*-
"""시험에서 함께 쓰는 경로·도우미. 시험은 저장소 맨 위에서 `python -m unittest discover -s tests -v`로 돌린다.

tests/ 폴더는 스킬 파일(.skill)에 들어가지 않는다 — 스킬은 gongyong-hwpx/ 폴더만 묶는다.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL = os.path.join(ROOT, "gongyong-hwpx")
SCRIPTS = os.path.join(SKILL, "scripts")
BASIC = os.path.join(SKILL, "assets", "basic_report.hwpx")
EXAMPLE_DIR = os.path.join(ROOT, "예시_보고서")
GOLDEN = os.path.join(ROOT, "tests", "golden")

# 문서마다 들어 있는 계획 파일 예시(```json … ```)를 찾을 곳
DOCS = ["SKILL.md", "references/write.md", "references/basic-report-map.md", "references/plan-format.md",
        "references/plan-format-advanced.md", "references/style-guide.md", "references/doc-types.md",
        "references/cover.md", "references/boxes-figures.md"]

sys.dont_write_bytecode = True  # 스킬 폴더(scripts/)에 __pycache__를 남기지 않음
if SCRIPTS not in sys.path:
    sys.path.insert(0, SCRIPTS)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def doc_plans():
    """문서 속 JSON 예시 가운데 그대로 만들 수 있는 '온전한 계획'(blocks가 있고 맨 앞이 제목 상자)만 돌려준다.
    [(열쇠, 이름, 계획)] — 열쇠는 '파일#차례'(스냅숏 파일 이름), 이름은 '파일:줄'(알림용)."""
    out = []
    for rel in DOCS:
        path = os.path.join(SKILL, rel)
        text = read(path)
        k = 0
        for m in re.finditer(r"^```json\n(.*?)^```", text, re.S | re.M):
            try:
                plan = json.loads(m.group(1))
            except json.JSONDecodeError:
                continue  # 문법 설명용 조각({블록} 같은 자리표시)
            blocks = plan.get("blocks") if isinstance(plan, dict) else plan
            if not isinstance(blocks, list) or not blocks or blocks[0].get("like") != 0:
                continue
            line = text[:m.start()].count("\n") + 1
            k += 1
            out.append((f"{rel}#{k}", f"{rel}:{line}", plan))
    return out


def build(plan, template=BASIC, brief=False):
    """계획을 만들어 (끝 번호, 출력 글)을 돌려준다. 출력 첫 줄(만든 파일 경로)은 뺀다."""
    with tempfile.TemporaryDirectory() as d:
        pf = os.path.join(d, "plan.json")
        with open(pf, "w", encoding="utf-8") as f:
            json.dump(plan, f, ensure_ascii=False)
        cmd = [sys.executable, os.path.join(SCRIPTS, "build.py"), "--template", template, "--plan", pf,
               "--out", os.path.join(d, "out.hwpx")] + (["--brief"] if brief else [])
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONIOENCODING="utf-8")
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", env=env)
    lines = r.stdout.splitlines()
    return r.returncode, "\n".join(lines[1:]) + ("\n" + r.stderr if r.stderr else "")


def fix_count(output):
    m = re.search(r"^## 한눈에: 고쳐야 함 (\d+)건", output, re.M)
    return int(m.group(1)) if m else None
