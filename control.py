"""User-private local controls. No paste, arbitrary paths or cloud commands."""
import json
import os
from pathlib import Path
import socket
import threading

PATH=Path.home()/'.local/state/opencode-stt/control/listener.sock'


def request(command,path=PATH):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
        client.settimeout(3);client.connect(str(path));client.sendall((json.dumps({'command':command})+'\n').encode())
        response=client.makefile('rb').readline(8192)
    data=json.loads(response)
    if data.get('error'):raise RuntimeError(data['error'])
    return data


class Server:
    def __init__(self,handler,path=PATH):
        self.path=path;self.handler=handler;self.closed=threading.Event()
        path.parent.mkdir(parents=True,exist_ok=True);path.parent.chmod(0o700);path.unlink(missing_ok=True)
        self.socket=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);self.socket.bind(str(path));path.chmod(0o600)
        self.socket.listen(4);self.socket.settimeout(.3)
        self.thread=threading.Thread(target=self.work,name='stt-tray-control',daemon=True);self.thread.start()

    def work(self):
        while not self.closed.is_set():
            try:client,_=self.socket.accept()
            except socket.timeout:continue
            except OSError:break
            with client:
                try:
                    client.settimeout(4);body=client.makefile('rb').readline(4096)
                    result=self.handler(json.loads(body).get('command'))
                except Exception as e:result={'error':str(e)}
                try:client.sendall((json.dumps(result)+'\n').encode())
                except OSError:pass

    def close(self):
        self.closed.set();self.socket.close();self.thread.join(1);self.path.unlink(missing_ok=True)
