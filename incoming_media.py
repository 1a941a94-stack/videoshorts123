"""Bounded intake of operator-provided videos from an explicit local inbox."""
import time
from pathlib import Path
from local_import import import_file, EXTENSIONS

def ingest(db, root, goal, now=None, importer=import_file):
    now=time.time() if now is None else now
    folder=Path(root)/'incoming-media'
    folder.mkdir(exist_ok=True)
    if folder.is_symlink(): raise ValueError('Incoming folder cannot be a symbolic link')
    db.execute("""CREATE TABLE IF NOT EXISTS incoming_media_seen(
        name TEXT PRIMARY KEY, size INTEGER NOT NULL, modified INTEGER NOT NULL,
        outcome TEXT NOT NULL)""")
    db.commit()
    added=duplicates=errors=attempts=0
    for path in sorted(folder.iterdir()):
        if added>=min(max(0,goal),20) or attempts>=40: break
        if path.is_symlink() or not path.is_file() or path.suffix.lower() not in EXTENSIONS: continue
        try: info=path.stat()
        except OSError: continue
        if now-info.st_mtime<30: continue
        seen=db.execute('SELECT size,modified FROM incoming_media_seen WHERE name=?',(path.name,)).fetchone()
        if seen and tuple(seen)==(info.st_size,info.st_mtime_ns): continue
        attempts+=1
        try:
            outcome=importer(db,root,path)
        except Exception:
            db.rollback()
            outcome='error'
        with db:
            db.execute('INSERT OR REPLACE INTO incoming_media_seen VALUES(?,?,?,?)',
                       (path.name,info.st_size,info.st_mtime_ns,outcome))
        if outcome=='ready': added+=1
        elif outcome=='duplicate': duplicates+=1
        else: errors+=1
    return dict(added=added,duplicates=duplicates,errors=errors)
