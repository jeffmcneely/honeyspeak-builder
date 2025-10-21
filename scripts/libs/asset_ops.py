"""
Asset generation operations library - granular functions for audio and image generation.
All functions are designed to be called from Celery tasks.
"""

import os
import base64
import json
import secrets
import requests
import logging
from typing import Optional, Dict
from openai import OpenAI
from openai._exceptions import BadRequestError, OpenAIError
from .openai_helpers import (
    strip_tags, log_400_error, call_openai_audio_streaming, 
    call_openai_audio_non_streaming, call_openai_image,
    audio_format, image_format
)

logger = logging.getLogger(__name__)


def generate_word_audio(
    word: str,
    uuid: str,
    output_dir: str,
    audio_model: str = "gpt-4o-mini-tts",
    audio_voice: str = "alloy",
    api_key: Optional[str] = None
) -> Dict[str, str]:
    """
    Generate audio file for a word.
    
    Args:
        word: The word text
        uuid: Word UUID
        output_dir: Output directory path
        audio_model: OpenAI TTS model
        audio_voice: Voice name
        api_key: OpenAI API key
        
    Returns:
        Dict with 'status' and 'file' keys
    """
    fname = os.path.join(output_dir, f"word_{uuid}_0.{audio_format}")
    
    if os.path.isfile(fname):
        logger.info(f"Skipping existing file: {fname}")
        return {"status": "skipped", "file": fname}
    
    text = strip_tags(word)
    if len(text) < 1:
        logger.warning(f"Text too short for audio: {fname}")
        return {"status": "skipped", "file": fname, "reason": "text_too_short"}
    
    logger.info(f"Generating audio for {fname}: '{text}'")
    
    client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
    
    try:
        call_openai_audio_streaming(client, audio_model, audio_voice, text, fname)
        logger.info(f"Successfully created: {fname}")
        return {"status": "success", "file": fname}
    except BadRequestError as bre:
        log_400_error(bre, text, f"word audio (model={audio_model}, voice={audio_voice})")
        logger.error(f"400 error for {fname}: {bre}")
        return {"status": "error", "file": fname, "error": f"400: {str(bre)}"}
    except Exception as e:
        try:
            audio_bytes = call_openai_audio_non_streaming(client, audio_model, audio_voice, text)
            with open(fname, "wb") as f:
                f.write(audio_bytes)
            logger.info(f"Successfully created (fallback): {fname}")
            return {"status": "success", "file": fname}
        except Exception as ee:
            logger.error(f"Error generating audio for {fname}: {ee}")
            return {"status": "error", "file": fname, "error": str(ee)}


def generate_definition_audio(
    definition: str,
    uuid: str,
    def_id: int,
    output_dir: str,
    audio_model: str = "gpt-4o-mini-tts",
    audio_voice: str = "alloy",
    api_key: Optional[str] = None
) -> Dict[str, str]:
    """
    Generate audio file for a definition.
    
    Args:
        definition: Definition text
        uuid: Word UUID
        def_id: Definition ID
        output_dir: Output directory path
        audio_model: OpenAI TTS model
        audio_voice: Voice name
        api_key: OpenAI API key
        
    Returns:
        Dict with 'status' and 'file' keys
    """
    fname = os.path.join(output_dir, f"shortdef_{uuid}_{def_id}.{audio_format}")
    
    if os.path.isfile(fname):
        logger.info(f"Skipping existing file: {fname}")
        return {"status": "skipped", "file": fname}
    
    text = strip_tags(definition)
    if len(text) < 10:
        logger.warning(f"Text too short for audio: {fname}")
        return {"status": "skipped", "file": fname, "reason": "text_too_short"}
    
    logger.info(f"Generating audio for {fname}: '{text[:50]}...'")
    
    client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
    
    try:
        call_openai_audio_streaming(client, audio_model, audio_voice, text, fname)
        logger.info(f"Successfully created: {fname}")
        return {"status": "success", "file": fname}
    except BadRequestError as bre:
        log_400_error(bre, text, f"definition audio (model={audio_model}, voice={audio_voice})")
        logger.error(f"400 error for {fname}: {bre}")
        return {"status": "error", "file": fname, "error": f"400: {str(bre)}"}
    except Exception as e:
        try:
            audio_bytes = call_openai_audio_non_streaming(client, audio_model, audio_voice, text)
            with open(fname, "wb") as f:
                f.write(audio_bytes)
            logger.info(f"Successfully created (fallback): {fname}")
            return {"status": "success", "file": fname}
        except Exception as ee:
            logger.error(f"Error generating audio for {fname}: {ee}")
            return {"status": "error", "file": fname, "error": str(ee)}


