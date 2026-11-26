"""Storage maintenance. Never remove original imports or live outputs."""
import shutil
from pathlib import Path

def size(path):
    return sum(p.stat().st_size for p in path.rglob('*') if p.is_file() and not p.is_symlink()) if path.is_dir() else 0

def stats(root,db):
    root=Path(root).resolve()
    out=root/'output'
    cache=out/'source-cache'
    trash=0
    counted=set()
    for row in db.execute("SELECT output,cover FROM clips WHERE status='archived' UNION SELECT v.output,v.cover FROM clip_versions v JOIN clips c ON c.id=v.clip_id WHERE c.status='archived'"):
        for value in row:
            if value:
                p=(root/value).resolve()
                if p.is_relative_to(out) and p.is_file() and p not in counted:
                    counted.add(p)
                    trash+=p.stat().st_size
    usage=shutil.disk_usage(root)
    return dict(free=usage.free,total=usage.total,cache=size(cache),originals=size(root/'local-sources'),output=max(0,size(out)-size(cache)-trash),trash=trash,assets=size(root/'assets'))

def purge(db,root,ids):
    root=Path(root).resolve()
    out=root/'output'
    marks=','.join('?' for _ in ids)
    rows=db.execute(f"SELECT id,output,cover,status FROM clips WHERE id IN ({marks})",ids).fetchall()
    if len(rows)!=len(ids) or any(r['status']!='archived' for r in rows): raise ValueError('Удалять окончательно можно только из корзины')
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='publications'").fetchone():
        if db.execute(f'SELECT 1 FROM publications WHERE clip_id IN ({marks}) LIMIT 1',ids).fetchone(): raise ValueError('Есть записи публикации')
    paths=set()
    versions=db.execute(f'SELECT clip_id AS id,output,cover FROM clip_versions WHERE clip_id IN ({marks})',ids).fetchall()
    for r in [*rows,*versions]:
        for key in ('output','cover'):
            if r[key]:
                p=(root/r[key]).resolve()
                if not p.is_relative_to(out) or p.suffix not in ('.mp4','.jpg'): raise ValueError('Недопустимый путь')
                if db.execute('SELECT 1 FROM clips WHERE id!=? AND (output=? OR cover=?)',(r['id'],r[key],r[key])).fetchone(): raise ValueError('Файл используется другой записью')
                if db.execute('SELECT 1 FROM clip_versions WHERE clip_id!=? AND (output=? OR cover=?)',(r['id'],r[key],r[key])).fetchone(): raise ValueError('Файл используется историей другого ролика')
                paths.add(p)
    for p in paths: p.unlink(missing_ok=True)
    with db:
        db.execute(f'DELETE FROM clip_versions WHERE clip_id IN ({marks})',ids)
        db.execute(f"UPDATE clips SET status='purged',output=NULL,cover=NULL,archived_status=NULL WHERE id IN ({marks})",ids)
    return len(rows)

def clear_cache(root):
    cache=Path(root).resolve()/'output'/'source-cache'
    if cache.is_symlink(): raise ValueError('Недопустимый путь кеша')
    if cache.is_dir(): shutil.rmtree(cache)
