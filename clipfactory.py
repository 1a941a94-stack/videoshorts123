import argparse, json, subprocess, sys
from pathlib import Path

def extract(url):
    import yt_dlp
    with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True, 'noplaylist': True}) as ydl:
        return ydl.extract_info(url, download=False)

from highlights import select

def render(source, start, end, output, banner=None):
    vf='[0:v]scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1'
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-y','-ss',str(start),'-i',str(source)]
    if banner:
        cmd += ['-i',str(banner)]
        vf+='[base];[1:v]scale=1000:260:force_original_aspect_ratio=decrease[ad];[base][ad]overlay=(W-w)/2:H-h-180[v]'
    else: vf+='[v]'
    cmd+=['-filter_complex_threads','1','-filter_complex',vf,'-map','[v]','-map','0:a?','-t',str(end-start),'-c:v','libx264','-threads','2','-preset','veryfast','-crf','22','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart',str(output)]
    subprocess.run(cmd,check=True)

def download(url, clip, target):
    subprocess.run([sys.executable,'-m','yt_dlp','--no-playlist','--download-sections',f"*{clip['start']}-{clip['end']}",'--force-keyframes-at-cuts','-f','bv*[height<=1080]+ba/b[height<=1080]','--merge-output-format','mp4','--remux-video','mp4','-o',str(target),url],check=True)

def main():
    ap=argparse.ArgumentParser(); sub=ap.add_subparsers(dest='action',required=True)
    for action in ('analyze','make','search'):
        p=sub.add_parser(action); p.add_argument('source'); p.add_argument('--length',type=int,default=45); p.add_argument('--count',type=int,default=3); p.add_argument('--threshold',type=float,default=.7); p.add_argument('--out',type=Path,default=Path('output')); p.add_argument('--banner',type=Path); p.add_argument('--metadata',type=Path); p.add_argument('--limit',type=int,default=20)
    a=ap.parse_args(); a.out.mkdir(parents=True,exist_ok=True)
    if a.length<=0 or a.count<=0 or not 0<=a.threshold<=1: ap.error('Invalid length/count/threshold')
    if a.action=='search':
        import yt_dlp
        with yt_dlp.YoutubeDL({'quiet':True,'extract_flat':True}) as ydl: entries=ydl.extract_info(f'ytsearch{a.limit}:{a.source}',download=False)['entries']
        results=[]
        for entry in entries:
            try:
                url='https://www.youtube.com/watch?v='+entry['id']; info=extract(url); clips=select(info,a.length,a.count,a.threshold)
                if clips: results.append({'url':url,'title':info.get('title'),'clips':clips})
            except Exception as e: print(str(e),file=sys.stderr)
        (a.out/'search.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(results,ensure_ascii=False,indent=2)); return
    info=json.loads(a.metadata.read_text(encoding='utf-8')) if a.metadata else extract(a.source)
    clips=select(info,a.length,a.count,a.threshold)
    report={'title':info.get('title'),'has_heatmap':bool(info.get('heatmap')),'clips':clips}
    (a.out/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(report,ensure_ascii=False,indent=2))
    if a.action=='make':
        for i,c in enumerate(clips):
            dest=a.out/f'clip_{i+1}.mp4'
            if a.metadata: render(a.source,c['start'],c['end'],dest,a.banner)
            else:
                raw=a.out/f'raw_{i+1}.mp4'; download(a.source,c,raw); render(raw,0,c['end']-c['start'],dest,a.banner); raw.unlink()

if __name__=='__main__': main()
