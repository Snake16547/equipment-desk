import os,tempfile,json,sys
from pathlib import Path
from fastapi.testclient import TestClient
p=Path(tempfile.mkdtemp())/'equipment.json'
os.environ.update(DATA_FILE=str(p),ADMIN_PASSWORD='supersecretpassword',SESSION_SECRET='a'*64,COOKIE_SECURE='false')
sys.path.insert(0,'/mnt/data/edwork/equipment-desk')
os.chdir(Path(__file__).resolve().parents[1])
from app.main import app
c=TestClient(app)
assert c.get('/api/version').json()['version'] == os.environ.get('APP_VERSION','dev')
for page in ('/', '/admin'):
    response = c.get(page)
    assert response.status_code == 200
    assert 'Version loading…' not in response.text
    assert os.environ.get('APP_VERSION','dev') in response.text
    assert 'Cache-Control' in response.headers and 'no-store' in response.headers['Cache-Control']
    assert '/static/style.css?v=' in response.text
    assert response.headers['Pragma'] == 'no-cache'
    assert response.headers['Expires'] == '0'
for path in ('/static/style.css', '/static/admin.js', '/api/version', '/api/public/inventory'):
    response = c.get(path)
    assert response.status_code == 200
    assert 'no-store' in response.headers['Cache-Control']
    assert response.headers['Pragma'] == 'no-cache'
assert c.get('/api/public/inventory').status_code==200
assert c.post('/api/admin/login',json={'password':'supersecretpassword'}).status_code==200
person={'first_name':'Test','last_name':'Person','phone':'1234567890','project':''}
assert c.post('/api/admin/people',json=person).status_code==200
pid=c.get('/api/admin/data').json()['people'][0]['id']
assert c.post('/api/public/people/'+pid+'/details').json()['phone']=='1234567890'
assert c.post('/api/admin/equipment',json={'name':'Batteries','category':'','tracking':'quantity','total_quantity':4,'notes':''}).status_code==422
assert c.post('/api/admin/equipment',json={'name':'Batteries','category':'Power','tracking':'quantity','total_quantity':4,'notes':''}).status_code==200
id=c.get('/api/public/inventory').json()[0]['id']
body={**person,'items':[{'equipment_id':id,'quantity':3}]}
assert c.post('/api/admin/checkout',json=body).status_code==200
loan=c.get('/api/admin/data').json()['loans'][0]
assert c.post('/api/admin/returns',json={'items':[{'loan_id':loan['id'],'quantity':1}]}).status_code==200
assert c.get('/api/public/inventory').json()[0]['available']==2
assert c.post('/api/public/returns/search',json=person).json()[0]['remaining']==2
assert c.post('/api/public/returns',json={**person,'loan_ids':[loan['id']]}).status_code==200
assert c.get('/api/public/inventory').json()[0]['available']==4
# legacy migration
legacy=json.loads(p.read_text());legacy['schema_version']=1;legacy.pop('people');legacy['equipment'][0]['category']='';p.write_text(json.dumps(legacy))
assert c.get('/api/public/inventory').json()[0]['category']=='Uncategorized'
assert p.with_name('equipment.json.v1-backup').exists()
print('PASS: admin auth, saved people, required categories, manual checkout, partial and public return, stock and v1 migration')
