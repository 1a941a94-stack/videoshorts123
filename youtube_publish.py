"""YouTube Data API upload, using a locally authorized desktop OAuth credential."""
import argparse
import re
from pathlib import Path

SCOPES=['https://www.googleapis.com/auth/youtube.upload','https://www.googleapis.com/auth/youtube.readonly']

def channel_id(value):
    if not re.fullmatch(r'UC[A-Za-z0-9_-]{22}',value): raise ValueError('Expected YouTube channel ID (UC...)')
    return value

def credentials_path(root,channel):
    return Path(root)/'youtube-sessions'/(channel_id(channel)+'.json')

def login(root,channel,secrets_file):
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build
    flow=InstalledAppFlow.from_client_secrets_file(str(secrets_file),SCOPES)
    credentials=flow.run_local_server(port=0,prompt='consent',access_type='offline')
    api=build('youtube','v3',credentials=credentials,cache_discovery=False)
    verify(api,channel)
    path=credentials_path(root,channel)
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(credentials.to_json(),encoding='utf-8')
    print('YouTube channel verified')

def verify(api,channel):
    data=api.channels().list(part='id',mine=True).execute(num_retries=0)
    ids={item['id'] for item in data.get('items',[])}
    if channel_id(channel) not in ids: raise ValueError('OAuth channel does not match configured destination')

def read_video_status(api,channel,video_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',video_id): raise ValueError('Invalid video ID')
    verify(api,channel)
    data=api.videos().list(part='snippet,status',id=video_id).execute(num_retries=0)
    items=data.get('items',[])
    if len(items)!=1 or items[0].get('id')!=video_id or items[0].get('snippet',{}).get('channelId')!=channel:
        return 'unknown','Видео не найдено в указанном канале'
    status=items[0].get('status',{})
    upload=status.get('uploadStatus')
    privacy=status.get('privacyStatus')
    if upload=='processed' and privacy=='public': return 'public','Публичная публикация подтверждена'
    if upload=='processed' and privacy in ('private','unlisted'): return privacy,'Видео обработано, но не является публичным'
    if upload in ('failed','rejected','deleted'): return 'unavailable','Видео недоступно или отклонено'
    return 'processing','Обработка или состояние видео не подтверждены'

def inspect_publication(root,channel,video_id):
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build
    from google_auth_httplib2 import AuthorizedHttp
    import httplib2
    creds=Credentials.from_authorized_user_file(str(credentials_path(root,channel)),SCOPES)
    api=build('youtube','v3',http=AuthorizedHttp(creds,http=httplib2.Http(timeout=15)),cache_discovery=False)
    return read_video_status(api,channel,video_id)

class UploadBlocked(Exception):
    """No video insertion request attempted."""

def publish(root,row,path):
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload
        channel=channel_id(row['destination'])
        credential_file=credentials_path(root,channel)
        credentials=Credentials.from_authorized_user_file(str(credential_file),SCOPES)
        if not credentials.valid:
            credentials.refresh(Request())
            credential_file.write_text(credentials.to_json(),encoding='utf-8')
        api=build('youtube','v3',credentials=credentials,cache_discovery=False)
        verify(api,channel)
        caption=row['caption'].strip()
        title=(caption.splitlines()[0] if caption else 'Short video')[:100]
        body={'snippet':{'title':title,'description':caption[:5000],'categoryId':'24'},
              'status':{'privacyStatus':'private'}}
        media=MediaFileUpload(str(path),mimetype='video/mp4',chunksize=8*1024*1024,resumable=True)
        request=api.videos().insert(part='snippet,status',body=body,media_body=media,notifySubscribers=False)
    except Exception as exc:
        raise UploadBlocked('YouTube OAuth, channel or local media unavailable') from exc
    result=None
    while result is None:
        _,result=request.next_chunk(num_retries=0)
    vid=result['id']
    if not re.fullmatch(r'[A-Za-z0-9_-]{11}',vid): raise RuntimeError('Invalid uploaded video ID')
    return vid,'https://www.youtube.com/shorts/'+vid

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('channel')
    p.add_argument('client_secrets',type=Path)
    p.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    a=p.parse_args()
    login(a.root,a.channel,a.client_secrets)