def generate_definition_image(
    definition: str,
    uuid: str,
    def_id: int,
    output_dir: str,
    image_model: str = "gpt-image-1",
    image_size: str = "vertical",
    api_key: Optional[str] = None
) -> Dict[str, str]:
    """
    Generate image file for a definition.
    
    Args:
        definition: Definition text
        uuid: Word UUID
        def_id: Definition ID
        output_dir: Output directory path
        image_model: OpenAI image model
        image_size: Size specification (square/vertical/horizontal)
        api_key: OpenAI API key
        
    Returns:
        Dict with 'status' and 'file' keys
    """
    fname = os.path.join(output_dir, f"image_{uuid}_{def_id}.{image_format}")
    
    if os.path.isfile(fname):
        logger.info(f"Skipping existing file: {fname}")
        return {"status": "skipped", "file": fname}
    
    text = strip_tags(definition)
    if len(text) < 10:
        logger.warning(f"Text too short for image: {fname}")
        return {"status": "skipped", "file": fname, "reason": "text_too_short"}
    
    # Determine size and aspect ratio
    size = "1024x1024"
    aspect_words = "square illustration (1:1 aspect)"
    
    if image_model == "gpt-image-1":
        if image_size == "vertical":
            size = "1024x1536"
            aspect_words = "vertical illustration (9:16 aspect)"
        elif image_size == "horizontal":
            size = "1536x1024"
            aspect_words = "horizontal illustration (16:9 aspect)"
    elif image_model == "dall-e-3":
        if image_size == "vertical":
            size = "1024x1792"
            aspect_words = "vertical illustration (4:7 aspect)"
        elif image_size == "horizontal":
            size = "1792x1024"
            aspect_words = "horizontal illustration (7:4 aspect)"
    
    prompt = (
        f"Create a clean, high-contrast educational non-offensive {aspect_words} "
        f"that represents: {text}. No text, centered subject, solid background. "
        f"The image should not be sexual, suggestive, or depict nudity in any form."
    )
    
    logger.info(f"Generating image for {fname} (size={size}, model={image_model})")
    
    # Special-case: send to ComfyUI server for the 'sdxl_turbo' workflow
    if image_model == "sdxl_turbo":
        comfy_server = os.getenv("COMFYUI_SERVER")
        if not comfy_server:
            logger.error("COMFYUI_SERVER not configured; cannot use sdxl_turbo model")
            return {"status": "error", "file": None, "error": "COMFYUI_SERVER not configured"}

        # Load the ComfyUI workflow payload and inject the prompt
        try:
            cfg_path = os.path.join(os.path.dirname(__file__), "image-sdxl_turbo.json")
            with open(cfg_path, "r") as fh:
                payload = json.load(fh)

            # If payload supplies a prompt_template, use it; otherwise try to
            # inject into nodes that have 'inputs' -> 'text'.
            payload["6"]["inputs"]["text"] = text + payload["6"]["inputs"]["text"]
            payload["13"]["inputs"]["noise_seed"] = secrets.randbits(64)
            if isinstance(payload, dict) and payload.get("prompt_template"):
                payload["prompt"] = payload["prompt_template"].format(prompt=prompt)
            else:
                # Walk through nodes and replace text inputs where present
                nodes = payload.get("nodes") if isinstance(payload, dict) else None
                if nodes and isinstance(nodes, dict):
                    for node in nodes.values():
                        try:
                            if isinstance(node, dict) and "inputs" in node and "text" in node["inputs"]:
                                node["inputs"]["text"] = prompt
                        except Exception:
                            continue

            # POST payload to COMFYUI_SERVER (COMFYUI_SERVER should be a full URL)
            logger.info(f"Posting sdxl_turbo payload to ComfyUI at {comfy_server}")
            resp = requests.post(comfy_server, json=payload, timeout=60)
            if not resp.ok:
                logger.error(f"ComfyUI server returned HTTP {resp.status_code}: {resp.text}")
                return {"status": "error", "file": None, "error": f"ComfyUI HTTP {resp.status_code}"}

            # If JSON response contains base64 images (common shape: {'images': ['...base64...']})
            try:
                data = resp.json()
                if isinstance(data, dict) and data.get("images") and isinstance(data["images"], list):
                    b64 = data["images"][0]
                    with open(fname, "wb") as f:
                        f.write(base64.b64decode(b64))
                    logger.info(f"Saved image from ComfyUI to: {fname}")
                    return {"status": "success", "file": fname}
            except Exception:
                # Not JSON / not a JSON image response; fall back to binary
                pass

            # If response is binary image data
            ctype = resp.headers.get("Content-Type", "")
            if ctype.startswith("image/"):
                with open(fname, "wb") as f:
                    f.write(resp.content)
                logger.info(f"Saved binary image from ComfyUI to: {fname}")
                return {"status": "success", "file": fname}

            # Unknown response
            logger.error(f"Unknown ComfyUI response: {resp.status_code} {resp.headers.get('Content-Type')}")
            return {"status": "error", "file": None, "error": "Unknown ComfyUI response"}
        except Exception as e:
            logger.error(f"Error calling ComfyUI for {fname}: {e}")
            return {"status": "error", "file": None, "error": str(e)}

    # Default: use OpenAI image API
    client = OpenAI(api_key=api_key or os.getenv("OPENAI_API_KEY"))
    try:
        result = call_openai_image(client, image_model, prompt, size)
        b64 = result.data[0].b64_json if hasattr(result.data[0], "b64_json") else None
        if not b64:
            raise ValueError("No image data returned from API")

        with open(fname, "wb") as f:
            f.write(base64.b64decode(b64))

        logger.info(f"Successfully created image: {fname}")
        return {"status": "success", "file": fname}
    except BadRequestError as bre:
        log_400_error(bre, text, f"image generation (model={image_model}, size={image_size})")
        logger.error(f"400 error for {fname}: {bre}")
        return {"status": "error", "file": fname, "error": f"400: {str(bre)}"}
    except Exception as e:
        logger.error(f"Error generating image for {fname}: {e}")
        return {"status": "error", "file": fname, "error": str(e)}
