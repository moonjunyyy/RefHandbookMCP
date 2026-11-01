# 앱 카탈로그·캘린더·볼트 — 설계 (2026-11-02)

프레임 설계(`docs/frame.md`)의 두 번째 묶음. 세 가지를 한 번에 정한다: (1) `/apps` 를 앱스토어처럼 — 앱이 제 이름과 한 줄로 제 자신을 말하고, 사람은 보고 고른다; (2) 캘린더 — 내 일정과 프로젝트 일정이 한 달력에, 서비스·페이지·위젯; (3) 볼트 — Obsidian 이 여는 그 마크다운 파일을 브라우저에서, 서비스·페이지·위젯. 캘린더와 볼트는 `docs/projects.md` 의 단계 3·4 이고, 그룹의 원리("사용자는 구성원이 한 명인 그룹")는 그 설계(`/work/design/portal-groups.md` §4·§5)를 따른다. 여기서는 그 설계를 이 사이트의 관례(프레임·앱·위젯·UI 규칙)에 맞춰 코드 단위로 정한다.

## 0. 세 결정
<!-- sec:s0 basis: U3 U2 A3 A5 A7 A9 -->

1. **앱은 제품처럼 말한다.** 이름은 제품명(상태 표시·괄호·가운뎃점 병기 없음), 한 줄(태그라인)은 무엇을 주는가, 소개(`about`)는 두세 문장, 태그는 고정 어휘에서 고른다. 설명이 사용법·관리자 기능의 나열이면 그것은 설명이 아니라 매뉴얼이다 — 페이지 안의 `help()` 로 간다.
2. **캘린더는 지금 그룹까지 간다.** 데이터가 파일이 아니라 서비스의 SQLite 이고 소속은 NSS 로 알 수 있으므로, 개인 캘린더와 프로젝트 캘린더를 함께 만든다. 폰은 ICS 구독으로.
3. **볼트는 개인 볼트부터.** 그룹 저장소(`/project/<cn>`)는 단계 2(프로비저너)가 아직 없어 파일이 없다. 개인 볼트 — 사용자 저장소 안의 디렉터리, 예: `/data/<uid>/Obsidian/Research Vault` — 를 핸드북과 같은 길(root 리콘실러의 idmapped 스테이징)로 서비스 앞에 올리고 읽고 쓴다. 그룹 볼트는 그 길에 그룹 gid 매핑만 더하면 된다(단계 2 뒤).

## 1. 앱 카탈로그 — 앱스토어
<!-- sec:s1 basis: U3 A7 A4 C1 E4 -->

### 1.1 선언 (`site.toml`, `portal/site.py`)
`[[app]]` 에 두 필드가 는다.
- `about` — 소개, 한두세 문장(`tr.en.about` 도). `description` 은 이제 **태그라인**(한 줄, 48자 이하)이다. 카드·실행기·검색이 쓰는 것은 태그라인, 상세가 쓰는 것은 소개.
- `tags` — 고정 어휘에서 고른 목록: `연구 · 글쓰기 · AI · 도구 · 일정 · 자료`. 어휘와 그 영어는 `site.py` 에(`N_`), 렌더러가 모르는 태그를 거부한다.

검사(`test_site`·`test_frame`): 카드가 있는 앱은 제목에 `(`·`·` 가 없고 24자 이하, 태그라인은 48자 이하에 끝 마침표 없음, 소개는 한–세 문장 240자 이하, 태그는 어휘 안이고 선택 앱마다 하나 이상. 문안(ko·en)은 §1.3.

### 1.2 화면
- `/apps` 의 첫 요소는 **검색**(한 입력, `?q=` 로 주소에 남음), 그 아래 **칩 한 줄**(전체 · 내 앱 · 태그들 — 하나 고르기), 그 아래 **격자**. 칸 하나 = 큰 아이콘 · 이름(링크 → 상세) · 태그라인 · 태그 · 스위치(켬/끔). 새 앱은 태그 하나. 순서는 사이트 파일의 순서(가게의 진열); '내 앱' 칩이 켠 것만 보인다 — 1차 묶음의 "켠 앱이 먼저" 를 이것으로 바꾼다.
- `/app/<id>` = **상세**(`/apps/<id>/` 는 호스트된 앱 자신의 자리이므로 단수). 머리: 아이콘 · 이름 · 태그라인 · 스위치(이 페이지의 결정 하나). 본문: 소개, 이 앱이 홈에 올리는 위젯(이름 목록), 링크, 연결 주소(`code`). 켜져 있으면 '열기' 가 첫 행동(primaryLink).
- 홈의 빈 상태(= 카탈로그)와 실행기는 태그라인을 쓴다.
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
<!-- sec:s3 basis: U2 A5 A8 A9 E4 -->

### 3.1 모델 (`portal/calendar.py`, SQLite `PORTAL_CALENDAR_DB`)
- `calendars(id, owner, kind 'user'|'group', name, color, created)` — 사람마다 기본 캘린더 하나(처음 볼 때 생김, 이름 '내 캘린더'), 프로젝트마다 기본 캘린더 하나(구성원이 처음 볼 때 생김, 이름 = 프로젝트 cn). 더 만들 수 있다(제 것·제 프로젝트 것).
- `events(id, cal, summary, description, location, start, end, allday, rrule, exdates, status, created, created_by, updated, updated_by, seq)` — VEVENT 의 부분집합. **시각은 UTC 순간**(`YYYY-MM-DDTHH:MM:SSZ`), 종일은 날짜(`YYYY-MM-DD`, `end` 는 배타). 반복은 `RRULE` 문자열의 부분집합: `FREQ=DAILY|WEEKLY|MONTHLY|YEARLY`, `INTERVAL`, `COUNT`, `UNTIL`, `BYDAY`(WEEKLY). 전개는 서비스가 한다(의존성 없음: `python-dateutil` 은 의존 트리에 없다).
- `feeds(token, uid, cals, name, created)` — ICS 구독 토큰(읽기 전용, 사람이 발급·회수).
- 읽기: 제 캘린더 + 소속 프로젝트의 캘린더. 쓰기: 같다(프로젝트는 구성원 모두 — 소유자 토글은 다음).

