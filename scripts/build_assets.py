import argparse
from argparse import Namespace
import os
from pathlib import Path
import base64
from openai import OpenAI
from openai._exceptions import (
    OpenAIError,
    APIError,
    RateLimitError,
    APITimeoutError,
    BadRequestError,
)
from libs.sqlite_dictionary import SQLiteDictionary
from rich.progress import Progress, track
from dotenv import load_dotenv
import re
from celery import Celery
import logging
import json
from datetime import datetime

logger = logging.getLogger(__name__)

# Celery configuration
app = Celery(
    "build_assets",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0",
)
app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)


# Models supported by audio/speech endpoint
TTS_MODELS = ["gpt-4o-mini-tts", "tts-1", "tts-1-hd"]  # per docs
IMAGE_MODELS = ["all-e-2", "dall-e-3", "gpt-image-1"]
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
IMAGE_SIZES = ["square", "vertical", "horizontal"]

audio_format = "aac"
image_format = "png"


def log_400_error(error: BadRequestError, text: str, context: str) -> None:
    """
    Log 400 Bad Request errors from OpenAI API to errors.txt file.

    Args:
        error: The BadRequestError exception
        text: The text/prompt that caused the error
        context: Context information (e.g., 'audio', 'image')
    """
    error_file = Path("errors.txt")

    timestamp = datetime.now().isoformat()
    error_message = str(error)

    # Try to extract the error message from the response if available
    error_details = ""
    if hasattr(error, "response") and error.response is not None:
        try:
            response_json = error.response.json()
            if "error" in response_json and "message" in response_json["error"]:
                error_details = response_json["error"]["message"]
        except:
            pass

    # Build log entry
    log_entry = f"""
{'='*80}
Timestamp: {timestamp}
Context: {context}
Status Code: 400
Error Message: {error_details or error_message}
Input Text: {text}
{'='*80}

"""

    # Append to errors.txt
    with open(error_file, "a", encoding="utf-8") as f:
        f.write(log_entry)


def strip_tags(text: str) -> str:
    """
    Remove anything between curly braces {} including the braces themselves.
    """
    return re.sub(r"\{.*?\}", "", text)


def _call_openai_audio_streaming(
    client: OpenAI, audio_model: str, audio_voice: str, text: str, fname: str
) -> None:
    """
    Call OpenAI audio API with streaming response and retry logic.
    Raises exception if all retries fail.
    """
    with client.audio.speech.with_streaming_response.create(
        model=audio_model,
        voice=audio_voice,
        input=text,
        response_format=audio_format,
    ) as resp:
        resp.stream_to_file(str(fname))


def _call_openai_audio_non_streaming(
    client: OpenAI, audio_model: str, audio_voice: str, text: str
) -> bytes:
    """
    Call OpenAI audio API without streaming and retry logic.
    Returns audio bytes. Raises exception if all retries fail.
    """
    resp = client.audio.speech.create(
        model=audio_model,
        voice=audio_voice,
        input=text,
        response_format=audio_format,
    )
    return resp.read() if hasattr(resp, "read") else resp.content


def _call_openai_image(client: OpenAI, image_model: str, prompt: str, size: str):
    """
    Call OpenAI images API with retry logic.
    Returns API result. Raises exception if all retries fail.
    """
    return client.images.generate(
        model=image_model,
        prompt=prompt,
        size=size,
    )


