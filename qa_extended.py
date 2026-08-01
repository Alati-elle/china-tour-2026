import json
from playwright.sync_api import sync_playwright

URL='https://alati-elle.github.io/china-tour-2026/?qa=extended-v20'
out={'checks':[],'errors':[]}
def check(name,value,detail=''):
    out['checks'].append({'name':name,'ok':bool(value),'detail':detail})
    if not value: out['errors'].append(f'{name}: {detail}')

with sync_playwright() as p:
  browser=p.chromium.launch(headless=True,executable_path='/home/vpnadmin/.cache/ms-playwright/chromium_headless_shell-1228/chrome-headless-shell-linux64/chrome-headless-shell',args=['--no-sandbox'])
  for width in (320,390,430,720):
    page=browser.new_page(viewport={'width':width,'height':844})
    console=[]
    page.on('console',lambda m:console.append(m.text) if m.type=='error' else None)
    page.on('pageerror',lambda e:console.append(str(e)))
    page.goto(URL+f'-{width}',wait_until='networkidle',timeout=60000)
    page.wait_for_selector('.detailed-card')
    for view in ('days','weather','rates','packing'):
      page.locator(f'.tab[data-view={view}]').click()
      visible=page.locator(f'#{view}View').is_visible()
      check(f'{width} {view} visible',visible)
      overflow=page.evaluate('document.documentElement.scrollWidth<=document.documentElement.clientWidth+1')
      check(f'{width} {view} document no overflow',overflow,str(page.evaluate('[document.documentElement.scrollWidth,document.documentElement.clientWidth]')))
    page.locator('.tab[data-view=rates]').click()
    page.wait_for_selector('#ratesBody tr')
    check(f'{width} rates four cards',page.locator('.rate-card').count()==4,str(page.locator('.rate-card').count()))
    check(f'{width} rates finite',page.locator('.rate-card').evaluate_all("els=>els.every(e=>!/NaN|undefined|null/.test(e.innerText))"))
    check(f'{width} rate rows',page.locator('#ratesBody tr').count()>=1,str(page.locator('#ratesBody tr').count()))
    check(f'{width} console clean',not console,'; '.join(console))
    page.close()

  page=browser.new_page(viewport={'width':390,'height':844})
  page.goto(URL+'-functional',wait_until='networkidle',timeout=60000)
  page.evaluate('localStorage.clear()')
  page.reload(wait_until='networkidle')
  page.wait_for_selector('.detailed-card')
  page.locator('.tab[data-view=packing]').click()
  for category in ('base','shoot','weather','clothes','hygiene'):
    page.locator(f'#packingFilters button[data-filter={category}]').click()
    name='QA-'+category
    page.fill('#customItem',name)
    page.locator('#addItemForm button').click()
    check(f'add into {category}',page.locator('.packing-item',has_text=name).count()==1)
  page.locator('#packingFilters button[data-filter=shoot]').click()
  item=page.locator('.packing-item',has_text='QA-shoot')
  item.locator('.category-picker').select_option('clothes')
  check('dot move leaves old category',page.locator('.packing-item',has_text='QA-shoot').count()==0)
  page.locator('#packingFilters button[data-filter=clothes]').click()
  check('dot move enters category',page.locator('.packing-item',has_text='QA-shoot').count()==1)
  page.reload(wait_until='networkidle');page.locator('.tab[data-view=packing]').click();page.locator('#packingFilters button[data-filter=clothes]').click()
  check('category persists reload',page.locator('.packing-item',has_text='QA-shoot').count()==1)
  page.locator('.tab[data-view=days]').click()
  page.locator('.detailed-card').first.locator('.edit-card').click()
  title=page.locator('.detailed-card').first.locator('[data-edit-field=title]')
  old=title.inner_text();title.fill('QA title');page.locator('.detailed-card').first.locator('.cancel-card').click()
  check('card cancel',page.locator('.detailed-card').first.locator('[data-edit-field=title]').inner_text()==old)
  page.locator('.detailed-card').first.locator('.edit-card').click();page.locator('.detailed-card').first.locator('[data-edit-field=title]').fill('QA saved');page.locator('.detailed-card').first.locator('.save-card').click();page.reload(wait_until='networkidle');page.wait_for_selector('.detailed-card')
  check('card save persists',page.locator('.detailed-card').first.locator('[data-edit-field=title]').inner_text()=='QA saved')
  page.locator('.detailed-card').first.locator('.edit-card').click();page.locator('.detailed-card').first.locator('.reset-card').click()
  check('card reset',page.locator('.detailed-card').first.locator('[data-edit-field=title]').inner_text()==old)
  browser.close()
print(json.dumps(out,ensure_ascii=False))
