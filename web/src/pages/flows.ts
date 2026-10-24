// The flow designer: a run drawn as blocks (agents) and arrows (what each passes on). Next step.

import { h, replace } from '../lib/dom';
import { main, pageHead, section } from '../lib/ui';

export async function flows(): Promise<void> {
  replace(main(), pageHead('순서도', '에이전트 단계를 블럭으로 놓고 이어서 실행 흐름을 설계합니다.'),
    section('준비 중', h('p', { class: 'muted' }, '블럭 편집기가 곧 여기에 들어옵니다.')));
}
