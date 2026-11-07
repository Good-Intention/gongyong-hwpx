# 이 저장소에서 일할 때(개발용 — 스킬 파일에는 들어가지 않음)

공무원 한글문서 편집스킬(`/gongyong-hwpx`)을 만드는 저장소다. 사용자는 대구시청 현직 공무원이고, 결과 한글 파일을 보고 고칠 점을 말로 준다. 그 말이 곧 규칙이 된다.

## 짜임

| 곳 | 무엇 | .skill에 들어가나 |
|---|---|---|
| `gongyong-hwpx/` | 스킬 자체: SKILL.md·references/·scripts/·assets/ | 들어감(이 폴더만) |
| `tests/` | 시험(문서 예시·스냅숏·한글 2024 맞대기·스킬 파일 검사) | 안 들어감 |
| `tools/package_skill.py` | .skill 묶기·받은 .skill 대조 | 안 들어감 |
| `예시_보고서/` | 스킬로 만든 4쪽 보고서 .hwpx + 그것을 한글 2024로 저장한 .pdf(맞대기 기준값) | 안 들어감 |
| `.github/workflows/` | 올릴 때 시험, 릴리스 때 .skill 붙이기·대조 | — |

## 규칙을 더하거나 바꿀 때

- **규칙 본문은 한 곳**: 글·짜임·표·쪽 원칙은 `references/style-guide.md`. 도구가 해 주는 것은 끝에 "(도구)"를 붙이고, 어떻게 하는지는 `references/auto-fit.md`에만 쓴다(style-guide에 방법을 되풀이하지 않음).
- **내력**: `references/history.md` 표에 날짜 | 규칙 | 사용자 말을 그대로 따옴표로 한 줄. 옛 규칙을 뒤집으면 그 줄에 "(→ 날짜에 뒤집힘)".
- **SKILL.md는 흐름만**(무엇을 언제 읽고 돌리나). 규칙을 SKILL.md에 옮겨 적지 않는다.
- **늘 읽는 분량 상한**: SKILL.md + style-guide.md + plan-format.md가 `tests/test_skill_package.py`의 `BUDGET`을 넘으면, 규칙을 더하기 전에 겹치는 설명을 덜어 낸다. 꼭 늘려야 하면 상한을 올리고 커밋에 이유를 적는다.
- **문서 속 계획 예시**(SKILL.md·basic-report-map.md의 ```json)는 모델이 그대로 본뜬다 — 늘 '고쳐야 함 0건'이어야 한다(`tests/test_doc_examples.py`).
- **글은 쉬운 우리말**: 도구 알림·README·SKILL.md에 개발 용어(JSON·XML·run 등)를 사용자에게 하는 말로 쓰지 않는다. 도구 알림은 사용자에게 그대로 옮겨질 수 있다.
- **지난 판을 약속하는 말 금지**: "v1.22에서 넓힙니다"처럼 판 번호로 약속하지 말고 "다음 판"으로(시험이 잡음).

## 고친 뒤

```bash
export PYTHONDONTWRITEBYTECODE=1           # 스킬 폴더에 파이썬 캐시를 남기지 않음
pip install lxml pdfplumber                # 처음 한 번
python -m unittest discover -s tests -v    # 모두 통과해야 올림
```

- 스냅숏(`tests/golden/`)이 바뀌었다고 나오면: 일부러 바꾼 규칙 때문인지 출력 차이를 읽어 보고, 맞으면 `UPDATE_GOLDEN=1 python -m unittest discover -s tests -p "test_snapshots.py"`로 다시 적어 함께 커밋한다. 바꾸려던 것이 아닌데 바뀌었으면 예전 규칙이 되돌아간 것 — history.md에서 그 규칙을 찾는다.
- 줄 바꿈·쪽 어림(layout·fit)을 고쳤으면 `tests/test_hangul_match.py`가 한글 2024 PDF와 맞댄다. 예시 보고서를 다시 만들면 한글 2024에서 PDF도 다시 저장해 둘 다 바꾼다.
- 비공개 시험 문서(기관 문서 원본)는 저장소에 올리지 않는다. 공개해도 되는 것만 `tests/`에, 사람 이름·전화는 ○로.

## 판 올리기

- 커밋 말머리: `v1.xx 도구:` / `v1.xx 설명서:` / `v1.xx SKILL.md:` / `v1.xx README:` / `v1.xx 예시 보고서:` — 무엇을 왜 바꿨는지 사용자 말로.
- 바꿀 곳: README의 `지금 판: **v1.xx**('26. ○. ○.)`, history.md 내력, 필요하면 예시 보고서.
- 릴리스: 태그 `v1.xx`로 Releases에 내면 `release.yml`이 시험 후 .skill을 붙인다(손으로 붙였으면 태그 내용과 같은지 대조). 손으로 묶을 때는 `python tools/package_skill.py`.
- 사용자에게: 새 .skill을 claude.ai(설정 → Skills)에 다시 올려야 대화에서 새 판이 쓰인다고 알린다.
