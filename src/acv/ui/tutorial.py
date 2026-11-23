"""First-run tutorial (reopen from Help → Tutorial)."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QVBoxLayout, QWizard, QWizardPage

PAGES = [
    ("Welcome to AutoClicker Visual",
     "AutoClicker Visual repeats the clicks you do for <b>one item</b> of a list, for every item, "
     "until the list is empty.<br><br>"
     "It only <b>looks at the screen</b> and moves the mouse and keyboard, exactly like you would. "
     "Nothing is sent anywhere: it all runs on this computer.<br><br>"
     "It never clicks blindly: if something isn't where it expects, it stops and asks you."),
    ("1 · Create a flow",
     "Create a flow with the <b>+</b> button. You don't need to pick a monitor: AutoClicker Visual finds the "
     "list on whichever screen shows it, even if you move the window later."),
    ("2 · Mark the list",
     "Open the app with the list and click <b>Mark anchor and first row</b>. The screens freeze; "
     "use the one that shows the list:<br><br>"
     "• First drag around the <b>anchor</b>: something near the list that always looks the same, "
     "such as its header or title. It is used to find the list even if the window moves.<br>"
     "• Then drag around the <b>first row</b>, while it contains an item.<br><br>"
     "The live indicator then tells you if the anchor is found and if the first row has an item. "
     "When the first row is empty, the work is done."),
    ("3 · Record the steps",
     "Click <b>Record</b> and process <b>one item</b> by hand, as usual. "
     "Each click is saved with a small picture of what you clicked, so it can be found again later, "
     "even if the window moves. Press <b>Finish</b> on the black bar at the top when the item is done.<br><br>"
     "Between steps it automatically waits for the next thing to appear, so you don't need to hurry."),
    ("4 · Test it",
     "<b>Test step</b> and <b>Simulate</b> show where it would click, without clicking.<br>"
     "<b>Run 1 item</b> processes just the first item for real, so you can check the result."),
    ("5 · Run",
     "Choose the flow and click <b>Run</b>. AutoClicker Visual steps aside and shows a small panel: "
     "bring the list into view, then press <b>Start</b>. The panel then shows the progress.<br><br>"
     "<b>Tips</b><br>"
     "• Press <b>F12</b> at any time to stop (or move the mouse to a corner of the screen).<br>"
     "• Don't use the mouse during a run: if you move it, the run pauses and asks you.<br>"
     "• Keep the window with the list visible and not covered.<br>"
     "• Use the same Windows display scale as when you recorded the flow."),
]


class Tutorial(QWizard):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tutorial")
        self.setWizardStyle(QWizard.ModernStyle)
        self.setButtonText(QWizard.FinishButton, "Create my first flow")
        self.resize(620, 420)
        for title, text in PAGES:
            page = QWizardPage()
            page.setTitle(title)
            label = QLabel(text)
            label.setWordWrap(True)
            QVBoxLayout(page).addWidget(label)
            self.addPage(page)
