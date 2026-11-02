import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch
spec=importlib.util.spec_from_file_location('desktop_keys',Path(__file__).parents[1]/'desktop_keys.py')
keys=importlib.util.module_from_spec(spec);spec.loader.exec_module(keys)

class UI:
    def __init__(self):self.events=[]
    def write(self,kind,key,state):self.events.append((kind,key,state))
    def syn(self):pass

class Tests(unittest.TestCase):
    def test_browser_pastes_without_enter(self):
        ui=UI()
        with patch.object(keys.time,'sleep'):keys.paste_keys(ui,False)
        self.assertEqual(ui.events,[(1,29,1),(1,47,1),(1,47,0),(1,29,0)])
        self.assertNotIn(28,[event[1] for event in ui.events])

    def test_terminal_uses_ctrl_shift_v(self):
        ui=UI()
        with patch.object(keys.time,'sleep'):keys.paste_keys(ui,True)
        self.assertEqual(ui.events,[(1,29,1),(1,42,1),(1,47,1),(1,47,0),(1,42,0),(1,29,0)])

    def test_modifiers_released_on_error(self):
        ui=UI()
        def fail_once(kind,key,state):
            ui.events.append((kind,key,state))
            if state==1 and key==47:raise RuntimeError('fake device error')
        ui.write=fail_once
        with self.assertRaises(RuntimeError):keys.paste_keys(ui,True)
        self.assertEqual(ui.events[-3:],[(1,47,0),(1,42,0),(1,29,0)])

    def test_terminal_class_detection(self):
        for app in ('kitty','org.kde.konsole','Alacritty','com.mitchellh.ghostty'):self.assertTrue(keys.is_terminal(app))
        for app in ('firefox','org.kde.kate','chromium'):self.assertFalse(keys.is_terminal(app))

if __name__=='__main__':unittest.main()
