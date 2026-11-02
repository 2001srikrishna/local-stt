import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('gpu_runtime',Path(__file__).parents[1]/'gpu_runtime.py')
gpu=importlib.util.module_from_spec(spec);spec.loader.exec_module(gpu)

class Tests(unittest.TestCase):
    def test_container_is_local_pinned_and_bounded(self):
        cmd=gpu.command(Path('/tmp/audio.wav'),Path('/tmp/model.bin'),'/dev/dri/renderD128','local-stt-gpu-test')
        self.assertEqual(cmd[cmd.index('--network')+1],'none')
        self.assertIn('--pull=never',cmd);self.assertIn('--read-only',cmd)
        self.assertIn('4g',cmd);self.assertIn('4608m',cmd)
        self.assertIn('no-new-privileges',cmd);self.assertIn('ALL',cmd)
        self.assertIn('timeout',cmd);self.assertIn('90s',cmd)
        self.assertIn('@sha256:',gpu.IMAGE)
        mounts=[cmd[i+1] for i,x in enumerate(cmd) if x=='--mount']
        self.assertEqual(len(mounts),2);self.assertTrue(all(x.endswith('readonly') for x in mounts))
        self.assertNotIn('-ng',cmd)

    def test_initial_headroom_gates(self):
        for data in [{'available_ram_GiB':3,'vram_total_GiB':16,'vram_used_GiB':1},{'available_ram_GiB':10,'vram_total_GiB':16,'vram_used_GiB':13}]:
            with self.assertRaises(RuntimeError):gpu.check_headroom(data,initial=True)
        gpu.check_headroom({'available_ram_GiB':10,'vram_total_GiB':16,'vram_used_GiB':1},initial=True)

    def test_runtime_headroom_gates(self):
        for data in [{'available_ram_GiB':1,'vram_total_GiB':16,'vram_used_GiB':1},{'available_ram_GiB':10,'vram_total_GiB':16,'vram_used_GiB':15.5}]:
            with self.assertRaises(RuntimeError):gpu.check_headroom(data)

if __name__=='__main__':unittest.main()
