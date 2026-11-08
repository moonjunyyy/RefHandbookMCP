# 앱 카탈로그·캘린더·볼트 — 설계 (2026-11-02)

프레임 설계(`docs/frame.md`)의 두 번째 묶음. 세 가지를 한 번에 정한다: (1) `/apps` 를 앱스토어처럼 — 앱이 제 이름과 한 줄로 제 자신을 말하고, 사람은 보고 고른다; (2) 캘린더 — 내 일정과 프로젝트 일정이 한 달력에, 서비스·페이지·위젯; (3) 볼트 — Obsidian 이 여는 그 마크다운 파일을 브라우저에서, 서비스·페이지·위젯. 캘린더와 볼트는 `docs/projects.md` 의 단계 3·4 이고, 그룹의 원리("사용자는 구성원이 한 명인 그룹")는 그 설계(`/work/design/portal-groups.md` §4·§5)를 따른다. 여기서는 그 설계를 이 사이트의 관례(프레임·앱·위젯·UI 규칙)에 맞춰 코드 단위로 정한다.

## 0. 세 결정
<!-- sec:s0 basis: U3 U2 A3 A5 A7 A9 -->

1. **앱은 제품처럼 말한다.** 이름은 제품명(상태 표시·괄호·가운뎃점 병기 없음), 한 줄(태그라인)은 무엇을 주는가, 소개(`about`)는 두세 문장, 태그는 고정 어휘에서 고른다. 설명이 사용법·관리자 기능의 나열이면 그것은 설명이 아니라 매뉴얼이다 — 페이지 안의 `help()` 로 간다.
2. **캘린더는 지금 그룹까지 간다.** 데이터가 파일이 아니라 서비스의 SQLite 이고 소속은 NSS 로 알 수 있으므로, 개인 캘린더와 프로젝트 캘린더를 함께 만든다. 폰은 ICS 구독으로.
3. **볼트는 개인 볼트부터.** 그룹 저장소(`/project/<cn>`)는 단계 2(프로비저너)가 아직 없어 파일이 없다. 개인 볼트 — 사용자 저장소 안의 디렉터리, 예: `/data/<uid>/Obsidian/Research Vault` — 를 핸드북과 같은 길(root 리콘실러의 idmapped 스테이징)로 서비스 앞에 올리고 읽고 쓴다. 그룹 볼트는 그 길에 그룹 gid 매핑만 더하면 된다(단계 2 뒤).

## 1. 앱 카탈로그 — 앱스토어
<!-- sec:s1 basis: U3 U4 A7 A4 C1 E4 -->

### 1.1 선언 (`site.toml`, `portal/site.py`)
`[[app]]` 에 두 필드가 는다.
- `about` — 소개, 한두세 문장(`tr.en.about` 도). `description` 은 이제 **태그라인**(한 줄, 48자 이하)이다. 카드·실행기·검색이 쓰는 것은 태그라인, 상세가 쓰는 것은 소개.
- `tags` — 고정 어휘에서 고른 목록: `연구 · 글쓰기 · AI · 도구 · 일정 · 자료`. 어휘와 그 영어는 `site.py` 에(`N_`), 렌더러가 모르는 태그를 거부한다.

검사(`test_site`·`test_frame`): 카드가 있는 앱은 제목에 `(`·`·` 가 없고 24자 이하, 태그라인은 48자 이하에 끝 마침표 없음, 소개는 한–세 문장 240자 이하, 태그는 어휘 안이고 선택 앱마다 하나 이상. 문안(ko·en)은 §1.3.

### 1.2 화면
- `/apps` 의 첫 요소는 **검색**(한 입력, `?q=` 로 주소에 남음), 그 아래 **칩 한 줄**(전체 · 태그들 — 하나 고르기), 그 아래 두 묶음(7차, R18). **내 앱**: 추가한 앱마다 타일(큰 아이콘 위 이름 — 누르면 그 앱; ⋯·우클릭에 '앱 정보'·'빼기'), 추가한 순서. **추가할 수 있는 앱**: 나머지마다 카드 — 큰 아이콘 · 이름(링크 → 상세) · 태그라인 · 태그 · 행동 하나 '추가'. 새 앱은 태그 하나. 카드의 순서는 사이트 파일의 순서(진열). 스위치는 없다(6차까지의 '켬/끔' 줄과 '내 앱' 칩을 이것으로 바꾼다).
- `/app/<id>` = **상세**(`/apps/<id>/` 는 호스트된 앱 자신의 자리이므로 단수). 머리: 아이콘 · 이름 · 태그라인. 그 아래 행동 하나 — '추가', 또는 '열기'(primaryLink)와 옆의 '빼기'. 본문: 소개, 이 앱이 홈에 올리는 위젯(이름과 `c×r`), 링크, 연결 주소(`code`).
- 실행기(홈의 앱 칸)는 아이콘과 이름, 쪽이 여럿이면 그 링크 줄(7차 — 태그라인·연결 주소는 가게와 상세의 몫). 홈은 가게가 아니다: 켠 앱이 없는 홈은 '앱 추가' 하나이고 가게는 `/apps` 에만 있다(3차).
- 규칙은 1차 묶음 그대로(R1–R8): 이동은 링크, 켜고 끄기는 스위치, 설명 문단 0(래칫), 버튼형 링크 0.

### 1.3 문안 (제안; 한 자리 `site.toml` 에서 바꾼다)
| id | 이름 | 태그라인 | 태그 |
|---|---|---|---|
| eq-sandbox | 수식 플립플롭 / Equation Flip-Flop | 수식을 블록처럼 뒤집고 옮기는 작업판 | 연구 · 도구 |
| wordgen | 글타래 / Geultarae | 소설을 위한 키워드와 집필 메모 | 글쓰기 |
| agents | 에이전트 / Agents | 내 API 키로 돌리는 에이전트 팀과 샌드박스 | AI · 도구 |
| refhandbook | 핸드북 / Handbook | Claude 에 붙이는 연구 카드와 원장 | AI · 연구 |
| projects | 프로젝트 / Projects | 함께 쓰는 그룹 — 저장소·캘린더·볼트의 주인 | 자료 |
| calendar | 캘린더 / Calendar | 내 일정과 프로젝트 일정을 한 달력에 | 일정 |
| vault | 노트 / Notes | Obsidian 볼트를 브라우저에서 | 글쓰기 · 연구 |
| account | 계정 / Account | 내 프로필과 비밀번호 | (카탈로그 밖: 이름 메뉴) |

소개(`about`)는 두세 문장으로 "무엇을 하는가 · 무엇이 남는가" 만: 예) 글타래 — "무작위 키워드로 이야기를 틔우고, 떠오른 메모를 적어 둡니다. 키워드 세트와 메모는 계정에 남습니다." `projects` 는 이제 앱이다(카드·위젯 '내 프로젝트'; 페이지와 API 는 지금 그대로 — 포털의 것).

