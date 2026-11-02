import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
import numpy as np

spec=importlib.util.spec_from_file_location('stt_core',Path(__file__).parents[1]/'stt.py')
stt=importlib.util.module_from_spec(spec);spec.loader.exec_module(stt)

class Tests(unittest.TestCase):
    def test_all_segments_preserved(self):
        self.assertEqual(stt.parse_local_text('First sentence.\n\nSecond sentence.\nThird sentence.\n'),'First sentence. Second sentence. Third sentence.')

    def test_wayland_clipboard_first_without_waiting_for_xclip(self):
        with patch.dict(stt.os.environ,{'XDG_SESSION_TYPE':'wayland'}),patch.object(stt.shutil,'which',return_value='/bin/tool'),patch.object(stt.subprocess,'run') as run,patch.object(stt,'notify'):
            self.assertEqual(stt.deliver('literal $text `code` "quote"'),'clipboard')
            self.assertEqual(run.call_args.args[0][0],'wl-copy')
            self.assertEqual(run.call_args.kwargs['input'],b'literal $text `code` "quote"')
            self.assertTrue(run.call_args.kwargs['check'])
            self.assertEqual(run.call_count,1)

    def test_clipboard_fallback_checks_returncode(self):
        with patch.dict(stt.os.environ,{'XDG_SESSION_TYPE':'wayland'}),patch.object(stt.shutil,'which',return_value='/bin/tool'),patch.object(stt.subprocess,'run',side_effect=[stt.subprocess.CalledProcessError(1,'wl-copy'),None]) as run,patch.object(stt,'notify'):
            stt.deliver('hi');self.assertEqual(run.call_count,2)

    def test_resampling_and_capped_gain(self):
        audio=np.sin(np.arange(48000)/20)*.0001
        pcm,stats=stt.prepare_audio(audio,48000)
        self.assertEqual(len(pcm),16000);self.assertEqual(stats['gain'],8)
        self.assertLessEqual(np.abs(pcm).max(),32767)

    def test_silence_and_invalid_rejected(self):
        for audio in [np.zeros(16000),np.ones(10),np.full(16000,np.nan)]:
            with self.assertRaises(ValueError):stt.prepare_audio(audio,16000)

    def test_single_listener(self):
        with tempfile.TemporaryDirectory() as temp,patch.object(stt,'STATE',Path(temp)):
            lease=stt.acquire_singleton()
            try:self.assertIsNone(stt.acquire_singleton())
            finally:lease.close()
            lease=stt.acquire_singleton();self.assertIsNotNone(lease);lease.close()

    def test_cloud_failure_falls_back_without_another_cloud_call(self):
        engine=stt.Engine()
        with patch.object(engine,'cloud',side_effect=TimeoutError),patch.object(engine,'local',return_value='offline transcript') as local,patch.object(stt,'notify'):
            self.assertEqual(engine.transcribe('x.wav','groq'),('offline transcript','Local'))
            local.assert_called_once()

    def test_resident_response_preserves_segments(self):
        from unittest.mock import Mock
        engine=stt.Engine();engine.local_client=Mock()
        engine.local_client.post.return_value.json.return_value={'text':'First.\nSecond.\n'}
        with tempfile.NamedTemporaryFile(suffix='.wav') as f,patch.dict(stt.os.environ,{'STT_RESIDENT':'1'}),patch.object(stt.subprocess,'run') as standalone:
            self.assertEqual(engine.local(f.name),'First. Second.')
            standalone.assert_not_called()
            self.assertTrue(engine.local_client.post.call_args.args[0].startswith('http://127.0.0.1:'))

    def test_resident_failure_uses_standalone(self):
        from unittest.mock import Mock
        import httpx
        engine=stt.Engine();engine.local_client=Mock()
        engine.local_client.post.side_effect=httpx.ConnectError('offline')
        result=type('Result',(),{'stdout':'Fallback.','stderr':'','returncode':0})()
        with tempfile.NamedTemporaryFile(suffix='.wav') as f,patch.dict(stt.os.environ,{'STT_RESIDENT':'1'}),patch.object(stt.subprocess,'run',return_value=result) as standalone:
            self.assertEqual(engine.local(f.name),'Fallback.')
            standalone.assert_called_once()

    def test_optional_gpu_routes_separately(self):
        engine=stt.Engine()
        with patch.object(engine,'gpu',return_value='quality words') as gpu,patch.object(engine,'local') as local,patch.object(engine,'cloud') as cloud:
            self.assertEqual(engine.transcribe('audio.wav','gpu'),('quality words','Local GPU Turbo'))
            gpu.assert_called_once();local.assert_not_called();cloud.assert_not_called()

    def test_gpu_busy_falls_back_to_cpu_never_cloud(self):
        engine=stt.Engine()
        with patch.object(engine,'gpu',side_effect=RuntimeError('busy')),patch.object(engine,'local',return_value='cpu words'),patch.object(engine,'cloud') as cloud,patch.object(stt,'notify'):
            self.assertEqual(engine.transcribe('audio.wav','gpu'),('cpu words','Local CPU fallback'));cloud.assert_not_called()

    def test_default_local_can_select_gpu_without_cloud(self):
        engine=stt.Engine()
        with patch.dict(stt.os.environ,{'STT_LOCAL_BACKEND':'gpu'}),patch.object(engine,'gpu',return_value='quality'),patch.object(engine,'local') as cpu,patch.object(engine,'cloud') as cloud:
            self.assertEqual(engine.transcribe('audio.wav','local'),('quality','Local GPU Turbo'));cpu.assert_not_called();cloud.assert_not_called()

    def test_continuous_is_off_until_explicit_start_and_default_can_change(self):
        app=stt.Dictation(None)
        try:
            self.assertFalse(app.control('status')['listening'])
            with patch.dict(stt.os.environ,{'STT_LOCAL_BACKEND':'cpu'}):
                self.assertEqual(app.control('default-gpu')['local_backend'],'gpu')
                self.assertEqual(app.control('default-cpu')['local_backend'],'cpu')
            with self.assertRaises(ValueError):app.control('paste')
        finally:app.close();app.worker.join(1)

    def test_home_never_calls_cloud(self):
        engine=stt.Engine()
        with patch.object(engine,'cloud') as cloud,patch.object(engine,'local',return_value='offline'):
            self.assertEqual(engine.transcribe('x.wav','local'),('offline','Local'));cloud.assert_not_called()

    def test_background_worker_and_immutable_recording(self):
        entered=threading.Event(); allow=threading.Event()
        class Engine:
            def transcribe(self,path,mode):
                entered.set();allow.wait(2);return 'First. Second.','Local'
        class Stream:
            def __init__(self,**kwargs):pass
            def start(self):pass
            def stop(self):pass
            def close(self):pass
        class SD:
            InputStream=Stream
            def query_devices(self):return [{'name':'pipewire','max_input_channels':2,'default_samplerate':48000}]
        with tempfile.TemporaryDirectory() as temp,patch.object(stt,'STATE',Path(temp)),patch.object(stt,'notify'),patch.object(stt,'deliver',return_value='clipboard') as deliver:
            app=stt.Dictation(SD(),Engine())
            try:
                app.press('local');app.audio(np.ones((48000,1),dtype=np.float32)*.1,48000,None,False)
                app.release('groq');self.assertTrue(app.recording) # wrong key release cannot end capture
                start=time.monotonic();app.release('local')
                self.assertLess(time.monotonic()-start,.1);self.assertTrue(entered.wait(1))
                app.press('local');self.assertTrue(app.recording) # previous transcription does not block a new press
                allow.set();app.jobs.join()
                deliver.assert_called_once_with('First. Second.')
                stats=json.loads((Path(temp)/'timings.jsonl').read_text())
                self.assertEqual(stats['audio_seconds'],1);self.assertEqual(stats['status'],'ok')
                self.assertNotIn('transcript',stats)
            finally:allow.set();app.close();app.worker.join(2)

    def test_auto_paste_flattens_cloud_newlines_and_keeps_target_private(self):
        from unittest.mock import Mock
        engine=Mock();engine.transcribe.return_value=('Hello.\nNext line.','Groq')
        desktop=Mock();desktop.paste.return_value='pasted'
        with tempfile.TemporaryDirectory() as temp,patch.object(stt,'STATE',Path(temp)),patch.object(stt,'notify'),patch.object(stt,'deliver',return_value='clipboard') as copy:
            app=stt.Dictation(None,engine);app.desktop=desktop
            try:
                target={'id':'window','app':'kitty'}
                app.jobs.put((np.ones((16000,1))*.1,16000,'groq',time.monotonic(),{'paste_target':target}))
                app.jobs.join()
                copy.assert_called_once_with('Hello. Next line.',announce=False)
                desktop.paste.assert_called_once_with(target)
                record=json.loads((Path(temp)/'timings.jsonl').read_text())
                self.assertEqual(record['delivery'],'pasted');self.assertEqual(record['status'],'ok');self.assertNotIn('paste_target',record)
            finally:app.close();app.worker.join(1)

    def test_input_switch_re_resolved(self):
        class SD:
            default=type('Default',(),{'device':[0,0]})()
            def query_devices(self):return [{'name':'first','max_input_channels':1,'default_samplerate':16000},{'name':'second','max_input_channels':1,'default_samplerate':48000}]
        app=stt.Dictation(SD())
        try:
            with patch.dict(stt.os.environ,{'STT_INPUT_DEVICE':'first'}):self.assertEqual(app.device()[0],0)
            with patch.dict(stt.os.environ,{'STT_INPUT_DEVICE':'second'}):self.assertEqual(app.device()[0],1)
        finally:app.close();app.worker.join(1)

    def test_config_is_literal_not_executed(self):
        with tempfile.TemporaryDirectory() as temp:
            p=Path(temp)/'stt.env';p.write_text("STT_THREADS=8\nSTT_LANGUAGE='en'\nIGNORED=value\n")
            with patch.dict(stt.os.environ,{},clear=True):
                stt.load_settings(p);self.assertEqual(stt.os.environ['STT_THREADS'],'8');self.assertNotIn('IGNORED',stt.os.environ)

if __name__=='__main__':unittest.main()
