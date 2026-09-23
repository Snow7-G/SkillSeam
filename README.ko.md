# SkillSeam

[English](README.md) | [简体中文](README.zh-CN.md) | [日本語](README.ja.md) | **한국어** | [Español](README.es.md) | [Deutsch](README.de.md)

<p align="center">
  <img src="assets/banner.svg" alt="SkillSeam" width="720">
</p>

에이전트가 스킬을 실제로 고르는 과정을 시뮬레이션하고, 어떤 스킬이 누구의 작업을 가로채는지 밝혀냅니다. 사용자가 알아채기 전에.

## 문제

Claude Code, Codex 같은 에이전트 런타임은 스킬을 로드할 때 description의 두세 줄만 읽습니다. 작업이 들어오면 가장 그럴듯해 보이는 스킬을 고릅니다.

description이 겹치지 않으면 잘 동작합니다. 겹치는 순간 문제가 생깁니다. 병원 데모에서 예약 스킬의 description에 "시력 검사 보고서 문의 접수"가 포함되어 있었고, 실제 담당은 보고서 해석 스킬이었습니다. 환자가 보고서 해석을 요청하자 예약 스킬이 응답하고, 사실을 지어냅니다. 에러도 없고, 로그도 없습니다. 환자 불만 접수로 알게 되었습니다.

SkillSeam은 출시 전에 이 선택 과정을 재현합니다. 6개 스킬, 40개 태스크 데모에서 심어둔 4건의 충돌을 모두 찾아냈고(투표 일치도 5/5), 깨끗한 태스크는 하나도 놓치지 않았습니다. 각 충돌 리포트는 가로챈 스킬 description 안의 원인 키워드까지 짚어줍니다.

## 빠른 시작 (웹, 설치 없음)

[https://snow7-g.github.io/SkillSeam/](https://snow7-g.github.io/SkillSeam/) 을 열고 데모 버튼을 누르면 10초 안에 히트맵이 나옵니다. 자신의 스킬을 붙여넣고, API 키를 추가하고(키는 브라우저에만 저장, 요청은 프로바이더로 직행), 실행하세요.

SKILL.md 파일로 관리 중이라면 페이지의 「选择技能文件夹」 버튼으로 폴더를 고르면 바로 읽어옵니다(브라우저 안에서만 파싱, 업로드 없음). 붙여넣기용으로 출력하려면:

```bash
python3 skill_seam.py export ~/.agents/skills
```

## CLI (로컬 디렉터리, CI 게이트)

```bash
git clone https://github.com/Snow7-G/SkillSeam && cd SkillSeam
echo '{"base_url": "https://.../v1", "api_key": "sk-...", "model": "..."}' > .atlasrc.json
python3 skill_seam.py ~/.agents/skills
open output/report.html
```

종료 코드: 0 충돌 없음, 1 충돌 발견, 2 설정 오류. CI 게이트는 한 줄입니다:

```bash
python3 skill_seam.py ./skills --tasks ci-tasks.json
```

## 생성된 질문보다 실제 질문이 강합니다

먼저 솔직한 한계부터: LLM이 생성하는 테스트 태스크에는 편향이 있습니다. 문제를 만드는 모델은 어느 스킬이 이겨야 하는지 알기 때문에 쉽게 통과합니다. 데모에서 생성 태스크는 충돌 0건, 실제 사용자 질문은 4건을 찾아냈습니다. 같은 스킬, 같은 모델.

그래서 실제 질문을 모으는 세 가지 방법이 내장되어 있습니다:

```bash
# 한 번만 설정: Claude Code에 보내는 모든 프롬프트가 조용히 로컬에 기록됩니다
python3 skill_seam.py capture --install-claude

# 에이전트가 잘못 고르는 순간을 포착하면, 영구 테스트 자산으로 저장
python3 skill_seam.py mark "复诊的时候顺便查下会员积分" followup-reminder

# 기록된 프롬프트(또는 Codex 세션 로그)에서 라벨付き 태스크 초안을 수확
python3 skill_seam.py harvest ./skills --codex --label --out tasks-draft.json
```

초안을 검토하고, 기대 스킬을 채우고, 실행하세요. 실제 사고 10건이면 어떤 생성기보다 좋은 태스크 세트가 됩니다.

생성된 태스크도 스모크 테스트로는 유용합니다. 다만 녹색 보고서를 충돌 없음의 증거로 삼지는 마세요.

## 동작 방식

1. 스킬 디렉터리를 훑고 각 SKILL.md의 프론트매터를 파싱해 형식을 검사합니다.
2. 태스크 세트를 구성: 스킬별 명확한 질문에 더해, 두 스킬이 겹치는 경계에 일부러 모호한 질문을 배치합니다.
3. 선택 재현: 모델에는 name과 description만 에이전트와 같은 형식으로 전달하고, 태스크마다 하나의 스킬을 고르게 합니다. 태스크당 5회, temperature 0.7.
4. 다수결로 집계. 5회 중 4회 이상 같은 잘못된 선택에 일치할 때만 충돌로 계산합니다. 그 미만은 불안정으로 표시해 리포트를 오염하지 않습니다.

리포트는 혼동 행렬 히트맵이 들어간 단일 HTML 파일입니다. 충돌이 있으면 description 수정안(전/후 대조)도 생성해 다시 검증할 수 있게 해줍니다.

## 유사 도구와의 비교

| 도구 | 검사 항목 | 범위 |
|---|---|---|
| agnix | 형식 규칙(프론트매터, 네이밍) | 단일 파일 |
| skilltest | 스킬 하나가 단독으로 트리거되는지 | 단일 스킬 |
| SkillSpector (NVIDIA) | 보안(인젝션, 유출, 공급망) | 단일 스킬 |
| **SkillSeam** | 조합 후의 선택 행동: 누가 누구의 작업을 가로채나 | 스킬 세트 전체 |

경쟁 관계가 아니라 보완입니다. 스킬별로 lint과 보안 스캔을 돌린 뒤, 세트 전체에 SkillSeam을 실행하세요.

## 알아둘 점

시뮬레이션은 주입 형식에 충실하지만 실제 에이전트 프로세스를 구동하지는 않습니다. 런타임 간 차이(Codex와 Claude의 선택이 다른가)는 로드맵에 있습니다. Codex 세션 파서는 관대한 추출기라, 툴 출력이 수집 후보에 섞일 수 있습니다. 웹 UI는 현재 중국어입니다.

## 이름의 유래

충돌은 스킬 안에 살지 않습니다. 두 스킬 사이의 이음선에 살고, 누군가 당기면 풀립니다. SkillSeam은 이음선을 검사합니다.

탐지 리포트는 Sirens Report(세이렌 보고서)라고 부릅니다. 하이네가 가장 잘 표현했습니다:

> Ich weiß nicht, was soll es bedeuten,
> dass ich so traurig bin.

처녀가 그 자리에 앉아 황금 머리를 빗으며 노래합니다. 뱃사공은 노래를 듣고 암초가 보이지 않습니다.

모든 description은 노래합니다. 어떤 노래는 당신의 태스크를 암초로 유인합니다.

## 개발

```bash
python3 tests/test_atlas.py   # 58 테스트, 표준 라이브러리만 사용
node tests/web_smoke.cjs      # 19 웹 어설션, node >= 18
```

CI는 Python 3.10 / 3.12 / 3.13에서 둘 다 실행합니다. PR 전에 CONTRIBUTING.md를 확인하세요.

## 라이선스

MIT
