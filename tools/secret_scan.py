# -*- coding: utf-8 -*-
"""공개·배포 파일의 비밀정보 점검(개발용, 읽기만): API 키·개인정보·이 PC 경로, 한글 파일 속 작성자 표시, 그림·PDF 메타데이터.

    python -X utf8 tools/secret_scan.py [폴더·파일 …]     # 기본: 저장소 전체(개발 PC에서는 dist/release, dist/*.skill, dist/*.zip)

한글 파일·.skill·.zip은 안까지 열어 본다. 찾은 값은 앞 두 글자만 보이고 가린다(이 출력이 또 다른 유출이 되지 않게).
끝 번호: 0 없음, 1 '위험' 있음. '확인'은 사람이 볼 것(공개된 업무 전화 등).
"""
import io
import os
import re
import sys
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.stdout.reconfigure(encoding="utf-8")

SECRET = [
    ("API 키", re.compile(r"\b(?:sk-(?:ant-)?[A-Za-z0-9_-]{20,}|ghp_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}|gho_[A-Za-z0-9]{30,}"
                         r"|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|xox[baprs]-[A-Za-z0-9-]{10,}|glpat-[A-Za-z0-9_-]{15,})")),
    ("비밀 키 파일", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("값이 적힌 비밀 항목", re.compile(r"(?i)\b(?:api[_-]?key|secret|password|passwd|service_?key|access_?token|auth_?token|oc_?key)\b\s*[:=]\s*['\"]?[A-Za-z0-9_\-+/=.]{12,}")),
    ("인증 머리글", re.compile(r"Bearer\s+[A-Za-z0-9._\-]{20,}")),
]
PERSONAL = [
    ("주민등록번호 꼴", re.compile(r"(?<!\d)\d{6}-[1-4]\d{6}(?!\d)")),
    ("휴대전화", re.compile(r"(?<![\d.])01[016789][- .]\d{3,4}[- .]\d{4}(?!\d)")),
    ("이메일", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")),
    ("이 PC 경로", re.compile(r"[A-Za-z]:[\\/]Users[\\/][^\\/\s\"'<>]+|/home/[a-z_][a-z0-9_-]*/|/Users/[A-Za-z0-9_-]+/")),
]
CHECK = [("일반 전화번호", re.compile(r"(?<![\d.-])0(?:2|[3-6][1-5])-\d{3,4}-\d{4}(?!\d)"))]
SAFE_MAIL = re.compile(r"@(?:example\.|users\.noreply\.github\.com|noreply\.)", re.I)
TEXT_EXT = (".md", ".py", ".json", ".txt", ".yml", ".yaml", ".xml", ".hpf", ".rdf", ".cfg", ".ini", ".toml", ".csv", ".html", ".svg", ".ps1", ".bat", ".sh", ".gitignore", ".env")
ZIP_EXT = (".hwpx", ".skill", ".zip", ".docx", ".xlsx", ".pptx")
IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tif", ".tiff")
BAD_NAMES = {".env", ".env.local", "id_rsa", "id_ed25519", "credentials.json", "token.json", "secrets.json"}
META_RE = re.compile(r'<opf:meta name="([^"]+)"[^>]*>([^<]*)</opf:meta>')
META_NAMES = {"creator", "lastsaveby", "publisher", "contributor"}


def mask(s):
    s = s.strip()
    return s[:2] + "*" * min(6, max(0, len(s) - 2))


class Scan:
    def __init__(self):
        self.danger, self.check = [], []
        self.seen = 0

    def text(self, name, t):
        for kind, rx in SECRET + PERSONAL:
            for m in rx.finditer(t):
                v = m.group(0)
                if kind == "이메일" and SAFE_MAIL.search(v):
                    continue
                self.danger.append((kind, name, mask(v)))
        for kind, rx in CHECK:
            for m in rx.finditer(t):
                self.check.append((kind, name, mask(m.group(0))))

    def hpf(self, name, t):
        for key, val in META_RE.findall(t):
            if key.lower() in META_NAMES and val.strip():
                self.check.append((f"한글 문서 표시 {key}", name, mask(val)))
        for tag in ("dc:creator", "dc:publisher", "opf:creator"):
            for val in re.findall(rf"<{tag}[^>]*>([^<]+)</{tag}>", t):
                self.check.append((f"한글 문서 표시 {tag}", name, mask(val)))

    def image(self, name, data):
        try:
            from PIL import Image
            im = Image.open(io.BytesIO(data))
            exif = im.getexif()
            tags = {271: "제조사", 272: "기종", 305: "프로그램", 315: "작성자", 33432: "저작권", 34853: "GPS"}
            for k, label in tags.items():
                if k in exif and exif.get(k) not in (None, "", {}):
                    hit = (f"그림 정보 {label}", name, mask(str(exif.get(k))))
                    (self.danger if k in (315, 34853) else self.check).append(hit)
            for k, v in (im.info or {}).items():
                if isinstance(v, (str, bytes)) and k.lower() in ("author", "software", "comment", "description", "xml:com.adobe.xmp"):
                    self.check.append((f"그림 정보 {k}", name, mask(v if isinstance(v, str) else v.decode("latin-1"))))
        except Exception:  # noqa: BLE001 — 그림이 아니면 넘어감
            pass

    def pdf(self, name, data):
        t = data.decode("latin-1")
        for key in ("Author", "Creator", "Producer", "Title"):
            for m in re.finditer(rf"/{key}\s*\(([^)]*)\)", t):
                if m.group(1).strip():
                    self.check.append((f"PDF 정보 {key}", name, mask(m.group(1))))
        self.text(name, t)

    def blob(self, name, data, depth=0):
        self.seen += 1
        low = name.lower()
        base = os.path.basename(low.split("!")[-1])
        if base in BAD_NAMES:
            self.danger.append(("비밀 파일 이름", name, base))
        if low.endswith(ZIP_EXT) and depth < 3:
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    for n in z.namelist():
                        if not n.endswith("/"):
                            self.blob(f"{name}!{n}", z.read(n), depth + 1)
                return
            except zipfile.BadZipFile:
                self.check.append(("열리지 않는 묶음", name, ""))
                return
        if low.endswith(IMG_EXT):
            self.image(name, data)
            return
        if low.endswith(".pdf"):
            self.pdf(name, data)
            return
        if low.endswith(TEXT_EXT) or "." not in base or base.startswith("."):
            t = data.decode("utf-8", "ignore")
            self.text(name, t)
            if low.endswith(".hpf"):
                self.hpf(name, t)

    def path(self, p):
        if os.path.isdir(p):
            for dp, dn, fs in os.walk(p):
                dn[:] = [d for d in dn if d not in (".git", "__pycache__", ".venv")]
                for f in fs:
                    self.path(os.path.join(dp, f))
        elif os.path.isfile(p):
            with open(p, "rb") as fp:
                self.blob(os.path.relpath(p, ROOT), fp.read())


def show(rows, title):
    print(f"## {title} {len(rows)}곳")
    grouped = {}
    for kind, name, val in rows:
        grouped.setdefault(kind, []).append((name, val))
    for kind, items in grouped.items():
        files = {}
        for name, val in items:
            files.setdefault(name, set()).add(val)
        print(f" - {kind}: {len(items)}곳, 파일 {len(files)}개")
        for name, vals in list(files.items())[:6]:
            print(f"     {name[:96]} {sorted(vals)[:3]}")
        if len(files) > 6:
            print(f"     … 그 밖 파일 {len(files) - 6}개")


def main():
    targets = sys.argv[1:]
    if not targets:
        d = os.path.join(ROOT, "dist")
        if os.path.isdir(os.path.join(d, "release")):  # 개발 PC — 공개·배포되는 것만
            targets = [os.path.join(d, "release")] + [os.path.join(d, f) for f in os.listdir(d) if f.endswith((".skill", ".zip"))]
        else:  # 공개 저장소
            targets = [ROOT]
    s = Scan()
    for t in targets:
        s.path(t)
    print(f"본 파일 {s.seen}개")
    show(s.danger, "위험")
    show(s.check, "확인")
    sys.exit(1 if s.danger else 0)


if __name__ == "__main__":
    main()
