# 글타래

소설 창작용 무작위 한국어 키워드 생성기와 집필 메모. 수식어·명사·동사 어휘 풀(약 5천 개, 사물·인물·공간·주제
네 영역)에서 "오래된 은시계", "은시계를 불태우다" 같은 구절을 뽑고, 쉼표 목록으로 복사하거나 세트로 저장합니다.

- 브라우저만으로 동작합니다(서버·API 키 불필요).
- 사이트(`/apps/wordgen/`, ldap-portal의 앱 호스트)에서 열면 저장한 세트, 집필 메모, 직접 추가한 단어가 **계정에**
  저장되어 어느 기기에서나 같습니다. 그 밖에서는 이 브라우저(localStorage)에만 남습니다. 처음 계정으로 열 때
  이 브라우저에 있던 것은 계정으로 옮겨집니다 (`src/lib/storage.ts`).

## 개발

```sh
npm install
npm run dev      # http://localhost:3000 (브라우저 저장)
npm test         # 생성기·저장 테스트
npm run build    # dist/ (상대 경로: 어느 경로에 올려도 동작)
```

## 사이트에 올리기

ldap-portal의 `deploy/site.toml`에 `id = "wordgen"`, `static = true`, `storage = true`인 앱이 있으면:

```sh
npm run build && sudo /path/to/ldap-portal/deploy/install.sh --app wordgen dist
```

## 구조

- `src/data/lexicon/` 어휘 풀 (수식어·명사·동사, 영역별)
- `src/utils/wordPoolManager.ts` 풀과 사용자 단어 (중복 없이), `generator.ts` 구절 합성, `grammar.ts` 조사
- `src/lib/storage.ts` 계정 또는 브라우저 저장
