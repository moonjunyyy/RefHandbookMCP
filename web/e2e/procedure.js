// Regression for U9: real WordGenerator build, onboarding lifecycle and semantic-theme compatibility.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const { chromium } = require('playwright');
const mock = require('./mock');
const results = [];

async function onboarding(page) {
  mock.put('site', 'prefs', { apps: ['calendar'], guides: [], theme: 'dark' });
  await page.goto(mock.ORIGIN + '/apps');
  const sheet = page.locator('.site-guide[open]');
  await sheet.waitFor();
  assert.match(await sheet.innerText(), /1 \/ 2/);
  await sheet.getByRole('button', { name: '다음', exact: true }).click();
  assert.match(await sheet.innerText(), /2 \/ 2/);
  await sheet.getByRole('button', { name: '이전', exact: true }).click();
  assert.match(await sheet.innerText(), /1 \/ 2/);
  await page.keyboard.press('Escape');
  assert.equal(await sheet.count(), 0);
  assert.deepEqual(mock.get('site', 'prefs').guides, []);
  // the replay is an item of the person's menu in the site header (docs/frame.md §1: one place on every page)
  const menu = page.locator('header details.me');
  const replay = menu.getByRole('button', { name: '사용 안내', exact: true });
  // (the menu opens on hover as well as on a click: open it as the page leaves it, then pick the item)
  const help = async () => { await menu.locator('summary').hover(); await menu.evaluate(d => { d.open = true; }); await replay.click(); };
  await help();
  await sheet.getByRole('button', { name: '건너뛰기', exact: true }).click();
  await sheet.waitFor({ state: 'detached' });
  assert.deepEqual(mock.get('site', 'prefs').guides, ['apps:1']);
  assert.equal(await menu.evaluate(d => d.contains(document.activeElement)), true);  // focus is back in the menu it came from
  await page.reload();
  await menu.locator('summary').waitFor();
  assert.equal(await sheet.count(), 0);
  await help();
  await page.route(mock.ORIGIN + '/apps/site/api/store/prefs', route => route.request().method() === 'PUT'
    ? route.fulfill({ status: 503, body: 'retry' }) : route.fallback());
  await sheet.getByRole('button', { name: '건너뛰기', exact: true }).click();
  await sheet.getByRole('alert').filter({ hasText: '저장하지 못했습니다' }).waitFor();
  assert.equal(await sheet.getByRole('button', { name: '건너뛰기', exact: true }).isEnabled(), true);
  await page.unroute(mock.ORIGIN + '/apps/site/api/store/prefs');
  await sheet.getByRole('button', { name: '다음', exact: true }).click();
  await sheet.getByRole('button', { name: '시작하기', exact: true }).click();
  await sheet.waitFor({ state: 'detached' });
  // New page guide gets its own completion. A key inside a guide cannot operate the page behind it.
  await page.goto(mock.ORIGIN + '/');
  await sheet.waitFor();
  await page.keyboard.press('w');
  assert.equal(await page.locator('dialog[open]').count(), 1);
  await page.keyboard.press('Escape');
  assert.equal(await page.locator('.guide-target').count(), 0);
  results.push({ check: 'onboarding lifecycle, failed save, focus, modal keyboard isolation', ok: true });
}

