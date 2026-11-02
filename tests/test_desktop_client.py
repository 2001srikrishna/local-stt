import importlib.util
import json
from pathlib import Path
import threading
import unittest

spec=importlib.util.spec_from_file_location('desktop_client',Path(__file__).parents[1]/'desktop_client.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

class Tests(unittest.TestCase):
    def bridge(self):
        b=module.DesktopBridge.__new__(module.DesktopBridge)
        b.focus={'id':'original','app':'kitty'};b.lock=threading.Lock();b.pending={}
        return b

    def test_focus_change_never_sends_command(self):
        b=self.bridge()
        self.assertEqual(b.paste({'id':'different'}),'focus-changed')
        self.assertEqual(b.paste(None),'focus-changed')
        self.assertEqual(b.paste({'id':''}),'focus-changed')

    def test_matching_focus_sends_only_request_and_window(self):
        b=self.bridge();messages=[]
        class Input:
            def write(self,line):
                message=json.loads(line);messages.append(message)
                done,result=b.pending[message['request']]
                result['status']='pasted';done.set()
            def flush(self):pass
        b.proc=type('Process',(),{'stdin':Input()})()
        self.assertEqual(b.paste({'id':'original'}),'pasted')
        self.assertEqual(set(messages[0]),{'command','request','window'})
        self.assertEqual(messages[0]['command'],'paste')
        self.assertEqual(b.pending,{})

    def test_closed_bridge_leaves_clipboard_result(self):
        b=self.bridge()
        class Input:
            def write(self,line):raise BrokenPipeError
        b.proc=type('Process',(),{'stdin':Input()})()
        self.assertEqual(b.paste({'id':'original'}),'unavailable')
        self.assertEqual(b.pending,{})

if __name__=='__main__':unittest.main()
