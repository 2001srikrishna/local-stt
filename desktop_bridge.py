#!/usr/bin/python3
"""KDE desktop bridge using preinstalled system dbus/GLib/evdev.

stdin/stdout are private JSON pipes to the STT parent. This process registers
only three global actions; it does not read raw keyboard events. The virtual
keyboard exposes only Ctrl, Shift and V, and never sends Enter.
"""
import contextlib
import json
import os
from pathlib import Path
import signal
import sys
import dbus
import dbus.service
from dbus.mainloop.glib import DBusGMainLoop
from gi.repository import GLib, GLibUnix
from evdev import UInput, ecodes
from desktop_keys import is_terminal, paste_keys

NAME='org.localstt.Dictation'
OBJECT='/org/localstt/Dictation'
SCRIPT_NAME='local-stt-focus'
# Qt Ctrl|Alt plus Home/Insert. Plain editing keys remain untouched.
KEYS={mode:int(os.getenv('STT_KEY_'+mode.upper(),str(default)),0) for mode,default in {'local':0x0D000010,'groq':0x0D000006,'gpu':0x0D000011}.items()}
if os.getenv('STT_GPU_ENABLED','1')!='1':KEYS.pop('gpu',None)


def output(event,**details):
    print(json.dumps({'event':event,**details}),flush=True)


class FocusObject(dbus.service.Object):
    def __init__(self,bus):
        super().__init__(bus,OBJECT);self.current={'id':'','app':''}

    @dbus.service.method(NAME,in_signature='s',out_signature='')
    def Focus(self,value):
        data=json.loads(str(value))
        self.current={'id':str(data.get('id','')),'app':str(data.get('app',''))}
        output('focus',**self.current)


def main():
    DBusGMainLoop(set_as_default=True)
    bus=dbus.SessionBus();name=dbus.service.BusName(NAME,bus=bus,do_not_queue=True)
    focus=FocusObject(bus)
    manager=dbus.Interface(bus.get_object('org.kde.kglobalaccel','/kglobalaccel'),'org.kde.KGlobalAccel')
    actions=[];ui=None;scripting=None
    loop=GLib.MainLoop()
    try:
        # /dev/uinput permission already exists in the deployment. Never change it here.
        ui=UInput({ecodes.EV_KEY:[ecodes.KEY_LEFTCTRL,ecodes.KEY_LEFTSHIFT,ecodes.KEY_V]},name='Local STT paste-only keyboard')
        scripting=dbus.Interface(bus.get_object('org.kde.KWin','/Scripting'),'org.kde.kwin.Scripting')
        with contextlib.suppress(dbus.DBusException):scripting.unloadScript(SCRIPT_NAME)
        index=int(scripting.loadScript(str(Path(__file__).with_name('kwin_focus.js')),SCRIPT_NAME,signature='ss'))
        if index<0:raise RuntimeError('Could not load the KWin focus guard')
        script=dbus.Interface(bus.get_object('org.kde.KWin','/Scripting/Script'+str(index)),'org.kde.kwin.Script')
        script.run()
        for action,key in KEYS.items():
            bindings=manager.getGlobalShortcutsByKey(key)
            if any(str(binding[2])!=NAME for binding in bindings):raise RuntimeError(f'{action} shortcut is already assigned to another KDE application')
            identity=dbus.Array([NAME,action,'Local STT',{'local':'Default local dictation','groq':'Groq dictation','gpu':'GPU Turbo offline dictation'}[action]],signature='s')
            manager.doRegister(identity);actions.append(identity)
            actual=manager.setShortcut(identity,dbus.Array([key],signature='i'),dbus.UInt32(6))
            if not actual:raise RuntimeError('KDE did not register shortcut '+action)
        component=str(manager.getComponent(NAME))
        def pressed(component,action,timestamp):
            if str(component)==NAME and str(action) in KEYS:output('press',mode=str(action),focus=focus.current)
        def released(component,action,timestamp):
            if str(component)==NAME and str(action) in KEYS:output('release',mode=str(action),focus=focus.current)
        bus.add_signal_receiver(pressed,signal_name='globalShortcutPressed',dbus_interface='org.kde.kglobalaccel.Component',path=component)
        bus.add_signal_receiver(released,signal_name='globalShortcutReleased',dbus_interface='org.kde.kglobalaccel.Component',path=component)
        def command(source,condition):
            if condition & (GLib.IO_HUP|GLib.IO_ERR):loop.quit();return False
            line=sys.stdin.readline()
            if not line:loop.quit();return False
            try:
                message=json.loads(line)
                if message.get('command')=='paste':
                    request=message.get('request')
                    # Always check the CURRENT window immediately before injecting.
                    if not message.get('window') or message['window']!=focus.current['id']:
                        output('paste_result',request=request,status='focus-changed');return True
                    paste_keys(ui,is_terminal(focus.current['app']))
                    output('paste_result',request=request,status='pasted')
                elif message.get('command')=='ping':output('pong',request=message.get('request'),focus=focus.current)
            except Exception as e:output('error',message=type(e).__name__)
            return True
        GLib.io_add_watch(sys.stdin,GLib.IO_IN|GLib.IO_HUP|GLib.IO_ERR,command)
        for sig in (signal.SIGTERM,signal.SIGINT):GLibUnix.signal_add(GLib.PRIORITY_DEFAULT,sig,lambda:(loop.quit(),False)[1])
        output('ready',keys=['Ctrl+Alt+Home','Ctrl+Alt+Insert','Ctrl+Alt+End'])
        loop.run()
    finally:
        for identity in actions:
            with contextlib.suppress(Exception):manager.setInactive(identity)
        if scripting:
            with contextlib.suppress(Exception):scripting.unloadScript(SCRIPT_NAME)
        if ui:ui.close()


if __name__=='__main__':
    try:main()
    except Exception as e:
        output('fatal',message=str(e));sys.exit(1)
