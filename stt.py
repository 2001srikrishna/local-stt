#!/usr/bin/env python3
"""Push-to-talk dictation: Home=offline Whisper, Insert=Groq (optional).

One listener, bounded background transcription, native Wayland clipboard.
Imports have no desktop/listener side effects, so the core can be tested offline.
"""
from __future__ import annotations
import argparse
import contextlib
import fcntl
import json
import math
import os
from pathlib import Path
import queue
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
import time

HOME = Path.home()
VENV = HOME/'.local/share/opencode-stt/venv/bin/python'
if __name__ == '__main__' and sys.prefix == sys.base_prefix and VENV.is_file():
    if Path(sys.executable).resolve() != VENV.resolve():
        os.execv(str(VENV), [str(VENV), str(Path(__file__).resolve()), *sys.argv[1:]])

import numpy as np
from scipy.io.wavfile import write
from scipy.signal import resample_poly

STATE = HOME/'.local/state/opencode-stt'
CONFIG = HOME/'.config/local-stt/stt.env'


def load_settings(path=CONFIG):
    """Read literal environment assignments; never execute shell code."""
    if not path.is_file(): return
    for line in path.read_text().splitlines():
        line=line.strip().removeprefix('export ')
        if not line or line.startswith('#') or '=' not in line: continue
        key,value=line.split('=',1)
        if not (key.startswith('STT_') or key=='GROQ_API_KEY'): continue
        try: parts=shlex.split(value,comments=True)
        except ValueError: continue
        if len(parts)==1: os.environ.setdefault(key,parts[0])


def cloud_key():
    if os.getenv('GROQ_API_KEY'): return os.environ['GROQ_API_KEY']
    # Existing installation compatibility. Read only this literal key.
    path=HOME/'.config/aider/credentials.env'
    if path.is_file():
        for line in path.read_text().splitlines():
            line=line.strip().removeprefix('export ')
            if line.startswith('GROQ_API_KEY='):
                try: values=shlex.split(line.split('=',1)[1],comments=True)
                except ValueError: continue
                if len(values)==1 and '$' not in values[0] and '`' not in values[0]: return values[0]
    return None