## 2. 서비스가 사이트에 붙는 길 (공통)
<!-- sec:s2 basis: A8 A6 A9 -->

- 역할: `facts.ROLES` 에 `vault: 8110`, `calendar: 8120`. 역할마다 `deploy/templates/<role>.service`(`apps.service` 꼴: 제 사용자·`StateDirectory`·`uvicorn portal.<mod>:create_app --factory --fd 3`), 소켓은 자동(`listen.socket`).
- 토큰: nginx 가 경로마다 그 audience 의 토큰을 찍고(`X-Auth-Token`), 서비스는 공개키로 `uid` 만 얻는다. **소속은 NSS** — `portal/membership.py` 의 `groups_of(uid)`(SSO 의 `nss_groups` 를 옮긴 것)와 `project_groups_of(uid)`(그 중 gid 가 프로젝트 구간 `[project_gid_min, project_gid_max]` 인 것). 요청마다 다시 본다.
- 선언: `[[app]]` 에 `audience`·`upstream = "@@upstream:<role>@@"`·`[[app.route]]`(`/calendar/api/`·`/vault/api/`: `limit = "api"`, `signin = false`; `/calendar/feed/`: `auth = "public"`); 페이지 경로는 `site` 앱의 `pages` 에(`/calendar`, `/vault`, `/vault/`).
- 위젯 모듈은 **페이지 앱이 낸다**: `web/widgets/<app>.ts` → `web/dist/widgets/<app>.js`(vite, 세 번째 설정, `/auth/static/site.js` 는 외부), 선언은 절대 경로 `module = "/apps/site/widgets/<app>.js"`. `/apps/site/` 는 공개 정적이므로 홈이 import 하고, 모듈은 제 서비스의 API 를 사이트 쿠키로 부른다(`docs/frame.md` §4.1 의 계약 그대로; `ctx.widget.id` 로 무엇을 그릴지 안다).
- 문서는 영어(`docs/calendar.md`, `docs/vault.md`; `docs/site.md`·`docs/projects.md` 갱신).

## 3. 캘린더
<!-- sec:s3 basis: U2 U4 A5 A8 A9 A11 E4 C5 E8 H5 -->

### 3.1 모델 (`portal/calendar.py`, SQLite `PORTAL_CALENDAR_DB`)
- `calendars(id, owner, kind 'user'|'group', name, color, created)` — 사람마다 기본 캘린더 하나(처음 볼 때 생김, 이름 '내 캘린더'), 프로젝트마다 기본 캘린더 하나(구성원이 처음 볼 때 생김, 이름 = 프로젝트 cn). 더 만들 수 있다(제 것·제 프로젝트 것).
- `events(id, cal, summary, description, location, start, end, allday, rrule, exdates, status, created, created_by, updated, updated_by, seq)` — VEVENT 의 부분집합. **시각은 UTC 순간**(`YYYY-MM-DDTHH:MM:SSZ`), 종일은 날짜(`YYYY-MM-DD`, `end` 는 배타). 반복은 `RRULE` 문자열의 부분집합: `FREQ=DAILY|WEEKLY|MONTHLY|YEARLY`, `INTERVAL`, `COUNT`, `UNTIL`, `BYDAY`(WEEKLY). 전개는 서비스가 한다(의존성 없음: `python-dateutil` 은 의존 트리에 없다).
- `feeds(token, uid, cals, name, created)` — ICS 구독 토큰(읽기 전용, 사람이 발급·회수).
- 읽기: 제 캘린더 + 소속 프로젝트의 캘린더. 쓰기: 같다(프로젝트는 구성원 모두 — 소유자 토글은 다음).

### 3.2 API (`/calendar/api/v1/`, audience `calendar`)
`GET calendars` · `POST calendars {name, color, group?}` · `PATCH/DELETE calendars/{id}`(기본 캘린더는 못 지움) · `GET events?from&to[&cal=a,b]` → 구간의 **발생**(occurrence; 반복은 전개, 각 항목에 `start`·`end` 와 계열의 `first`·`recurring`) · `POST events` · `PATCH/DELETE events/{id}` · `GET freebusy?group=cn&from&to` → 구성원별 바쁜 구간(제목 없이) · `GET/POST/DELETE feeds` · 공개 `GET /calendar/feed/{token}.ics` → `text/calendar`(VEVENT 그대로, RRULE 포함). 쓰기는 `Content-Type: application/json` 만(apps.py 와 같은 이유).

### 3.3 페이지 `/calendar`
첫 요소는 **달력**(월). 머리 한 줄: ‹ 달 › · 오늘 · 보기 칩(월 · 주) · 소스 칩(내 캘린더·프로젝트들; 끄고 켠 것은 이 브라우저에 기억) · 구독. 날을 누르면 그 날의 목록이 달력 아래에 펼쳐지고 '+ 일정' 이 거기 있다. 일정은 **대화상자**에서(제목·시작·끝·종일 스위치·캘린더·반복·장소·메모; 기존 일정은 같은 대화상자 + 지우기). 구독은 대화상자 하나: 주소를 만들어 보여 주고(복사), 회수 링크.

**주 보기**(4차): 월요일부터 7 열 × 24 시간 격자(한 시간 44px), 위에 종일 행, 왼쪽에 시각 열; 일정은 시작·끝 시각 높이의 블록이고 겹치면 같은 묶음 안에서 나란히 좁아진다(차선 배정); 오늘 열에 지금 시각 선; 처음에 아침(07:00)으로 스크롤. ‹ › 는 주 단위, '오늘' 은 오늘의 주. 빈 칸을 누르면 그 시각(30분 단위)으로 새 일정 대화상자(끝 = +1h). 주소는 `?v=week&d=YYYY-MM-DD` 로 남아 새로고침·링크에서 그대로 열린다.

**끌어 옮기기**(4차): 일정 칩은 `draggable` — 월 격자에서 다른 날 칸에 놓으면 그 날수만큼, 주 격자에서 시간 칸에 놓으면 그 날·그 시각(30분 단위)으로, 종일 칸에 놓으면 그 날로 — 길이를 지킨 채 `PATCH events/{id} {start, end}`(종일은 날짜, 시각은 UTC 순간) 하고 다시 그린다. 반복 일정(`recurring`)은 끌 수 없고(`↻` 표시, draggable 아님) 누르면 대화상자뿐 — 계열째 옮기는 것은 대화상자의 시작·끝으로. 키보드 대안은 그 대화상자. 일 보기·에이전트 예약 소스는 아직 밖.

