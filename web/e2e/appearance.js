const assert = require('node:assert/strict');
const { chromium } = require('playwright');
const mock = require('./mock');

async function checkAppearance(page) {
  const routes = [
    ['/', '.widgets'], ['/apps', '.catalog'], ['/app/vault', '.store-head'],
    ['/settings', '.settings-controls'], ['/calendar', '.cal-day'],
    ['/calendar?v=week', '.wk-body'], ['/vault', '.note-body'],
    ['/agents/files', 'main table'], ['/agents/runs/run:b1', 'ul.branches'],
  ];
  const failures = [];
  let inspected = 0;
  for (const [width, radius] of [[320, 0], [320, 45], [320, 100], [390, 100], [768, 100], [1100, 45], [1100, 100]]) {
    await page.setViewportSize({ width, height: 820 });
    mock.put('site', 'prefs', { apps: ['calendar', 'projects', 'vault', 'agents', 'eq-sandbox'], theme: 'dark',
      look: { radius, size: 'larger', columns: 6, accent: '#ffffff' } });
    for (const [path, ready] of routes) {
      await page.goto(mock.ORIGIN + path);
      await page.waitForSelector(ready);
      const issues = await page.evaluate(() => {
        const bad = [];
        const root = document.documentElement;
        const overflow = root.scrollWidth - root.clientWidth;
        if (overflow > 1) {
          const nodes = [...document.querySelectorAll('main *')].filter(el => el.getBoundingClientRect().right > innerWidth + 1
            && !el.closest('.table-wrap,pre,svg,.wk-body'));
          bad.push('horizontal overflow ' + overflow + 'px (' + nodes.slice(0, 4).map(el => el.tagName + '.' + el.className).join(', ') + ')');
        }
        const grid = document.querySelector('.widgets-ruler');  // the window's columns, a cell wide each (the grid itself counts units, parts of a cell)
        if (grid && innerWidth > 560) {
          const tracks = getComputedStyle(grid).gridTemplateColumns.split(' ').map(parseFloat);
          if (tracks.some(px => px < Math.min(grid.clientWidth, parseFloat(getComputedStyle(root).fontSize) * 12) - 1)) {
            bad.push('compressed widget track: ' + tracks.join(','));
          }
        }
        const radii = ['--panel-radius', '--control-radius', '--grid-radius'].map(name => {
          const probe = document.createElement('span');
          probe.style.borderRadius = 'var(' + name + ')';
          document.body.append(probe);
          const px = parseFloat(getComputedStyle(probe).borderTopLeftRadius);
          probe.remove();
          return px;
        });
        if (radii.some((value, i) => !Number.isFinite(value) || value > [24, 12, 8][i])) bad.push('unsafe radii ' + radii);
        return bad;
      });
      if (path === '/') {
        const button = page.locator('.add-widget');
        await button.scrollIntoViewIfNeeded();
        const clickable = await button.evaluate(el => {
          const r = el.getBoundingClientRect();
          return el.contains(document.elementFromPoint(r.left + 9, r.top + 9));
        });
        if (!clickable) issues.push('widget button loses its top-left hit area');
        if (radius === 100 && width === 320) {
          await button.click();
          await page.waitForSelector('dialog[open] .pick-list');
          await page.keyboard.press('Escape');
        }
      }
      if (path === '/settings' && width <= 390) {
        await page.locator('#palette-editor summary').evaluate(el => el.scrollIntoView({ block: 'start' }));
        const coversSettings = await page.locator('header').evaluate(el => el.getBoundingClientRect().bottom > 1);
        if (coversSettings) issues.push('wrapped mobile header covers the scrolled settings');
      }
      inspected++;
      if (issues.length) failures.push(width + '/' + radius + ' ' + path + ': ' + issues.join('; '));
    }
  }
  assert.equal(failures.length, 0, failures.join('\n'));
  return inspected;
}

