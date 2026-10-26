"""Microphone input (speech-to-text) and speaker output (text-to-speech).

The microphone stays open in a background thread that records every phrase into a queue,
so nothing you say is lost while Jarvis is busy turning the previous phrase into text.

Noise handling with VAD (Voice Activity Detection):
  Without VAD, "someone is talking" just means "the sound is loud", so a fan, music or a door
  also count. With VAD, a small neural network (Silero VAD, 2 MB, under 1 ms per frame on the
  CPU) checks every 32 ms of sound: "is this a human voice?". Only voice starts a phrase, and
  the phrase ends after 1.2 seconds without voice, even if the fan keeps running. So Google
  receives only real speech. Set JARVIS_VAD=off in .env to go back to loudness only.
"""
import audioop
import os
import queue
import threading
import time
import urllib.request
from collections import deque
from pathlib import Path

import pythoncom
import speech_recognition as sr
import win32com.client

_recognizer = sr.Recognizer()
_recognizer.dynamic_energy_threshold = False  # keep our calibrated threshold (see _calibrate)
_recognizer.pause_threshold = 1.2  # seconds of silence that end a phrase (0.8 cut people off mid-sentence)
_recognizer.operation_timeout = 10  # never wait forever for Google's speech-to-text (it froze listening)

_phrases = queue.Queue()  # (time recording started, audio)
_recorder = None
_last_speech_end = 0.0  # when Jarvis last finished talking
_local = threading.local()


def _get_voice():
    # Windows' built-in speech engine (SAPI). More reliable than pyttsx3, which can go silent.
    # COM objects belong to one thread, so each thread (e.g. in the desktop app) gets its own.
    if not hasattr(_local, "voice"):
        pythoncom.CoInitialize()
        _local.voice = win32com.client.Dispatch("SAPI.SpVoice")
        _local.voice.Volume = 100  # 0-100
        _local.voice.Rate = 1      # -10 (slow) to 10 (fast)
    return _local.voice


def speak(text: str) -> None:
    global _last_speech_end
    print(f"Agent: {text}")
    _last_speech_end = time.time() + 60  # "still talking" while Speak() runs
    try:
        _get_voice().Speak(text)  # blocks until finished
    finally:
        _last_speech_end = time.time()


