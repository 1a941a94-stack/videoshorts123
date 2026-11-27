"""Local credential presence, not a remote authorization guarantee."""
import os
from pathlib import Path

def describe(root, account):
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
    if account.get('lifecycle')=='archived':
        return 'Архив'
    if account.get('issues'):
        return 'Требуется проверка владельцем'
    return 'Локальные данные есть; вход не проверен' if present else 'Требуется подключение'
