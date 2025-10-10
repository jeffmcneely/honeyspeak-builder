# pip install openai>=1.40
import os
import time
from pathlib import Path
from openai import OpenAI
from openai._exceptions import OpenAIError
import subprocess, tempfile, pathlib

from dotenv import load_dotenv

TEXT = "a vehicle (such as an airplane or balloon) for traveling through the air"
OUTDIR = Path("tts_outputs")
OUTDIR.mkdir(exist_ok=True)

# Models supported by audio/speech endpoint
MODELS = ["gpt-4o-mini-tts", "tts-1", "tts-1-hd"]  # per docs

# Built-in voices per docs
VOICES = [
    "alloy",
    "ash",
    "ballad",
    "coral",
    "echo",
    "fable",
    "onyx",
    "nova",
    "sage",
    "shimmer",
    "verse",
]
output_format = "aac"

load_dotenv()  # Load .env file if present
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def synth(model: str, voice: str, text: str) -> None:
    """
    Generate MP3 using audio.speech. Tries streaming first, falls back to non-streaming if unavailable.
    """
    fname = OUTDIR / f"{model}__{voice}.mp3"
    try:
        # Preferred: streaming writer (efficient for larger outputs)
        with client.audio.speech.with_streaming_response.create(
            model=model,
            voice=voice,
            input=text,
            response_format="mp3",
        ) as resp:
            resp.stream_to_file(str(fname))
        print(f"OK  {fname}")
        return
    except Exception as e:
        # Fallback to non-streaming API or models that don't support streaming in current SDK
        try:
            resp = client.audio.speech.create(
                model=model,
                voice=voice,
                input=text,
                response_format="mp3",
            )
            audio_bytes = resp.read() if hasattr(resp, "read") else resp.content
            with open(fname, "wb") as f:
                f.write(audio_bytes)
            print(f"OK  {fname} (fallback)")
            return
        except OpenAIError as oe:
            print(f"ERR {model}/{voice}: {oe}")
        except Exception as ee:
            print(f"ERR {model}/{voice}: {ee}")


def encode_to_crap(model: str, voice: str, bitrate) -> None:
    """Encode to low-bitrate mono mp3 using ffmpeg"""

    raw_path = OUTDIR / f"{model}__{voice}.mp3"
    low_path = OUTDIR / f"{model}__{voice}_{bitrate}kbps.mp3"

    # after you write raw_path
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(raw_path),
            "-ac",
            "1",  # mono
            "-b:a",
            f"{bitrate}k",  # target bitrate
            "-ar",
            "24000",  # optional: resample
            str(low_path),
        ],
        check=True,
    )


if __name__ == "__main__":
    load_dotenv()
        # Load .env file if present
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    for m in MODELS:
        for v in VOICES:
            synth(m, v, TEXT)
            for bitrate in [16, 24, 32, 40, 48]:
                encode_to_crap(m, v, bitrate)
            time.sleep(0.2)
    print("Done.")
