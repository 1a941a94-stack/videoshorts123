import argparse, json, subprocess, sys, os, tempfile
from pathlib import Path

def extract(url):
    import yt_dlp
    with yt_dlp.YoutubeDL({'quiet': True, 'skip_download': True, 'noplaylist': True}) as ydl:
        return ydl.extract_info(url, download=False)

from highlights import select

def render(source, start, end, output, banner=None):
    vf='[0:v]scale=1080:1920:force_original_aspect_ratio=decrease:force_divisible_by=2,pad=1080:1920:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1'
    print('CF_STAGE '+json.dumps({'stage':'framing','detail':''}),flush=True)
    from framing import plan
    try:
        adaptive=plan(source,start,end)
        if adaptive: vf='[0:v]'+adaptive
    except Exception as exc:
        print(f'Framing fallback: {exc}',file=sys.stderr)
    cmd=['ffmpeg','-hide_banner','-loglevel','error','-y','-ss',str(start),'-i',str(source)]
    if banner:
        from banners import Banner,media_input
        spec=banner if isinstance(banner,Banner) else Banner(Path(banner))
        cmd += media_input(spec.path)
        vf+=spec.filter(end-start)
    else: vf+='[v]'
    cmd+=['-filter_complex_threads','1','-filter_complex',vf,'-map','[v]','-map','0:a?','-t',str(end-start),'-c:v','libx264','-threads','2','-preset','veryfast','-crf','22','-pix_fmt','yuv420p','-c:a','aac','-movflags','+faststart','-map_metadata','-1','-map_metadata:s:v','-1','-map_metadata:s:a','-1','-map_chapters','-1',str(output)]
    if os.getenv('CLIP_CAPTIONS','0') == '1':
        from captions import prepare
        with tempfile.TemporaryDirectory() as folder:
            print('CF_STAGE '+json.dumps({'stage':'captions','detail':''}),flush=True)
            prepare(Path(source).resolve(),start,end,folder)
            # Absolute media paths allow a temporary working directory and simple ASS filename.
            for i,arg in enumerate(cmd[:-1]):
                if arg=='-i': cmd[i+1]=str(Path(cmd[i+1]).resolve())
            cmd[-1]=str(Path(output).resolve())
            idx=cmd.index('-filter_complex')+1
            cmd[idx]=cmd[idx].removesuffix('[v]')+'[pre];[pre]ass=captions.ass[v]'
            print('CF_STAGE '+json.dumps({'stage':'render','detail':''}),flush=True)
            subprocess.run(cmd,check=True,cwd=folder)
    else:
        print('CF_STAGE '+json.dumps({'stage':'render','detail':''}),flush=True)
        subprocess.run(cmd,check=True)

def download(url, clip, target):
    import shutil
    target=Path(target).resolve()
    base=[sys.executable,'-m','yt_dlp','--no-playlist','--newline',
          '--socket-timeout','25','--retries','2','--fragment-retries','2']
    fmt='bv*[height<=1080]+ba/b[height<=1080]'
    with tempfile.TemporaryDirectory(prefix='clip-download-',dir=target.parent) as folder:
        folder=Path(folder)
        section=folder/'section.mp4'
        try:
            subprocess.run(base+['--download-sections',f"*{clip['start']}-{clip['end']}",
                '--force-keyframes-at-cuts','-f',fmt,'--merge-output-format','mp4',
                '--remux-video','mp4','-o',str(section),url],check=True,timeout=300)
            if not section.is_file(): raise RuntimeError('Missing downloaded section')
            section.replace(target)
            return
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired,RuntimeError):
            print('CF_STAGE '+json.dumps({'stage':'fallback','detail':'Native download, then local cut'}),flush=True)
        if shutil.disk_usage(folder).free < 3*1024**3:
            raise RuntimeError('At least 3 GiB of free space required for full-source fallback')
        full=folder/'full.mp4'
        try:
            subprocess.run(base+['--downloader','native','--max-filesize','1G',
                '-f','bv*[height<=720][ext=mp4]+ba[ext=m4a]/b[height<=720][ext=mp4]',
                '--merge-output-format','mp4','--remux-video','mp4','-o',str(full),url],
                check=True,timeout=900)
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired) as exc:
            raise RuntimeError('Both section and native download failed; inspect download log and network connection') from exc
        if not full.is_file(): raise RuntimeError('Native downloader did not produce a video')
        print('CF_STAGE '+json.dumps({'stage':'localcut','detail':'Local FFmpeg'}),flush=True)
        subprocess.run(['ffmpeg','-hide_banner','-loglevel','error','-y','-ss',str(clip['start']),
            '-i',str(full),'-t',str(clip['end']-clip['start']),'-map','0:v:0','-map','0:a?',
            '-c:v','libx264','-preset','veryfast','-threads','2','-c:a','aac',str(target)],
            check=True,timeout=300)

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
