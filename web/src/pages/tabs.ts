// The agents' pages' tabs, one list for every page of them.

import { n_, t } from '../lib/i18n';

const AGENT_TABS = [{ href: '/agents/', label: n_('실행') }, { href: '/agents/presets', label: n_('프리셋') },
  { href: '/agents/keys', label: n_('API 키') }, { href: '/agents/files', label: n_('파일') }, { href: '/approvals', label: n_('승인') }];

/** The tabs, their labels in the page's language. */
export const agentTabs = () => AGENT_TABS.map(x => ({ href: x.href, label: t(x.label) }));
