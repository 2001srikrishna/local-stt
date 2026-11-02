import importlib.util
from pathlib import Path
import stat
import tempfile
import unittest
spec=importlib.util.spec_from_file_location('settings_store',Path(__file__).parents[1]/'settings_store.py')
store=importlib.util.module_from_spec(spec);spec.loader.exec_module(store)

class Tests(unittest.TestCase):
    def test_preserves_private_and_unknown_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'stt.env';path.write_text("# private configuration\nGROQ_API_KEY='example-private-value'\nSTT_THREADS=16\nUNRELATED=keep\n")
            store.write({'STT_THREADS':8,'STT_INPUT_DEVICE':''},path)
            values=store.read(path)
            self.assertEqual(values['GROQ_API_KEY'],'example-private-value')
            self.assertEqual(values['UNRELATED'],'keep');self.assertEqual(values['STT_THREADS'],'8')
            self.assertEqual(values['STT_INPUT_DEVICE'],'')
            self.assertIn('# private configuration',path.read_text())
            self.assertEqual(stat.S_IMODE(path.stat().st_mode),0o600)

    def test_literal_quoting_and_duplicate_updates(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'stt.env';path.write_text('STT_INPUT_DEVICE=old\nSTT_INPUT_DEVICE=duplicate\n')
            value="Microphone's name with spaces"
            store.write({'STT_INPUT_DEVICE':value},path)
            self.assertEqual(store.read(path)['STT_INPUT_DEVICE'],value)
            self.assertEqual(path.read_text().count('STT_INPUT_DEVICE='),1)

    def test_cannot_edit_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):store.write({'GROQ_API_KEY':'unwanted'},Path(directory)/'config')

if __name__=='__main__':unittest.main()
