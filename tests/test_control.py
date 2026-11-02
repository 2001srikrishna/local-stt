import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('control',Path(__file__).parents[1]/'control.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class Tests(unittest.TestCase):
    def test_local_control_is_private_and_removed_on_close(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'private/listener.sock';commands=[]
            def handler(command):commands.append(command);return {'listening':False}
            server=m.Server(handler,path)
            try:
                self.assertFalse(m.request('status',path)['listening']);self.assertEqual(commands,['status'])
                self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode),0o700)
            finally:server.close()
            self.assertFalse(path.exists())

if __name__=='__main__':unittest.main()
