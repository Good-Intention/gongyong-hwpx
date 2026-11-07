# -*- coding: utf-8 -*-
"""스킬 파일(gongyong-hwpx.skill) 묶기 — Releases에 올리는 것과 같은 모양(맨 위 폴더 gongyong-hwpx/, 압축 zip).

    python tools/package_skill.py              # dist/gongyong-hwpx.skill
    python tools/package_skill.py --compare 받은.skill   # 받은 파일이 지금 폴더와 내용이 같은지(같으면 끝 번호 0)

파이썬 캐시(__pycache__·.pyc)와 .DS_Store 같은 군더더기는 넣지 않는다. 파일 차례·시각을 고정해 같은 내용이면 같은 파일이 나온다.
"""
import argparse
import hashlib
import os
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "gongyong-hwpx"
SKILL = os.path.join(ROOT, NAME)
SKIP_DIRS = {"__pycache__", ".git"}
SKIP_FILES = {".DS_Store", "Thumbs.db"}
STAMP = (2026, 1, 1, 0, 0, 0)


def skill_files():
    out = []
    for dirpath, dirs, files in os.walk(SKILL):
        dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
        for f in sorted(files):
            if f in SKIP_FILES or f.endswith((".pyc", ".pyo")):
                continue
            full = os.path.join(dirpath, f)
            out.append((os.path.relpath(full, ROOT).replace(os.sep, "/"), full))
    return out


def package(out_path):
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        for arc, full in skill_files():
            info = zipfile.ZipInfo(arc, STAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with open(full, "rb") as f:
                z.writestr(info, f.read())
    with open(out_path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def compare(skill_path):
    """받은 .skill의 파일 목록·내용이 지금 폴더와 같은지. 다른 것 목록을 돌려준다."""
    want = {arc: full for arc, full in skill_files()}
    diff = []
    with zipfile.ZipFile(skill_path) as z:
        names = {n for n in z.namelist() if not n.endswith("/")}
        for n in sorted(names - set(want)):
            if not (n.endswith((".pyc", ".pyo")) or "/__pycache__/" in n):
                diff.append(f"받은 파일에만 있음: {n}")
        for arc, full in sorted(want.items()):
            if arc not in names:
                diff.append(f"받은 파일에 없음: {arc}")
                continue
            with open(full, "rb") as f:
                if z.read(arc) != f.read():
                    diff.append(f"내용이 다름: {arc}")
    return diff


def main():
    ap = argparse.ArgumentParser(description="스킬 폴더를 .skill 파일로 묶는다")
    ap.add_argument("--out", default=os.path.join(ROOT, "dist", f"{NAME}.skill"))
    ap.add_argument("--compare", help="받은 .skill이 지금 폴더와 같은지 보기")
    a = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if a.compare:
        diff = compare(a.compare)
        for d in diff:
            print(" - " + d)
        print("같음" if not diff else f"다름 {len(diff)}곳")
        sys.exit(1 if diff else 0)
    sha = package(a.out)
    print(f"묶음: {a.out} ({len(skill_files())}개 파일)")
    print(f"sha256: {sha}")


if __name__ == "__main__":
    main()
