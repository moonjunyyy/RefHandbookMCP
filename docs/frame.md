# 사이트 프레임 — 상속·활성·위젯·UI 규칙 (2026-11-01)

기준 문서. 사이트의 모든 화면과 앱이 공유하는 것(프레임)이 무엇이고 어디서 오는지, 사람의 것(테마·언어·켠 앱·홈)이 어떻게 모든 앱에 닿는지, 앱이 홈에 무엇을 올리는지, 화면 요소를 낳는 규칙이 무엇인지를 한 번에 정한다. 캘린더·볼트는 이 관례 안에서의 자리만 정하고 백엔드는 `docs/projects.md` 의 단계 3·4 가 만든다.

## 0. 원리 둘
<!-- sec:s0 basis: U1 U2 A1 -->

1. **상속 — 프레임 → 앱.** 테마(토큰)·부품(CSS)·프레임 코드(JS)의 주인은 로그인(SSO, `/auth`)이고, 모든 화면은 그것을 `<link>`·`import` 한 줄로 받는다. 덮어쓰기는 CSS 캐스케이드다: 앱이 자기 CSS 에서 토큰을 다시 선언하면 그 앱만 바뀐다. `site.toml` 에 테마 필드는 없다 — 링크가 선언이다.
2. **기여 — 앱 → 프레임.** 앱은 자기 선언(`[[app]]`)에 위젯을 덧붙이고, 프레임은 사람이 켠 앱의 위젯을 홈에 배치한다. 프레임은 앱의 데이터를 알지 못한다: 위젯 모듈이 제 앱의 API 를 부른다.

사람의 것은 한 자리(`/apps/site/api/store/prefs`)에 있고, 모든 화면은 프레임 코드로 같은 자리를 읽는다. 언어가 이미 그렇게 흐른다; 테마·켠 앱·홈이 같은 길을 탄다.

## 1. 프레임 — 무엇을 어디서
<!-- sec:s1 basis: A1 A6 C1 E1 -->

| 파일 (`/auth/static/`) | 담는 것 | 받는 쪽 |
|---|---|---|
| `theme.css` | 토큰만: `:root` 의 색·글꼴·그림자·반지름, `[data-theme=dark]`, 그리고 `prefers-color-scheme` 폴백(`:root:not([data-theme=light])`) | 토큰만 쓰는 앱(자기 부품을 가진 앱) |
| `parts.css` | 부품: 프레임(header·main)·card·section·chips·tag·flash·form·button·table·app-list·flow-* … 토큰만 참조하고 색 리터럴 0 | 부품까지 쓰는 앱 |
| `style.css` | `@import` 둘 — 지금 링크의 호환 이름 | 지금의 web/·eq-sandbox |
| `theme.js` | 세 줄: `theme` 쿠키를 읽어 `<html data-theme>` 를 첫 칠 전에 세운다(동기, `<head>` 의 첫 줄) | 모든 화면 |
| `site.js` (+ `site.d.ts`) | 프레임 코드(ESM): `load()`(me + prefs), `frame`, `prefs`·`save()`, `applyTheme`·`setLang`·`t`(프레임의 말), `header()`, 부품 함수(`pageHead`·`section`·`flash`·`act`·`form`·`button`·`toggle`·`select`·`link`·`go`·`tag`·`help`·`dialog`), 위젯 호스트(`mount`) | 모든 화면 — `import { … } from '/auth/static/site.js'` |

- **출처.** `web/frame/*.ts` 가 원본이고 `npm run build` 가 `src/portal/static/site.js`(vite lib, ES, 축소 없음, 의존성 0)와 `site.d/`·`site.d.ts`(tsc 선언)를 낸다. 둘 다 **커밋한다**: 설치본은 페이지 빌드 없이도 프레임을 서빙해야 한다. CSS 둘은 손으로 쓴다. 설치는 지금처럼 SSO 의 static 마운트가 서빙한다.
- **계약과 버전.** 토큰 이름·부품 클래스·`site.js` 의 export 가 공개 API 다. `site.js` 는 `export const version = 1`, `/auth/api/v1/me` 도 `frame: 1` 을 돌려준다. 깨뜨리는 변경은 `/auth/static/v2/` 로 나란히 두고 옛 것을 남긴다 — 페이지와 서비스가 따로 갱신되는 지금 원칙의 연장.
- **왜 런타임 import 인가.** 앱(eq-sandbox, 글타래)은 저장소가 따로라 빌드 시점에 `web/` 을 못 본다; 런타임이면 프레임이 바뀌어도 앱 재배포가 없고, 브라우저 캐시에 한 벌이다. CSP `default-src 'self'` 안이다. 타입은 `site.d.ts` 를 앱이 복사해 `import type` 한다.
- **첫 칠.** `theme.js` 가 쿠키로 `data-theme` 를 먼저 세우고, `theme.css` 는 속성이 없으면 OS 를 따른다. 쿠키가 없는 새 브라우저는 OS 를 따르다가 `site.js` 의 `load()` 가 계정의 값을 읽어 쿠키를 쓰고 속성을 고친다 — 언어 쿠키와 같다.