### 3.2 API (`/calendar/api/v1/`, audience `calendar`)
`GET calendars` · `POST calendars {name, color, group?}` · `PATCH/DELETE calendars/{id}`(기본 캘린더는 못 지움) · `GET events?from&to[&cal=a,b]` → 구간의 **발생**(occurrence; 반복은 전개, 각 항목에 `start`·`end` 와 계열의 `first`·`recurring`) · `POST events` · `PATCH/DELETE events/{id}` · `GET freebusy?group=cn&from&to` → 구성원별 바쁜 구간(제목 없이) · `GET/POST/DELETE feeds` · 공개 `GET /calendar/feed/{token}.ics` → `text/calendar`(VEVENT 그대로, RRULE 포함). 쓰기는 `Content-Type: application/json` 만(apps.py 와 같은 이유).

### 3.3 페이지 `/calendar`
첫 요소는 **달력**(월). 머리 한 줄: ‹ 달 › · 오늘 · 소스 칩(내 캘린더·프로젝트들; 끄고 켠 것은 이 브라우저에 기억) · 구독. 날을 누르면 그 날의 목록이 달력 아래에 펼쳐지고 '+ 일정' 이 거기 있다. 일정은 **대화상자**에서(제목·시작·끝·종일 스위치·캘린더·반복·장소·메모; 기존 일정은 같은 대화상자 + 지우기). 구독은 대화상자 하나: 주소를 만들어 보여 주고(복사), 회수 링크. 주/일 보기·끌어 옮기기·에이전트 예약 소스는 이 묶음 밖.

### 3.4 위젯
`today`(오늘, 2x1): 오늘의 일정 목록, 없으면 '일정 없음' 한 줄 + 날짜. `upcoming`(다가오는 일, 1x1): 앞으로 7일. 둘 다 `/apps/site/widgets/calendar.js` 하나가 `ctx.widget.id` 로 그린다.

## 4. 볼트
<!-- sec:s4 basis: U2 A5 A8 A9 A6 E4 -->

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
`recent`(최근 노트, 1x1): 최근 고친 노트 5. `home`(Home, 2x2): Home.md 를 그려 보인다(이 모듈만 markdown-it 을 품는다). 모듈 `/apps/site/widgets/vault.js`.

## 5. 통과 기준 (실행 전 선언)
<!-- sec:s5 basis: C1 C3 U3 U2 A8 E4 -->

**카탈로그** — `/apps` 가 검색·칩·격자(아이콘·이름·태그라인·태그·스위치), `/app/<id>` 가 상세(스위치 하나·소개·위젯·링크); `site.py` 가 `about`·`tags` 를 검증(모르는 태그 거부); 카드 있는 앱의 제목에 `(`·`·` 없음·24자 이하, 태그라인 48자 이하, 소개 240자 이하; 래칫 0·버튼형 링크 0 유지.

**캘린더** — 서비스 테스트(기본 캘린더 생성, 일정 CRUD, 구간 조회와 반복 전개 — DAILY·WEEKLY/BYDAY·MONTHLY·YEARLY, INTERVAL·COUNT·UNTIL, exdate —, 다른 사람 404, 프로젝트 캘린더는 구성원만, 피드 토큰과 공개 ICS, JSON 아닌 쓰기 415), 페이지·위젯 둘, 역할·유닛·선언.

**볼트** — 서비스 테스트(등록과 뿌리 검사, 트리, 읽기·쓰기 If-Match 412/409, 이동, 휴지통, 검색, 링크·백링크, 최근, 경로 탈출 거부, 다른 사람 404), 스테이징 계획 테스트(`mounts.plan` 이 vault.db 의 등록을 읽음), 페이지·위젯 둘, 역할·유닛 넷·선언.

**전체** — pytest 두 스위트가 스냅샷 대비 같거나 낫고(남는 실패는 스냅샷의 것뿐 — `test_site` 의 audiences 단언은 선언에 맞게 고친다) 새 테스트 통과; tsc 0; vite 빌드(페이지·프레임·위젯); e2e(1차 28 + 카탈로그·상세·캘린더·볼트 시나리오) 통과, 콘솔 오류 0, 새 페이지 대비 4.5:1 미만 0; 문서(영어 둘 + site.md·projects.md 갱신, frame.md §3 문구); 반환 = 복사본 브랜치 `frame` 위 커밋 + `/Workspace/_patches/site-frame/` 의 증분 diff(`frame` 1차 끝..HEAD)와 누적 diff(cf896d6..HEAD)·번들; 사용자 트리 미변경.

## 6. 이 묶음 밖
<!-- sec:s6 basis: U2 A5 A9 -->

그룹 볼트(단계 2 프로비저너 뒤: 스테이징에 gid 매핑), CodeMirror 편집기, git 자동 커밋, Obsidian Local REST 호환, 주/일 보기와 끌어 옮기기, 에이전트 예약을 캘린더 소스로, CalDAV, 프로젝트 소유자의 '구성원 쓰기' 토글, 래칫 아래 페이지들의 설명 축소.
