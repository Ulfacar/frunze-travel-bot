from datetime import date,timedelta
from urllib.parse import unquote
from bs4 import BeautifulSoup

from tests.test_standalone_crm import configured,crm,login,form,submit


def test_manual_card_uses_real_tasks_and_local_assets_without_provider_actions(crm):
    client=crm['client'];assert login(client).status_code==303
    values=form(client,'/admin/intake')|{'name':'Synthetic <script>bad()</script> person','phone':'+372555123'}
    intake=submit(client,'/admin/intake',values);assert intake.status_code==303
    uid=unquote(intake.headers['location'].split('/conversation/')[1].split('/preliminary')[0])
    assert submit(client,f'/admin/conversation/{uid}/task/create',{'kind':'call',
        'scheduled_date':(date.today()+timedelta(days=2)).isoformat(),'scheduled_time':'00:30',
        'priority':'normal','comment':'Synthetic manual task'}).status_code==200
    result=client.get(f'/admin/conversation/{uid}');assert result.status_code==200
    soup=BeautifulSoup(result.text,'html.parser')
    text=soup.get_text(' ',strip=True)
    assert '+372555123' in text and '00:30' in text and 'Synthetic manual task' in text
    assert soup.find('script',string='bad()') is None
    assert soup.select_one(f'a[href="/admin/calendar"]')
    actions=[n.get('action','') or n.get('hx-post','') for n in soup.select('[action],[hx-post]')]
    assert not any(any(denied in a for denied in ['/send','/resend','/suggest','/takeover','/release','/followup']) for a in actions)
    shell=BeautifulSoup(client.get('/admin').text,'html.parser')
    scripts=[s.get('src') for s in shell.select('script[src]')]
    assert '/crm-static/htmx-1.9.12.min.js' in scripts
    assert not any(s.startswith(('https://','http://')) for s in scripts)
    asset=client.get('/crm-static/htmx-1.9.12.min.js')
    assert asset.status_code==200 and len(asset.content)>30000