async function checkPalette(page) {
  mock.put('site', 'prefs', { apps: ['calendar', 'vault'], theme: 'light', look: { palette: 'ruby' } });
  await page.goto(mock.ORIGIN + '/settings');
  const sample = page.locator('.look-preview');
  const sampleRadius = () => sample.evaluate(el => getComputedStyle(el).borderTopLeftRadius);
  assert.equal(await sampleRadius(), '10px');
  await page.locator('#radius').evaluate(el => { el.value = '100'; el.dispatchEvent(new Event('input')); });
  assert.equal(await sampleRadius(), '24px');
  assert.equal(mock.get('site', 'prefs').look.radius, undefined);
  await page.locator('#palette-editor summary').click();
  const editor = page.locator('#palette-editor');
  assert.equal(await editor.locator('input[type=color]').count(), 11);
  await editor.locator('#palette-bg').fill('#000');
  await editor.locator('#palette-card').fill('#fff');
  await editor.locator('#palette-soft').fill('#777');
  assert.equal(await editor.getByRole('button', { name: '팔레트 저장' }).isDisabled(), true);
  assert.equal(mock.get('site', 'prefs').look.colors, undefined);
  await editor.locator('#palette-bg').fill('#faf3e7');
  await editor.locator('#palette-card').fill('#fffcf2');
  await editor.locator('#palette-soft').fill('#f1e8d8');
  await editor.locator('#palette-accent').fill('#abc');
  await editor.locator('#palette-link').fill('#952080');
  await editor.locator('#palette-text').fill('#fff');
  const preview = await editor.locator('.palette-preview').evaluate(el => {
    const css = getComputedStyle(el);
    return [css.backgroundColor, css.color, css.getPropertyValue('--accent-fill').trim()];
  });
  const ratios = await editor.locator('.palette-preview .card').evaluate(card => {
    const lum = color => color.match(/[0-9.]+/g).slice(0, 3).map(Number).reduce((sum, c, i) => {
      c /= 255;
      return sum + [0.2126, 0.7152, 0.0722][i] * (c <= .04045 ? c / 12.92 : ((c + .055) / 1.055) ** 2.4);
    }, 0);
    const surface = getComputedStyle(card).backgroundColor;
    return [...card.querySelectorAll('strong, .muted, .palette-link, .look-sample-accent, .tag')].map(el => {
      const style = getComputedStyle(el);
      const fill = el.matches('.look-sample-accent') ? style.backgroundColor : surface;
      const [hi, lo] = [lum(style.color), lum(fill)].sort((a, b) => b - a);
      return (hi + .05) / (lo + .05);
    });
  });
  assert.ok(ratios.every(ratio => ratio >= 4.5), 'custom palette contrast: ' + ratios);
  assert.equal(preview[0], 'rgb(250, 243, 231)');
  assert.notEqual(preview[1], 'rgb(255, 255, 255)');
  assert.equal(preview[2], '#aabbcc');
  assert.equal(mock.get('site', 'prefs').look.colors, undefined);
  await editor.locator('select[name=palette-mode]').selectOption('dark');
  await editor.locator('#palette-accent').fill('#123abc');
  await editor.getByRole('button', { name: '팔레트 저장' }).click();
  await page.waitForFunction(() => JSON.parse(localStorage.getItem('prefs')).look.colors?.dark?.accent === '#123abc');
  assert.equal(mock.get('site', 'prefs').look.colors.light.accent, '#aabbcc');
  await page.goto(mock.ORIGIN + '/apps');
  await page.waitForSelector('.catalog');
  assert.equal(await page.evaluate(() => getComputedStyle(document.body).backgroundColor), 'rgb(250, 243, 231)');
  await page.goto(mock.ORIGIN + '/settings');
  await page.locator('select[name=theme]').selectOption('dark');
  await page.waitForFunction(() => document.documentElement.style.getPropertyValue('--accent-fill') === '#123abc');
  await page.route(mock.ORIGIN + '/appearance-first-paint', route => route.fulfill({
    contentType: 'text/html', body: '<!doctype html><script src="/auth/static/theme.js"></script>',
  }));
  await page.goto(mock.ORIGIN + '/appearance-first-paint');
  assert.equal(await page.evaluate(() => document.documentElement.style.getPropertyValue('--accent-fill')), '#123abc');
}

(async () => {
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  try {
    const ctx = await browser.newContext({ locale: 'ko-KR' });
    await mock.install(ctx);
    mock.reset();
    const page = await ctx.newPage();
    const inspected = await checkAppearance(page);
    await checkPalette(page);
    console.log('appearance: ' + inspected + ' page/viewport/radius combinations and palette persistence passed');
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