@app.task
def generate_audio_task(
    text: str,
    fname: str,
    audio_model: str,
    audio_voice: str,
    verbosity: int,
    dryrun: bool,
) -> dict:
    """
    Celery task for generating audio.
    Returns dict with status and filename.
    """
    load_dotenv()  # Load env vars in worker context

    if os.path.isfile(fname):
        if verbosity >= 2:
            print(f"[synth] Skipping existing file: {fname}")
        return {"status": "skipped", "file": fname}

    text = strip_tags(text)
    if len(text) < 10:
        if verbosity >= 2:
            print(f"[synth] Text too short, skipping audio generation for: {fname}")
        return {"status": "skipped", "file": fname}
    if dryrun:
        if verbosity >= 1:
            print(f"[DRY RUN] Would generate audio: {fname} = '{text[:50]}...'")
        return {"status": "dryrun", "file": fname}

    if verbosity >= 2:
        print(f"[synth] Generating audio for {fname}: '{text[:50]}...'")

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    try:
        # Preferred: streaming writer (efficient for larger outputs)
        _call_openai_audio_streaming(client, audio_model, audio_voice, text, fname)
        if verbosity >= 2:
            print(f"[synth] Successfully created: {fname}")
        return {"status": "success", "file": fname}
    except BadRequestError as bre:
        # Log 400 errors to errors.txt
        log_400_error(
            bre, text, f"audio generation (model={audio_model}, voice={audio_voice})"
        )
        if verbosity >= 1:
            print(f"ERR 400 {audio_model}/{audio_voice}: {bre}")
        return {"status": "error", "file": fname, "error": f"400: {str(bre)}"}
    except Exception as e:
        # Fallback to non-streaming API or models that don't support streaming in current SDK
        try:
            audio_bytes = _call_openai_audio_non_streaming(
                client, audio_model, audio_voice, text
            )
            with open(fname, "wb") as f:
                f.write(audio_bytes)
            if verbosity >= 2:
                print(f"[synth] Successfully created (fallback): {fname}")
            return {"status": "success", "file": fname}
        except BadRequestError as bre:
            # Log 400 errors to errors.txt
            log_400_error(
                bre,
                text,
                f"audio generation fallback (model={audio_model}, voice={audio_voice})",
            )
            if verbosity >= 1:
                print(f"ERR 400 {audio_model}/{audio_voice}: {bre}")
            return {"status": "error", "file": fname, "error": f"400: {str(bre)}"}
        except OpenAIError as oe:
            if verbosity >= 1:
                print(f"ERR {audio_model}/{audio_voice}: {oe}")
            return {"status": "error", "file": fname, "error": str(oe)}
        except Exception as ee:
            if verbosity >= 1:
                print(f"ERR {audio_model}/{audio_voice}: {ee}")
            return {"status": "error", "file": fname, "error": str(ee)}


@app.task
def generate_image_task(
    text: str,
    fname: str,
    image_model: str,
    image_size: str,
    verbosity: int,
    dryrun: bool,
) -> dict:
    """
    Celery task for generating images.
    Returns dict with status and filename.
    """
    load_dotenv()  # Load env vars in worker context

    # Must be one of 1024x1024, 1536x1024 (landscape), 1024x1536 (portrait), or auto (default value) for gpt-image-1
    # one of 256x256, 512x512, or 1024x1024 for dall-e-2
    # one of 1024x1024, 1792x1024, or 1024x1792 for dall-e-3.

    size = "1024x1024"
    aspect_words = "square illustration (1:1 aspect)"
    match image_model:
        case "gpt-image-1":
            match image_size:
                case "vertical":
                    size = "1024x1536"
                    aspect_words = "vertical illustration (9:16 aspect) "
                case "horizontal":
                    size = "1536x1024"
                    aspect_words = "horizontal illustration (16:9 aspect) "

        case "dall-e-3":
            match image_size:
                case "vertical":
                    size = "1024x1792"
                    aspect_words = "vertical illustration (4:7 aspect) "
                case "horizontal":
                    size = "1792x1024"
                    aspect_words = "horizontal illustration (7:4 aspect) "

    if os.path.isfile(fname):
        if verbosity >= 2:
            print(f"[generate_image] Skipping existing file: {fname}")
        return {"status": "skipped", "file": fname}

    text = strip_tags(text)
    if len(text) < 10:
        if verbosity >= 2:
            print(
                f"[generate_image] Text too short, skipping image generation for: {fname}"
            )
        return {"status": "skipped", "file": fname}
    if dryrun:
        if verbosity >= 1:
            preview = (text or "").strip().replace("\n", " ")
            print(f"[DRY RUN] Would generate image: {fname} = '{preview[:60]}...'")
        return {"status": "dryrun", "file": fname}

    # Encourage vertical composition and clarity in the prompt

    prompt = (
        f"Create a clean, high-contrast educational non-offensive {aspect_words}"
        f"that represents: {text}. No text, centered subject, solid background. The image should not be sexual, suggestive, or depict nudity in any form."
    )

    if verbosity >= 2:
        print(
            f"[generate_image] Creating image for {fname} (size={size}, model={image_model})"
        )

    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    try:
        result = _call_openai_image(client, image_model, prompt, size)
        # OpenAI Images API returns base64 JSON in data[0].b64_json
        b64 = result.data[0].b64_json if hasattr(result.data[0], "b64_json") else None
        if not b64:
            raise ValueError("No image data returned from API")
        with open(fname, "wb") as f:
            f.write(base64.b64decode(b64))
        if verbosity >= 2:
            print(f"[generate_image] Wrote {fname}")
        return {"status": "success", "file": fname}
    except BadRequestError as bre:
        # Log 400 errors to errors.txt
        log_400_error(
            bre, text, f"image generation (model={image_model}, size={image_size})"
        )
        if verbosity >= 1:
            print(f"[generate_image] 400 error: {bre}")
        return {"status": "error", "file": fname, "error": f"400: {str(bre)} {text}"}
    except OpenAIError as oe:
        if verbosity >= 1:
            print(f"[generate_image] OpenAI error: {oe}")
        return {"status": "error", "file": fname, "error": str(oe)}

    except Exception as e:
        if verbosity >= 1:
            print(f"[generate_image] {text} Error: {e}")
        return {"status": "error", "file": fname, "error": str(e)}


