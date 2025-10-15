import argparse
from argparse import Namespace
import os
from pathlib import Path
import base64
from openai import OpenAI
from openai._exceptions import OpenAIError
from libs.sqlite_dictionary import SQLiteDictionary
from rich.progress import Progress, track
from dotenv import load_dotenv
import re


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


def strip_tags(text: str) -> str:
    """
    Remove anything between curly braces {} including the braces themselves.
    """
    return re.sub(r"\{.*?\}", "", text)


def generate_audio(client: OpenAI, text: str, fname: str, args: Namespace) -> None:
    """
    Generate audio using audio.speech. Tries streaming first, falls back to non-streaming if unavailable.
    """

    if os.path.isfile(fname):
        if args.verbosity >= 2:
            print(f"[synth] Skipping existing file: {fname}")
        return

    text = strip_tags(text)
    if args.dryrun:
        if args.verbosity >= 1:
            print(f"[DRY RUN] Would generate audio: {fname} = '{text[:50]}...'")
        return

    if args.verbosity >= 2:
        print(f"[synth] Generating audio for {fname}: '{text[:50]}...'")

    try:
        # Preferred: streaming writer (efficient for larger outputs)
        with client.audio.speech.with_streaming_response.create(
            model=args.audio_model,
            voice=args.audio_voice,
            input=text,
            response_format=audio_format,
        ) as resp:
            resp.stream_to_file(str(fname))
        if args.verbosity >= 2:
            print(f"[synth] Successfully created: {fname}")
        return
    except Exception as e:
        # Fallback to non-streaming API or models that don't support streaming in current SDK
        try:
            resp = client.audio.speech.create(
                model=args.audio_model,
                voice=args.audio_voice,
                input=text,
                response_format=audio_format,
            )
            audio_bytes = resp.read() if hasattr(resp, "read") else resp.content
            with open(fname, "wb") as f:
                f.write(audio_bytes)
            if args.verbosity >= 2:
                print(f"[synth] Successfully created (fallback): {fname}")
            return
        except OpenAIError as oe:
            if args.verbosity >= 1:
                print(f"ERR {args.audio_model}/{args.audio_voice}: {oe}")
        except Exception as ee:
            if args.verbosity >= 1:
                print(f"ERR {args.audio_model}/{args.audio_voice}: {ee}")


def generate_image(
    client: OpenAI,
    text: str,
    fname: str,
    args: Namespace,
) -> None:
    """
    Generate a vertical image using OpenAI Images API.
    - assetgroup: logical group (e.g., 'word' or 'shortdef') used in filename
    - text: prompt/description to visualize
    - id: sequence id for the asset within the group
    - uuid: sense UUID for consistent naming
    - model: image model (e.g., 'gpt-image-1')
    - size: image size (use a vertical dimension like '1024x1792')
    - dryrun/verbosity: execution controls similar to synth()
    """

    # Must be one of 1024x1024, 1536x1024 (landscape), 1024x1536 (portrait), or auto (default value) for gpt-image-1
    # one of 256x256, 512x512, or 1024x1024 for dall-e-2
    # one of 1024x1024, 1792x1024, or 1024x1792 for dall-e-3.

    size = "1024x1024"
    aspect_words = "square illustration (1:1 aspect)"
    match args.image_model:
        case "gpt-image-1":
            match args.image_size:
                case "vertical":
                    size = "1024x1536"
                    aspect_words = "vertical illustration (9:16 aspect) "
                case "horizontal":
                    size = "1536x1024"
                    aspect_words = "horizontal illustration (16:9 aspect) "

        case "dall-e-3":
            match args.image_size:
                case "vertical":
                    size = "1024x1792"
                    aspect_words = "vertical illustration (4:7 aspect) "
                case "horizontal":
                    size = "1792x1024"
                    aspect_words = "horizontal illustration (7:4 aspect) "

    if os.path.isfile(fname):
        if args.verbosity >= 2:
            print(f"[generate_image] Skipping existing file: {fname}")
        return

    text = strip_tags(text)
    if args.dryrun:
        if args.verbosity >= 1:
            preview = (text or "").strip().replace("\n", " ")
            print(f"[DRY RUN] Would generate image: {fname} = '{preview[:60]}...'")
        return

    # Encourage vertical composition and clarity in the prompt

    prompt = (
        f"Create a clean, high-contrast {aspect_words}"
        f"that represents: {text}. No text, centered subject, solid background."
    )

    if args.verbosity >= 2:
        print(
            f"[generate_image] Creating image for {fname} (size={size}, model={args.image_model})"
        )

    try:
        result = client.images.generate(
            model=args.image_model,
            prompt=prompt,
            size=size,
        )
        # OpenAI Images API returns base64 JSON in data[0].b64_json
        b64 = result.data[0].b64_json if hasattr(result.data[0], "b64_json") else None
        if not b64:
            raise ValueError("No image data returned from API")
        with open(fname, "wb") as f:
            f.write(base64.b64decode(b64))
        if args.verbosity >= 2:
            print(f"[generate_image] Wrote {fname}")
    except OpenAIError as oe:
        if args.verbosity >= 1:
            print(f"[generate_image] OpenAI error: {oe}")
    except Exception as e:
        if args.verbosity >= 1:
            print(f"[generate_image] Error: {e}")


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

    args = parser.parse_args()

    load_dotenv()

    if args.verbosity >= 1:
        print(f"Using model={args.audio_model} voice={args.audio_voice}")
        if args.verbosity >= 2:
            print(f"Audio format={audio_format}, outdir={args.outdir}")
        if args.dryrun:
            print("[DRY RUN MODE] - No files will be created")

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
