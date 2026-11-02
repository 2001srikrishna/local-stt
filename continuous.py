"""Bounded local continuous capture: phrase chunks at silence, not cloud streaming."""
from collections import deque
import queue
import threading
import time
import numpy as np


class Segmenter:
    def __init__(self,rate,threshold=.008,pause=.7,minimum=.25,maximum=15,preroll=.2):
        self.rate=rate;self.threshold=threshold;self.pause=pause;self.minimum=minimum;self.maximum=maximum;self.preroll=preroll
        self.before=deque();self.before_frames=0;self.blocks=[];self.frames=0;self.voiced=0;self.silent=0;self.target=None

    def push(self,block,target=None):
        block=np.asarray(block,dtype=np.float32).reshape(-1,1)
        seconds=len(block)/self.rate
        speech=float(np.sqrt(np.mean(block**2)))>=self.threshold
        if not self.blocks:
            if not speech:
                self.before.append(block);self.before_frames+=len(block)
                while self.before and self.before_frames>self.preroll*self.rate:
                    self.before_frames-=len(self.before.popleft())
                return None
            self.blocks=list(self.before);self.frames=self.before_frames;self.before.clear();self.before_frames=0
            self.target=target
        self.blocks.append(block);self.frames+=len(block)
        if speech:self.voiced+=seconds;self.silent=0
        else:self.silent+=seconds
        if self.silent>=self.pause or self.frames/self.rate>=self.maximum:return self.flush()
        return None

    def flush(self):
        result=None
        if self.blocks and self.voiced>=self.minimum:result=(np.concatenate(self.blocks),self.target)
        self.blocks=[];self.frames=0;self.voiced=0;self.silent=0;self.target=None
        self.before.clear();self.before_frames=0
        return result


class ContinuousCapture:
    def __init__(self,sd,device,rate,emit,focus,on_error,threshold=.008,pause=.7):
        self.sd=sd;self.device=device;self.rate=rate;self.emit=emit;self.focus=focus;self.on_error=on_error
        self.segmenter=Segmenter(rate,threshold=threshold,pause=pause)
        self.incoming=queue.Queue(maxsize=128);self.running=False;self.stream=None;self.error=None
        self.flush_on_stop=True;self.thread=None

    def audio(self,indata,frames,time_info,status):
        if not self.running:return
        if status:self.error='Microphone capture overflowed';return
        try:self.incoming.put_nowait((indata.copy(),self.focus()))
        except queue.Full:self.error='Continuous capture could not keep up'

    def start(self):
        self.stream=self.sd.InputStream(samplerate=self.rate,channels=1,device=self.device,dtype='float32',callback=self.audio)
        self.running=True
        try:self.stream.start()
        except Exception:self.running=False;self.stream.close();raise
        self.thread=threading.Thread(target=self.work,name='stt-continuous-segments',daemon=True);self.thread.start()

    def work(self):
        try:
            while True:
                if self.error:raise RuntimeError(self.error)
                try:item=self.incoming.get(timeout=.15)
                except queue.Empty:
                    if not self.running:break
                    continue
                if item is None:break
                result=self.segmenter.push(*item)
                if result:self.emit(result[0],self.rate,result[1])
            if self.flush_on_stop:
                result=self.segmenter.flush()
                if result:self.emit(result[0],self.rate,result[1])
        except Exception as e:
            self.running=False
            self.on_error(str(e))
        finally:
            self.running=False
            if self.stream:
                try:self.stream.stop();self.stream.close()
                except Exception:pass

    def stop(self,flush=True):
        self.flush_on_stop=flush;self.running=False
        if self.stream:
            try:self.stream.stop();self.stream.close()
            except Exception:pass
            self.stream=None
        try:self.incoming.put(None,timeout=.3)
        except queue.Full:pass
        if self.thread and threading.current_thread()!=self.thread:self.thread.join(timeout=3)