### 3.4 위젯
`/apps/site/widgets/calendar.js` 하나가 `ctx.widget.id` 로 그리고, 칸의 크기(`ctx.size`)만큼 보인다 — 부품은 프레임의 것(`docs/frame.md` §4.2). `today`(오늘, 2x1): 날짜와 수(일정·오늘 마감·지남), 오늘의 일정을 시간선으로(종일 먼저, 지난 것 흐리게, 지금·다음 표시, 캘린더 색), 마감이거나 지난 할 일(바로 체크); 두 행이면 내일도. `upcoming`(다가오는 일, 1x1): 7일의 띠(날마다 수와 색)와 날마다 묶인 일정. `month`(이번 달, 2x2): 달(날마다 단계, 오늘, ‹ ›)과 고른 날의 일정. `tasks`(할 일): 마감별 묶음과 끝낸 정도(§7.5).

## 4. 볼트
<!-- sec:s4 basis: U2 A5 A8 A9 A6 A11 E4 -->

### 4.1 모델 (`portal/vault.py`, SQLite `PORTAL_VAULT_DB` + 볼트마다 색인)
- `vaults(id, uid, name, path, created)` — 사람이 **경로로 등록**한다(허용 뿌리 `PORTAL_VAULT_ROOTS`, 핸드북의 `RHB_SANDBOX_MOUNTS` 와 같은 문법 `FROM[=NAME][:ro]`, 기본 `/data/{user}=storage`; `agents/mounts.py` 의 `parse`·`source_path` 를 그대로 쓴다). 그룹 볼트는 단계 2 뒤.
- **스테이징**: 서비스는 사용자 파일을 못 보므로, 등록된 경로를 root 리콘실러가 `/run/<name>-vault-mounts/<uid>/<key>` 에 idmapped 로 올린다 — 핸드북의 `refhandbook mounts` 에 `--picks vault`(등록 목록을 `<data>/vault.db` 에서 읽는다; 기본 `handbook` 은 지금처럼 정책에서)를 더해 같은 코드가 한다. 유닛 셋(`vault-mounts.service/.path/.timer`)은 `mounts.*` 와 같은 꼴, 서비스가 등록을 쓰면 `<data>/mount-requests` 로 즉시. 서비스는 `PORTAL_VAULT_STAGE` 가 있으면 스테이지 경로를, 없으면(개발·테스트) 실제 경로를 연다. 아직 안 올라온 볼트는 목록에 `pending` 으로 보인다.
- **파일**: `.md`·`.txt`·`.json`·`.canvas`·`.csv` 는 글(읽기·쓰기), 그 밖(이미지·pdf)은 첨부(읽기만). `.obsidian`·`.git`·`.trash` 는 트리에서 숨긴다. 경로는 볼트 안으로만(정규화 뒤 검사; 심링크는 따라가지 않음). 쓰기는 `If-Match: <sha256>` 낙관적 동시성(다르면 412; 새 파일은 `If-Match` 없이, 있는 파일에 없이 쓰면 409). 지우기는 `.trash/<path>` 로 옮김.
- **색인**: 볼트마다 `index.db`(FTS5: path·title·body; links: from·to) — 요청이 올 때 mtime 으로 바뀐 파일만 다시 읽는다(inotify 없음; 볼트 하나의 노트 수천까지). `[[wikilink]]`·`[[link|alias]]`·`[[note#heading]]` 과 `#tag` 를 읽는다.
- git 자동 커밋은 이 묶음 밖(색인·편집이 먼저).

### 4.2 API (`/vault/api/v1/`, audience `vault`)
`GET vaults` → `{vaults:[{id,name,path,status}], roots:[…]}` · `POST vaults {path, name}` · `DELETE vaults/{id}`(등록만 지움) · `GET vaults/{id}/tree` · `GET vaults/{id}/file?path=` → `{path, text, sha256, mtime}` · `PUT vaults/{id}/file?path=` (`If-Match`) · `GET vaults/{id}/raw?path=` (첨부) · `POST vaults/{id}/move {from, to}` · `DELETE vaults/{id}/file?path=` → `.trash` · `GET vaults/{id}/search?q=` · `GET vaults/{id}/links?path=` → `{links, backlinks}` · `GET vaults/{id}/recent?n=`.

### 4.3 페이지 `/vault`
첫 요소는 **노트**(Home.md 가 있으면 그것, 없으면 첫 노트). 왼쪽 **트리**(접히는 폴더, 끝 행 '새 노트'), 위 **검색 하나**(결과가 트리 자리에). 노트 머리: 경로 · 보기↔편집 **스위치** · 백링크 ⓘ. 편집은 같은 자리의 `textarea`(저장 = 버튼 하나, 충돌이면 flash 한 줄; CodeMirror 는 이 묶음 밖). 렌더는 브라우저에서 `markdown-it` + wikilink + KaTeX(페이지 묶음에만 든다 — 동적 import). 볼트가 여럿이면 머리의 칩, 없으면 빈 상태 = '볼트 추가' 대화상자(경로·이름; 뿌리 목록을 보여 준다). 주소: `/vault`, `/vault/<id>/<path>`.

### 4.4 위젯
`recent`(최근 노트, 1x1): 7일 동안 고친 수와 14일의 활동, 최근 고친 노트(폴더, 얼마 전) — 칸이 담는 만큼. `tags`(태그, 1x1): 태그별 노트 수 막대, 누르면 볼트 검색(`/vault/<id>?q=<tag>`). `home`(Home, 2x2): Home.md 를 그려 보인다(이 모듈만 markdown-it 을 품는다). 모듈 `/apps/site/widgets/vault.js`, 부품은 프레임의 것(`docs/frame.md` §4.2).

## 5. 통과 기준 (실행 전 선언)
<!-- sec:s5 basis: C1 C3 U3 U2 A8 E4 -->

**카탈로그** — `/apps` 가 검색·칩·격자(아이콘·이름·태그라인·태그·스위치), `/app/<id>` 가 상세(스위치 하나·소개·위젯·링크); `site.py` 가 `about`·`tags` 를 검증(모르는 태그 거부); 카드 있는 앱의 제목에 `(`·`·` 없음·24자 이하, 태그라인 48자 이하, 소개 240자 이하; 래칫 0·버튼형 링크 0 유지.

**캘린더** — 서비스 테스트(기본 캘린더 생성, 일정 CRUD, 구간 조회와 반복 전개 — DAILY·WEEKLY/BYDAY·MONTHLY·YEARLY, INTERVAL·COUNT·UNTIL, exdate —, 다른 사람 404, 프로젝트 캘린더는 구성원만, 피드 토큰과 공개 ICS, JSON 아닌 쓰기 415), 페이지·위젯 둘, 역할·유닛·선언.

