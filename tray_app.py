#!/usr/bin/python3
"""Small KDE system-tray controller. No inference, recording or provider calls."""
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
from PySide6.QtCore import Qt,QTimer,QObject,Slot
from PySide6.QtDBus import QDBusConnection,QDBusInterface
from PySide6.QtGui import QAction,QActionGroup,QColor,QDesktopServices,QIcon,QKeySequence,QPainter,QPixmap
from PySide6.QtWidgets import QApplication,QCheckBox,QComboBox,QDialog,QDialogButtonBox,QFormLayout,QGroupBox,QHBoxLayout,QKeySequenceEdit,QLabel,QMenu,QMessageBox,QPushButton,QSpinBox,QSystemTrayIcon,QVBoxLayout
import settings_store
import control

ROOT=Path(__file__).resolve().parent
HOME=Path.home()
PYTHON=HOME/'.local/share/opencode-stt/venv/bin/python'
DEFAULT_KEYS={'LOCAL':0x0D000010,'GROQ':0x0D000006,'GPU':0x0D000011}


def command(*args):
    return subprocess.run(args,capture_output=True,text=True,timeout=12)


def active():return command('systemctl','--user','is-active','local-stt.service').returncode==0


def enabled():return command('systemctl','--user','is-enabled','local-stt.service').returncode==0


def icon(on,listening=False,starting=False):
    image=QPixmap(32,32);image.fill(Qt.GlobalColor.transparent)
    painter=QPainter(image);painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    color='#e34c55' if listening else '#e5a538' if starting else '#23b899' if on else '#7b8290'
    painter.setBrush(QColor(color));painter.setPen(Qt.PenStyle.NoPen)
    painter.drawRoundedRect(12,4,8,16,4,4)
    painter.setPen(QColor(color))
    painter.drawArc(8,9,16,16,180*16,180*16);painter.drawLine(16,25,16,29);painter.drawLine(11,29,21,29)
    painter.end();return QIcon(image)


