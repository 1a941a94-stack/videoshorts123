"""Local credential presence, not a remote authorization guarantee."""
import os
from pathlib import Path

def describe(root, account):
    if account.get('lifecycle')=='archived':
        return 'Архив'
    platform=account['platform']
    if platform=='youtube':
        from youtube_publish import credentials_path
        try:
            present=credentials_path(root,account['destination']).is_file()
        except ValueError:
            return 'Некорректный ID канала'
    elif platform=='instagram_browser':
        from instagram_browser import username
        try:
            folder=Path(root)/'instagram-sessions'/username(account['destination'])/'browser'
            present=folder.is_dir() and any(folder.iterdir())
        except (ValueError,OSError):
            return 'Сессия недоступна'
    elif platform in ('telegram','instagram'):
        present=bool(os.getenv(account['token_env'],'').strip())
    else:
        return 'Адаптер не подключён'
    if account.get('issues'):
        return 'Требуется проверка владельцем'
    return 'Локальные данные есть; вход не проверен' if present else 'Требуется подключение'

def instructions(account):
    if account.get('lifecycle')=='archived':
        return 'Аккаунт архивирован. Новые публикации отключены.'
    p=account['platform']
    return {
        'youtube':'Подключите канал через OAuth Google на компьютере, где установлен ClipFactory. Проверьте совпадение ID канала. Загрузки пока сохраняются как private.',
        'instagram_browser':'Выполните вход владельцем в локальном браузере ClipFactory. Проверки безопасности завершайте вручную.',
        'instagram':'Настройте токен официального Meta API для профессионального аккаунта.',
        'telegram':'Настройте токен бота в окружении и предоставьте ему право публикации в целевом канале.',
        'tiktok':'Адаптер публикаций пока не подключён.',
        'vk':'Адаптер публикаций пока не подключён.'
    }.get(p,'Подключение не поддерживается')

def check_connection(root, account):
    """Read-only API verification; never creates a post or clears a restriction."""
    import requests
    platform=account['platform']
    if platform not in ('telegram','youtube'):
        return False,'Удалённая проверка для этого адаптера пока недоступна'
    try:
        if platform=='telegram':
            token=os.getenv(account['token_env'],'').strip()
            if not token: return False,'Токен не настроен'
            base='https://api.telegram.org/bot'+token
            def get(method,params=None):
                r=requests.get(base+'/'+method,params=params,timeout=10)
                data=r.json()
                if not r.ok or not data.get('ok'): raise ValueError('Telegram API rejected request')
                return data['result']
            bot=get('getMe')
            chat=get('getChat',{'chat_id':account['destination']})
            member=get('getChatMember',{'chat_id':chat['id'],'user_id':bot['id']})
            allowed=member.get('status')=='creator' or (member.get('status')=='administrator' and member.get('can_post_messages') is True)
            return allowed,'Право публикации в канале подтверждено' if allowed else 'Нет подтверждённого права публикации в канале'
        from youtube_publish import credentials_path,SCOPES,verify
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        import httplib2
        from google_auth_httplib2 import AuthorizedHttp
        path=credentials_path(root,account['destination'])
        if not path.is_file(): return False,'OAuth не настроен'
        creds=Credentials.from_authorized_user_file(str(path),SCOPES)
        if not creds.valid:
            request=Request()
            def bounded(*args,**kwargs):
                kwargs['timeout']=10
                return request(*args,**kwargs)
            creds.refresh(bounded)
        api=build('youtube','v3',http=AuthorizedHttp(creds,http=httplib2.Http(timeout=10)),cache_discovery=False)
        verify(api,account['destination'])
        return True,'OAuth и ID канала подтверждены'
    except Exception:
        return False,'API недоступен или подключение не подтверждено; проверьте настройки'


def init_checks(db):
    db.execute("""CREATE TABLE IF NOT EXISTS account_connection_checks(
        account_id INTEGER PRIMARY KEY REFERENCES accounts(id),
        checked INTEGER NOT NULL, ok INTEGER NOT NULL, detail TEXT NOT NULL,
        last_success INTEGER)""")


def save_check(db,aid,ok,detail):
    import time
    now=int(time.time())
    with db:
        init_checks(db)
        db.execute("""INSERT INTO account_connection_checks(account_id,checked,ok,detail,last_success)
        VALUES(?,?,?,?,?) ON CONFLICT(account_id) DO UPDATE SET
        checked=excluded.checked,ok=excluded.ok,detail=excluded.detail,
        last_success=coalesce(excluded.last_success,account_connection_checks.last_success)""",
        (aid,now,int(ok),detail[:300],now if ok else None))


def decorate_checks(db,accounts):
    from datetime import datetime,timezone
    init_checks(db)
    def label(value):
        return datetime.fromtimestamp(value,timezone.utc).strftime('%Y-%m-%d %H:%M UTC') if value is not None else '—'
    for account in accounts:
        row=db.execute('SELECT * FROM account_connection_checks WHERE account_id=?',(account['id'],)).fetchone()
        account['connection_check']=None if row is None else dict(
            ok=bool(row['ok']),detail=row['detail'],checked=label(row['checked']),
            last_success=label(row['last_success']))
    return accounts
