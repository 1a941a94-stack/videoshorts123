"""Smoke test against an isolated running business container; no external accounts."""
import http.cookiejar
import re
import urllib.parse
import urllib.request
import sqlite3
from pathlib import Path

base = 'http://127.0.0.1:8080'
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def get(path):
    with client.open(base + path, timeout=20) as response:
        assert response.status == 200, path
        return response.read().decode()

def post(path, token):
    data = urllib.parse.urlencode({'csrf': token}).encode()
    with client.open(base + path, data=data, timeout=20) as response:
        assert response.status == 200, path

def controller():
    with sqlite3.connect('/data/clipfactory.sqlite3') as db:
        return db.execute('SELECT enabled FROM factory_controller WHERE id=1').fetchone()[0]

for path in ('/healthz', '/', '/business', '/business/accounts', '/business/calendar',
             '/business/monetization', '/business/finance', '/business/analytics',
             '/business/reports', '/business/resources', '/business/library', '/publishing'):
    get(path)
    print('HTTP OK', path)
token = re.search(r'name="csrf" value="([^"]+)"', get('/business')).group(1)
assert controller() == 0
try:
    post('/business/controller/start', token)
    assert controller() == 1
    print('Controller start persisted')
finally:
    post('/business/controller/stop', token)
assert controller() == 0
print('Controller stop persisted')
assert Path('/data/clipfactory.sqlite3').is_file()