def _calibrate(source) -> None:
    """Set how loud a sound must be to count as speech.

    The library's own calibration uses the average level, so one door slam while it
    measures makes the threshold so high that normal speech is ignored. Using the
    median ignores short spikes, and the cap keeps normal speech above the threshold.
    MIC_THRESHOLD in .env overrides this (lower = more sensitive).
    """
    if os.getenv("MIC_THRESHOLD"):
        _recognizer.energy_threshold = int(os.getenv("MIC_THRESHOLD"))
    else:
        reads = int(1.5 * source.SAMPLE_RATE / source.CHUNK)
        levels = sorted(audioop.rms(source.stream.read(source.CHUNK), source.SAMPLE_WIDTH) for _ in range(reads))
        _recognizer.energy_threshold = max(300, min(levels[len(levels) // 2] * 3, 1200))
    print(f"[mic] voice threshold: {round(_recognizer.energy_threshold)}")


# ---------- Voice Activity Detection ----------
VAD_MODEL = Path(__file__).parent / ".models" / "silero" / "silero_vad.onnx"
VAD_MODEL_URL = "https://github.com/snakers4/silero-vad/raw/v5.1.2/src/silero_vad/data/silero_vad.onnx"
RATE = 16000          # Silero works on 16 kHz audio...
FRAME = 512           # ...in frames of 512 samples = 32 ms
FRAME_SECONDS = FRAME / RATE
VOICE_START = 0.5     # probability needed to count a frame as voice
VOICE_KEEP = 0.35     # lower bar once a phrase has started, so quiet word endings aren't cut
START_FRAMES = 6      # a phrase starts when 6 of the last 10 frames are voice (about 0.2 s)...
PRE_ROLL = 10         # ...and keeps the 0.3 s before that, so the first syllable isn't lost
END_FRAMES = round(1.2 / FRAME_SECONDS)   # 1.2 s without voice ends the phrase
MAX_FRAMES = round(10 / FRAME_SECONDS)    # never longer than 10 s


class SileroVAD:
    """Answers "is this 32 ms of sound a human voice?" with a probability from 0 to 1."""

    def __init__(self, model_path: Path = VAD_MODEL):
        import numpy as np
        import onnxruntime

        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = options.inter_op_num_threads = 1  # tiny model: 1 thread is enough
        self.np = np
        self.session = onnxruntime.InferenceSession(str(model_path), sess_options=options,
                                                    providers=["CPUExecutionProvider"])
        self.sr = np.array(RATE, dtype=np.int64)
        self.state = np.zeros((2, 1, 128), dtype=np.float32)  # the model's memory of the last frames
        self.context = np.zeros((1, 64), dtype=np.float32)    # last 64 samples, as Silero expects

    def probability(self, frame: bytes) -> float:
        np = self.np
        x = np.frombuffer(frame, dtype=np.int16).astype(np.float32)[None, :] / 32768
        x = np.concatenate([self.context, x], axis=1)
        out, self.state = self.session.run(None, {"input": x, "state": self.state, "sr": self.sr})
        self.context = x[:, -64:]
        return float(out[0][0])


def _load_vad() -> SileroVAD | None:
    """Silero VAD, downloaded once (2 MB) on first use. None = fall back to loudness only."""
    if os.getenv("JARVIS_VAD", "on").lower() in ("off", "0", "false", "no"):
        return None
    try:
        if not VAD_MODEL.exists():
            print("[mic] downloading the voice detection model (2 MB, first time only)...")
            VAD_MODEL.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(VAD_MODEL_URL, VAD_MODEL)
        return SileroVAD()
    except Exception as e:
        print(f"[mic] voice detection unavailable ({e}); using loudness only")
        return None


def vad_phrases(read_frame, vad, min_energy: float):
    """Cut a never-ending stream of 32 ms frames into phrases that contain a voice.

    A frame counts as voice when the model says so AND it's loud enough (min_energy), so a TV
    in the next room counts less than you speaking at the laptop.
    Yields (seconds since the stream started, raw 16-bit audio of the phrase).
    """
    def is_voice(frame, bar):
        return vad.probability(frame) >= bar and audioop.rms(frame, 2) >= min_energy

    pre_roll, recent = deque(maxlen=PRE_ROLL), deque(maxlen=10)
    position = 0  # frames read so far
    while True:
        frame = read_frame()
        position += 1
        pre_roll.append(frame)
        recent.append(is_voice(frame, VOICE_START))
        if sum(recent) < START_FRAMES:
            continue
        # A voice started: keep recording until 1.2 s without voice (or 10 s in total).
        start = position - len(pre_roll)
        frames, quiet = list(pre_roll), 0
        while quiet < END_FRAMES and len(frames) < MAX_FRAMES:
            frame = read_frame()
            position += 1
            frames.append(frame)
            quiet = 0 if is_voice(frame, VOICE_KEEP) else quiet + 1
        yield start * FRAME_SECONDS, b"".join(frames[:len(frames) - quiet + 8])  # drop most trailing silence
        pre_roll.clear()
        recent.clear()


def _record_forever():
    vad = _load_vad()
    print("[mic] voice detection: Silero VAD (ignores fans, music and other non-voice noise)"
          if vad else "[mic] voice detection: loudness only")
    while True:  # if the microphone fails (unplugged, taken by another app), reopen it
        try:
            if vad:
                with sr.Microphone(sample_rate=RATE, chunk_size=FRAME) as source:
                    _calibrate(source)
                    min_energy = _recognizer.energy_threshold / 2  # VAD does the main work now
                    opened = time.time()
                    for offset, data in vad_phrases(lambda: source.stream.read(FRAME), vad, min_energy):
                        _phrases.put((opened + offset, sr.AudioData(data, RATE, 2)))
            else:
                with sr.Microphone() as source:
                    _calibrate(source)
                    while True:
                        started = time.time()
                        try:
                            audio = _recognizer.listen(source, timeout=2, phrase_time_limit=10)
                        except sr.WaitTimeoutError:
                            continue
                        _phrases.put((started, audio))
        except Exception as e:
            print(f"[mic] error, reopening the microphone: {e}")
            time.sleep(2)


def start() -> None:
    """Open the microphone (called automatically by listen())."""
    global _recorder
    if _recorder is None:
        _recorder = threading.Thread(target=_record_forever, daemon=True)
        _recorder.start()


def clear() -> None:
    """Forget phrases recorded so far (e.g. when the mic is switched off)."""
    while not _phrases.empty():
        _phrases.get_nowait()


def listen(timeout: float | None = None) -> str | None:
    """Wait for the next phrase and return it as lowercase text.

    Returns None if nothing was said within `timeout` seconds, and "" if something was
    heard but could not be understood. Phrases recorded while Jarvis was talking are skipped,
    so Jarvis never answers its own voice.
    """
    start()
    deadline = None if timeout is None else time.time() + timeout
    while True:
        remaining = None if deadline is None else deadline - time.time()
        if remaining is not None and remaining <= 0:
            return None
        try:
            started, audio = _phrases.get(timeout=remaining)
        except queue.Empty:
            return None
        if started < _last_speech_end:
            continue  # recorded while Jarvis was speaking
        try:
            return _recognizer.recognize_google(audio).lower()
        except sr.UnknownValueError:
            return ""
        except (sr.RequestError, OSError) as e:  # no internet, or Google too slow (timeout)
            print(f"[speech-to-text error] {e}")
            return ""
