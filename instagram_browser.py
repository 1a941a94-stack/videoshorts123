"""Visible browser workflow for personal Instagram accounts; no challenge bypass."""
import argparse
import re
from pathlib import Path
from contextlib import contextmanager
from filelock import FileLock

class BrowserBlocked(Exception):
    """No share action was attempted."""

def username(value):
    value=value.strip().lstrip('@').lower()
    if not re.fullmatch(r'[a-z0-9_.]{1,30}',value): raise ValueError('Invalid Instagram username')
    return value

@contextmanager
def browser(root,handle):
    from playwright.sync_api import sync_playwright
    folder=Path(root).resolve()/'instagram-sessions'/username(handle)
    folder.mkdir(parents=True,exist_ok=True)
    with FileLock(str(folder/'session.lock'),timeout=0),sync_playwright() as p:
        context=p.chromium.launch_persistent_context(str(folder/'browser'),headless=False,viewport={'width':1280,'height':900})
        try: yield context.pages[0] if context.pages else context.new_page()
        finally: context.close()

def check(page):
    url=page.url.lower()
    if any(s in url for s in ('/challenge','/checkpoint','/accounts/login','/two_factor')):
        raise BrowserBlocked('Instagram requires manual login or verification')
    if page.get_by_text(re.compile(r'captcha|confirm it.s you|verify your identity|try again later|подтвердите.*личность|попробуйте позже',re.I)).count():
        raise BrowserBlocked('Instagram verification or restriction')

def verify_account(page,handle):
    page.goto('https://www.instagram.com/',wait_until='domcontentloaded',timeout=60000)
    check(page)
    link=page.locator('a[href="/'+username(handle)+'/"]').first
    try: link.wait_for(state='visible',timeout=20000)
    except Exception: raise BrowserBlocked('Cannot verify active Instagram account')
    check(page)

def login(root,handle):
    with browser(root,handle) as page:
        page.goto('https://www.instagram.com/accounts/login/')
        input('Log in manually, complete verification, then press Enter: ')
        verify_account(page,handle)
        print('Instagram session verified')

def manual_login_window(root,handle):
    """Open a visible login window; the owner enters all credentials and closes it."""
    from playwright.sync_api import TimeoutError
    with browser(root,handle) as page:
        page.goto('https://www.instagram.com/accounts/login/',wait_until='domcontentloaded',timeout=60000)
        try: page.wait_for_event('close',timeout=300000)
        except TimeoutError: pass

def verify_session(root,handle):
    with browser(root,handle) as page:
        verify_account(page,handle)

def publish(root,row,path):
    handle=username(row['destination'])
    if len(row['caption'])>2200: raise BrowserBlocked('Caption too long')
    with browser(root,handle) as page:
        try:
            verify_account(page,handle)
            create=page.get_by_role('link',name=re.compile(r'^(Create|Создать)$',re.I))
            if not create.count(): create=page.get_by_role('button',name=re.compile(r'^(Create|Создать)$',re.I))
            create.first.click(timeout=15000)
            post=page.get_by_text(re.compile(r'^(Post|Публикация)$',re.I))
            if post.count(): post.first.click(timeout=10000)
            check(page)
            chooser=page.locator('input[type=file]').first
            chooser.set_input_files(str(path),timeout=30000)
            for _ in range(2):
                check(page)
                page.get_by_role('button',name=re.compile(r'^(Next|Далее)$',re.I)).last.click(timeout=60000)
            check(page)
            caption=page.locator('[contenteditable=true][role=textbox]').last
            if row['caption']: caption.fill(row['caption'],timeout=15000)
            share=page.get_by_role('button',name=re.compile(r'^(Share|Поделиться)$',re.I)).last
            share.wait_for(state='visible',timeout=15000)
            check(page)
        except BrowserBlocked: raise
        except Exception as exc: raise BrowserBlocked('Instagram interface or session unavailable before sharing') from exc
        # Once the share click is attempted, any failure is uncertain; never retry blindly.
        share.click(timeout=15000)
        page.get_by_text(re.compile(r'your (post|reel) has been shared|публикация опубликована|видео reels опубликовано',re.I)).first.wait_for(timeout=120000)
        return None,None

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('username')
    parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parent)
    parser.add_argument('--manual-window',action='store_true')
    args=parser.parse_args()
    if args.manual_window: manual_login_window(args.root,args.username)
    else: login(args.root,args.username)
