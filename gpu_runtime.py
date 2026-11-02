"""On-demand, bounded, network-disabled official Whisper Vulkan container."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import uuid

IMAGE='ghcr.io/ggml-org/whisper.cpp@sha256:f723c938f4e0938c979cd82cef1f64c9a73cad3c3f4f8d6b1ab038bc9e981ff9'


def resources(node='/dev/dri/renderD128'):
    info={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines()}
    device=Path('/sys/class/drm')/Path(node).name/'device'
    total=int((device/'mem_info_vram_total').read_text())
    used=int((device/'mem_info_vram_used').read_text())
    return {'available_ram_GiB':info['MemAvailable']/2**30,'vram_total_GiB':total/2**30,'vram_used_GiB':used/2**30}


def check_headroom(data,initial=False):
    if data['available_ram_GiB']<(4 if initial else 1.5):raise RuntimeError('Insufficient available RAM for GPU dictation')
    if data['vram_total_GiB']-data['vram_used_GiB']<(4 if initial else .75):raise RuntimeError('Insufficient VRAM headroom for GPU dictation')


def command(audio,model,node,name):
    return ['docker','run','--rm','--pull=never','--name',name,'--network','none','--read-only','--cap-drop','ALL','--security-opt','no-new-privileges','--user',f'{os.getuid()}:{os.getgid()}','--tmpfs','/tmp:rw,nosuid,noexec,size=128m','--env','HOME=/tmp','--env','XDG_CACHE_HOME=/tmp','--env','GGML_VK_VISIBLE_DEVICES=0','--device',node,'--memory','4g','--memory-swap','4608m','--cpus','8','--mount',f'type=bind,source={model},target=/model.bin,readonly','--mount',f'type=bind,source={audio},target=/audio.wav,readonly',IMAGE,'timeout','--signal=TERM','--kill-after=5s','90s','whisper-cli','-m','/model.bin','-f','/audio.wav','-t','8','-bs','5','-bo','5','-nt','-l',os.getenv('STT_LANGUAGE','en')]


def run(audio):
    if not shutil.which('docker'):raise RuntimeError('Docker is not installed')
    model=Path(os.path.expanduser(os.getenv('STT_GPU_MODEL','~/whisper.cpp/models/ggml-large-v3-turbo.bin'))).resolve()
    audio=Path(audio).resolve();node=os.getenv('STT_GPU_RENDER_NODE','/dev/dri/renderD128')
    if not model.is_file() or not audio.is_file():raise RuntimeError('GPU model/audio file is missing')
    if subprocess.run(['pgrep','-x','llama-server'],capture_output=True).returncode==0 or subprocess.run(['pgrep','-x','llama-cli'],capture_output=True).returncode==0:
        raise RuntimeError('Stop local LLM inference before GPU dictation')
    if subprocess.run(['curl','-sf','--max-time','1','http://127.0.0.1:8188/system_stats'],capture_output=True).returncode==0:
        raise RuntimeError('ComfyUI is running; use CPU dictation during video work')
    check_headroom(resources(node),initial=True)
    inspect=subprocess.run(['docker','image','inspect',IMAGE],capture_output=True,timeout=10)
    if inspect.returncode:raise RuntimeError('Pinned GPU runtime is not installed; see GPU.md')
    name='local-stt-gpu-'+uuid.uuid4().hex[:12]
    start=time.monotonic();samples=[];process=None
    with tempfile.TemporaryDirectory(prefix='stt-gpu-') as temp:
        out=Path(temp)/'stdout';err=Path(temp)/'stderr'
        try:
            with out.open('w') as stdout,err.open('w') as stderr:
                process=subprocess.Popen(command(audio,model,node,name),stdout=stdout,stderr=stderr)
                while process.poll() is None:
                    sample=resources(node);samples.append(sample);check_headroom(sample)
                    if time.monotonic()-start>90:raise RuntimeError('GPU transcription timed out')
                    time.sleep(.15)
            detail=err.read_text()
            if process.returncode:raise RuntimeError('GPU runtime failed: '+(detail.strip().splitlines() or ['unknown error'])[-1])
            if 'using Vulkan0 backend' not in detail:raise RuntimeError('Whisper did not confirm GPU execution')
            meta={'gpu_wall_seconds':round(time.monotonic()-start,4),'gpu_peak_sampled_vram_GiB':round(max((s['vram_used_GiB'] for s in samples),default=0),3),'gpu_min_available_ram_GiB':round(min((s['available_ram_GiB'] for s in samples),default=0),3),'gpu_runtime':IMAGE}
            return out.read_text(),meta,detail
        finally:
            # Killing only the docker client does not reliably kill its container.
            subprocess.run(['docker','rm','-f',name],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,timeout=10)
            if process and process.poll() is None:
                process.terminate()
                try:process.wait(timeout=3)
                except subprocess.TimeoutExpired:process.kill();process.wait()
