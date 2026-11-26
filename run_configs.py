import json
from pathlib import Path
from production_runs import ENV_KEYS
from short_templates import load as templates,validate
from caption_style import from_form

def load(root):
    p=Path(root)/'run-configs.json'
    return json.loads(p.read_text(encoding='utf-8')) if p.exists() else {'last':'','items':{}}

def write(root,data):
    p=Path(root)/'run-configs.json'
    tmp=p.with_suffix('.tmp')
    tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    tmp.replace(p)

def save(root,form):
    name=form.get('name','').strip()
    if not 1<=len(name)<=80: raise ValueError('Invalid configuration name')
    mode=form.get('mode','short')
    goal=int(form.get('goal',10))
    if mode not in ('short','long') or not 1<=goal<=1000: raise ValueError('Invalid configuration')
    data=load(root)
    if len(data['items'])>=100 and name not in data['items']: raise ValueError('Configuration limit')
    item=dict(mode=mode,goal=goal,template=form.get('template',''),campaign=form.get('campaign',''),auto_search=form.get('auto_search')=='1',captions=form.get('captions')=='1')
    resolve(root,item)
    data['items'][name]=item
    data['last']=name
    write(root,data)
    return name

def resolve(root,item):
    root=Path(root).resolve()
    name=item['template']
    spec=validate(templates(root)[name] if name else {'fit':'cover'})
    env=dict.fromkeys(ENV_KEYS)
    env.update(CLIP_SHORT_TEMPLATE=json.dumps(spec),CLIP_SHORT_LAYOUT=spec['layout'],CLIP_CAPTIONS='1' if item['captions'] else '0',CLIP_NORMALIZE_AUDIO='1',CLIP_COVER_MODE='auto',CLIP_SMART_SPEECH='1' if item['mode']=='long' else '0')
    if spec['background']:
        path=root/'assets'/'backgrounds'/spec['background']
        if not path.is_file(): raise ValueError('Background missing')
        env['CLIP_SHORT_BACKGROUND']=str(path)
    campaign=item['campaign']
    path=root/'campaigns.json'
    if campaign:
        if not path.is_file(): raise ValueError('Campaign missing')
        rows=json.loads(path.read_text(encoding='utf-8'))['campaigns']
        if not any(c['name']==campaign and c.get('enabled',True) for c in rows): raise ValueError('Campaign unavailable')
        env['CLIP_CAMPAIGN_NAME']=campaign
    perf=root/'performance.json'
    env['CLIP_ENCODER']=json.loads(perf.read_text(encoding='utf-8')).get('encoder','cpu') if perf.exists() else 'cpu'
    return dict(mode=item['mode'],env=env,campaigns=str(path) if campaign else None,auto_search=item['auto_search'])