**볼트** — 서비스 테스트(등록과 뿌리 검사, 트리, 읽기·쓰기 If-Match 412/409, 이동, 휴지통, 검색, 링크·백링크, 최근, 경로 탈출 거부, 다른 사람 404), 스테이징 계획 테스트(`mounts.plan` 이 vault.db 의 등록을 읽음), 페이지·위젯 둘, 역할·유닛 넷·선언.

**전체** — pytest 두 스위트가 스냅샷 대비 같거나 낫고(남는 실패는 스냅샷의 것뿐 — `test_site` 의 audiences 단언은 선언에 맞게 고친다) 새 테스트 통과; tsc 0; vite 빌드(페이지·프레임·위젯); e2e(1차 28 + 카탈로그·상세·캘린더·볼트 시나리오) 통과, 콘솔 오류 0, 새 페이지 대비 4.5:1 미만 0; 문서(영어 둘 + site.md·projects.md 갱신, frame.md §3 문구); 반환 = 복사본 브랜치 `frame` 위 커밋 + `/Workspace/_patches/site-frame/` 의 증분 diff(`frame` 1차 끝..HEAD)와 누적 diff(cf896d6..HEAD)·번들; 사용자 트리 미변경.

## 6. 이 묶음 밖
<!-- sec:s6 basis: U2 U4 A5 A9 H5 -->

그룹 볼트(단계 2 프로비저너 뒤: 스테이징에 gid 매핑), CodeMirror 편집기(의존이 크다 — 페이지 묶음을 따로 쪼개야 한다), git 자동 커밋·이력(서비스 사용자가 idmapped 스테이지 안에서 git 을 돌릴 권한과 `.git` 의 소유가 먼저다), Obsidian Local REST 호환, 일 보기, 에이전트 예약을 캘린더 소스로, CalDAV, 프로젝트 소유자의 '구성원 쓰기' 토글. 주 보기와 끌어 옮기기는 4차에서 들어왔다(§3.3); 래칫 아래 페이지들의 설명 축소는 3차에서(docs/frame.md §9).

## 7. 5차 — 편의성: 기본 앱·노트·캘린더·할 일·위젯 고르기 (2026-11-02)
<!-- sec:s7 basis: U5 A13 C6 -->

배포본을 쓴 뒤의 지적 다섯(앱이 다 꺼진 채 시작, 볼트 등록의 오류와 바꿀 길 없음, 캘린더의 우클릭·공유 없음, 홈에서 다룰 체크리스트 없음, 위젯 고르기가 무엇인지 모르겠고 줄 간격이 넓음)과 총평 "기능 구현에만 집중해 편의성이 떨어진다". 다섯은 증상이고 원인은 생성 규칙 하나다: **동작을 화면의 다른 자리(대화상자·버튼 줄·설정 페이지)에 두고, 객체 자리에는 보기만 두었다.** 그래서 일정은 눌러 대화상자를 열어야 복제도 지우기도 되고, 볼트는 등록하고 나면 손댈 자리가 없고, 위젯은 이름만 적힌 체크박스였다. 규칙을 넷 더한다(docs/frame.md §5 의 표에 R10–R13).

| 규칙 | 뜻 | 강제 |
|---|---|---|
| R10 동작은 객체의 자리 | 화면의 객체(일정·날짜 칸·캘린더·볼트·노트·트리 항목·위젯 칸)는 제 자리에서 제 동작을 연다 — 우클릭 = ⋯ 버튼 = Shift+F10, 같은 메뉴(`menu()` 부품). 대화상자는 글을 받을 때만 | `web/frame/parts.ts menu()`; 캘린더·노트·홈 편집이 쓴다 |
| R11 상태는 다음 행동과 함께 | '준비 중'·'안 됨' 은 이유(사람의 말)와 지금 할 수 있는 동작(다시 시도·설정·빼기)을 한 카드에 | 볼트 상태 카드; 서비스가 이유를 한국어로 준다 |
| R12 고르기는 설명과 함께 | 고르는 것(위젯·볼트의 뿌리·옮길 캘린더)은 이름·한 줄 설명·크기(또는 경로)를 보이고, 행 높이는 글 한 줄 | 위젯 선언 `description`; 고르기 대화상자의 행(`.pick-row`); layout.js 가 행 높이를 잰다 |
| R13 기본은 쓸 수 있는 상태 | 새 계정은 빈 홈이 아니라 캘린더·프로젝트·노트가 켜진 채 시작한다; 끄는 것은 가게에서 | `DEFAULTS.apps`; 저장된 선택은 그대로 |

### 7.1 기본 앱 (R13)
`Prefs.apps` 의 기본값 `['calendar', 'projects', 'vault']` — 저장된 설정이 없는 계정(새 계정, 또는 한 번도 저장하지 않은 계정)에만 닿는다. 저장된 `apps`(빈 목록을 포함)는 그대로다: 사람이 끈 것은 꺼진 채다. 옛 `hidden`·`order` 의 변환(§2)은 그대로. 그 사람에게 없는 앱(그룹 밖)은 `onApps()` 가 걸러 낸다. 가게는 기본으로 켜진 앱도 똑같이 끌 수 있다.

### 7.2 메뉴 부품 (R10)
`menu(anchor, sections, opts)`: `anchor` 는 좌표(우클릭 자리) 또는 요소(⋯ 버튼 아래); `sections = [{title?, items: [{label, detail?, run, danger?, disabled?, kbd?}]}]`. 한 항목 한 줄, 굵은 키워드(label) 와 흐린 나머지(detail) — 4차 메뉴 규칙(docs/frame.md §9 의 "메뉴 항목 = 키워드 + 흐린 나머지")을 프레임으로 올린 것. 키보드: ↑↓ 로 이동, Enter 실행, Esc 닫기, 밖을 누르면 닫힘; 연 요소로 초점이 돌아간다. `contextmenu` 와 `Shift+F10` 을 같은 메뉴에 묶는 `onMenu(el, build)`, 행이나 머리의 ⋯ 인 `menuButton(build, label)` 도 함께; 행의 ⋯ 는 hover·초점에만 보인다(행이 버튼 줄이 되지 않게). 항목 수가 적을 때(≤ 2) 도 메뉴다 — 버튼을 늘어놓지 않는다(R1).