function measure() {
  const canvas = document.createElement('canvas');canvas.width = canvas.height = 1;
  const ctx = canvas.getContext('2d', { willReadFrequently: true });
  const rgba = color => {ctx.clearRect(0, 0, 1, 1);ctx.fillStyle = color;ctx.fillRect(0, 0, 1, 1);return [...ctx.getImageData(0,0,1,1).data].map((v,i) => i===3?v/255:v);};
  const blend = (a,b) => [0,1,2].map(i => a[i]*a[3]+b[i]*(1-a[3])).concat(1);
  const bg = el => { const stack=[];for(let e=el;e;e=e.parentElement) stack.unshift(rgba(getComputedStyle(e).backgroundColor));return stack.reduce((b,a)=>blend(a,b),[255,255,255,1]); };
  const lum = c => c.slice(0,3).map(v=>{v/=255;return v<=.04045?v/12.92:((v+.055)/1.055)**2.4;}).reduce((s,v,i)=>s+v*[.2126,.7152,.0722][i],0);
  const bad=[];let count=0,min=100;
  const scope=document.querySelector('dialog[open]') || document.body;
  for(const el of scope.querySelectorAll('*')) {
    if (el.disabled || el.closest(':disabled,svg,option,[aria-hidden=true]')) continue;
    if(![...el.childNodes].some(n=>n.nodeType===3&&n.textContent.trim()) && !el.matches('input:not([type=checkbox]):not([type=range]),textarea,select'))continue;
    if(el instanceof HTMLInputElement && ['checkbox','radio','range'].includes(el.type))continue;
    if(el.matches('input,textarea')&&!el.value&&!el.placeholder)continue;
    const r=el.getBoundingClientRect(),s=getComputedStyle(el);
    if(!r.width||!r.height||s.visibility==='hidden'||s.display==='none'||+s.opacity===0)continue;
    const b=bg(el),a=blend(rgba(s.color),b),v=[lum(a),lum(b)].sort((a,b)=>b-a),ratio=(v[0]+.05)/(v[1]+.05);
    count++;min=Math.min(min,ratio);
    if(ratio<4.5-.02)bad.push({text:el.textContent.trim().slice(0,30),cls:el.className,ratio:+ratio.toFixed(2),fg:s.color,bg:b});
  }
  const overflow=document.documentElement.scrollWidth-document.documentElement.clientWidth;
  const outside=[...scope.querySelectorAll('*')].filter(el=>{const r=el.getBoundingClientRect();return r.width&&r.right>innerWidth+1&&getComputedStyle(el).position!=='fixed';}).slice(0,5).map(el=>el.tagName+'.'+el.className);
  return {count,min,overflow,outside,bad};
}

