// Run with NODE_PATH pointing to the installed Playwright package. No live API calls.
const { chromium } = require('playwright');
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const assert = require('node:assert/strict');
const web = path.resolve(__dirname, '../../web');
const server = http.createServer((req, res) => {
  const pathname = new URL(req.url, 'http://localhost').pathname;
  if (pathname === '/') {
    res.setHeader('Content-Type', 'text/html; charset=utf-8');
    return res.end('<!doctype html><html lang="fr"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/css/app.css"><body><main id="root" style="padding:24px;max-width:1200px;margin:auto"></main><div id="toast"></div></body></html>');
  }
  const file = path.resolve(web, '.' + pathname);
  if (!file.startsWith(web + path.sep) || !fs.existsSync(file)) { res.statusCode = 404; return res.end(); }
  res.setHeader('Content-Type', file.endsWith('.js') ? 'text/javascript' : 'text/css');
  res.end(fs.readFileSync(file));
});
(async () => {
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  let browser;
  try {
    browser = await chromium.launch({headless:true, ...(process.env.PLAYWRIGHT_CHANNEL ? {channel:process.env.PLAYWRIGHT_CHANNEL} : {})});
    const page = await browser.newPage({viewport:{width:1365,height:900}});
    const errors = [];
    page.on('pageerror', e => errors.push(String(e)));
    let liveCalls = 0, commandCalls = 0, contracts = 0, rosterPhase = 0, failLive = false, lastContractUrl;
    const now = Math.floor(Date.now()/1000);
    const player = (u,n) => ({u,n,f:'Rainor',l:12});
    const rows = () => rosterPhase === 1 ? [] : [
      {jobId:'hub-a',kind:'hub',hb:now-4,players:[player(1,'Alice'),player(2,'Bob')],maxPlayers:60},
      {jobId:'match-a',kind:'match',mode:'EXFIL',map:'Forest',hb:now,players:[player(2,'Bob'),player(3,'Chloe')],maxPlayers:60},
      {jobId:'old',kind:'hub',stale:true,hb:now-100,players:[player(4,'Ghost')]},
    ];
    await page.route('**/api/**', async route => {
      const url = new URL(route.request().url()); let result = {};
      if (url.pathname === '/api/live') {
        liveCalls++;
        if (failLive) result = {error:'403 test'};
        else result = {servers:rows(),at:now,summary:{players:3,hubs:1,matches:1}};
      } else if (url.pathname === '/api/live/contracts') {
        contracts++; lastContractUrl = url;
        result = {issues:contracts === 1 ? ['HUB : aucun contrat publié.'] : []};
      } else if (url.pathname === '/api/live/events') result = {events:[],timeline:[],watcher:{}};
      else if (url.pathname === '/api/player/search') result = {userId:Number(url.searchParams.get('q'))};
      else if (url.pathname === '/api/player') result = {at:now,sections:{identity:{ok:true,data:{name:'Bob'}},presence:{ok:true,data:{kind:'match',mode:'EXFIL'}}}};
      else if (url.pathname === '/api/cmd') { commandCalls++; result = {acks:[{ok:true,place:'hub',job:'a',msg:'1 joueur prevenu'}],done:false}; }
      await route.fulfill({json:result});
    });
    await page.goto(`http://127.0.0.1:${server.address().port}/`);
    await page.clock.install();
    await page.evaluate(async () => (await import('/js/live.js')).viewPlayers(document.getElementById('root')));
    await page.getByRole('heading',{name:'Joueurs connectés (3)'}).waitFor();
    assert.equal(await page.getByRole('button',{name:'Bob',exact:true}).count(),1);
    assert.equal(await page.getByText('Ghost',{exact:true}).count(),0);
    assert.match(await page.getByRole('button',{name:'Bob',exact:true}).locator('..').locator('..').innerText(),/EXFIL/);
    await page.getByRole('button',{name:'Bob',exact:true}).click();
    await page.getByRole('heading',{name:'Bob',exact:true}).waitFor();
    await page.screenshot({path:path.join(os.tmpdir(),'cc-fiches-desktop.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});
    await page.screenshot({path:path.join(os.tmpdir(),'cc-fiches-mobile.png'),fullPage:true});
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), 'mobile page overflow');
    await page.setViewportSize({width:1365,height:900});
    rosterPhase = 1;
    const before = liveCalls;
    await page.clock.runFor(5100);
    await page.getByRole('heading',{name:'Joueurs connectés (0)'}).waitFor();
    assert.ok(liveCalls > before);
    failLive = true;
    await page.getByRole('button',{name:'Actualiser',exact:true}).click();
    await page.getByText(/Liste indisponible : 403 test/).waitFor();
    failLive = false;
    await page.evaluate(async () => (await import('/js/live.js')).viewLive(document.getElementById('root')));
    await page.getByText('HUB : aucun contrat publié.',{exact:true}).waitFor();
    await page.getByRole('textbox',{name:'Filtrer les serveurs'}).fill('Alice');
    await page.clock.runFor(5100);
    assert.equal(await page.evaluate(() => document.activeElement?.value),'Alice');
    assert.equal(await page.evaluate(() => document.activeElement?.selectionStart),5);
    await page.waitForFunction(() => !document.body.textContent.includes('HUB : aucun contrat publié.'));
    await page.getByRole('button',{name:'Relire maintenant'}).click();
    await page.waitForFunction(() => ![...document.querySelectorAll('button')].find(b => b.textContent === 'Relire maintenant').disabled);
    assert.equal(lastContractUrl.searchParams.get('force'),'1');
    await page.evaluate(async () => {
      document.getElementById('root').replaceChildren();
      const el = document.createElement('div'); document.getElementById('root').append(el);
      (await import('/js/actions.js')).trackCommand({id:'broadcast'},el);
    });
    await page.clock.runFor(1600);
    await page.getByText(/Fait par le serveur Hub/).waitFor();
    await page.clock.runFor(45000);
    await page.waitForTimeout(50);
    // Let any pending response schedule its final tick, then check that polling stops.
    await page.clock.runFor(2100);
    const after = commandCalls;
    await page.clock.runFor(10000);
    assert.equal(commandCalls,after,'broadcast acknowledgments must not poll forever');
    assert.deepEqual(errors,[]);
    console.log('UI_OK: roster, deduplication, stale exclusion, click to sheet, refresh, empty/error states, responsive layout, contract refresh/force, bounded acknowledgment tracking');
  } finally { if(browser) await browser.close(); await new Promise(resolve => server.close(resolve)); }
})().catch(e => { console.error(e); process.exitCode = 1; });