### 7.3 노트 (R10·R11·R12)
- **등록.** 대화상자 '볼트 추가' = 어디의(허용된 뿌리가 하나면 그 경로를 보이고, 여럿이면 select) + 그 안의 경로 입력 + 이름(비우면 폴더 이름); 한 줄 힌트(내 저장소 안의 폴더 — Obsidian 이 여는 그 폴더). 보내는 경로 = 뿌리 + 안의 경로. 서비스의 400 은 한국어이고 어디에 둘 수 있는지를 말한다: `"{path} 은(는) 볼트로 등록할 수 있는 곳이 아닙니다. 등록할 수 있는 곳: {where} 안의 폴더"`, `"경로에 '..' 은 쓰지 않습니다."`; 뿌리가 하나도 없으면 관리자에게 물으라는 한 줄. 거절은 flash 한 줄에 그대로 선다(프레임의 `api()` 가 문자열 `error` 를 메시지로 — 전에는 '요청이 실패했습니다 (400)' 로 뭉개졌다).
- **상태 카드.** 등록된 볼트가 `ok` 가 아니면 페이지는 카드 하나: 이름, 상태 태그(준비 중 / 오류), 경로, 이유(`reason` — 그 폴더가 없다 · 폴더가 아니다 · 내 것이 아니다 · 등록할 수 있는 곳 밖 · 읽기 전용 · 준비 중이면 "1분 안에 붙습니다, 그 뒤에도 그대로면 다시 시도")와 동작 넷(다시 시도 = `POST /vaults/{id}/retry`, 이름 바꾸기, 볼트 빼기, 다른 볼트 추가). 서비스가 `status` 를 `ok | pending | error` 로, 이유를 `reason`(사람의 언어)으로 준다 — 리콘실러의 영어 이유를 서비스가 옮긴다(`reason_of`).
- **볼트 설정.** 트리 머리(볼트가 여럿이면 칩 줄, 하나면 이름)의 ⋯ 메뉴: 이름 바꾸기(`PATCH /vaults/{id} {name}` — 새로), 경로(누르면 복사), 다시 시도(준비됐으면 비활성), 볼트 빼기(목록에서; 파일은 그대로 — 대화상자에서 확인), 볼트 추가.
- **노트의 자리.** 노트 머리: 편집 스위치는 그대로, ⋯ 메뉴(우클릭도) = 이름 바꾸기·옮기기(`POST /move`), 파일 열기(원본, 새 탭), 지우기(.trash). 트리 행의 우클릭 메뉴: 열기, 이름 바꾸기·옮기기, 파일 열기, 지우기; 폴더(summary): 여기에 새 노트. '새 노트' 는 트리 위의 한 버튼으로 올라온다(첫 동작; 연 노트의 폴더를 접두로).
- 그대로인 것: 서비스 사용자는 사용자 파일을 못 보므로(A11(c)) 등록 전의 폴더 둘러보기는 없다 — 뿌리를 보여 주고 아래 경로를 받는 것이 이 전제 안에서 가장 가까운 길이다(이 묶음 밖: 뿌리 자체를 읽기 전용으로 올려 둘러보기).

### 7.4 캘린더 (R10)
- **일정의 메뉴**(칩의 우클릭·Shift+F10, 패널 행의 ⋯): 열기(대화상자), 복제(계열째 `GET` → `POST`; 반복이면 '반복 전체' 라고 적힘), 다른 캘린더로 옮기기…(대화상자에서 고르기 → `PATCH {cal}`), 다른 캘린더에 복사…(→ `POST`), 지우기(확인 뒤 `DELETE`); 캘린더가 하나면 옮기기·복사는 비활성.
- **날의 메뉴**(월 칸의 우클릭·더블클릭, 주 머리의 우클릭, 주 칸의 우클릭 = 그 시각, 패널 머리의 ⋯): 새 일정, 종일 일정, 이 주 보기 / 이 달 보기.
- **캘린더의 메뉴**(칩의 우클릭): 숨기기/보이기(이 브라우저), 이것만 보기, 이름·색 바꾸기…(`PATCH calendars/{id}`; 프로젝트 캘린더면 "프로젝트 {cn} 의 — 구성원이 함께 봅니다" 가 옆에 — 공유는 소속으로 정해진다, §3.1), 구독 주소…(이 캘린더만의 피드 — `cals: [id]`), 지우기(이름을 쳐서; 기본 캘린더는 비활성 + "기본 캘린더는 남습니다"). 칩 줄의 ⋯: 새 캘린더…(내 것 / 프로젝트의 것), 모두 보이기, 폰에 구독(보이는 것 모두). 머리의 '폰에 구독' 버튼은 이 ⋯ 로 들어갔다.
- '공유' 의 뜻: 이 사이트에서 일정을 함께 보는 길은 프로젝트 캘린더(구성원 = NSS 소속)다. 그러므로 공유 = 그 일정을 프로젝트 캘린더로 옮기거나 복사하는 것, 그리고 밖의 캘린더(폰)에는 구독 주소. 사람 대 사람 공유(ACL)는 이 묶음 밖(§6).

### 7.5 할 일 — 체크리스트 위젯 (R10·R12)
- **모델.** `portal/calendar.py` 에 사람의 할 일: `tasks(id, uid, text ≤ 200, done 0|1, due date|'', rank, created, updated)`; API `GET /tasks`(열린 것 먼저 rank 순, 끝난 것은 뒤에 최근 순) · `POST /tasks {text, due?}` · `PATCH /tasks/{id} {text?, done?, due?, rank?}` · `DELETE /tasks/{id}` · `POST /tasks/clear-done`; 200개까지. 한 사람의 것만(프로젝트 할 일은 밖). ICS 피드에는 넣지 않는다(VTODO 는 폰 캘린더가 대개 무시한다).
- **위젯 `calendar/tasks` '할 일'**(`web/src/lib/tasks.ts` 의 `taskList` — 위젯과 날 패널이 같이 쓴다). 입력 한 줄(적고 Enter), 항목 행 = 체크박스 + 글 + 기한 표식(오늘 = warn, 지남 = bad "{n}일 지남", 내일, 날짜), 행의 메뉴(우클릭·⋯): 오늘까지·내일까지·날짜 고르기…·기한 없애기 / 고치기…·끝남(다시 할 일로)·지우기; 아래 "{n}개 남음" 또는 "다 끝났습니다" 와 '끝난 것 치우기'. 끝난 항목은 줄을 긋고 아래로. 저장은 즉시(R6), 실패하면 되돌린다.
- **대시보드.** '오늘'(2x1) 은 일정 아래에 '마감인 할 일'(오늘까지·지난 것)을 보이고, 옆에 '할 일'(1x1) 을 두면 홈이 일정 대시보드다; 캘린더 페이지의 날 패널은 '이 날까지인 할 일' 을 일정 아래에 보이고(체크·메뉴 그대로), 거기 적은 줄은 그 날까지다. 위젯 선언의 설명이 이 쓰임을 말한다.

