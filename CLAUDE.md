# 이 저장소에서 일할 때(개발용 — 스킬 파일에는 들어가지 않음)

공무원 한글문서 편집스킬(`/gongyong-hwpx`)의 공개 저장소다. 사용자는 대구시청 현직 공무원이고, 결과 한글 파일을 보고 고칠 점을 말로 준다. 그 말이 곧 규칙이 된다.

## 원본은 관리자 PC에 있다

- 이 저장소의 `gongyong-hwpx/`는 **배포판 사본**이다. 원본(개발판)은 관리자 PC에 있고, 판을 낼 때 배포판 만들기 도구가 개인·기관 흔적(이름·부서·시험 문서 이름)을 바꾼 사본을 만들어 올린다. 여기서 `gongyong-hwpx/`를 직접 고치면 다음 판에 덮어써진다 — 고친 것은 브랜치에 두고, 관리자가 PC 원본에 옮겨 PC 시험을 통과시킨 뒤 다음 판으로 낸다.
- **PC에서만 도는 시험**: 회귀(시험 계획마다 쪽 수·고쳐야 함 수·서식 상태 통째 대조, 사람이 쓴 문서 검사만)와 한글 2024 맞대기(비공개 기관 문서 포함). 여기 `tests/`는 그 가운데 공개해도 되는 것만이고, 같은 방식·같은 파일 형식을 쓴다.
- 판을 낼 때 스킬 폴더와 이 저장소의 개발용 파일(`tests/`·`tools/`·`CLAUDE.md`·`.github/`·`README.md`) 모두 개인·기관 흔적이 0건이어야 올린다. 여기에 사람 이름·전화·기관 내부 문서를 넣지 않는다(○로).

## 짜임

| 곳 | 무엇 | .skill에 들어가나 |
|---|---|---|
| `gongyong-hwpx/` | 스킬 자체: SKILL.md·references/·scripts/·assets/ | 들어감(이 폴더만) |
| `tests/` | 공개 시험: 문서 속 계획 예시 '고쳐야 함 0건'·출력 스냅숏(`golden/`)·한글 2024 맞대기(`hangul/` — PC 회귀와 같은 정답 형식)·스킬 파일 검사 | 안 들어감 |
| `tools/package_skill.py` | .skill 묶기·받은 .skill 대조(PC 묶기 도구와 같은 검사·같은 넣는 파일) | 안 들어감 |
| `tools/hangul_truth.py`·`tools/pdf_glyphs.py` | 한글 2024 PDF에서 정답 뽑기·맞대기(PC 회귀와 같은 파일, 별도 패키지 없음) | 안 들어감 |
| `tools/secret_scan.py` | API 키·개인 연락처·PC 경로·문서와 그림 속 작성자 점검(PC 도구와 같은 파일, 올릴 때마다 자동) | 안 들어감 |
| `예시_보고서/` | 스킬로 만든 4쪽 보고서 .hwpx + 그것을 한글 2024로 저장한 .pdf + 미리보기 | 안 들어감 |
| `.github/workflows/` | 올릴 때 시험, 릴리스 때 .skill 대조·붙이기 | — |

## 규칙을 더하거나 바꿀 때

