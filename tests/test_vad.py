"""Voice Activity Detection tests: real speech (made with the Windows voice) mixed with
fan-like noise. Skipped if the Silero model hasn't been downloaded yet (Jarvis does that on
its first start) or if this isn't Windows."""
import numpy as np
import pytest

import voice

pytestmark = pytest.mark.skipif(not voice.VAD_MODEL.exists(), reason="Silero VAD model not downloaded yet")
RATE = voice.RATE


def windows_speech(text: str, path) -> np.ndarray:
    win32 = pytest.importorskip("win32com.client")
    fmt = win32.Dispatch("SAPI.SpAudioFormat")
    fmt.Type = 18  # 16 kHz, 16-bit, mono
    stream = win32.Dispatch("SAPI.SpFileStream")
    stream.Format = fmt
    stream.Open(str(path), 3)
    speaker = win32.Dispatch("SAPI.SpVoice")
    speaker.AudioOutputStream = stream
    speaker.Speak(text)
    stream.Close()
    import wave
    with wave.open(str(path)) as w:
        return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)


def fan_noise(seconds: float, loudness: float = 2500) -> np.ndarray:
    rng = np.random.default_rng(0)
    x = np.cumsum(rng.normal(0, 1, int(seconds * RATE)))
    x -= np.convolve(x, np.ones(400) / 400, "same")  # brown-ish rumble, like a fan or AC
    return loudness * x / np.sqrt(np.mean(x ** 2))


def phrases_in(audio: np.ndarray, min_energy: float = 150):
    pcm = audio.clip(-32768, 32767).astype(np.int16).tobytes()
    frames = [pcm[i:i + voice.FRAME * 2] for i in range(0, len(pcm) - voice.FRAME * 2, voice.FRAME * 2)]
    it = iter(frames)

    def read_frame():
        return next(it)  # raises StopIteration at the end of the recording

    found = []
    try:
        for start, data in voice.vad_phrases(read_frame, voice.SileroVAD(), min_energy):
            found.append((start, len(data) / 2 / RATE))
    except RuntimeError:  # the generator ran out of audio
        pass
    return found


def test_fan_noise_alone_is_never_a_phrase():
    assert phrases_in(fan_noise(8)) == []


def test_speech_in_fan_noise_is_one_phrase(tmp_path):
    speech = windows_speech("Hey Jarvis, what is the weather in Bhopal today?", tmp_path / "s.wav")
    noise = fan_noise(3 + len(speech) / RATE + 3, loudness=1500)
    start = 3 * RATE
    noise[start:start + len(speech)] += speech  # the sentence starts after 3 s of fan noise
    found = phrases_in(noise)
    assert len(found) == 1
    began, length = found[0]
    loud = np.flatnonzero(np.abs(speech) > 300)  # the file has silence before and after the words
    words_start, words_seconds = 3 + loud[0] / RATE, (loud[-1] - loud[0]) / RATE
    assert words_start - 0.5 <= began <= words_start          # starts just before the first word
    assert words_seconds <= length <= words_seconds + 1.5     # keeps all the words, little extra