### 7.6 홈 편집 — 위젯 고르기 (R12)
- 위젯 선언에 `description`(한 줄, ko; `tr.en.description`)이 생기고 `/auth/api/v1/me` 가 넘긴다. 모든 위젯이 설명을 갖는다(선언 검사: 서비스·정적 앱 모두, 비어 있으면 거부하지 않되 카탈로그 테스트가 사이트의 위젯은 전부 있음을 확인).
- '위젯 고르기' 시트(`dialog(…, { justClose })` — 닫기 하나) = 앱별 묶음(아이콘·이름 머리) 아래 위젯마다 한 행(`.pick-row`): 스위치(켜면 바로 끝에 추가·끄면 빼기 — 적용 버튼 없음, R6), 제목, 설명(흐림), 크기 태그(한 칸·넓은 칸·큰 칸). 행 높이 ≤ 44px(측정 40), 행 사이 간격 0. 실행기도 한 행("바로가기 — 앱의 이름과 링크").
- 편집 모드의 칸: 도구에 ⋯ 메뉴(앞으로 Alt+← · 뒤로 Alt+→ · 빼기 Del; 우클릭·Shift+F10 도 같은 메뉴) — 끌기·Alt+←→·× 는 그대로.

### 7.7 통과 기준 (실행 전 선언 — 원장 C6)
C22 기본 앱: 저장된 설정 없는 계정의 `onApps()` = 캘린더·프로젝트·노트(그 순) → 헤더 링크 셋·홈 실행기 셋(e2e 새 계정); 저장된 `apps: []` 계정은 빈 홈 그대로, 옛 hidden/order 계정은 전과 같이 변환(e2e). [충족: e2e (a0)·(a)·(k)] C23 메뉴 부품: 우클릭·⋯·Shift+F10 이 같은 메뉴, ↑↓ Enter Esc, 밖 클릭 닫힘, 초점 복귀(e2e); 대비·배치 측정에 메뉴 패스; `a.button` 0·래칫 0·색 리터럴 0 유지. C24 노트: 등록 대화상자에 뿌리(select 또는 접두)와 아래 경로; 400 과 `reason` 이 한국어(test_vault); 상태 카드에 이유·다시 시도·설정; `PATCH /vaults/{id}` 이름(test_vault); 볼트 메뉴(이름·빼기·추가)와 노트 메뉴(편집·옮기기·지우기·원본); e2e 로 등록(뿌리+경로 → POST 의 path 가 합쳐진 경로)·이름 바꾸기·빼기·상태 카드(pending 과 error 의 문구). C25 캘린더 메뉴: 일정 메뉴 5(열기·복제·옮기기·복사·지우기), 칸 메뉴 2, 캘린더 메뉴(이름·색·숨기기·구독·새 캘린더); e2e 로 복제 → 일정 +1, 옮기기 → cal 바뀜, 지우기 → −1, 칸 메뉴 → 대화상자/주 보기, 캘린더 이름 바꾸기 → PATCH. C26 할 일: test_calendar 에 tasks(추가·목록 순서·done·due·rank·지우기·치우기·남의 것 404); 위젯 e2e(적기 → 행 +1, 체크 → done, 새로고침 뒤 유지, 마감 지남 표식, 치우기); 날짜 패널의 할 일. C27 위젯 고르기: 대화상자의 `.pick-row` 수 = 켠 앱의 위젯 수(실행기 포함), 행마다 설명 비어 있지 않음, 행 높이 ≤ 44·행 간 중심 차 일정(layout.js 새 패스), 스위치로 바로 추가·빼기(e2e); 선언에 설명 없는 위젯 0(test_site). C28 회귀: pytest 스냅샷 대비 같거나 나음(남는 실패는 test_deploy 2 뿐), tsc 0, vite 셋, e2e 63 + 새 단계 전부·콘솔 오류 0, 대비 4.5:1 미만 0(새 패스: 메뉴·고르기·상태 카드·할 일), 배치 위반 0; 문서(docs/frame.md §2·§4·§5·§11, 이 절, docs/site.md·vault.md·calendar.md); 반환 = frame 위 커밋 + `/Workspace/_patches/site-frame/frame-5.diff`(`11fccd5..HEAD`; 사용자 트리 = 2b07830 + 4차·태그라인 작업본 위에 얹힘) + README; 사용자 트리 미변경.

### 7.8 측정 (2026-11-02)
C22–C28 전부 충족 — `docs/frame.md` §11 에 수치: e2e 104/104(전 63 + 새 41), 대비 light 569 요소 0 미달·dark 0, 배치 137 쌍 0 위반, pytest 132(+8: tasks 1, vault 상태·이름·재시도, 위젯 설명), tsc 0, i18n 0. 짓다 고친 것: (1) 프레임 `api()` 가 서비스의 `{error: "왜"}` 를 메시지로 — 거절이 읽히지 않던 원인; (2) `web/e2e/package.json`(commonjs) + `NODE_PATH` — 트리 안의 `run.sh` 가 `web/` 의 `type: module` 아래서 돌지 않던 것; (3) e2e 의 끌기가 날 패널이 길어져 스크롤된 격자를 놓치던 것(끌 요소를 먼저 보이게). 이 묶음 밖으로 남는 것: 노트의 등록 전 폴더 둘러보기(A11(c)), 사람 대 사람 공유(§6), 프로젝트 할 일.

## 8. 6차 — 직접 조작·뷰어·CalDAV·간격과 키·선언 (2026-11-03)
<!-- sec:s8 basis: U7 A15 A16 C7 -->

5차 보고에 대한 반응: 위젯의 끌어 놓기·크기 조절·미리보기(아이콘은 줄여도 됨), md 뷰어의 느림과 표의 가로 넘침, 캘린더의 표준 API 연동, 여백 과다와 "확인을 Enter, 취소를 Esc 로 할 수 없음", 그리고 "하드코딩 하지 마세요". 원인은 셋이다: **조작이 모드 뒤에 있었다**(편집 모드 안에서만 끌림, 크기는 선언 고정), **치수가 수였다**(간격·아이콘·기본 앱·크기 표가 코드의 리터럴), **키가 요소에 매여 있었다**(Enter 는 글 입력에서만 제출, 페이지 단축키 없음). 규칙 셋을 더한다(docs/frame.md §5 R14–R16).