### 1.1 토큰 (계약)
`--bg --card --soft --text --muted --line --accent --accent-hover --accent-text --accent-soft --ok --bad --bad-text --warn --shadow --shadow-pop --scrim --serif --sans --mono --radius --radius-s`. 테마 값은 `auto | light | dark`; 이름 있는 팔레트는 쓰일 때 `[data-theme=<name>]` 블록 하나로 더한다(지금은 만들지 않는다). 부품·앱·`web/src` 에 색 리터럴이 0 임을 테스트가 잰다(통과 기준 1) — 그림자·스크림도 토큰이다.

### 1.2 부품의 시그니처가 규칙이다 (4절과 함께)
- `pageHead(heading, tabs?)` — **설명 인자가 없다.** 머리는 이름과 탭뿐.
- `section(heading, ...body)` — 설명 문단을 받지 않는다; 본문이 곧 설명이다.
- `button(verb, fn, kind?)` — 글은 동사 하나; `act` 가 누르는 동안 잠그고 실패만 `flash` 한다. 성공은 제자리의 상태 변화가 말한다.
- `toggle(label, on, fn)` — 켜고 끄기는 스위치(즉시 저장). 버튼이 아니다.
- `select(name, choices, value, fn)` — 하나 고르기. 바뀌는 즉시 저장.
- `link(href, …)` — 이동은 글 링크. `buttonLink` 는 없앤다(이동이 버튼처럼 보이는 유일한 자리는 빈 상태의 첫 행동뿐이고, 그것은 `primaryLink`).
- `help(text)` — 설명이 남아야 할 때의 **유일한** 자리: ⓘ 하나, 눌러야 보인다. 한 줄.
- 데이터가 제 자신을 말하는 한 줄(앱의 설명)은 설명 문단이 아니라 `.desc` 다 — 래칫은 `p.muted` 만 센다.
- `flash(kind, text, action?)` — 다른 자리에서 난 결과(저장됨·오류) 한 줄, 고정 토스트, 자동으로 사라짐; 되돌릴 수 있으면 `action` 하나.
- `dialog(title, body, {ok, cancel})` — 파괴와 입력은 대화상자에서; Enter/Esc.

