"""Optional H.264 hardware encoding. Default remains predictable CPU encoding."""
import os
import subprocess
from functools import lru_cache

CPU=['-c:v','libx264','-threads','2','-preset','veryfast','-crf','22']
QSV=['-c:v','h264_qsv','-preset','medium','-global_quality','23']

@lru_cache(maxsize=1)
def qsv_available():
    try:
        subprocess.run(['ffmpeg','-v','error','-f','lavfi','-i','color=s=128x128:r=30','-frames:v','3','-pix_fmt','nv12',*QSV,'-f','null','-'],capture_output=True,check=True,timeout=20)
        return True
    except (OSError,subprocess.SubprocessError): return False

def encode(command,tail,output,cwd,mode=None,report=print):
    mode=mode or os.getenv('CLIP_ENCODER','cpu')
    if mode not in ('cpu','auto','qsv'): raise ValueError('Invalid encoder')
    if mode!='cpu' and qsv_available():
        try:
            subprocess.run([*command,*QSV,'-pix_fmt','nv12',*tail,str(output)],check=True,cwd=cwd,timeout=600,stderr=subprocess.PIPE)
            return 'qsv'
        except (subprocess.CalledProcessError,subprocess.TimeoutExpired):
            output.unlink(missing_ok=True)
            report('Quick Sync failed; falling back to CPU')
    try:
        subprocess.run([*command,*CPU,'-pix_fmt','yuv420p',*tail,str(output)],check=True,cwd=cwd,timeout=600,stderr=subprocess.PIPE)
    except subprocess.CalledProcessError as exc:
        detail=(exc.stderr or b'').decode('utf-8','replace').strip()
        raise RuntimeError('FFmpeg: '+(detail[-850:] or f'exit code {exc.returncode}')) from exc
    return 'cpu'
