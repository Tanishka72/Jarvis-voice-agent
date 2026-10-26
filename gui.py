"""Desktop window for Jarvis: shows the conversation, what Jarvis is doing right now,
and lets you type as well as speak.

Run:  python gui.py      (or double-click Jarvis.bat)
"""
import functools
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog

import agent
import rag
import voice
import tools
from tools import TOOLS

NAME = agent.AGENT_NAME.title()

BG = "#101418"
PANEL = "#181e24"
TEXT = "#e6edf3"
MUTED = "#8b98a5"
YOU_BG = "#2563eb"
AGENT_BG = "#232b33"
TOOL_FG = "#e3b341"
ERROR_FG = "#f47067"

STATUS = {  # state: (dot colour, text)
    "starting": ("#8b98a5", "Starting..."),
    "sleeping": ("#8b98a5", f'Sleeping - say "Hey {NAME}"'),
    "listening": ("#3fb950", "Listening... go ahead"),
    "thinking": ("#e3b341", "Thinking..."),
    "speaking": ("#58a6ff", "Speaking..."),
    "muted": ("#f47067", "Mic is off - type below"),
    "error": ("#f47067", "Not ready - see the message above"),
}


class JarvisApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.events = queue.Queue()  # background threads -> UI (tkinter is not thread-safe)
        self.busy = threading.Lock()  # one question at a time, spoken or typed
        self.mic_on = threading.Event()
        self.mic_on.set()
        self.awake = False  # True while waiting for follow-up questions
        self.talk_until = 0.0  # after clicking Talk, the next phrase needs no wake word

        self._build_ui()
        self.root.after(100, self._process_events)

        self.add_message("system", f'Say "Hey {NAME}, are you listening?", click Talk and ask, '
                                   "or type a message below.")
        try:
            # With long-term memory: saved answers + earlier chats, kept in data/jarvis.db.
            self.chat = agent.create_desktop_brain([self._show_tool_use(t) for t in TOOLS], log=self._log)
        except SystemExit as e:
            self.chat = None
            self.add_message("error", str(e))
            self.set_status("error")
            return
        tools.on_reminder = lambda message: self._speak(f"Reminder: {message}")
        rag.on_event = self._rag_log  # show RAG pipeline steps and answer checks in the chat
        threading.Thread(target=rag.index_folder, args=(self._rag_log,), daemon=True).start()
        threading.Thread(target=self._voice_loop, daemon=True).start()

    # ---------- UI ----------
    def _build_ui(self):
        self.root.title(f"{NAME} - Voice Agent")
        self.root.geometry("480x700")
        self.root.minsize(380, 500)
        self.root.configure(bg=BG)
        body = ("Segoe UI", 11)

        header = tk.Frame(self.root, bg=PANEL, padx=16, pady=12)
        header.pack(fill="x")
        tk.Label(header, text=NAME, font=("Segoe UI Semibold", 16), bg=PANEL, fg=TEXT).pack(anchor="w")
        status_row = tk.Frame(header, bg=PANEL)
        status_row.pack(anchor="w", pady=(4, 0))
        self.dot = tk.Canvas(status_row, width=12, height=12, bg=PANEL, highlightthickness=0)
        self.dot_id = self.dot.create_oval(2, 2, 11, 11, fill=MUTED, outline="")
        self.dot.pack(side="left")
        self.status_text = tk.Label(status_row, font=("Segoe UI", 10), bg=PANEL, fg=MUTED)
        self.status_text.pack(side="left", padx=(6, 0))
        self.heard_text = tk.Label(header, text="", font=("Segoe UI", 9, "italic"), bg=PANEL, fg=MUTED)
        self.heard_text.pack(anchor="w")

        # Scrollable conversation area
        wrap = tk.Frame(self.root, bg=BG)
        wrap.pack(fill="both", expand=True)
        self.canvas = tk.Canvas(wrap, bg=BG, highlightthickness=0)
        bar = tk.Scrollbar(wrap, command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        self.messages = tk.Frame(self.canvas, bg=BG)
        win = self.canvas.create_window((0, 0), window=self.messages, anchor="nw")
        self.messages.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(win, width=e.width))
        self.canvas.bind_all("<MouseWheel>", lambda e: self.canvas.yview_scroll(-e.delta // 120, "units"))

        # Bottom bar: mic toggle + text box + send
        bottom = tk.Frame(self.root, bg=PANEL, padx=10, pady=10)
        bottom.pack(fill="x")
        self.mic_btn = tk.Button(bottom, text="Mic ON", width=8, font=body, relief="flat", bd=0,
                                 bg="#238636", fg="white", activebackground="#2ea043",
                                 cursor="hand2", command=self.toggle_mic)
        self.mic_btn.pack(side="left", ipady=4)
        tk.Button(bottom, text="Talk", width=6, font=body, relief="flat", bd=0, bg="#1f6feb", fg="white",
                  activebackground="#388bfd", cursor="hand2",
                  command=self.talk_now).pack(side="left", padx=(8, 0), ipady=4)
        tk.Button(bottom, text="Upload PDF", font=body, relief="flat", bd=0, bg="#6e40c9", fg="white",
                  activebackground="#8957e5", cursor="hand2", padx=8,
                  command=self.upload_pdf).pack(side="left", padx=(8, 0), ipady=4)
        self.entry = tk.Entry(bottom, font=body, bg=AGENT_BG, fg=TEXT, insertbackground=TEXT,
                              relief="flat", bd=0)
        self.entry.pack(side="left", fill="x", expand=True, padx=8, ipady=7)
        self.entry.bind("<Return>", lambda e: self.send_typed())
        tk.Button(bottom, text="Send", width=6, font=body, relief="flat", bd=0, bg=YOU_BG, fg="white",
                  activebackground="#3b82f6", cursor="hand2", command=self.send_typed).pack(side="left", ipady=4)

        self.set_status("starting")

    def add_message(self, who: str, text: str):
        width = max(self.canvas.winfo_width(), 460)
        row = tk.Frame(self.messages, bg=BG)
        row.pack(fill="x", padx=12, pady=5)
        if who in ("you", "agent"):
            you = who == "you"
            side = "e" if you else "w"
            tk.Label(row, text="You" if you else NAME, font=("Segoe UI", 9), bg=BG, fg=MUTED).pack(anchor=side)
            tk.Label(row, text=text, font=("Segoe UI", 11), justify="left", wraplength=int(width * 0.7),
                     bg=YOU_BG if you else AGENT_BG, fg="white" if you else TEXT,
                     padx=12, pady=8).pack(anchor=side)
        else:  # tool / system / error notes
            fg = {"tool": TOOL_FG, "error": ERROR_FG}.get(who, MUTED)
            tk.Label(row, text=text, font=("Segoe UI", 9, "italic"), justify="left",
                     wraplength=int(width * 0.9), bg=BG, fg=fg).pack(anchor="w")
        self.root.after(20, lambda: self.canvas.yview_moveto(1.0))

    def set_status(self, state: str):
        if state == "idle":
            state = "listening" if self.awake else ("sleeping" if self.mic_on.is_set() else "muted")
        colour, text = STATUS[state]
        self.dot.itemconfigure(self.dot_id, fill=colour)
        self.status_text.configure(text=text)

    def toggle_mic(self):
        if self.mic_on.is_set():
            self.mic_on.clear()
            self.mic_btn.configure(text="Mic OFF", bg="#6e7681", activebackground="#8b949e")
        else:
            self.mic_on.set()
            self.mic_btn.configure(text="Mic ON", bg="#238636", activebackground="#2ea043")
        if not self.busy.locked():
            self.set_status("idle")

    def talk_now(self):
        """Talk button: the next thing you say is treated as a question, no "Hey Jarvis" needed."""
        if not self.mic_on.is_set():
            self.toggle_mic()
        voice.clear()  # don't treat something said earlier as the question
        self.talk_until = time.time() + 10
        self.set_status("listening")
        self.heard_text.configure(text="Talk now, I'm listening...")

    def upload_pdf(self):
        path = filedialog.askopenfilename(title="Choose a PDF for Jarvis to read",
                                          filetypes=[("PDF files", "*.pdf")])
        if path:
            threading.Thread(target=rag.add_pdf, args=(path, self._rag_log), daemon=True).start()

    def _rag_log(self, message: str):
        self._post("msg", "tool", message)

    def send_typed(self):
        text = self.entry.get().strip()
        if not text or self.chat is None:
            return
        self.entry.delete(0, "end")
        self.add_message("you", text)
        command = agent.strip_wake_word(text)
        threading.Thread(target=self._respond, args=(text if command is None else command,), daemon=True).start()

    # ---------- background work (never touches widgets directly) ----------
    def _post(self, kind: str, *args):
        self.events.put((kind, args))

    def _process_events(self):
        while not self.events.empty():
            kind, args = self.events.get()
            if kind == "msg":
                self.add_message(*args)
            elif kind == "status":
                self.set_status(*args)
            elif kind == "heard":
                self.heard_text.configure(text=f'Heard: "{args[0]}"' if args[0] else "")
        self.root.after(100, self._process_events)

    def _show_tool_use(self, tool):
        @functools.wraps(tool)  # keeps the name, docstring and type hints Gemini reads
        def wrapper(*args, **kwargs):
            shown = ", ".join([repr(a) for a in args] + [f"{k}={v!r}" for k, v in kwargs.items()])
            self._post("msg", "tool", f"Using tool: {tool.__name__}({shown})")
            return tool(*args, **kwargs)
        return wrapper

    def _log(self, message: str):
        self._post("msg", "error" if message.startswith("[error]") else "system", message)

    def _speak(self, text: str):
        self._post("msg", "agent", text)
        self._post("status", "speaking")
        try:
            voice.speak(text)
        except Exception as e:
            self._post("msg", "error", f"Could not play voice: {e}")

    def _respond(self, command: str):
        with self.busy:
            if agent.is_just_a_ping(command):
                reply = agent.GREETING
            else:
                self._post("status", "thinking")
                started = time.time()
                reply = self.chat.ask(command, log=self._log)
                seconds = time.time() - started
                if self.chat.last_from_cache:
                    self._post("msg", "tool", f"Instant answer from memory in {seconds:.2f} s (no Gemini call)")
                else:
                    self._post("msg", "tool", f"Answered in {seconds:.1f} s")
            self._speak(reply)
            self._post("status", "idle")

    def _listen(self, timeout: float) -> str:
        """Listen once; returns '' if nothing useful was heard."""
        heard = voice.listen(timeout=timeout)
        if heard is None or self.busy.locked() or not self.mic_on.is_set():
            return ""
        self._post("heard", heard or "(heard a sound, but couldn't understand it)")
        return heard

    def _voice_loop(self):
        while True:
            try:
                self._voice_turn()
            except Exception as e:  # never let one error switch the microphone off for good
                self.awake = False
                self._post("msg", "error", f"Voice problem, still listening: {e}")
                time.sleep(1)

    def _voice_turn(self):
        if not self.mic_on.is_set():
            self._post("status", "idle")
            self.mic_on.wait()
            voice.clear()  # drop anything recorded while the mic was "off"
        talk_mode = time.time() < self.talk_until  # Talk button was clicked
        if not self.busy.locked():
            self._post("status", "listening" if talk_mode else "sleeping")
        heard = self._listen(timeout=2 if talk_mode else 5)
        if heard and time.time() < self.talk_until + 8:  # allow for speech-to-text time
            self.talk_until = 0
            command = agent.strip_wake_word(heard)  # no wake word needed...
            if command is None:
                command = heard  # ...but if it was said alone, "" gets the normal greeting
        else:
            command = agent.strip_wake_word(heard) if heard else None
        if command is None:
            return  # not talking to us

        self._post("msg", "you", heard)
        self.awake = True
        self._respond(command)
        for _ in range(agent.FOLLOW_UP_TURNS):
            self._post("status", "listening")
            follow_up = self._listen(timeout=agent.FOLLOW_UP_SECONDS)
            if not follow_up:
                break
            self._post("msg", "you", follow_up)
            if any(w in follow_up for w in agent.STOP_WORDS):
                with self.busy:
                    self._speak("Okay, call me if you need anything.")
                break
            self._respond(agent.strip_wake_word(follow_up) or follow_up)
        self.awake = False


def main():
    root = tk.Tk()
    JarvisApp(root)
    root.protocol("WM_DELETE_WINDOW", lambda: os._exit(0))  # also stops the mic/voice threads
    root.mainloop()


if __name__ == "__main__":
    main()
