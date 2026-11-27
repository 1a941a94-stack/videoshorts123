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
    """Check transport independently of the persistent Telegram session."""
    import socket
    cfg=load(root)
    target='149.154.167.51'
    if cfg['type']=='direct':
        sock=socket.create_connection((target,443),timeout=10)
    else:
        from python_socks.sync import Proxy
        from python_socks import ProxyType
        proxy=Proxy.create(proxy_type=ProxyType.SOCKS5 if cfg['type']=='socks5' else ProxyType.HTTP,host=cfg['host'],port=int(cfg['port']),username=cfg.get('username') or None,password=cfg.get('password') or None,rdns=True)
        sock=proxy.connect(dest_host=target,dest_port=443,timeout=10)
    sock.close()
    return True
