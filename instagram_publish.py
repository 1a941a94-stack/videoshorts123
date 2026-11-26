"""Instagram Reels via Facebook Login for Business and Meta Graph API."""
import os
import re
import time
import requests

def publish(row,path,token):
    version=os.getenv('CLIP_META_API_VERSION','v26.0')
    if not re.fullmatch(r'v\d+\.\d+',version): raise ValueError('Invalid Meta API version')
    user=str(row['destination'])
    if not re.fullmatch(r'\d{5,30}',user): raise ValueError('Expected numeric Instagram professional account ID')
    if len(row['caption'])>2200: raise ValueError('Caption too long')
    base='https://graph.facebook.com/'+version
    headers={'Authorization':'Bearer '+token}
    def call(method,url,**kwargs):
        response=requests.request(method,url,headers=headers,timeout=(15,60),allow_redirects=False,**kwargs)
        if not response.ok: raise RuntimeError('Meta API rejected request')
        result=response.json()
        if 'error' in result: raise RuntimeError('Meta API error')
        return result
    container=call('POST',f'{base}/{user}/media',data={'media_type':'REELS','upload_type':'resumable','caption':row['caption'],'share_to_feed':'true'})
    cid=str(container['id'])
    if not re.fullmatch(r'\d+',cid): raise RuntimeError('Invalid container ID')
    upload=f'https://rupload.facebook.com/ig-api-upload/{version}/{cid}'
    with path.open('rb') as fp:
        response=requests.post(upload,headers={'Authorization':'OAuth '+token,'offset':'0','file_size':str(path.stat().st_size),'Content-Type':'application/octet-stream'},data=fp,timeout=(15,300),allow_redirects=False)
    if not response.ok or not response.json().get('success'): raise RuntimeError('Meta upload failed')
    for _ in range(20):
        state=call('GET',f'{base}/{cid}',params={'fields':'status_code'}).get('status_code')
        if state=='FINISHED': break
        if state in ('ERROR','EXPIRED','PUBLISHED'): raise RuntimeError('Unexpected container state')
        time.sleep(30)
    else: raise RuntimeError('Meta processing timeout')
    media=str(call('POST',f'{base}/{user}/media_publish',data={'creation_id':cid})['id'])
    link=None
    try:
        link=call('GET',f'{base}/{media}',params={'fields':'permalink'}).get('permalink')
    except Exception: pass
    return media,link
