"""Private pipe client for the system-Python KDE shortcut/paste bridge."""
import contextlib
import json
import os
from pathlib import Path
import subprocess
import threading
import uuid


class DesktopBridge:
    def __init__(self,app):
        self.app=app;self.focus={'id':'','app':''};self.ready=threading.Event()
        self.error=None;self.pending={};self.lock=threading.Lock()
        helper=Path(__file__).with_name('desktop_bridge.py')
        self.proc=subprocess.Popen([os.getenv('STT_SYSTEM_PYTHON','/usr/bin/python3'),str(helper)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,text=True,bufsize=1)
        self.thread=threading.Thread(target=self.read,name='stt-desktop-events',daemon=True)
        self.thread.start()
        if not self.ready.wait(8) or self.error:
            self.close();raise RuntimeError(self.error or 'Desktop bridge startup timed out')

    def read(self):
        try:
            for line in self.proc.stdout:
                event=json.loads(line);kind=event.get('event')
                if kind=='focus':self.focus={'id':event.get('id',''),'app':event.get('app','')}
                elif kind=='ready':self.ready.set()
                elif kind=='fatal':self.error=event.get('message','Desktop bridge failed');self.ready.set()
                elif kind in ('press','release'):
                    self.focus=dict(event.get('focus',self.focus));mode=event['mode']
                    if os.getenv('STT_TRIGGER_MODE','hold')=='toggle':
                        if kind=='press':
                            if self.app.recording:self.app.release(self.app.mode)
                            else:self.app.press(mode)
                    elif kind=='press':self.app.press(mode)
                    else:self.app.release(mode)
                elif kind in ('paste_result','pong'):
                    with self.lock:pending=self.pending.get(event.get('request'))
                    if pending:pending[1].update(event);pending[0].set()
        except (OSError,ValueError) as e:self.error=str(e)
        finally:
            self.ready.set()
            with self.lock:
                for done,result in self.pending.values():done.set()

    def snapshot(self):return dict(self.focus)

    def paste(self,target):
        if not target or not target.get('id') or target['id']!=self.focus.get('id'):
            return 'focus-changed'
        request=uuid.uuid4().hex;done=threading.Event();result={}
        with self.lock:
            self.pending[request]=(done,result)
            try:
                self.proc.stdin.write(json.dumps({'command':'paste','request':request,'window':target['id']})+'\n')
                self.proc.stdin.flush()
            except (OSError,ValueError):
                self.pending.pop(request,None);return 'unavailable'
        done.wait(1)
        with self.lock:self.pending.pop(request,None)
        return result.get('status','unavailable')

    def wait(self):return self.proc.wait()

    def close(self):
        with contextlib.suppress(Exception):
            if self.proc.poll() is None:
                self.proc.terminate();self.proc.wait(timeout=3)