### 1.3 모양 — 사람이 고르는 토큰 (7차)
테마(밝음·어두움)와 나란히 사람이 고르는 **모양**: 색(팔레트) · 모서리 · 글꼴 · 글자 크기 · 홈 칸 수 · 배경 이미지. 고를 것은 코드가 아니라 사이트 파일의 선언이다.
- **선언.** `site.toml [look]` — `[[look.palette]]`(id·label·tr, `light`·`dark` 가 같은 토큰 이름을 다시 선언: `accent`·`accent-hover`·`accent-text`·`accent-soft`), `[[look.corner]]`·`[[look.type]]`·`[[look.size]]`(id·label·tr·`tokens`), `columns = [0, 2, …]`(0 = 들어가는 만큼). 각 종류의 첫 선택이 theme.css 그대로(토큰 없음). `portal/site.py _look` 이 검사한다(종류·id·label, 토큰 이름은 theme.css 의 꼴, 값에 `;{}<>` 없음, 팔레트의 light/dark 같은 키, columns 0–12); `/auth/api/v1/me` 가 `look` 으로 그 사람의 언어로 내려 준다.
- **저장과 적용.** `prefs.look = {palette?, corner?, type?, size?, columns?, image?}`(고른 id; 기본이면 키가 없다). `site.js applyLook()` 이 고른 선택들의 토큰을 `<html>` 의 사용자 속성으로 CSSOM 에 놓는다(`style.setProperty` — CSP 가 인라인 `<style>` 을 막아도 된다; 인라인은 테마 선택자보다 앞선다). 팔레트는 지금의 테마(`data-theme` 또는 OS)의 값; 테마가 바뀌면 다시 놓는다. 칸 수는 `--home-grid`, 이미지는 `--page-image`(https:// 또는 이 사이트의 `/…` 주소만 — `IMAGE` 정규식; 이 밖은 받지 않는다).
- **첫 칠.** `applyLook()` 은 놓은 토큰을 이 브라우저(`localStorage.look`: `{light, dark, both}`)에도 두고, `theme.js` 가 다음 첫 칠 전에 그것을 놓는다 — site.js 없이(e2e: theme.js 하나뿐인 페이지가 이미 고른 색·모서리를 입는다).
- **닿는 자리.** 모서리는 parts.css 의 모든 둥글기가 `--radius`·`--radius-s` 이기 때문에 닿는다(남는 것은 알약 999px·원 50%·3px 이하 — test_frame 이 잰다); 글자 크기는 뿌리 크기 `--root-size` 를 rem 이 따른다; 글꼴은 `--sans`. 선언된 팔레트마다 두 테마에서 부품이 만드는 짝(버튼 글·호버, 페이지·카드 위 링크, 연한 바탕 위 호버)이 4.5:1 이상임을 test_site 가 잰다.
- **화면.** 설정의 '모양' 묶음: 종류마다 칩 한 줄(팔레트 칩은 그 색의 점), 기본이 아니면 옆에 '기본값'; 홈 칸 수 칩(자동·n칸); 배경 이미지 주소 + 적용(Enter).
- **밖.** SSO 의 로그인 화면은 CSP `default-src 'self'` 라 바깥(https) 배경 이미지는 그 화면에서 보이지 않는다(사이트 화면은 nginx 정적 서빙이라 보인다).

## 2. 사람의 것 — prefs
<!-- sec:s2 basis: U2 U4 A4 A6 E1 -->

```
Prefs { lang: 'auto'|'ko'|'en', theme: 'auto'|'light'|'dark', start: string,
        apps: string[],            // 켠 앱, 그 순서 — 저장된 설정이 없으면 사이트 파일이 default = true 로 표시한 앱(6차 R14)
        home: {app, widget, size?}[],  // 홈의 위젯 배치, 그 순서와 (바꿨으면) 크기 — 기본 [] (= 켠 앱의 실행기, 켠 순서)
        seen: string[],
        look: {palette?, corner?, type?, size?, columns?, image?} }  // 7차 §1.3 — 기본이면 키 없음
```

- **기본은 쓸 수 있는 상태(5차 R13, 6차 R14).** 저장된 설정이 없는 계정(새 계정)은 사이트 파일이 `default = true` 로 표시한 앱(프로젝트·캘린더·노트, 그 순)이 켜진 채 시작한다 — `/me` 의 `card.default` 로 오고 코드에 앱 이름은 없다; 저장된 `apps` 는 빈 목록이라도 그 사람의 선택이라 그대로다. 켜지 않은 앱은 헤더·홈·시작 페이지 후보에 없다. 켜고 끄는 자리는 가게(`/apps`)뿐이다 — 홈은 가게가 아니다(3차). `optional = false` 인 앱(계정)은 켜고 끌 수 없고 헤더의 이름 메뉴에 산다.
- **쿠키 둘.** `lang`·`theme` 은 저장과 함께 사이트 쿠키로도 쓴다(서버 페이지와 첫 칠이 읽는다). `me` 는 둘을 돌려준다.
- **옛 데이터.** `hidden`·`order` 는 읽을 때 `apps` 로 옮긴다(`order` 의 순서로, `hidden` 을 뺀 것을 켠 앱으로) — 지금 계정이 빈 홈으로 깨어나지 않게. 저장 데이터는 고치지 않는다.
- **첫 읽기.** 저장된 적 없는 키는 404 로 답하고 브라우저는 그것을 콘솔 오류로 적는다. 그래서 계정의 설정을 아직 본 적 없는 브라우저는 저장소 목록(`/apps/site/api/store`)을 먼저 묻고, 한 번 본 뒤에는 바로 읽는다(`localStorage` 표식).

## 3. 앱 — 카탈로그·켜기·검색
<!-- sec:s3 basis: U2 U3 A4 A7 -->

- `/apps` = **가게**(7차에서 다시 짬, `docs/apps-vault-calendar.md` §1.2). 첫 요소는 검색 입력(초점), 다음은 칩 한 줄(전체 · 태그들 — 하나 고르기), 다음은 **내 앱**: 추가한 앱마다 타일 하나(큰 아이콘 위 이름 — 누르면 그 앱; 타일의 ⋯·우클릭에 '앱 정보'·'빼기'), 추가한 순서. 그 아래 **추가할 수 있는 앱**: 아직 추가하지 않은 앱마다 카드(큰 아이콘·이름(링크 → `/app/<id>`)·태그라인·태그)와 행동 하나 '추가'. 스위치는 없다 — 한 화면에 모든 앱이 켬/끔으로 늘어서지 않는다. 추가한 앱은 헤더와 홈에 바로 나타난다. 상세(`/app/<id>`)의 행동 하나: '추가', 또는 '열기'(첫 행동)와 그 옆 '빼기'.
- 카드의 순서는 사이트 파일의 순서(진열), 타일은 추가한 순서. 검색은 이름·태그라인·소개·태그·링크 이름을 보고 타일과 카드를 함께 거르며 `/apps?q=&tag=` 로 주소에 남는다.
- '새 앱' 알림은 카탈로그 행의 태그 하나로 줄인다; 홈의 flash 는 없앤다.
- `site.toml`: `[[app]]` 에 `optional`(기본 true) 과 `[[app.widget]]`(4절) 이 는다. 그 밖의 선언은 그대로.

## 4. 홈 — 위젯
<!-- sec:s4 basis: U1 U4 A4 A6 E1 -->

### 4.1 계약
```
[[app.widget]]
id = "boards"                # 앱 안에서 유일
title = "최근 작업판"
description = "최근에 연 작업판으로 바로"   # 한 줄(80자): 고르는 사람이 읽는 것 (5차 R12)
module = "widget.js"         # 정적 앱: /apps/<id>/ 기준 상대 경로; 서비스: 절대 경로(/calendar/widget.js)
size = "1x1"                 # portal/site.py SIZES 의 하나(1x1 | 2x1 | 1x2 | 2x2) — 기본 크기; 사람이 배치마다 바꾼다
tr.en = { title = "Recent boards", description = "Straight to the boards you opened last" }
```
- 렌더러는 `site.py` 가 검증한다(없는 `module`·중복 `id`·모르는 `size`·80자를 넘는 `description` 은 거부; `tr.<lang>` 은 title 이나 description 을 말한다). `me.cards[].widgets` 로 내려간다 — `{id, title, description, href, size}`, 사람의 언어로; `me.sizes` 가 크기 표 자체(`[{id, cols, rows}]`)를 나르고 프레임은 그것으로 칸의 span 을 inline style 로 만든다(`spanStyle`), 크기별 클래스는 없다.
- 모듈 계약: `export default (host, ctx) => void | (() => void)`; `ctx = { frame, prefs, t, lang, theme, go, api, card, widget }`. 요소 빌더(`h`)·부품은 모듈이 `/auth/static/site.js` 에서 직접 import 한다 — 페이지와 같은 길. 모듈은 제 앱의 API 만 부른다(`/apps/<id>/api/…`, `/calendar/api/v1/…`) — 브라우저의 사이트 쿠키와 nginx 의 경로별 토큰이 그대로 통한다. 스타일은 토큰과 부품으로만. 정적 앱은 모듈을 `public/widget.js` 에 두면 vite 가 dist 뿌리에 그대로 복사한다(eq-sandbox 의 `boards` 가 그 예).
- **기본 위젯.** 모듈을 선언하지 않은 앱은 '실행기'(아이콘·이름·링크) 위젯 하나를 가진다 — 지금의 카드 격자는 그 퇴화형이다.
- 실패(모듈 404·예외)는 그 칸을 실행기로 대체하고 콘솔에만 남긴다.

### 4.2 화면
- 홈의 첫 요소는 격자다 — 사람이 배치한 위젯, 배치가 없으면 켠 앱의 실행기(= 앱 메뉴). 인사 문장·'내 계정'·'설정' 버튼은 없다(이름은 헤더에 있다).
- 조작은 격자 위에서, 모드 없이(6차 R15): 위젯 머리(실행기는 칸)를 끌어 다른 칸에 놓으면 순서가, 모서리 손잡이를 끌면 크기가(선언 크기로 스냅) 바뀌어 저장된다; 칸의 ⋯(hover)·우클릭·Shift+F10 메뉴에 크기 전부·앞으로·뒤로·빼기; 초점 둔 칸은 Alt+←→·Delete. 격자의 마지막 칸 '위젯 고르기'(키 w; 7차 — 격자 위의 도구 줄과 설명 ⓘ 은 없앴다): 앱별 묶음 아래 위젯마다 한 행 — 스위치(바로 저장)·제목·설명·크기 `c×r` — 짚은 행의 위젯이 옆에 그대로 뜬다(R16). 설정 페이지의 '홈 화면' 절은 없다.
- 빈 상태(켠 앱을 다 끈 계정) = '앱 추가' 하나(`primaryLink` → `/apps`); 새 계정은 비어 있지 않다(2절 R13). 문장이 아니라 행동이고, 홈이 가게를 그리지는 않는다 — 앱을 켜고 끄는 일은 가게의 것(3차 — "메인화면이 웹스토어가 아닙니다"); 테스트가 home.ts 의 가게 import 를 막는다.
- 로그인 전 홈 = 사이트 이름 + '로그인' 하나 + 공개 앱의 실행기.

## 5. UI — 생성 규칙과 감사
<!-- sec:s5 basis: U1 U4 A4 A12 -->

현재 화면을 낳은 규칙은 "기능마다 요소 하나 + 설명 하나" 였다. 결과: pageHead 설명 12곳, 본문 설명 문단 25곳 이상, 이동이 버튼(홈 '내 계정'·'설정', 앱 '열기'), 상태가 버튼(앱 '홈에서 숨기기', 설정 '초기화'), 순서가 버튼(설정 ↑↓), 결과가 문장(act 의 ok flash). 바꾸는 규칙:

| 규칙 | 뜻 | 강제 |
|---|---|---|
| R1 요소 = 결정 | 화면 요소 하나는 사람의 결정 하나(이동·실행·값). 정보는 요소가 아니라 내용 | 부품 시그니처 |
| R2 종류는 의미로 | 이동=링크, 실행=버튼, 켜고 끄기=스위치, 하나 고르기=select/칩, 순서=끌기, 찾기=입력 하나 | `buttonLink` 삭제, `toggle`·`select` 부품, 테스트 |
| R3 설명은 실패의 표시 | 요소가 제 뜻을 못 말하면 이름을 고친다. 남는 설명은 `help()` 한 줄뿐 | `pageHead` 에 intro 없음; 설명 문단 래칫 테스트(전 페이지 0) |
| R9 간격은 행이 정한다 | 아이콘은 제 여백을 갖지 않는다; 아이콘·글자의 간격(4–12px)과 수직 중심(≤2px), 한 행의 높이·중심, 잘림 0, 헤더 줄바꿈 0 은 행(nav·위젯 머리·실행기·카드·칩)의 규칙이고 측정한다 | `web/e2e/layout.js`(run.sh 의 셋째 측정) |
| R4 한 화면 한 주인 | 첫 요소가 그 페이지의 일(홈=격자, 앱=검색+행, 설정=값 셋) | 각 페이지 |
| R5 기본값으로 동작 | 설정 없이 쓰인다; '초기화' 절 대신 값 옆 '기본값' | 설정 |
| R6 결과는 제자리 | 바뀐 요소가 바뀐 상태를 보인다; flash 는 다른 자리의 결과만 | `act` 의 ok 인자 삭제 |
| R7 동사 하나, 파괴는 두 걸음 | 버튼 글은 동사; 지우기는 대화상자에서 이름을 친다 | `dialog` |
| R8 메뉴는 사람의 것 | 헤더 = 사이트 이름 · 켠 앱 · 이름(계정·설정·로그아웃은 이름 메뉴 안) | `header()` |
| R10 동작은 객체의 자리 (5차) | 화면의 객체(일정·날짜 칸·캘린더·볼트·노트·트리 항목·할 일·위젯 칸)는 제 자리에서 제 동작을 연다 — 우클릭 = ⋯ = Shift+F10, 같은 메뉴. 대화상자는 글을 받을 때만 | `menu()`·`onMenu()`·`menuButton()`; 대비·배치 측정에 메뉴 패스 |
| R11 상태는 다음 행동과 함께 (5차) | '준비 중'·'오류' 는 이유(사람의 말)와 지금 할 수 있는 동작을 한 카드에; 서비스의 거절은 `{error: "왜"}` 를 그대로 보인다 | 볼트 상태 카드; `api()` 가 문자열 `error` 를 메시지로 |
| R12 고르기는 설명과 함께 (5차) | 고르는 것은 이름·한 줄 설명·크기(또는 경로)를 보이고, 행 높이는 글 두 줄(≤ 44px) | 위젯 `description`; `.pick-row`; e2e 가 행 높이를 잰다 |
| R13 기본은 쓸 수 있는 상태 (5차) | 새 계정은 빈 홈이 아니라 일상 앱이 켜진 채 시작한다; 끄는 것은 가게에서 | site.toml `default = true` → `/me`; 저장된 선택은 그대로 |
| R14 치수는 토큰, 선언은 한 곳 (6차) | 간격·아이콘·칸 높이는 theme.css 의 토큰(--s1…--s5·--pad·--gap·--icon·--icon-big·--cell); 기본 앱·크기 표는 site.toml·site.py 의 선언 하나를 /me 로 받는다 — 코드에 그 복사본이 없다 | test_frame: parts.css 간격 px 래칫, 프레임의 앱 id 0·크기 id 0, /me 의 sizes·default |
| R15 조작은 객체 위에서, 모드 없이 (6차) | 옮기기 = 머리 끌기, 크기 = 모서리 끌기, 나머지 = 메뉴와 Alt+←→·Delete; 편집 모드 없음 | home.ts; e2e |
| R16 미리보기는 그 모듈, 키는 선언 (6차) | 고르는 행을 짚으면 그 위젯 모듈이 옆에 뜬다; 페이지의 키는 `keys()` 표로 선언되고 `?` 가 그 표를 보인다; 대화상자는 초점이 어디든 Enter = 확인, Esc = 취소 | `mount()` 로 미리보기; `keys()`·`keysDialog()`; `dialog()` 의 keydown |
| R17 꾸밈은 사람이 고르는 토큰 (7차) | 색·모서리·글꼴·글자 크기·칸 수·배경은 사이트 파일이 선언한 선택을 사람이 고르고, 프레임은 그 토큰을 `<html>` 에 놓을 뿐이다; 부품은 토큰만 쓴다(둥글기 리터럴 0) | `[look]`·`_look`·`/me.look`; `applyLook()`·theme.js; test_frame(둥글기)·test_site(팔레트 대비); e2e |
| R18 가게는 추가·열기·빼기 (7차) | 앱을 켜고 끄는 스위치 줄 대신: 추가한 앱은 타일(열기, ⋯ 에 빼기), 나머지는 카드와 '추가' 하나 | apps.ts; e2e |
| R19 한 쪽 앱은 링크, 여러 쪽 앱은 펼침 (7차) | 헤더·실행기에서 쪽이 하나인 앱은 이름 링크 하나; 여럿이면 헤더에서는 짚으면(초점·클릭도) 아래로 펼쳐지는 목록, 실행기에서는 링크 줄; 이름 메뉴도 같은 펼침; Esc·떠남이 닫는다 | parts.ts `hoverMenu`·`header()`; widgets.ts `launcher()`; e2e |

감사 — 이 묶음에서 고치는 것과 남는 것:

| 화면 | 지금 | 뒤 |
|---|---|---|
| 홈 | hero(인사·문장·버튼 2) + 새 앱 flash + 카드 격자 | 격자(위젯) + 편집; 빈 상태 = '앱 추가' 하나 |
| 앱 목록 | 머리 설명 2문장, 행마다 '열기'·'숨기기' 버튼, 미로그인 안내문 | 검색 + 행(이름 링크·설명 한 줄·스위치) |
| 설정 | 절 4 + 설명 문단 4 + ↑↓ + 초기화 | 언어·테마·시작 페이지 세 값, 각 값 옆 기본값 |
| 헤더 | 홈·앱·내 계정·프로젝트·메뉴·uid·로그아웃 | 이름 · 켠 앱 · 이름 메뉴 |
| 계정·에이전트·프리셋·프로젝트 | 설명 문단 25+ | 1차: 부품 교체만, 문단은 래칫. 3차: 29 문단 전부를 `help()` 한 줄·label 안 힌트·`meta()`(id·상태·수치 — 데이터)·`empty()`·파괴 폼의 ⓘ 로 옮겨 래칫 0; 기능(필드·버튼·링크)은 하나도 줄지 않음 |

## 6. 캘린더·볼트의 자리
<!-- sec:s6 basis: U2 A3 A5 A8 A9 -->

둘 다 "그룹 G 의 X"(`docs/projects.md`)이고, 사이트에서는 **앱 둘**이다 — 선언·위젯·흐름만 여기서 정한다.

```
[[app]] id = "calendar"  title = "캘린더"  icon = "📅"  audience = "calendar"  upstream = "@@upstream:calendar@@"
  [[app.widget]] id = "today"    title = "오늘"      module = "/apps/site/widgets/calendar.js"  size = "2x1"
  [[app.widget]] id = "upcoming" title = "다가오는 일" module = "/apps/site/widgets/calendar.js"
[[app]] id = "vault"     title = "노트"    icon = "📝"  audience = "vault"     upstream = "@@upstream:vault@@"
  [[app.widget]] id = "recent"   title = "최근 노트"  module = "/apps/site/widgets/vault.js"
  [[app.widget]] id = "home"     title = "Home"      module = "/apps/site/widgets/vault.js"  size = "2x2"
```
(실현: 2차 묶음 — 위젯 모듈은 페이지 앱이 내고(`web/widgets/<app>.ts`), 한 모듈이 `ctx.widget.id` 로 제 위젯 둘을 가른다; 서비스·API·화면은 `docs/apps-vault-calendar.md` §3·§4, `docs/calendar.md`·`docs/vault.md`.)
- **흐름(R4).** 캘린더의 첫 요소는 달력이다; 그룹(내 것·프로젝트들)은 달력 위의 칩이고, 날을 누르면 대화상자에서 일정을 쓴다. ICS 구독 주소는 그 캘린더의 ⓘ 한 줄. 볼트의 첫 요소는 Home 노트이고, 왼쪽 트리·위 검색 하나; 편집은 같은 자리에서(보기↔편집 스위치). '새 노트' 는 트리의 끝 행이다.
- **위젯이 먼저.** 단계 3·4 의 첫 산출물은 위젯이다(홈에 보이는 순간 앱이 있는 것이다).
- 켜기 전에는 둘 다 카탈로그에만 있다(기본 미사용).

## 7. 통과 기준 (실행 전 선언)
<!-- sec:s7 basis: C1 U1 U2 A1 A2 -->

C1 토큰 밖 색 리터럴 0 — `parts.css`·`web/src`·eq-sandbox `app.css`(테스트). C2 테마: `prefs.theme`·쿠키·`me.theme`·`theme.js`; 테스트 `test_sso`. C3 프레임 코드 한 벌: `web/src/lib/{api,dom,ui,prefs}.ts` 삭제, 둘 다 `site.js` 에서 — eq-sandbox 의 `src/lib/site.ts` 는 16줄 재수출(이름 호환; 그 저장소는 다른 작업이 병행 중이라 표면을 남긴다); `tsc` 0. C4 `apps` 기본 `[]`; 켠 앱만 헤더·홈·시작 후보. C5 `[[app.widget]]` 검증·`me.cards[].widgets`·홈의 import 와 대체; eq-sandbox 위젯 하나 실측. C6 `pageHead` intro 없음(컴파일); 설명 문단 래칫(홈·앱·설정 0, 나머지 현재 이하); 이동 버튼 0(홈·앱·설정). C7 pytest 둘 다, e2e(빈 홈→켜기→위젯→끌기→테마→새로고침 유지→eq-sandbox 같은 테마), 대비 4.5:1. C8 문서(`docs/site.md` 갱신, 이 문서) + 반환(`/Workspace/_patches/site-frame/` 의 format-patch·bundle; 사용자 WIP 미변경).

## 8. 절차 — 복사본 브랜치
<!-- sec:s8 basis: A2 -->

`/Workspace` 는 공유 폴더다. `/work/site` 로 복사(`.venv`·`node_modules` 제외) → 브랜치 `frame` → 첫 커밋 = 사용자 트리의 스냅샷(그 위에 패치가 깨끗이 얹히게) → 작업 커밋들. TypeScript 빌드·브라우저 측정은 node 가 있는 작업공간에서, pytest 는 샌드박스(`rhb-test`)에서. 반환은 `git format-patch <snapshot>..frame` 과 `git bundle` 을 `/Workspace/_patches/site-frame/` 에; eq-sandbox 는 커밋이 없으므로 패치 디렉터리(`patch.json`)로. 사용자 트리는 손대지 않는다.

## 9. 측정 (2026-11-01)
<!-- sec:s9 basis: E1 E2 H1 E4 E5 H3 C4 E6 E7 H4 C5 E8 E9 H5 -->

복사본 `/work/site` 브랜치 `frame`(스냅샷 cf896d6 위). 통과 기준 C1–C8 대로:

- **pytest** `tests/portal` 109 pass · 2 skip · 3 fail — 그 3(test_deploy 2, test_site 1)은 사용자 WIP(site.toml 의 eq-sandbox)가 스냅샷에서도 떨어뜨리는 것이고 이 묶음과 무관(스냅샷 worktree 에서 같은 3 실패 확인). `tests/refhandbook` 265 pass · 25 skip · 6 fail — 스냅샷과 같음. 새 테스트 `test_frame.py` 12 통과(색 리터럴·토큰·테마·위젯 검증·래칫·버튼형 링크).
- **tsc** web 0, 프레임 선언 0, eq-sandbox 0; vite 빌드 셋.
- **e2e**(Chromium 모의 사이트, `web/e2e/run.sh`) 28/28: 빈 홈=카탈로그, 스위치로 켜기→저장·헤더·홈, 검색이 주소에 남음, eq-sandbox 위젯 모듈이 제 저장소를 그림, 편집(Alt+←, Delete, 끌기), 테마 즉시 적용·저장·새로고침 유지, 앱 페이지 같은 테마·헤더, 새 브라우저가 계정 값을 받음, 옛 계정(hidden/order) 변환, 로그아웃 홈; 페이지 오류 0, 콘솔 오류 0(4xx 포함).
- **대비** 보이는 글자 105 요소(홈·메뉴·편집·대화상자·카탈로그·설정), 4.5:1 미만 0 — light 최소 4.56, dark 최소 6.41.
- **eq-sandbox** 자기 e2e 를 런타임 프레임(`FRAME_ROOT`) 위에서 재실행: 55/55 + 대비 2(최소 4.8·6.41) = 57/57, 전과 같다 — `flash` 만 앱 것으로 남겼다(앱의 CSS·시나리오가 그 모양을 안다).

**2차 묶음(2026-11-02, `docs/apps-vault-calendar.md` §5 기준)** — 같은 브랜치 위. pytest `tests/portal` 128 pass · 2 skip · 2 fail(둘 다 test_deploy 의 설치 복사가 사용자 WIP 의 끊어진 심링크 `apps/equation-sandbox` 를 만나는 것 — 스냅샷과 같음; 1차의 test_site 실패는 선언에 맞춰 고쳐 사라짐), `tests/refhandbook` 265 pass · 25 skip · 6 fail(스냅샷과 같은 6); 새 테스트 test_calendar 7·test_vault 6·test_site/test_sso/test_frame/test_deploy/test_i18n 의 추가 단언 통과. tsc 0, vite 빌드 셋(프레임·페이지·위젯). e2e 53/53(1차 28 을 가게에 맞춰 고친 것 + 가게·상세·캘린더·노트·위젯 셋 시나리오), 페이지 오류 0·콘솔 오류 0(일부러 낸 412 하나만 허용). 대비: 보이는 글자 367 요소 × 2 테마(홈·메뉴·편집·대화상자·가게·상세·설정·캘린더·일정 대화상자·노트·검색 결과·편집기), 4.5:1 미만 0 — light 최소 4.56, dark 최소 6.32(다른 달의 날짜 숫자가 3.82 였던 것을 카드 배경 위의 muted 로 고침). eq-sandbox 는 사용자 트리에 적용되어 57/57.

**3차 묶음(2026-11-02, 홈≠가게·배치·래칫)** — 배치 측정 `layout.js`: 9 화면(홈·편집·가게·상세·설정·캘린더·노트·빈 홈·로그아웃)의 아이콘·글자 쌍과 행 77 쌍, 규칙(아이콘·글자 간격 4–12px — 큰 아이콘은 높이의 0.35 까지 —, 중심 ≤2px, 행의 높이·중심, 잘림, 헤더 줄바꿈) 위반 0(고치기 전 90 쌍 중 46: 실행기 h2 간격 0, 위젯 머리 14, 가게 카드·상세의 아이콘이 글 블록 위에 붙어 중심 18–32px 어긋남, 백링크 요약이 ⓘ 원 스타일에 넘침). 래칫 account·agents·flows·projects 모두 0(설명 문단 29 → help/힌트/meta/empty/ⓘ), 기능 개수 불변. e2e 54/54(빈 홈 = '앱 추가' 하나 → 가게로 가는 단계가 늘었다), 페이지·콘솔 오류 0, 대비 367 요소 × 2 테마 4.5:1 미만 0(light 최소 4.56, dark 6.32 — 백링크 알약의 글자색을 muted 에서 text 로).

**4차 묶음(2026-11-02, 캘린더 주 보기·끌어 옮기기)** — e2e 63/63(월 격자 끌기 → start 가 그 날로, 주 보기 7 열·종일 행·24 시간·스크롤, 종일 칩의 자리, 빈 칸 → 10:00 대화상자, 블록 top 440/height 42, 14:00 으로 끌기 → start 14:00·길이 1h, 반복 일정 draggable 아님, 주소로 돌아와도 주, 월로 돌아오면 v 빠짐), 페이지·콘솔 오류 0; 대비 13 패스(주 보기 추가) 444 요소 × 2 테마 4.5:1 미만 0(light 최소 4.56, dark 6.32) — 측정이 DIV 의 글자를 빠뜨리고 있어서 더했더니 달력·주의 요일 머리(muted on soft)가 4.29 로 드러나 배경을 카드로 고쳤다; 배치 10 화면 88 쌍 위반 0; pytest(129 pass, test_deploy 2 는 전과 같음)·tsc 0 불변. 서비스 변경 없음(PATCH events/{id} 가 start·end 를 받는다).

## 10. 이 묶음 밖
<!-- sec:s10 basis: U1 U2 U3 U4 A5 -->

이름 있는 팔레트, 위젯 크기 조절 UI, 글타래의 `site.js` 전환(저장소 확인 뒤). 캘린더·볼트는 2차 묶음에서, 래칫 아래 페이지들의 설명 축소는 3차에서, 캘린더 주 보기·끌어 옮기기는 4차에서 들어왔다(`docs/apps-vault-calendar.md`; 그 밖 — CodeMirror·git 이력·그룹 볼트·일 보기 — 은 그 문서 §6 에 이유와 함께).

## 11. 5차 — 편의성 (2026-11-02)
<!-- sec:s11 basis: U5 U6 C6 E8 -->

규칙 R10–R13(5절)과 그 설계는 `docs/apps-vault-calendar.md` §7 에; 여기는 프레임에 든 것과 측정.
- **프레임.** `menu(at, sections)`·`onMenu(el, build)`·`menuButton(build)`·`closeMenu()`(parts.ts; `.menu`·`.menu-item`·`button.more` 는 parts.css 의 토큰만); `dialog(…, { justClose })` — 켜는 대로 저장되는 시트의 닫기 하나; `START_APPS`·`DEFAULTS.apps`; `Widget.description`; `api()` 의 오류 메시지 — 서비스의 `{error: "왜"}` 가 그대로 flash 에 선다(전에는 '요청이 실패했습니다 (400)' 로 뭉개졌다 — 볼트 등록이 왜 안 되는지 읽을 수 없던 원인 하나).
- **측정**(`web/e2e/run.sh`; `web/e2e/package.json` 이 `commonjs` 를 말해 `web/` 의 `type: module` 아래서도 돈다, playwright 는 `NODE_PATH`): e2e 104/104(새 계정 셋 켜짐·빈 선택 유지, 위젯 시트의 행 8 과 높이 ≤ 44, 칸 메뉴 키보드·⋯, 일정 메뉴의 복제·옮기기·지우기, 날 메뉴, 캘린더 이름·새 캘린더·이름 쳐서 지우기·기본은 비활성·캘린더 하나의 구독 주소, 날 패널의 할 일(그 날까지)·체크, 볼트 메뉴·이름 바꾸기, 노트 옮기기·트리 행 메뉴, 볼트 추가(뿌리 안 경로)·거절 한 줄·상태 카드·다시 시도·빼기, 할 일 위젯·메뉴·기한·치우기), 페이지 오류 0, 콘솔 오류 0; 대비 light 569 요소 0 미달(min 4.56)·dark 0(min 5.85) — 메뉴 4 패스·시트·할 일·상태 카드·추가 대화상자 포함; 배치 137 쌍 위반 0(`.pick-row`·할 일 행·볼트 머리 행 추가); pytest 132 passed(test_deploy 2 는 환경); tsc 0; i18n 0.

## 12. 6차 — 직접 조작·뷰어·CalDAV·간격과 키·선언 (2026-11-03)
<!-- sec:s12 basis: U7 A16 C7 E11 -->

규칙 R14–R16(5절)과 설계는 `docs/apps-vault-calendar.md` §8 에; 여기는 프레임에 든 것과 측정.
- **프레임.** `Frame.sizes`·`sizeOf()`·`spanStyle()`, `Placement.size`, `DEFAULTS.apps` 가 로드 뒤 `card.default` 로 채워짐(상수 없음); `keys(list)`·`keysDialog()`·`Key` — 페이지의 단축키 표, `?`; `dialog()` 가 Enter 를 어디서든 확인으로(독립 폼·textarea·button 제외), 입력란 없는 물음은 확인에 초점; theme.css 간격·아이콘 토큰; parts.css 는 그 척도로(래칫 32); 실행기·카드의 아이콘 36px.
- **측정**(`web/e2e/run.sh`): e2e 124/124, 페이지·콘솔 오류 0; 대비 light 608 요소 0 미달(min 4.56)·dark 0(min 5.85); 배치 125 쌍 0; pytest 138(test_deploy 2 는 환경); tsc 0; i18n 0. 서비스: CalDAV 왕복(기기 비밀번호·PROPFIND·PUT·GET·REPORT 셋·DELETE·거절) test_calendar.

## 13. 7차 — 모양·가게·헤더·홈 (2026-11-04)
<!-- sec:s13 basis: U8 E12 -->

사용자의 7차 요구(원장 U8): 테마의 색·둥글기·이미지·글꼴 설정, 홈의 자리만 차지하는 것과 갱신되지 않은 링크, 홈 칸 수·글자 크기, 단일 링크 앱의 간소화, 헤더의 펼침 메뉴, 스위치 줄이 아닌 가게.
- **모양**(§1.3, R17): `[look]` 선언 → `/me.look` → 설정의 '모양' → `applyLook()`·theme.js. parts.css 의 둥글기 15곳을 토큰으로(모서리 선택이 버튼·칸·대화상자에 닿게).
- **가게**(§3, R18): 내 앱 타일 + 추가할 앱 카드; 상세는 추가 또는 열기·빼기.
- **헤더·실행기**(R19): 여러 쪽 앱(에이전트)은 펼침, 이름 메뉴도 짚으면 펼침; 실행기는 아이콘·이름(쪽이 여럿일 때만 링크 줄) — 태그라인·연결 주소는 가게의 몫.
- **홈**: 격자 위의 도구 줄(버튼 하나와 ⓘ 설명)을 없애고 '위젯 고르기' 를 격자의 마지막 칸으로; 에이전트의 '파일' 링크를 사이트 파일에(쪽이 바뀐 구조 반영).
- **측정**(`web/e2e/run.sh`, 2026-11-04): e2e 168/168, 페이지·콘솔 오류 0; 대비 light 620 요소 0 미달(min 4.56)·dark 0(min 5.85); 배치 124 쌍 0; pytest(test_portal) 144 passed(test_deploy 2 는 환경); tsc 0; i18n 0. 모의 사이트의 `look` 은 run.sh 가 `portal/site.py` 로 사이트 파일에서 읽어 넘긴다(복사본 없음).