class Settings(QDialog):
    def __init__(self,owner):
        super().__init__();self.owner=owner;self.setWindowTitle('Local STT — Settings');self.setMinimumWidth(540)
        self.values=settings_store.read();v=self.values
        layout=QVBoxLayout(self)
        title=QLabel('<h2>Local dictation</h2>Hold your shortcut, speak, release to paste.');layout.addWidget(title)
        behavior=QGroupBox('Behavior');form=QFormLayout(behavior);layout.addWidget(behavior)
        self.auto=QCheckBox('Automatically paste into the original window');self.auto.setChecked(v.get('STT_AUTO_PASTE','1')=='1');form.addRow(self.auto)
        self.login=QCheckBox('Enable dictation at desktop login');self.login.setChecked(enabled());form.addRow(self.login)
        self.local_backend=QComboBox();self.local_backend.addItem('CPU — fast and lightweight','cpu');self.local_backend.addItem('GPU — larger local model','gpu');self.local_backend.setCurrentIndex(1 if v.get('STT_LOCAL_BACKEND','cpu')=='gpu' else 0);form.addRow('Default local engine',self.local_backend)
        self.gpu=QCheckBox('Enable optional on-demand GPU shortcut');self.gpu.setChecked(v.get('STT_GPU_ENABLED','1')=='1');form.addRow(self.gpu)
        self.keys={}
        for mode,label in [('LOCAL','Default local'),('GROQ','Groq cloud'),('GPU','Explicit GPU local')]:
            key=QKeySequenceEdit(QKeySequence(int(v.get('STT_KEY_'+mode,str(DEFAULT_KEYS[mode])),0)))
            key.setMaximumSequenceLength(1);self.keys[mode]=key;form.addRow(label+' shortcut',key)
        models=QGroupBox('Microphone and models');form=QFormLayout(models);layout.addWidget(models)
        self.device=QComboBox();self.device.addItem('Follow desktop microphone','')
        try:
            result=command(str(PYTHON),str(HOME/'stt.py'),'--devices-json')
            devices=json.loads(result.stdout)
            for item in devices:self.device.addItem(item['name'],item['name'])
        except (ValueError,OSError,subprocess.SubprocessError):pass
        configured=v.get('STT_INPUT_DEVICE','')
        index=self.device.findData(configured)
        if index<0:self.device.addItem(configured,configured);index=self.device.count()-1
        self.device.setCurrentIndex(index);form.addRow('Microphone',self.device)
        self.cpu_model=QComboBox();self.gpu_model=QComboBox()
        paths=list((HOME/'whisper.cpp/models').glob('ggml-*.bin'))
        for combo,key,default in [(self.cpu_model,'STT_WHISPER_MODEL','ggml-base.en.bin'),(self.gpu_model,'STT_GPU_MODEL','ggml-large-v3-turbo.bin')]:
            selected=v.get(key,str(HOME/'whisper.cpp/models'/default))
            for path in paths:combo.addItem(path.name,str(path))
            idx=combo.findData(selected)
            if idx<0:combo.addItem(Path(selected).name,selected);idx=combo.count()-1
            combo.setCurrentIndex(idx)
        form.addRow('CPU model',self.cpu_model);form.addRow('GPU model',self.gpu_model)
        self.threads=QSpinBox();self.threads.setRange(1,os.cpu_count() or 16);self.threads.setValue(int(v.get('STT_THREADS','8')));form.addRow('CPU threads',self.threads)
        self.language=QComboBox();self.language.setEditable(True);self.language.addItems(['en','auto','hi','ta','de','fr','es']);self.language.setCurrentText(v.get('STT_LANGUAGE','en'));form.addRow('Language',self.language)
        self.limit=QSpinBox();self.limit.setRange(5,300);self.limit.setSuffix(' seconds');self.limit.setValue(int(v.get('STT_MAX_SECONDS','120')));form.addRow('Recording limit',self.limit)
        self.threshold=QSpinBox();self.threshold.setRange(-65,-20);self.threshold.setSuffix(' dBFS');self.threshold.setValue(int(v.get('STT_LISTEN_THRESHOLD_DB','-42')));form.addRow('Continuous speech threshold',self.threshold)
        helptext=QLabel('The default local engine is used by the local shortcut and continuous listening.\nContinuous mode transcribes phrases at pauses; it stays off until toggled on.\nCPU base.en is English-only. GPU loads on demand and falls back to CPU if busy.')
        helptext.setWordWrap(True);layout.addWidget(helptext)
        self.note=QLabel('Settings do not contain or display your cloud API key.');self.note.setWordWrap(True);layout.addWidget(self.note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Close)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(self.save);buttons.rejected.connect(self.hide);layout.addWidget(buttons)

    def save(self):
        try:
            keycodes={mode:edit.keySequence()[0].toCombined() if not edit.keySequence().isEmpty() else 0 for mode,edit in self.keys.items()}
            relevant=['LOCAL','GROQ']+(['GPU'] if self.gpu.isChecked() else [])
            if any(not keycodes[m] for m in relevant):raise ValueError('Each enabled mode needs a shortcut')
            if len({keycodes[m] for m in relevant})!=len(relevant):raise ValueError('Shortcuts must be different')
            if any(not (keycodes[m]&0x1E000000) for m in relevant):raise ValueError('Use a modifier such as Ctrl+Alt to preserve normal editing keys')
            import dbus
            bus=dbus.SessionBus();manager=dbus.Interface(bus.get_object('org.kde.kglobalaccel','/kglobalaccel'),'org.kde.KGlobalAccel')
            for m in relevant:
                if any(str(x[2])!='org.localstt.Dictation' for x in manager.getGlobalShortcutsByKey(keycodes[m])):raise ValueError(m+' shortcut is used by another KDE application')
            language=self.language.currentText().strip()
            if not language or not language.replace('-','').isalpha():raise ValueError('Use a language code such as en, hi or auto')
            updates={'STT_LOCAL_BACKEND':self.local_backend.currentData(),'STT_LISTEN_THRESHOLD_DB':self.threshold.value(),'STT_AUTO_PASTE':int(self.auto.isChecked()),'STT_GPU_ENABLED':int(self.gpu.isChecked()),'STT_INPUT_DEVICE':self.device.currentData(),'STT_WHISPER_MODEL':self.cpu_model.currentData(),'STT_GPU_MODEL':self.gpu_model.currentData(),'STT_THREADS':self.threads.value(),'STT_LANGUAGE':language,'STT_MAX_SECONDS':self.limit.value()}
            updates.update({'STT_KEY_'+m:str(code) for m,code in keycodes.items()})
            was_active=active();settings_store.write(updates)
            result=command('systemctl','--user','enable' if self.login.isChecked() else 'disable','local-stt.service')
            if result.returncode:raise RuntimeError(result.stderr.strip())
            if was_active:
                result=command('systemctl','--user','restart','local-stt.service')
                if result.returncode:raise RuntimeError(result.stderr.strip())
            self.note.setText('Saved. '+('Dictation restarted with your settings.' if was_active else 'Dictation remains disabled.'))
            self.owner.refresh()
        except Exception as e:QMessageBox.warning(self,'Could not apply settings',str(e))


