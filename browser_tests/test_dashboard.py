"""Browser integration tests; never use the user's database or media."""
import json
import tempfile
import threading
from pathlib import Path
import pytest
from playwright.sync_api import expect
from werkzeug.serving import make_server
from dashboard import create_app

@pytest.fixture
def local_app():
    with tempfile.TemporaryDirectory() as folder:
        root=Path(folder)
        app=create_app(root)
        server=make_server('127.0.0.1',0,app,threaded=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{server.server_port}',root
        finally:
            server.shutdown()
            thread.join(timeout=10)
            server.server_close()

def test_navigation_and_api(page,local_app):
    url,root=local_app
    errors=[]
    page.on('pageerror',lambda error: errors.append(str(error)))
    page.goto(url)
    for view,section in [('queue','queue'),('library','sources'),('results','clips'),('design','short-template'),('media','media-library'),('ads','campaigns'),('storage','storage'),('system','diagnostics'),('overview','production-runs')]:
        page.locator(f'nav [data-view="{view}"]').first.click()
        expect(page.locator('#'+section)).to_be_visible()
    for endpoint in ('/api/job-status','/api/production','/api/queue','/api/storage','/api/diagnostics'):
        assert page.request.get(url+endpoint).ok, endpoint
    assert not errors,errors

def test_first_run_and_configuration(page,local_app):
    url,root=local_app
    page.goto(url)
    page.get_by_role('button',name='Создать стандартную конфигурацию').click()
    expect(page.locator('#run-launch')).to_be_visible()
    expect(page.locator('#launch-goal')).to_have_value('10')
    assert json.loads((root/'run-configs.json').read_text(encoding='utf-8'))['items']
    page.goto(url+'/#run-configurations')
    form=page.locator('#config-form')
    form.locator('[name=name]').fill('Browser smoke')
    form.locator('[name=goal]').fill('3')
    form.locator('[name=auto_search]').uncheck()
    form.get_by_role('button',name='Сохранить конфигурацию').click()
    expect(page.locator('#launch-goal')).to_have_value('3')
    assert json.loads((root/'run-configs.json').read_text(encoding='utf-8'))['items']['Browser smoke']['auto_search'] is False

def test_studio_and_safe_zone(page,local_app):
    url,root=local_app
    page.goto(url+'/#short-template')
    form=page.locator('#template-form')
    expect(form).to_be_visible()
    page.locator('[data-layer=video]').click()
    form.locator('[name=name]').fill('browser_template')
    form.locator('[name=source_zoom]').fill('180')
    form.locator('[name=source_pan_x]').fill('40')
    assert 'scale(1.8)' in page.locator('#studio-source').evaluate('(el)=>el.style.transform')
    page.locator('#studio-safe-toggle').check()
    expect(page.locator('#studio-safe')).to_be_visible()
    page.locator('#studio-seek').fill('2')
    expect(page.locator('#studio-time')).to_contain_text('2.0')
    form.get_by_role('button',name='Сохранить шаблон').click()
    saved=json.loads((root/'short-templates.json').read_text(encoding='utf-8'))['browser_template']
    assert saved['source_zoom']==180 and saved['source_pan_x']==40

def test_csrf_rejects_untrusted_post(page,local_app):
    url,root=local_app
    page.goto(url)
    assert page.request.post(url+'/sources',form={'query':'test'}).status==403
