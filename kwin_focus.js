// Minimal focus guard. Sends only window identity/class, never title or content.
function reportFocus() {
    var w = workspace.activeWindow;
    var value = w ? {id: String(w.internalId), app: String(w.resourceClass)} : {id: "", app: ""};
    callDBus("org.localstt.Dictation", "/org/localstt/Dictation", "org.localstt.Dictation", "Focus", JSON.stringify(value));
}
workspace.windowActivated.connect(reportFocus);
reportFocus();
