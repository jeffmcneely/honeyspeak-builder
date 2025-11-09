import os
import re
from openai import OpenAI
from openai._exceptions import BadRequestError, OpenAIError, APIError, RateLimitError, APITimeoutError
from datetime import datetime
from pathlib import Path

audio_format = "aac"
image_format = "png"

TTS_MODELS = ["gpt-4o-mini-tts", "tts-1", "tts-1-hd"]
IMAGE_MODELS = ["all-e-2", "dall-e-3", "gpt-image-1"]
VOICES = [
    "alloy", "ash", "ballad", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse"
]
IMAGE_SIZES = ["square", "vertical", "horizontal"]

def strip_tags(text: str) -> str:
    """Remove anything between curly braces {} including the braces themselves."""
    return re.sub(r"\{.*?\}", "", text)
def strip_tags_smart(text: str) -> str:
    text = re.sub(r"\{b\}.+?\{/b\}", "", text)
    text = re.sub(r"\{bc\}", "", text)
    text = re.sub(r"\{inf\}.+?\{/inf\}", "", text)
    text = re.sub(r"\{it\}.+?\{/it\}", "", text)
    text = re.sub(r"\{i{ldquo}\}", "", text)
    text = re.sub(r"\{i{ldquo}\}", "", text)
    text = re.sub(r"\{sd\}.+?\{/sd\}", "", text)
    text = re.sub(r"\{sup\}.+?\{/sup\}", "", text)
    return text


def log_400_error(error: BadRequestError, text: str, context: str) -> None:
    error_file = Path("errors.txt")
    timestamp = datetime.now().isoformat()
    error_message = str(error)
    error_details = ""
    if hasattr(error, "response") and error.response is not None:
        try:
            error_details = error.response.text
        except Exception:
            pass
    log_entry = f"""
{'='*80}
Timestamp: {timestamp}
Context: {context}
Status Code: 400
Error Message: {error_details or error_message}
Input Text: {text}
{'='*80}

"""
    with open(error_file, "a", encoding="utf-8") as f:
        f.write(log_entry)

def call_openai_audio_streaming(client: OpenAI, audio_model: str, audio_voice: str, text: str, fname: str) -> None:
    with client.audio.speech.with_streaming_response.create(
        model=audio_model,
        voice=audio_voice,
        input=text,
        response_format=audio_format,
    ) as resp:
        resp.stream_to_file(str(fname))

def call_openai_audio_non_streaming(client: OpenAI, audio_model: str, audio_voice: str, text: str) -> bytes:
    resp = client.audio.speech.create(
        model=audio_model,
        voice=audio_voice,
        input=text,
        response_format=audio_format,
    )
    return resp.read() if hasattr(resp, "read") else resp.content

def call_openai_image(client: OpenAI, image_model: str, prompt: str, size: str):
    return client.images.generate(
        model=image_model,
        prompt=prompt,
        size=size,
    )
