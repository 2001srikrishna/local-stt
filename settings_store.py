"""Literal config editing that preserves unrelated lines and private credentials."""
import os
from pathlib import Path
import shlex
import tempfile

CONFIG=Path.home()/'.config/local-stt/stt.env'


def read(path=CONFIG):
    values={}
    if path.is_file():
        for line in path.read_text().splitlines():
            line=line.strip().removeprefix('export ')
            if not line or line.startswith('#') or '=' not in line:continue
            key,value=line.split('=',1)
            try:parts=shlex.split(value,comments=True)
            except ValueError:continue
            if len(parts)==1:values[key]=parts[0]
    return values


def write(updates,path=CONFIG):
    if any(not key.startswith('STT_') for key in updates):raise ValueError('Only STT settings may be updated')
    path.parent.mkdir(parents=True,exist_ok=True)
    lines=path.read_text().splitlines() if path.is_file() else []
    output=[];remaining=dict(updates)
    for line in lines:
        assignment=line.strip().removeprefix('export ')
        key=assignment.split('=',1)[0] if '=' in assignment and not assignment.startswith('#') else None
        if key in updates:
            if key in remaining:output.append(key+'='+shlex.quote(str(remaining.pop(key))))
        else:output.append(line)
    output.extend(key+'='+shlex.quote(str(value)) for key,value in remaining.items())
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,prefix='.stt-',delete=False) as f:
        temporary=Path(f.name)
        try:
            os.fchmod(f.fileno(),0o600);f.write('\n'.join(output)+'\n');f.flush();os.fsync(f.fileno())
        except Exception:temporary.unlink(missing_ok=True);raise
    try:os.replace(temporary,path)
    finally:temporary.unlink(missing_ok=True)