| 규칙 | 뜻 | 강제 |
|---|---|---|
| R14 치수는 토큰, 선언은 한 곳 | 간격·아이콘·칸 높이는 theme.css 의 토큰(--s1…--s5·--pad·--gap·--icon·--icon-big·--cell); 기본 앱은 site.toml 의 `default = true`, 크기 표는 site.py 의 SIZES 한 곳 — 프레임·페이지는 /me 로 받아 쓴다 | test_frame: parts.css 간격 px 래칫(32), 프레임 코드에 앱 id 0·크기 id 0, /me 가 sizes·default 를 나른다 |
| R15 조작은 객체 위에서, 모드 없이 | 옮기기 = 머리를 끌기, 크기 = 모서리를 끌기, 나머지 = ⋯/우클릭/Shift+F10 메뉴와 Alt+←→·Delete; '편집' 모드 없음 | home.ts; e2e (d) |
| R16 미리보기는 그 모듈 | 고르는 행을 짚으면 그 위젯 모듈이 옆 칸에 그대로 뜬다 — 그림 파일·설명문 없음; 키는 페이지가 표로 선언하고 `?` 가 그 표를 보인다 | home.ts pick; frame keys()·keysDialog() |

### 8.1 위젯 (R14·R15·R16)
- **배치의 크기.** `Placement {app, widget, size?}` — 선언의 size 는 기본값, 사람이 바꾼 값이 배치에 남는다. 칸의 span 은 inline style(`grid-column: span c; grid-row: span r`)로 생성되고 크기별 CSS 클래스는 없다; 좁은 화면(≤560px)은 한 열로 접는다. 크기의 이름은 `c×r`(낱말표 없음). 크기 표 SIZES = 1x1·2x1·1x2·2x2 (site.py 한 곳 → /me.sizes → `frame.sizes`·`sizeOf()`).
- **손잡이.** 위젯 머리(`.widget-head`)가 draggable, 실행기는 칸 자체; 놓는 자리는 어느 칸이든; 끌리는 동안 반투명, 놓일 칸은 테두리. 모서리의 손잡이(`.widget-grip`, hover·초점에만 보임)를 pointer 로 끌면 칸이 가장 가까운 선언 크기로 스냅되고(열 폭·행 높이는 그 칸의 지금 치수에서 셈) 놓으면 저장. 칸의 ⋯(hover 에 보임)·우클릭·Shift+F10 메뉴: 선언 크기 전부(지금 것은 비활성 + '지금'), 앞으로(Alt+←), 뒤로(Alt+→), 빼기(Del). '편집'·'완료'·× 는 없다; 머리의 한 도구는 '위젯 고르기'(단축키 w).
- **미리보기.** 시트가 두 열: 행 목록 | 미리보기 칸(≤720px 에서 숨김). 행에 hover/초점이 오면 150ms 뒤 그 위젯을 `mount()` 로 띄운다(실행기면 실행기) — 한 번에 하나, 제목에 `c×r`. 그 모듈이 그대로 돌므로 보이는 것이 곧 홈에 올 것이다.
- **아이콘.** `--icon`(머리·헤더, 1.5em) · `--icon-big`(실행기·카드, 36px; 전 40–44).

### 8.2 md 뷰어 (U7(2))
- **순서.** `drawNote` 는 노트 응답으로 본문을 바로 그리고, 백링크는 자리(`.backlinks-slot`)를 두고 `/links` 응답이 오면 채운다 — 노트가 그 응답을 기다리지 않는다(그 사이 다른 노트로 갔으면 버린다).
- **KaTeX.** `lib/markdown.ts` 가 KaTeX 를 정적으로 묶지 않고 `loadMath()` 로 첫 필요 때 동적 import(별도 청크 262KB + css 31KB; markdown 청크는 370KB → 108KB); 글에 `$` 가 없는 노트는 그 청크를 요청하지 않는다. 로드 전에는 수식이 `code.math` 로 선다.
- **폭.** `.note-body table` 은 block + overflow-x auto(표가 노트 안에서 스크롤), `pre`·`.katex-display` 도 overflow-x auto; 페이지 폭은 늘지 않는다(측정: article·document 의 scrollWidth ≤ clientWidth).
- **트리.** 볼트를 열 때 한 번 그리고, 이 볼트 안의 링크(트리·검색 결과·백링크·위키링크)는 페이지 안에서 연다(pushState + open; 뒤로/앞으로는 라우터가 그린다) — current 표식만 옮기고 접힌 폴더는 그 노트의 것만 편다.
- **키.** `/` 찾기, `n` 새 노트, `e` 편집/보기, `Esc` 보기로(저장하지 않은 변경이면 묻는다: Enter = 돌아가기, Esc = 편집기에 남기).

### 8.3 CalDAV (U7(3); A16(e))
- **왜 CalDAV.** 폰·데스크톱 캘린더 앱의 표준 양방향 연동은 CalDAV(RFC 4791: WebDAV 위의 iCalendar 자원)다. 읽기 전용 ICS 피드(§3)는 남고, 쓰기가 더해진다. 외부 ICS 주소를 서버가 가져오는 구독은 이번 묶음 밖(서비스 유닛의 외부 접속 정책을 모른다; 폰 쪽에서 구독하면 된다).
- **자격 = 기기 비밀번호.** 캘린더 서비스는 Kerberos keytab 이 없고(SSO 만), 폰에 계정 비밀번호를 두는 것도 피한다. `devices(id, uid, name, secret=sha256, created, last_used)`: `POST /calendar/api/v1/devices {name}` 이 무작위 비밀번호(token_urlsafe 18)를 한 번 돌려주고, 목록(`GET`)은 이름·만든 때·마지막 사용만, `DELETE` 로 거둔다(20개까지). `/calendar/dav/…` 는 HTTP Basic(uid:비밀번호, 상수 시간 비교)이고 틀리면 401 + `WWW-Authenticate: Basic`.
- **자원.** `/calendar/dav/` PROPFIND → current-user-principal; `/calendar/dav/<uid>/` = principal 이자 calendar-home(depth 1: 그 사람이 보는 캘린더들 — 자기 것과 프로젝트의 것); `/calendar/dav/<uid>/<cid>/` = 캘린더 컬렉션(resourcetype calendar, displayname, supported-calendar-component-set VEVENT, getctag, sync-token, calendar-color, supported-report-set, current-user-privilege-set read·write); `/calendar/dav/<uid>/<cid>/<id>.ics` = 일정(getetag = `"seq"`, GET · PUT(If-None-Match: * 새로, If-Match 갱신; 틀리면 412) · DELETE). REPORT: calendar-query(time-range 로 expand 하여 겹치는 것), calendar-multiget(href 목록, 없는 것은 404 응답), sync-collection(토큰 = 캘린더 version; 그 뒤의 변경 + 지워진 것은 tombstones 로 404). MKCALENDAR·MKCOL·MOVE·COPY·PROPPATCH 는 403(캘린더는 페이지에서). OPTIONS: `DAV: 1, 3, calendar-access`. `/.well-known/caldav` → nginx 301 → `/calendar/dav/`(RFC 6764 발견).
- **자원 이름과 UID.** 클라이언트가 PUT 한 자원 이름(`<name>.ics`, 글자·숫자·._@-)이 일정의 id 가 되어 그 뒤의 GET 이 찾고, VEVENT 의 UID 는 `ical_uid` 로 보존되어 피드·GET 에 그대로 나간다(페이지에서 만든 일정은 `<id>@<host>`). 캘린더의 `version` 은 그 아래의 모든 변경(추가·수정·삭제·옮김)에 +1 — ctag 이자 sync-token; 일정은 마지막으로 쓰인 version(`ver`)을 갖고 지워진 것은 `tombstones(cal, id, version)` 에 남는다. 열 추가는 `MIGRATIONS`(PRAGMA table_info 로 없는 열만 ALTER).
- **iCalendar 읽기**(`caldav.read_vevent`): 줄 펼침, 파라미터(따옴표 안의 `:` 포함), 글 이스케이프; DTSTART/DTEND 의 `VALUE=DATE`(종일, 끝은 배타적 — 없으면 +1일)·`Z`·`TZID`(zoneinfo → UTC)·떠 있는 시각(UTC 로 읽음); DURATION; RRULE 은 서비스의 부분집합(parse_rule)만 — 밖이면 403 과 이유; EXDATE 여럿; SEQUENCE·STATUS; VALARM 은 무시. RECURRENCE-ID(반복의 한 회만 고침)는 403 과 이유(모델이 EXDATE 까지만 갖는다 — 폰이 동기화 오류로 보인다; 정직한 거절).
- **페이지.** 칩 줄 ⋯ → '기기 연결…': 서버 주소(복사)·사용자명·기기 목록(마지막 사용·거두기)·기기 이름 + 만들기(Enter) → 비밀번호 한 번 보임(복사).