def notify(message, title='STT', urgency='low'):
    if shutil.which('notify-send'):
        try: subprocess.Popen(['notify-send','-u',urgency,title,message],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except OSError: pass


def clipboard_commands(wayland):
    way=['wl-copy','--type','text/plain;charset=utf-8']
    x11=['xclip','-selection','clipboard']
    return [way,x11] if wayland else [x11,way]


def deliver(text, announce=True):
    """Use the clipboard immediately; never inject a delayed result into another app."""
    wayland=bool(os.getenv('WAYLAND_DISPLAY')) or os.getenv('XDG_SESSION_TYPE')=='wayland'
    for cmd in clipboard_commands(wayland):
        if shutil.which(cmd[0]):
            try:
                subprocess.run(cmd,input=text.encode(),check=True,timeout=1,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                if announce:notify('Transcript copied — Ctrl+V to paste')
                return 'clipboard'
            except (OSError,subprocess.SubprocessError): pass
    raise RuntimeError('Could not copy transcript. Check wl-copy/xclip and the desktop session.')


def parse_local_text(stdout):
    # Preserve EVERY segment. The legacy implementation returned only lines[-1].
    return ' '.join(line.strip() for line in stdout.splitlines() if line.strip() and not line.lstrip().startswith('[')).strip()


def prepare_audio(audio, rate):
    audio=np.asarray(audio,dtype=np.float32).reshape(-1)
    if audio.size<rate*.35: raise ValueError('Recording too short (minimum 0.35 seconds)')
    if not np.all(np.isfinite(audio)): raise ValueError('Invalid audio samples')
    peak=float(np.max(np.abs(audio))); rms=float(np.sqrt(np.mean(audio**2)))
    if peak<float(os.getenv('STT_MIN_AUDIO_PEAK','0.00001')) or rms<1e-6:
        raise ValueError('No usable microphone signal; check input device/mute')
    # Avoid amplifying near-silence by thousands of times. Never scale down speech unnecessarily.
    gain=min(8.0,0.95/peak)
    audio=np.clip(audio*gain,-1,1)
    if rate!=16000:
        divisor=math.gcd(int(rate),16000)
        audio=resample_poly(audio,16000//divisor,int(rate)//divisor)
    return (audio*32767).astype(np.int16), {'peak':peak,'rms':rms,'gain':gain,'input_rate':rate,'audio_seconds':round(len(audio)/16000,3),'clipped_fraction':float(np.mean(np.abs(np.asarray(audio,dtype=np.float32)/gain)>=.999))}


class Engine:
    def __init__(self):
        self.binary=os.getenv('STT_WHISPER_BIN',str(HOME/'whisper.cpp/whisper-cli'))
        self.model=os.path.expanduser(os.getenv('STT_WHISPER_MODEL',str(HOME/'whisper.cpp/models/ggml-base.en.bin')))
        self.threads=int(os.getenv('STT_THREADS','8'))
        self.client=None
        self.local_client=None

    def local(self,path):
        if os.getenv('STT_RESIDENT')=='1':
            import httpx
            if self.local_client is None:
                self.local_client=httpx.Client(timeout=httpx.Timeout(90,connect=.3),trust_env=False)
            try:
                with open(path,'rb') as f:
                    response=self.local_client.post('http://127.0.0.1:'+os.getenv('STT_SERVER_PORT','18765')+'/inference',files={'file':(Path(path).name,f,'audio/wav')},data={'response_format':'json','language':os.getenv('STT_LANGUAGE','en'),'beam_size':'5','best_of':'5','temperature':'0'})
                response.raise_for_status()
                return parse_local_text(response.json()['text'])
            except (httpx.HTTPError,ValueError,KeyError,OSError):
                print('Resident local engine unavailable; using standalone Whisper.',flush=True)
        result=subprocess.run([self.binary,'-m',self.model,'-f',str(path),'-t',str(self.threads),'-bs','5','-bo','5','-ac','0','--no-timestamps','--no-gpu','-l',os.getenv('STT_LANGUAGE','en')],capture_output=True,text=True,timeout=90)
        if result.returncode:
            raise RuntimeError('Local Whisper failed: '+(result.stderr.strip().splitlines() or ['unknown error'])[-1])
        return parse_local_text(result.stdout)

    def serve(self):
        binary=os.getenv('STT_WHISPER_SERVER',str(Path(self.binary).with_name('whisper-server')))
        args=[binary,'-m',self.model,'-t',str(self.threads),'-bs','5','-bo','5','-ng','-nt','--host','127.0.0.1','--port',os.getenv('STT_SERVER_PORT','18765')]
        os.execv(binary,args)

    def cloud(self,path):
        key=cloud_key()
        if not key: raise RuntimeError('GROQ_API_KEY not configured')
        if self.client is None:
            import httpx
            from groq import Groq
            # No invisible multi-retry stalls. Fall back to local on a failed cloud request.
            self.client=Groq(api_key=key,max_retries=0,timeout=httpx.Timeout(25,connect=5))
        with open(path,'rb') as f:
            return self.client.audio.transcriptions.create(file=(Path(path).name,f.read()),model='whisper-large-v3-turbo',language=os.getenv('STT_LANGUAGE','en'),response_format='text',temperature=0).strip()

    def transcribe(self,path,mode):
        if mode=='groq':
            try:return self.cloud(path),'Groq'
            except Exception as e:
                # Avoid logging provider error bodies or request credentials.
                print(f'Cloud request failed ({type(e).__name__}); using local Whisper.',flush=True)
                notify('Cloud unavailable — transcribing locally',urgency='normal')
        return self.local(path),'Local'


class Dictation:
    def __init__(self,sd,engine=None):
        self.sd=sd; self.engine=engine or Engine()
        self.stream=None; self.recording=False; self.chunks=[]; self.rate=16000
        self.frames=0; self.mode=None; self.device_name=''; self.overflow=False
        self.desktop=None; self.origin_focus=None
        self.started=0; self.max_seconds=int(os.getenv('STT_MAX_SECONDS','120'))
        self.jobs=queue.Queue(maxsize=1); self.shutdown=threading.Event()
        self.worker=threading.Thread(target=self.work,name='stt-transcription',daemon=True)
        self.worker.start()

    def device(self):
        # Re-resolve on EVERY press: headphones/microphone can change between recordings.
        devices=self.sd.query_devices(); requested=os.getenv('STT_INPUT_DEVICE','').strip()
        if requested:
            if requested.isdigit(): index=int(requested)
            else:
                exact=[i for i,d in enumerate(devices) if d['name']==requested]
                matches=exact or [i for i,d in enumerate(devices) if requested.lower() in d['name'].lower() and d['max_input_channels']>0]
                if not matches:raise RuntimeError('Configured input device was not found')
                index=matches[0]
        else:
            # ALSA PipeWire follows the desktop's default source. Do not pick an arbitrary hardware input.
            matches=[i for i,d in enumerate(devices) if d['name']=='pipewire' and d['max_input_channels']>0]
            index=matches[0] if matches else int(self.sd.default.device[0])
        if not 0<=index<len(devices) or devices[index]['max_input_channels']<1:raise RuntimeError('No microphone input available')
        info=devices[index]; return index,round(info['default_samplerate']),info['name']

    def audio(self,indata,frames,time_info,status):
        if status:self.overflow=True
        if self.recording and self.frames<self.rate*self.max_seconds:
            remaining=self.rate*self.max_seconds-self.frames
            block=indata[:remaining].copy(); self.chunks.append(block); self.frames+=len(block)

    def press(self,mode):
        if self.recording:return
        if self.jobs.full():
            notify('One recording is already waiting; retry when transcription finishes',urgency='normal'); return
        try:
            start=time.monotonic()
            index,self.rate,self.device_name=self.device()
            self.chunks=[]; self.frames=0; self.overflow=False; self.mode=mode
            self.origin_focus=self.desktop.snapshot() if self.desktop else None
            self.stream=self.sd.InputStream(samplerate=self.rate,channels=1,device=index,dtype='float32',callback=self.audio)
            self.recording=True; self.started=time.monotonic(); self.stream.start()
            self.open_seconds=time.monotonic()-start
            notify(f'Recording: {"local" if mode=="local" else "Groq"} — release key to transcribe')
            print(f'Recording {mode}: {self.device_name}, {self.rate}Hz; opened in {self.open_seconds:.3f}s',flush=True)
        except Exception as e:
            self.recording=False
            if self.stream:
                with contextlib.suppress(Exception):self.stream.close()
                self.stream=None
            notify(str(e),title='STT recording error',urgency='critical')

    def release(self,mode):
        if not self.recording or self.mode!=mode:return
        released=time.monotonic(); self.recording=False
        stream,self.stream=self.stream,None
        try:
            if stream:stream.stop(); stream.close()
            if not self.chunks:return
            job=(np.concatenate(self.chunks,axis=0),self.rate,self.mode,released,{'capture_open_seconds':round(self.open_seconds,4),'input_device':self.device_name,'input_overflow':self.overflow,'hit_recording_limit':self.frames>=self.rate*self.max_seconds,'paste_target':self.origin_focus})
            self.jobs.put_nowait(job)
            notify('Transcribing…')
        except queue.Full:notify('Transcription queue is full',urgency='critical')
        except Exception as e:notify(str(e),title='STT audio error',urgency='critical')
        finally:self.chunks=[]

    def work(self):
        while not self.shutdown.is_set():
            try:job=self.jobs.get(timeout=.2)
            except queue.Empty:continue
            audio,rate,mode,released,stats=job
            target=stats.pop('paste_target',None)
            stats.update(mode=mode,timestamp=time.strftime('%Y-%m-%dT%H:%M:%S%z'),queue_seconds=round(time.monotonic()-released,4))
            path=None
            try:
                pcm,levels=prepare_audio(audio,rate); stats.update(levels)
                with tempfile.NamedTemporaryFile(suffix='.wav',delete=False) as f:path=f.name
                write(path,16000,pcm)
                start=time.monotonic(); text,source=self.engine.transcribe(path,mode)
                stats['transcription_seconds']=round(time.monotonic()-start,4)
                if not text or text=='.':raise ValueError('Empty transcript')
                start=time.monotonic()
                if self.desktop and os.getenv('STT_AUTO_PASTE','1')=='1':
                    # Dictation never synthesizes Enter. Flatten cloud line breaks before auto-paste.
                    text=' '.join(text.splitlines())
                    stats['delivery']=deliver(text,announce=False)
                    result=self.desktop.paste(target)
                    stats['paste_status']=result
                    if result=='pasted':
                        stats['delivery']='pasted';notify('Transcript pasted into your text field')
                    else:notify('Transcript copied — focus changed or auto-paste unavailable; Ctrl+V to paste',urgency='normal')
                else:stats['delivery']=deliver(text)
                stats.update(delivery_seconds=round(time.monotonic()-start,4),source=source,characters=len(text),status='ok')
                if os.getenv('STT_LOG_TRANSCRIPTS')=='1': print(text,flush=True)
                if stats.get('input_overflow',False):notify('Audio capture overflowed; close CPU-heavy apps if words are missing',urgency='normal')
            except Exception as e:
                stats.update(status='error',error_type=type(e).__name__)
                notify(str(e),title='STT error',urgency='critical')
            finally:
                if path:
                    with contextlib.suppress(OSError):os.unlink(path)
                stats['release_to_result_seconds']=round(time.monotonic()-released,4)
                STATE.mkdir(parents=True,exist_ok=True)
                with (STATE/'timings.jsonl').open('a') as f:f.write(json.dumps(stats)+'\n')
                print(json.dumps(stats),flush=True)
                self.jobs.task_done()

    def close(self):
        self.recording=False; self.shutdown.set()
        if self.stream:
            with contextlib.suppress(Exception):self.stream.stop(); self.stream.close()


def acquire_singleton():
    STATE.mkdir(parents=True,exist_ok=True)
    lease=(STATE/'listener.lock').open('a')
    try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:lease.close(); return None
    lease.seek(0); lease.truncate(); lease.write(str(os.getpid())); lease.flush()
    return lease


def main():
    load_settings()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--devices',action='store_true',help='List microphone inputs without starting the listener')
    parser.add_argument('--transcribe',metavar='WAV',help='Offline file test; prints text without touching the clipboard')
    parser.add_argument('--serve',action='store_true',help='Run the resident local inference engine on loopback')
    args=parser.parse_args()
    if args.serve:Engine().serve(); return
    if args.transcribe:print(Engine().local(args.transcribe)); return
    import sounddevice as sd
    if args.devices:print(sd.query_devices()); return
    lease=acquire_singleton()
    if lease is None: print('STT is already running; reusing the existing listener.',flush=True);return
    app=Dictation(sd)
    bridge=None
    try:
        if os.getenv('STT_DESKTOP_BACKEND','auto')!='legacy':
            try:
                from desktop_client import DesktopBridge
                bridge=DesktopBridge(app);app.desktop=bridge
            except Exception as e:
                print('Desktop integration unavailable: '+str(e),flush=True)
                notify('Global integration unavailable; using legacy shortcuts + clipboard',urgency='normal')
        if bridge:
            print('STT ready system-wide: hold HOME=local, INSERT=Groq; release to paste. No agent wrapper needed.',flush=True)
            notify('System-wide ready: hold HOME=local · INSERT=Groq · release to paste')
            if bridge.wait()!=0:raise RuntimeError('Desktop bridge exited unexpectedly')
        else:
            from pynput import keyboard
            modes={keyboard.Key.home:'local',keyboard.Key.insert:'groq'}
            def pressed(key):
                if key in modes:app.press(modes[key])
            def released(key):
                if key in modes:app.release(modes[key])
            print('STT ready (legacy): hold HOME=local, INSERT=Groq; release, then Ctrl+V.',flush=True)
            with keyboard.Listener(on_press=pressed,on_release=released) as listener:listener.join()
    finally:
        app.close()
        if bridge:bridge.close()
        lease.close()


if __name__=='__main__':main()
