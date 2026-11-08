// The site's chrome for 글타래 (RefHandbookMCP docs/frame.md §1): served by the site, the app takes the site's
// header (its name, the person's apps, their menu with this app's help) and the person's look from the frame
// the sign-in serves, as every page does. Run on its own (a dev server, offline), there is no frame: the app
// and its browser storage work without it.
export async function connectHost(): Promise<void> {
  try {
    const url = '/auth/static/site.js';
    const { load, chrome, guide } = await import(/* @vite-ignore */ url);
    await load();
    chrome();
    guide('wordgen:1', '글타래', [
      { title: '키워드 만들기', text: '개수와 조합 방식을 고른 뒤 키워드 뽑기를 누릅니다. 잠근 단어는 다시 뽑아도 유지됩니다.', target: 'main' },
      { title: '저장하고 이어 쓰기', text: '결과를 복사하거나 세트로 보관하고, 집필 메모에서 글을 이어 쓸 수 있습니다. 저장 위치는 화면 위에 계정 또는 이 브라우저로 표시됩니다.', target: '#root header nav' },
      { title: '사이트와 같은 모양', text: '맨 위 머리글은 사이트의 것입니다. 홈과 다른 앱으로 가고, 내 메뉴의 설정에서 색·글꼴·모서리를 바꾸며, 이 안내는 내 메뉴의 사용 안내에서 다시 엽니다.', target: 'body > header' },
    ]);
  } catch { /* on its own / temporarily offline: the app and its browser storage stay available */ }
}