### 8.4 간격과 키 (U7(4); A16(f)(g))
- **토큰.** theme.css: `--s1 4 · --s2 8 · --s3 12 · --s4 16 · --s5 24`, `--pad 16`(카드·대화상자; 전 22), `--pad-s 10`, `--gap 10`(격자; 전 14), `--cell 110`(격자 행; 전 120), `--icon`·`--icon-big`. parts.css 의 padding·margin·gap 은 그 척도로 바꿨다(가장 가까운 단으로, 같은 거리면 아래; 3px 이하의 미세 값과 페이지 폭 1100px 만 수로 남음 — 285 → 32, 래칫). 헤더 8/16, main 16/24, 카드 16: 전체가 한 단 좁다.
- **대화상자.** `dialog()` 가 keydown 을 받아 Enter 는 어디에 초점이 있든(select·checkbox·switch·대화상자 자체) 확인 버튼을 누른다 — textarea·button·링크·메뉴·시트 안의 독립 폼(기기 추가 줄)은 제 Enter 를 지킨다; 입력란이 없는 물음은 확인 버튼에 초점을 둔다(Enter = 확인, Esc = 취소). Esc 는 dialog 의 cancel 그대로.
- **페이지 키.** 프레임 `keys([{key, label, run, when?}])` — 페이지가 그릴 때 선언, 라우터가 페이지를 바꿀 때 비운다; 글을 치는 중(input·textarea·select·contenteditable)에는 글자 키가 먹지 않고 Esc·Alt·Ctrl 조합만 먹는다; 대화상자·메뉴가 열려 있으면 안 먹는다. `?` 는 선언된 표를 그대로 보이는 대화상자(글은 표에서 생성). 선언: 홈 `w`; 캘린더 `t` 오늘 · `←`/`→` 이전/다음 · `m` 월 · `w` 주 · `n` 새 일정; 노트 `/` `n` `e` `Esc`.

### 8.5 선언 (U7 강조; A16(h))
- site.toml `[[app]] default = true`(projects·calendar·vault; optional 이 아닌 앱에는 거부) → `/me` card.default → `DEFAULTS.apps` 는 로드 뒤 그 카드들(사이트 파일 순 — 5차의 "캘린더·프로젝트·노트" 는 선언 순 "프로젝트·캘린더·노트" 가 된다); 프레임 코드에 앱 id 리터럴 0(test_frame).
- SIZES(site.py) → `/me.sizes` → `frame.sizes`; 크기 id 리터럴은 코드에 0(test_frame; 프레임의 마지막 fallback 하나만).
- 모의 사이트(mock.js)는 같은 꼴을 데이터로 가진다(테스트 더블).

### 8.6 통과 기준 (실행 전 선언 — 원장 C7, C29–C35) 과 측정 (2026-11-03)
기준은 원장 C7 에 적은 대로(위젯 직접 조작 C29, 미리보기 C30, md 뷰어 C31, CalDAV C32, 간격·키보드 C33, 선언 C34, 회귀·반환 C35). 측정: pytest 138 passed(+6: 선언·크기·default, 간격 래칫·리터럴 0, iCalendar 리더, CalDAV 왕복 — test_deploy 2 는 환경), tsc 0, i18n 0, e2e 124/124(전 104 + 새 20: 시트의 w·행의 c×r·미리보기 둘·Esc, 머리 손잡이·메뉴 크기·모서리 스냅, 주/월 키·? 목록·n + select 에서 Enter, 기기 연결 셋, 본문-먼저·백링크-뒤·KaTeX 있음/없음·넓은 표·트리 유지·/ e Esc Enter, 기본 앱 순서), 콘솔·페이지 오류 0, 대비 light 608 요소 0 미달(min 4.56)·dark 0(5.85)(새 패스: hovered·keys·devices; 시트는 미리보기를 띄운 채), 배치 125 쌍 0. 짓다 고친 것: 간격 토큰화가 헤더의 1100px 까지 바꿔 nav 가 세로로 쌓였던 것(측정이 잡음); 시트 안의 독립 폼에서 Enter 가 시트를 닫던 것; 입력란 없는 물음에서 Enter 가 취소를 누르던 것(초점이 취소에 있었다 — 사용자의 "확인을 Enter 로 못 한다"의 한 실체); 트리 유지는 프레임 `link()` 가 라우터로 가던 것을 페이지 안 열기로. 밖: 외부 ICS 구독(위), 반복의 한 회 고침(RECURRENCE-ID), 위젯을 시트에서 격자로 끌어 넣기(스위치가 그 일을 한다).

## 9. 7차 — 가게 (2026-11-04)
<!-- sec:s9 basis: U8 E12 -->

가게를 스위치 줄에서 추가·열기·빼기로(§1.2, `docs/frame.md` R18): 추가한 앱은 위의 타일, 나머지는 카드와 '추가'; 상세는 '추가' 또는 '열기'·'빼기'. 모양(색·모서리·글꼴·글자 크기·홈 칸 수·배경)과 헤더·홈의 변경은 `docs/frame.md` §1.3·§13. 측정은 그 §13.
