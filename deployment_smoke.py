"""Smoke test against an isolated running business container; no external accounts."""
import http.cookiejar
import re
import urllib.parse
import urllib.request
import sqlite3
import sys
import json
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
import telethon
import requests

base = 'http://127.0.0.1:8080'
client = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
def get(path):
    with client.open(base + path, timeout=20) as response:
        assert response.status == 200, path
        return response.read().decode()

def post(path, token, **fields):
    data = urllib.parse.urlencode({'csrf': token, **fields}).encode()
    with client.open(base + path, data=data, timeout=20) as response:
        assert response.status == 200, path
        return response.geturl()

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
if '--restart' in sys.argv:
    with sqlite3.connect('/data/clipfactory.sqlite3') as db:
        config = json.loads(db.execute('SELECT config FROM business_settings WHERE id=1').fetchone()[0])
        assert config['configuration'] == 'ci-smoke', config
    print('Configuration and stopped controller survived restart')
    url = post('/business/controller/start', token)
    try:
        assert 'error=' not in url, url
        assert controller() == 1
    finally:
        post('/business/controller/stop', token)
    assert controller() == 0
    print('Controller can start and stop after restart')
    sys.exit(0)
# An unconfigured installation must refuse to start.
url = post('/business/controller/start', token)
assert 'error=' in url, url
assert controller() == 0
print('Unconfigured start rejected')
# Configure an isolated local-only production profile through the actual UI.
post('/run-configs', token, name='ci-smoke', mode='long', goal='1')
url = post('/business/settings', token, configuration='ci-smoke')
assert 'error=' not in url, url
try:
    url = post('/business/controller/start', token)
    assert 'error=' not in url, url
    assert controller() == 1
    print('Controller start persisted')
finally:
    post('/business/controller/stop', token)
assert controller() == 0
print('Controller stop persisted')
assert Path('/data/clipfactory.sqlite3').is_file()
