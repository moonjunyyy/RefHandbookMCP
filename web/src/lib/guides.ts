// Each page owns its explanation; the frame knows neither app ids nor page-specific selectors.
import { guide } from '/auth/static/site.js';
import type { GuideStep } from '/auth/static/site.js';
import { t } from './i18n';
let dispose = () => undefined as void;
export function closeGuide(): void { dispose(); dispose = () => undefined; }
export function pageGuide(path: string): void {
  const pages: [RegExp, string, string, GuideStep[]][] = [
    [/^\/$/, 'home', t('홈'), [
      { title: t('내 작업 공간'), text: t('앱을 추가하면 홈에 실행기가 생깁니다. 위젯 고르기에서 일정·노트 같은 내용을 바로 올릴 수 있습니다.'), target: '.widgets, .empty-home' },
      { title: t('배치와 크기'), text: t('위젯 제목을 끌어 순서를 바꾸고, 오른쪽 아래 모서리나 ⋯ 메뉴로 크기를 바꿉니다. 키보드에서는 위젯에 초점을 두고 Alt+방향키로 옮깁니다.'), target: '.widget' }]],
    [/^\/apps\/?$/, 'apps', t('앱'), [
      { title: t('앱 찾기'), text: t('검색과 갈래로 앱을 찾고 이름을 눌러 기능과 연결 주소를 확인합니다.'), target: '.catalog' },
      { title: t('내 앱에 추가'), text: t('추가한 앱은 상단 메뉴와 홈에 나타납니다. 앱의 ⋯ 메뉴에서 정보를 열거나 뺄 수 있습니다.'), target: '.my-apps, .store' }]],
    [/^\/calendar(?:\/|$)/, 'calendar', t('캘린더'), [
      { title: t('일정 보기'), text: t('월·주 보기를 바꾸고 내 캘린더와 프로젝트 캘린더를 함께 봅니다.'), target: '.cal-nav' },
      { title: t('일정과 할 일'), text: t('날짜를 누르면 일정을 추가할 수 있습니다. 일정과 할 일은 해당 캘린더에 저장됩니다.'), target: '.cal-grid, .wk-body' }]],
    [/^\/vault(?:\/|$)/, 'vault', t('노트'), [
      { title: t('볼트 열기'), text: t('볼트를 고른 뒤 파일 목록이나 검색에서 노트를 엽니다.'), target: '.vault-layout, main' },
      { title: t('편집과 저장'), text: t('편집한 내용은 저장을 눌러 반영합니다. 저장하지 않은 변경이 있으면 다른 페이지로 이동하기 전에 확인합니다.'), target: '.note-body' }]],
    [/^\/projects(?:\/|$)/, 'projects', t('프로젝트'), [
      { title: t('함께 쓰는 공간'), text: t('내 프로젝트를 열거나 새 프로젝트를 만들 수 있습니다. 공유된 가입 링크로 프로젝트에 참여합니다.'), target: 'main' }]],
    [/^\/agents(?:\/|$)/, 'agents', t('에이전트'), [
      { title: t('실행 준비'), text: t('키를 등록하고 프리셋에서 모델과 실행 조건을 정합니다. 요청은 승인 화면에서 확인한 뒤 실행됩니다.'), target: 'main' },
      { title: t('진행 확인'), text: t('실행 목록에서 상태와 결과를 열고, 파일 메뉴에서 작업 산출물을 확인합니다.'), target: '#nav' }]],
    [/^\/settings\/?$/, 'settings', t('설정'), [
      { title: t('나에게 맞게'), text: t('밝음·어두움과 언어, 시작 페이지를 고릅니다. 변경은 계정에 저장됩니다.'), target: '.settings-controls' },
      { title: t('색과 배경'), text: t('모양에서 팔레트·글꼴·모서리와 배경 효과를 고릅니다. 색상 편집기는 밝음과 어두움의 배경·글자·상태 색을 각각 편집하고 저장 전 미리 보여줍니다.'), target: '#palette-editor' }]],
    [/^\/account\/?$/, 'account', t('계정'), [
      { title: t('내 계정'), text: t('프로필과 비밀번호를 관리합니다. 앱과 모양 설정은 내 메뉴의 설정에서 바꿀 수 있습니다.'), target: 'main' }]],
  ];
  const found = pages.find(([pattern]) => pattern.test(path));
  if (!found) return;
  const [, id, title, steps] = found;
  const host = document.querySelector<HTMLElement>('.page-head') ?? document.querySelector<HTMLElement>('main');
  if (host) dispose = guide(id + ':1', title, steps, host);
}