class Tray:
    def __init__(self,app):
        self.app=app;self.window=None;self.listen_generation=0;self.listen_pending=False;self.tray=QSystemTrayIcon(icon(active()),app)
        self.menu=QMenu();self.toggle=QAction('Dictation enabled',self.menu);self.toggle.setCheckable(True);self.toggle.triggered.connect(self.set_enabled);self.menu.addAction(self.toggle)
        self.listen=QAction('Listen continuously (local)',self.menu);self.listen.setCheckable(True);self.listen.triggered.connect(self.set_listening);self.menu.addAction(self.listen)
        defaults=self.menu.addMenu('Default local engine');self.default_group=QActionGroup(self.menu);self.default_actions={}
        for mode,label in [('cpu','CPU — fast/light'),('gpu','GPU — larger model')]:
            action=defaults.addAction(label);action.setCheckable(True);self.default_group.addAction(action);action.triggered.connect(lambda checked,m=mode:self.set_default(m));self.default_actions[mode]=action
        settings=self.menu.addAction('Settings…');settings.triggered.connect(self.settings)
        self.menu.addSeparator();self.info=self.menu.addAction('Hold shortcut → speak → release');self.info.setEnabled(False)
        logs=self.menu.addAction('Recent latency');logs.triggered.connect(self.latency)
        self.menu.addSeparator();quit_action=self.menu.addAction('Quit tray (dictation stays as set)');quit_action.triggered.connect(app.quit)
        self.tray.setContextMenu(self.menu);self.tray.activated.connect(lambda reason:self.settings() if reason==QSystemTrayIcon.ActivationReason.DoubleClick else None)
        self.timer=QTimer(app);self.timer.timeout.connect(self.refresh);self.timer.start(2500)
        self.refresh();self.tray.show()

    def refresh(self):
        state=active();self.toggle.blockSignals(True);self.toggle.setChecked(state);self.toggle.blockSignals(False)
        try:data=control.request('status') if state else {}
        except (OSError,ValueError,RuntimeError):data={}
        listening=data.get('listening',False)
        self.listen.blockSignals(True);self.listen.setChecked(listening or self.listen_pending);self.listen.blockSignals(False)
        backend=settings_store.read().get('STT_LOCAL_BACKEND','cpu')
        for mode,action in self.default_actions.items():action.setChecked(mode==backend)
        self.tray.setIcon(icon(state,listening,self.listen_pending))
        self.tray.setToolTip('Local STT — '+('MIC ON · continuously listening' if listening else 'starting listening…' if self.listen_pending else 'enabled · push-to-talk' if state else 'disabled'))

    def set_enabled(self,state):
        if not state:self.listen_generation+=1;self.listen_pending=False
        try:
            result=command('systemctl','--user','start' if state else 'stop','local-stt.service')
            if result.returncode:raise RuntimeError(result.stderr.strip())
        except Exception as e:self.tray.showMessage('Local STT',str(e),QSystemTrayIcon.MessageIcon.Warning)
        self.refresh()

    def set_default(self,mode):
        try:
            settings_store.write({'STT_LOCAL_BACKEND':mode})
            if active():control.request('default-'+mode)
        except Exception as e:self.tray.showMessage('Local STT',str(e),QSystemTrayIcon.MessageIcon.Warning)
        self.refresh()

    def set_listening(self,state):
        self.listen_generation+=1;generation=self.listen_generation
        self.listen_pending=state
        if state and not active():self.set_enabled(True)
        def attempt(number=0):
            if generation!=self.listen_generation:return
            try:
                control.request('listen-start' if state else 'listen-stop');self.listen_pending=False;self.refresh()
            except (OSError,ValueError,RuntimeError) as e:
                if state and number<12:QTimer.singleShot(300,lambda:attempt(number+1));return
                self.listen_pending=False;self.refresh();self.tray.showMessage('Local STT',str(e),QSystemTrayIcon.MessageIcon.Warning)
        attempt()
        self.refresh()

    def settings(self):
        if self.window:self.window.close()
        self.window=Settings(self);self.window.show();self.window.raise_();self.window.activateWindow()

    def latency(self):
        path=HOME/'.local/state/opencode-stt/timings.jsonl'
        try:
            row=json.loads(path.read_text().splitlines()[-1]);text=f"Mode: {row.get('source',row.get('mode'))}\nAudio: {row.get('audio_seconds')} seconds\nRelease to result: {row.get('release_to_result_seconds')} seconds\nDelivery: {row.get('delivery')}"
        except (OSError,ValueError,IndexError):text='No dictation timing is available yet.'
        QMessageBox.information(None,'Latest dictation timing',text)


class Controller(QObject):
    def __init__(self,tray):super().__init__();self.tray=tray
    @Slot()
    def ShowSettings(self):self.tray.settings()


def main():
    app=QApplication(sys.argv);app.setApplicationName('Local STT');app.setDesktopFileName('local-stt-tray');app.setQuitOnLastWindowClosed(False)
    folder=HOME/'.local/state/opencode-stt';folder.mkdir(parents=True,exist_ok=True)
    lease=(folder/'tray.lock').open('a')
    try:fcntl.flock(lease,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        QDBusInterface('org.localstt.Tray','/LocalSTT','local.stt.Tray',QDBusConnection.sessionBus()).call('ShowSettings');return
    tray=Tray(app)
    controller=Controller(tray);connection=QDBusConnection.sessionBus()
    connection.registerService('org.localstt.Tray');connection.registerObject('/LocalSTT','local.stt.Tray',controller,QDBusConnection.RegisterOption.ExportAllSlots)
    if '--settings' in sys.argv:tray.settings()
    if '--smoke-test' in sys.argv:
        tray.settings()
        def finish():
            tray.window.grab().save('/tmp/local-stt-settings-preview.png');app.quit()
        QTimer.singleShot(500,finish)
    sys.exit(app.exec())

if __name__=='__main__':main()
