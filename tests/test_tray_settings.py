import importlib.util
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch

@unittest.skipUnless(importlib.util.find_spec('PySide6'),'System Qt modules required; run this test with /usr/bin/python3')
class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
        root=Path(__file__).parents[1];sys.path.insert(0,str(root))
        import tray_app
        cls.module=tray_app
        cls.application=tray_app.QApplication.instance() or tray_app.QApplication([])

    def test_apply_preserves_disabled_state(self):
        m=self.module;owner=Mock();manager=SimpleNamespace(getGlobalShortcutsByKey=lambda key:[])
        fake_dbus=SimpleNamespace(SessionBus=lambda:SimpleNamespace(get_object=lambda *a:manager),Interface=lambda *a:manager)
        with patch.object(m.settings_store,'read',return_value={}),patch.object(m.settings_store,'write') as write,patch.object(m,'enabled',return_value=True),patch.object(m,'active',return_value=False),patch.object(m,'command',return_value=SimpleNamespace(returncode=0,stdout='[]',stderr='')) as command,patch.object(m.QMessageBox,'warning') as warning,patch.dict(sys.modules,{'dbus':fake_dbus}):
            window=m.Settings(owner);window.save()
            warning.assert_not_called();write.assert_called_once()
            self.assertFalse(any('restart' in call.args for call in command.call_args_list))
            self.assertEqual(write.call_args.args[0]['STT_KEY_LOCAL'],str(0x0D000010))
            window.close()

    def test_reject_duplicate_shortcuts(self):
        m=self.module
        with patch.object(m.settings_store,'read',return_value={}),patch.object(m.settings_store,'write') as write,patch.object(m,'enabled',return_value=True),patch.object(m,'command',return_value=SimpleNamespace(returncode=0,stdout='[]',stderr='')),patch.object(m.QMessageBox,'warning') as warning:
            window=m.Settings(Mock());window.keys['GROQ'].setKeySequence(window.keys['LOCAL'].keySequence());window.save()
            warning.assert_called_once();write.assert_not_called();window.close()

if __name__=='__main__':unittest.main()