async function wordgen(page) {
  let inspected=0;const failures=[];const measurements=[];
  for(const width of [320,768,1100]) for(const theme of ['light','dark']) for(const radius of [0,100]) {
    mock.put('site','prefs',{theme,apps:['wordgen'],look:{radius,size:'larger',type:'mono',palette:'cobalt'}});
    await page.setViewportSize({width,height:820});
    await page.goto(mock.ORIGIN+'/apps/wordgen/');
    await page.waitForSelector('body > header #nav a');
    await page.getByRole('button',{name:'키워드 생성기',exact:true}).waitFor();
    const root=await page.evaluate(()=>({font:getComputedStyle(document.body).fontFamily,size:getComputedStyle(document.documentElement).fontSize,bg:getComputedStyle(document.body).backgroundColor,token:getComputedStyle(document.documentElement).getPropertyValue('--bg').trim(),scheme:document.documentElement.dataset.theme}));
    assert.equal(root.scheme,theme);assert.equal(root.size,'20px');assert.match(root.font,/mono|Menlo/i);
    for(const tab of ['키워드 생성기','소설 집필실','단어 사전','보관함']) {
      await page.getByRole('button',{name:tab,exact:true}).click();
      await page.waitForTimeout(60);
      const state=await page.evaluate(measure);
      inspected++;measurements.push({width,theme,radius,tab,...state});
      if(state.bad.length||state.overflow>1)failures.push({width,theme,radius,tab,...state});
    }
    await page.getByRole('button',{name:'키워드 생성기',exact:true}).click();
    await page.getByRole('button',{name:'어휘 추가 & 중복 검사',exact:true}).click();
    await page.getByRole('dialog',{name:'어휘 풀 관리 및 중복 방지 등록기'}).waitFor();
    const state=await page.evaluate(measure);inspected++;measurements.push({width,theme,radius,tab:'pool dialog',...state});
    if(state.bad.length||state.overflow>1)failures.push({width,theme,radius,tab:'pool dialog',...state});
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('dialog[open]').count(),0);
    assert.match(await page.evaluate(()=>document.activeElement.textContent),/어휘 추가/);
    if(width===320&&theme==='dark'&&radius===100)await page.screenshot({path:'out/wordgen-mobile.jpg',type:'jpeg',quality:35});
  }
  fs.writeFileSync('out/wordgen-measurements.json',JSON.stringify({inspected,failures,measurements},null,2));
  assert.equal(failures.length,0,JSON.stringify(failures.slice(0,8),null,2));
  // Actual editing and account save, beyond a decorative tab.
  await page.getByRole('button',{name:'소설 집필실',exact:true}).click();
  await page.locator('textarea').fill('다음에 이어 쓸 초안');
  // the browser's copy is the account's own: its name carries the uid (apps/WordGenerator/src/lib/storage.ts localName)
  await page.waitForFunction(()=>Object.keys(localStorage).some(k=>k.startsWith('geultarae_draft:uid:')&&localStorage.getItem(k).includes('다음에 이어 쓸 초안')));
  assert.equal(await page.evaluate(()=>localStorage.getItem('geultarae_draft')),null);
  await page.waitForTimeout(1000);
  assert.match(JSON.stringify(mock.get('wordgen','draft')),/다음에 이어 쓸 초안/);
  await page.reload();await page.waitForSelector('body > header #nav a');
  await page.getByRole('button',{name:'소설 집필실',exact:true}).click();
  await page.waitForFunction(()=>document.querySelector('textarea')?.value==='다음에 이어 쓸 초안');
  // the way back is the site's own header (the frame's chrome()), not a bar of the app's
  for(const href of ['/','/apps','/settings'])assert.ok(await page.locator('body > header a').evaluateAll((els,href)=>els.some(el=>el.getAttribute('href')===href),href));
  // Custom backgrounds and exact accent fills travel through the shared account into the actual app.
  for (const theme of ['light','dark']) {
    const colors = { light: { bg:'#dff3df',card:'#f6fff2',soft:'#d0e5d0',accent:'#e8b0fa' },
      dark: { bg:'#10222b',card:'#18323d',soft:'#21414e',accent:'#efbfff' } };
    mock.put('site','prefs',{theme,look:{colors,radius:100,image:'/e2e/look.png',imageBlur:12,imageDim:55}});
    await page.goto(mock.ORIGIN+'/apps/wordgen/');await page.waitForSelector('body > header #nav a');
    const style=await page.evaluate(()=>({bg:getComputedStyle(document.body).backgroundColor,image:getComputedStyle(document.body,'::before').backgroundImage,filter:getComputedStyle(document.body,'::before').filter,bodyFilter:getComputedStyle(document.body).filter}));
    assert.equal(style.bg,theme==='light'?'rgb(223, 243, 223)':'rgb(16, 34, 43)');
    assert.match(style.image,/look.png/);assert.match(style.filter,/blur\(12px\)/);assert.match(style.filter,/brightness\(0.45\)/);assert.equal(style.bodyFilter,'none');
    const measured=await page.evaluate(measure);assert.equal(measured.bad.length,0,JSON.stringify(measured.bad));
  }
  mock.put('site','prefs',{guides:[]});
  await page.goto(mock.ORIGIN+'/apps/wordgen/');
  await page.locator('.site-guide[open]').waitFor();
  for(let i=0;i<9;i++) {await page.keyboard.press('Tab');assert.equal(await page.evaluate(()=>!!document.activeElement.closest('dialog[open]')),true);}
  await page.getByRole('button',{name:'건너뛰기',exact:true}).click();
  await page.waitForFunction(()=>!document.querySelector('.site-guide'));
  assert.deepEqual(mock.get('site','prefs').guides,['wordgen:1']);
  await page.reload();await page.waitForSelector('body > header #nav a');assert.equal(await page.locator('.site-guide').count(),0);
  await page.hover('header details.me summary');await page.$eval('header details.me',d=>{d.open=true;});await page.locator('header details.me').getByRole('button',{name:'사용 안내',exact:true}).click();await page.keyboard.press('Escape');
  results.push({check:'WordGenerator real build: '+inspected+' tab/modal/viewport/theme/radius cases, draft save/reload and the site header',ok:true});
}

(async()=>{
  const browser=await chromium.launch({args:['--no-sandbox']});
  try {
    const ctx=await browser.newContext({locale:'ko-KR'});await mock.install(ctx);mock.reset();
    await ctx.route('https://fonts.googleapis.com/**',route=>route.fulfill({body:'',contentType:'text/css'}));
    const page=await ctx.newPage();page.setDefaultTimeout(7000);
    await onboarding(page);await wordgen(page);
    mock.addCard({id:'connection-demo',title:'연결 정보',description:'',about:'',tags:[],code:[{label:'주소',value:'smb://example.test/user'}],icon:'',href:'/app/connection-demo',optional:true,default:false,links:[],widgets:[]});
    mock.put('site','prefs',{apps:['connection-demo']});
    await page.goto(mock.ORIGIN+'/');await page.locator('.launcher').waitFor();
    assert.equal(await page.locator('header a[href="/app/connection-demo"]').count(),1);
    await page.locator('.launcher a').click();await page.locator('.addresses').waitFor();
    assert.equal(await page.getByRole('link',{name:'열기',exact:true}).count(),0);
    assert.equal(await page.locator('a[href=""]').count(),0);
    results.push({check:'connection-only app header/home links lead to its information and copy controls, no self-open',ok:true});
    console.log(JSON.stringify(results,null,2));
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