def generate_audio(client: OpenAI, text: str, fname: str, args: Namespace) -> None:
    """
    Synchronous wrapper for generate_audio_task.
    Used when not running in Celery mode.
    """
    generate_audio_task(
        text=text,
        fname=fname,
        audio_model=args.audio_model,
        audio_voice=args.audio_voice,
        verbosity=args.verbosity,
        dryrun=args.dryrun,
    )


def generate_image(client: OpenAI, text: str, fname: str, args: Namespace) -> None:
    """
    Synchronous wrapper for generate_image_task.
    Used when not running in Celery mode.
    """
    generate_image_task(
        text=text,
        fname=fname,
        image_model=args.image_model,
        image_size=args.image_size,
        verbosity=args.verbosity,
        dryrun=args.dryrun,
    )


def main():
    parser = argparse.ArgumentParser(
        description="Generate audio/image files for dictionary words and definitions"
    )
    parser.add_argument(
        "--no_audio",
        action="store_true",
        default=False,
        help="Generate audio files (default: True)",
    )
    parser.add_argument(
        "--audio_model",
        default="gpt-4o-mini-tts",
        choices=TTS_MODELS,
        help="OpenAI TTS model to use",
    )
    parser.add_argument(
        "--audio_voice",
        default="alloy",
        choices=VOICES,
        help="Voice to use for synthesis",
    )

    parser.add_argument(
        "--no_images",
        action="store_true",
        default=False,
        help="Generate image files (default: True)",
    )
    parser.add_argument(
        "--image_model",
        default="gpt-image-1",
        choices=IMAGE_MODELS,
        help="OpenAI image model to use",
    )
    parser.add_argument(
        "--image_size",
        default="vertical",
        choices=IMAGE_SIZES,
        help="Size of image (default: square)",
    )

    parser.add_argument(
        "--verbosity",
        "-v",
        type=int,
        default=1,
        choices=[0, 1, 2],
        help="Verbosity level: 0=silent, 1=progress bars, 2=detailed logging",
    )
    parser.add_argument(
        "--outdir",
        default="assets_hires",
        help="Output directory for audio assets (default: assets_hires)",
    )
    parser.add_argument(
        "--dryrun",
        action="store_true",
        help="Show what would be done without actually doing it",
    )
    parser.add_argument(
        "--enqueue",
        action="store_true",
        help="Enqueue all jobs to Celery workers instead of processing synchronously",
    )

    args = parser.parse_args()

    load_dotenv()

    if args.verbosity >= 1:
        print(f"Using model={args.audio_model} voice={args.audio_voice}")
        if args.verbosity >= 2:
            print(f"Audio format={audio_format}, outdir={args.outdir}")
        if args.dryrun:
            print("[DRY RUN MODE] - No files will be created")
        if args.enqueue:
            print("[ENQUEUE MODE] - Jobs will be queued for Celery workers")

    if args.no_audio and args.no_images:
        if args.verbosity >= 1:
            print("Nothing to do - both audio and images disabled")
        return

    OUTDIR = Path(args.outdir)
    OUTDIR.mkdir(exist_ok=True)

    # Initialize OpenAI client only if needed
    client = None
    if not args.dryrun:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    db = SQLiteDictionary()
    words = db.get_all_words()  # List[str]

    if args.verbosity >= 1:
        print(f"Found {len(words)} words in database")

    # Enqueue mode: collect all jobs and send to Celery
    if args.enqueue:
        job_count = 0
        if args.verbosity >= 1:
            print("Enqueuing jobs to Celery...")

        for w in words:
            uuids = db.get_uuids(w.word)
            for uuid in uuids:
                if not args.no_audio:
                    # Enqueue word audio
                    generate_audio_task.delay(
                        text=w.word,
                        fname=os.path.join(
                            args.outdir, f"word_{uuid}_0.{audio_format}"
                        ),
                        audio_model=args.audio_model,
                        audio_voice=args.audio_voice,
                        verbosity=args.verbosity,
                        dryrun=args.dryrun,
                    )
                    job_count += 1

                    # Enqueue definition audios
                    for sd in db.get_shortdefs(uuid):
                        generate_audio_task.delay(
                            text=sd.definition,
                            fname=os.path.join(
                                args.outdir,
                                f"shortdef_{sd.uuid}_{sd.id}.{audio_format}",
                            ),
                            audio_model=args.audio_model,
                            audio_voice=args.audio_voice,
                            verbosity=args.verbosity,
                            dryrun=args.dryrun,
                        )
                        job_count += 1

                if not args.no_images:
                    # Enqueue definition images
                    for sd in db.get_shortdefs(uuid):
                        generate_image_task.delay(
                            text=sd.definition,
                            fname=os.path.join(
                                args.outdir, f"image_{sd.uuid}_{sd.id}.{image_format}"
                            ),
                            image_model=args.image_model,
                            image_size=args.image_size,
                            verbosity=args.verbosity,
                            dryrun=args.dryrun,
                        )
                        job_count += 1

        db.close()
        if args.verbosity >= 1:
            print(f"Enqueued {job_count} jobs to Celery workers")
            print("Monitor progress with: celery -A build_assets flower")
        return

    # Synchronous mode: process jobs directly
    # Initialize OpenAI client only if needed
    client = None
    if not args.dryrun:
        client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # Use progress bar only for verbosity level 1
    if args.verbosity == 1:
        with Progress() as progress:
            main_task = progress.add_task("[cyan]Processing words", total=len(words))

            for w in words:
                uuids = db.get_uuids(w.word)

                # Calculate total assets for this word
                total_assets = 0
                for uuid in uuids:
                    shortdefs = db.get_shortdefs(uuid)
                    if not args.no_audio:
                        total_assets += 1 + len(
                            shortdefs
                        )  # word audio + definition audios
                    if not args.no_images:
                        total_assets += len(shortdefs)  # definition images

                asset_task = progress.add_task(
                    f"[green]  └─ {w.word}", total=total_assets
                )

                for uuid in uuids:
                    if not args.no_audio:
                        # synthesize the word itself
                        progress.update(
                            asset_task,
                            description=f"[green]  └─ {w.word} (audio: word)",
                        )
                        generate_audio(
                            client,
                            w.word,
                            os.path.join(args.outdir, f"word_{uuid}_0.{audio_format}"),
                            args,
                        )
                        progress.advance(asset_task)

                        # synthesize each short definition for this sense
                        for i, sd in enumerate(db.get_shortdefs(uuid), 1):
                            progress.update(
                                asset_task,
                                description=f"[green]  └─ {w.word} (audio: def {i})",
                            )
                            generate_audio(
                                client,
                                sd.definition,
                                os.path.join(
                                    args.outdir,
                                    f"shortdef_{sd.uuid}_{sd.id}.{audio_format}",
                                ),
                                args,
                            )
                            progress.advance(asset_task)

                    if not args.no_images:
                        # Images for short definitions
                        for i, sd in enumerate(db.get_shortdefs(uuid), 1):
                            progress.update(
                                asset_task,
                                description=f"[green]  └─ {w.word} (image: def {i})",
                            )
                            generate_image(
                                client,
                                sd.definition,
                                os.path.join(
                                    args.outdir,
                                    f"image_{sd.uuid}_{sd.id}.{image_format}",
                                ),
                                args,
                            )
                            progress.advance(asset_task)

                progress.remove_task(asset_task)
                progress.advance(main_task)
    else:
        # No progress bars for verbosity 0 or 2
        for w in words:
            if args.verbosity >= 2:
                print(f"Processing word: {w.word}")

            uuids = db.get_uuids(w.word)
            for uuid in uuids:
                if not args.no_audio:
                    # synthesize the word itself
                    generate_audio(
                        client,
                        w.word,
                        os.path.join(args.outdir, f"word_{uuid}_0.{audio_format}"),
                        args,
                    )

                    # synthesize each short definition for this sense
                    for sd in db.get_shortdefs(uuid):
                        generate_audio(
                            client,
                            sd.definition,
                            os.path.join(
                                args.outdir,
                                f"shortdef_{sd.uuid}_{sd.id}.{audio_format}",
                            ),
                            args,
                        )

                if not args.no_images:
                    # Images for short definitions
                    for sd in db.get_shortdefs(uuid):
                        generate_image(
                            client,
                            sd.definition,
                            os.path.join(
                                args.outdir, f"image_{sd.uuid}_{sd.id}.{image_format}"
                            ),
                            args,
                        )

    db.close()

    if args.verbosity >= 1:
        print("Processing complete!")


if __name__ == "__main__":
    main()
