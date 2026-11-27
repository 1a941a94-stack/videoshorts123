import json
from pathlib import Path

def load(root):
    p=Path(root)/'telegram-proxy.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'type':'direct','host':'','port':1080,'username':'','password':''}

def save(root,form):
    kind=form.get('type','direct')
    if kind not in ('direct','socks5','http'): raise ValueError('Неизвестный тип прокси')
    host=form.get('host','').strip()
    port=int(form.get('port') or 1080)
    if kind!='direct' and (not host or len(host)>253 or any(c.isspace() for c in host) or '/' in host or not 1<=port<=65535):
        raise ValueError('Укажите адрес и порт прокси')
    old=load(root)
    username=form.get('username','')
    password=form.get('password','') or (old.get('password','') if old.get('host')==host and old.get('port')==port and old.get('type')==kind and old.get('username')==username else '')
    if form.get('clear_password')=='1': password=''
    if kind=='direct': username=password=''
    data=dict(type=kind,host=host,port=port,username=username,password=password)
    p=Path(root)/'telegram-proxy.json'
    temp=p.with_suffix('.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
    temp.replace(p)

def connection_options(root):
    cfg=load(root)
    if cfg['type']=='direct': return {}
    return {'proxy':dict(proxy_type=cfg['type'],addr=cfg['host'],port=int(cfg['port']),rdns=True,username=cfg.get('username') or None,password=cfg.get('password') or None)}

def check(root):
    from telegram_source import client
    from filelock import FileLock
    with FileLock(str(Path(root)/'telegram-reader.lock'),timeout=0):
        c=client(root)
        try:
            c.connect()
            return c.is_user_authorized()
        finally: c.disconnect()