- **규칙 하나 = 고침 + 시험 + 설명서 한 곳 + history.md 한 줄.**
- **한 주제 = 한 파일 한 곳**: 글·짜임·표·배치 원칙은 `style-guide.md`, 작성 순서는 `write.md`, 계획 파일 문법은 `plan-format.md`(덜 쓰는 항목은 `plan-format-advanced.md`), 번호표는 `basic-report-map.md`, 종류별 차례는 `doc-types.md`, 표지는 `cover.md`, 도표·그림·제목 걸친 상자·참고1 발췌는 `boxes-figures.md`, 낱말은 `words.md`, 정돈은 `tidy.md`, 검사만은 `review.md`, 도구 동작은 `auto-fit.md`, 내력은 `history.md`(모두 `references/`). 같은 규칙을 두 곳에 쓰지 않는다.
- **도구가 지키는 규칙은 한 줄**: build.py가 '고쳐야 함'에 규칙과 고치는 법을 적어 주는 것은 설명서에 규칙 한 줄만 두고, 어떻게 하는지는 `auto-fit.md`에만 쓴다.
- **참고 파일은 SKILL.md에서 한 단계**: 무엇을 언제 읽는지는 SKILL.md가 가리킨다. 참고 파일끼리 읽으라고 서로 가리키지 않는다.
- **내력**: `references/history.md` 표에 날짜 | 규칙 | 사용자 말(따옴표 그대로) 한 줄. 옛 규칙을 뒤집으면 그 줄에 "(→ 날짜에 뒤집힘)".
- **사용자가 정한 값은 그대로**: 다시 만들기 횟수·간격·글자 크기처럼 history.md에 사용자 말이 있는 값은 바꾸지 않는다 — 바꾸고 싶으면 이유와 함께 먼저 묻는다.
- **SKILL.md는 길잡이만**(약 3KB — 모드 갈림길·모드마다 읽을 파일·늘 지킬 것 네 줄·전달하기). 규칙을 SKILL.md에 옮겨 적지 않는다.
- **늘 읽는 분량 상한**: 작성 모드에서 늘 읽는 SKILL.md + write.md + style-guide.md + plan-format.md가 `tests/test_skill_package.py`의 `BUDGET`을 넘으면, 규칙을 더하기 전에 겹치는 설명을 덜어 낸다. 꼭 늘려야 하면 상한을 올리고 그 자리 주석과 커밋에 이유를 적는다.
- **문서 속 계획 예시**(basic-report-map.md 끝의 ```json — 한 곳)는 모델이 그대로 본뜬다 — 늘 '고쳐야 함 0건'이어야 한다(`tests/test_doc_examples.py`).
- **글은 쉬운 우리말**: 도구 알림·README·SKILL.md에 개발 용어(JSON·XML·run 등)를 사용자에게 하는 말로 쓰지 않는다. 도구 알림은 사용자에게 그대로 옮겨질 수 있다.
- **지난 판을 약속하는 말 금지**: "v1.22에서 넓힙니다"처럼 판 번호로 약속하지 말고 "다음 판"으로(시험이 잡음).

## 고친 뒤

```bash
export PYTHONDONTWRITEBYTECODE=1           # 스킬 폴더에 파이썬 캐시를 남기지 않음
pip install lxml                           # 처음 한 번(한글 맞대기도 별도 패키지 없이 돎)
python tools/secret_scan.py                # 위험 0건이어야 올림
python -m unittest discover -s tests -v    # 모두 통과해야 올림
```

- 스냅숏(`tests/golden/`)이 바뀌었다고 나오면: 일부러 바꾼 규칙 때문인지 출력 차이를 읽어 보고, 맞으면 `UPDATE_GOLDEN=1 python -m unittest discover -s tests -p "test_snapshots.py"`로 다시 적어 함께 커밋한다. 바꾸려던 것이 아닌데 바뀌었으면 예전 규칙이 되돌아간 것 — history.md에서 그 규칙을 찾는다.
- 한글 맞대기(`tests/test_hangul_match.py`)는 `tests/hangul/`의 정답(한글 2024 PDF에서 뽑아 둔 쪽 수·줄마다 글·문단 줄 수)보다 어림이 나빠지면 실패한다 — 어림(layout·fit)을 고친다. **정답은 한글로만 바꾼다**: 예시 보고서를 다시 만들면 한글 2024에서 PDF도 다시 저장하고 `HANGUL_TRUTH_DIR=tests/hangul python tools/hangul_truth.py make 예시_보고서 예시_보고서/○○.hwpx 예시_보고서/○○.pdf`로 정답을 다시 만든다.

## 판 올리기

- 판 번호는 작게(v2.1 → v2.2 → …), 큰 방향 전환만 앞자리(v2.0 → v3.0).
- 커밋 말머리: `v2.x 도구:` / `v2.x 설명서:` / `v2.x SKILL.md:` / `v2.x README:` / `v2.x 예시 보고서:` / `v2.x 시험:` — 무엇을 왜 바꿨는지 사용자 말로.
- 바꿀 곳: README의 `지금 판: **v2.x**`와 '바뀐 점', history.md 내력, 필요하면 예시 보고서(정답도 함께).
- 릴리스: 태그 `v2.x`로 Releases에 내고, 관리자가 PC에서 만든 배포판 .skill을 붙인다. `release.yml`이 시험 뒤 붙은 파일을 태그의 스킬 폴더와 대조하고(다르면 실패), 안 붙어 있으면 묶어 붙인다. 손으로 묶을 때는 `python tools/package_skill.py`.
- 사용자에게: 새 .skill을 쓰는 AI 앱(Claude·ChatGPT의 스킬 설정)에 다시 올려야 대화에서 새 판이 쓰인다고 알린다.
