import importlib.util
from pathlib import Path
import tempfile
import time
import unittest
import numpy as np
spec=importlib.util.spec_from_file_location('continuous',Path(__file__).parents[1]/'continuous.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Tests(unittest.TestCase):
    def block(self,value=.1):return np.full((100,1),value,dtype=np.float32)
    def test_silence_produces_no_transcription(self):
        s=m.Segmenter(1000)
        for _ in range(100):self.assertIsNone(s.push(self.block(0)))
        self.assertIsNone(s.flush());self.assertLessEqual(s.before_frames,200)

    def test_each_phrase_emitted_once_after_pause(self):
        s=m.Segmenter(1000);out=[]
        for value in [0]*3+[.1]*6+[0]*8+[.1]*5+[0]*8:
            result=s.push(self.block(value),{'id':'window'})
            if result:out.append(result)
        self.assertEqual(len(out),2);self.assertEqual(out[0][1],{'id':'window'})
        self.assertIsNone(s.flush())

    def test_stop_flushes_final_phrase_and_preserves_initial_window(self):
        s=m.Segmenter(1000)
        for _ in range(3):s.push(self.block(),{'id':'original'})
        s.push(self.block(),{'id':'other'})
        audio,target=s.flush();self.assertEqual(len(audio),400);self.assertEqual(target['id'],'original')

    def test_short_final_word_is_padded_for_engine_minimum(self):
        s=m.Segmenter(1000)
        for _ in range(3):s.push(self.block())
        audio,_=s.flush();self.assertEqual(len(audio),400)
        self.assertTrue(np.all(audio[-100:]==0))

    def test_long_speech_is_bounded(self):
        s=m.Segmenter(1000,maximum=1)
        out=[s.push(self.block()) for _ in range(25)]
        self.assertEqual(len([x for x in out if x is not None]),2)
        self.assertLess(s.frames,1000)

    def test_microphone_closes_on_stop(self):
        class Stream:
            def __init__(self,**kwargs):self.closed=False
            def start(self):pass
            def stop(self):pass
            def close(self):self.closed=True
        class SD:InputStream=Stream
        emitted=[];capture=m.ContinuousCapture(SD(),0,1000,lambda *args:emitted.append(args),lambda:{'id':'window'},lambda e:None)
        capture.start();stream=capture.stream
        for _ in range(5):capture.audio(self.block(),100,None,False)
        capture.stop(flush=True)
        self.assertTrue(stream.closed);self.assertFalse(capture.running);self.assertFalse(capture.thread.is_alive())
        self.assertEqual(len(emitted),1)

if __name__=='__main__':unittest.main()
