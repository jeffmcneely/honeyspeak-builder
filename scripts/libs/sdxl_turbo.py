"""
Helpers for interacting with a ComfyUI instance for the sdxl_turbo workflow.

This module encapsulates loading a JSON workflow template, injecting the
prompt/seed, posting to a ComfyUI server, and saving the resulting image
to disk. It mirrors the previous behavior embedded in
`scripts/libs/asset_ops.py` but is written defensively so a missing
template or an unexpected response won't crash the caller.
"""

import os
import json
import base64
import secrets
import logging
import time
from typing import Dict, Optional
import re

import requests

logger = logging.getLogger(__name__)



def poll_comfyui_history(prompt_id, base_url=None) -> dict:
    comfy_server = os.getenv("COMFYUI_SERVER")
    if base_url is None:
        base_url = f"{comfy_server}/history/"
    url = base_url + str(prompt_id)
    delay = 1
    for i in range(600):
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except Exception:
                    data = resp.text
                    logger.debug(f"Error parsing JSON response: {data}")
                if data != {}:
                    retval = data[prompt_id]["outputs"]
                    logger.debug(
                        f"History for {prompt_id} received after {i+1} seconds."
                    )
                    return retval
            else:
                logger.debug(f"Non-200 response: {resp.status_code}")
        except Exception as e:
            logger.debug(f"Error polling history: {e}")
        time.sleep(delay)
        delay = min(delay * 2, 10)  # Exponential backoff, max 10 seconds
    logger.debug(f"Timeout: No history for {prompt_id} after 600 seconds.")
    return None


def generate_image_via_comfy(
    word: str,
    prompt: str,
    text: str,
    output_path: str,
    cfg_filename: str = "image-sdxl_turbo.json",
    timeout: int = 60,
) -> Dict[str, Optional[str]]:
    """Run a ComfyUI workflow to generate an image and save it to output_path.

    Args:
        prompt: Full formatted prompt to inject into the workflow.
        text: Short text (raw definition) that some templates may expect.
        output_path: Destination file path for the generated image.
        cfg_filename: Workflow JSON filename located next to this module.
        timeout: HTTP request timeout in seconds.

    Returns:
        Dict containing 'status' and 'file' keys (and 'error' on failure).
    """
    text = re.sub(r"\{b\}.+?\{/b\}", "", text)
    text = re.sub(r"\{bc\}", "", text)
    text = re.sub(r"\{inf\}.+?\{/inf\}", "", text)
    text = re.sub(r"\{it\}.+?\{/it\}", "", text)
    text = re.sub(r"\{i{ldquo}\}", "", text)
    text = re.sub(r"\{i{ldquo}\}", "", text)
    text = re.sub(r"\{sd\}.+?\{/sd\}", "", text)
    text = re.sub(r"\{sup\}.+?\{/sup\}", "", text)

    # prompt = re.sub(r"\{gloss\}.+?\{/sup\}", "", prompt)
    # prompt = re.sub(r"\{parahw\}.+?\{/sup\}", "", prompt)
    # prompt = re.sub(r"\{phrase\}.+?\{/phrase\}", "", prompt)
    # prompt = re.sub(r"\{qword\}.+?\{/qword\}", "", prompt)
    # prompt = re.sub(r"\{wi\}.+?\{/wi\}", "", prompt)

    # prompt = re.sub(r"\{dx\}.+?\{/wi\}", "", prompt)
    # prompt = re.sub(r"\{dx_def\}.+?\{/wi\}", "", prompt)
    # prompt = re.sub(r"\{dx_ety\}.+?\{/wi\}", "", prompt)
    # prompt = re.sub(r"\{ma\}.+?\{/wi\}", "", prompt)

    # prompt = re.sub(r"\{ma\}.+?\{/wi\}", "", prompt)
    # prompt = re.sub(r"\{ma\}.+?\{/wi\}", "", prompt)
    # prompt = re.sub(r"\{ma\}.+?\{/wi\}", "", prompt)
    # prompt = re.sub(r"\{ma\}.+?\{/wi\}", "", prompt)
    # prompt = re.sub(r"\{ma\}.+?\{/wi\}", "", prompt)
    # prompt = re.sub(r"\{ma\}.+?\{/wi\}", "", prompt)
    # prompt = re.sub(r"\{ma\}.+?\{/wi\}", "", prompt)
    # prompt = re.sub(r"\{ma\}.+?\{/wi\}", "", prompt)
    # prompt = re.sub(r"\{ma\}.+?\{/wi\}", "", prompt)
    # prompt = re.sub(r"\{ma\}.+?\{/wi\}", "", prompt)
    # prompt = re.sub(r"\{ma\}.+?\{/wi\}", "", prompt)
    # prompt = re.sub(r"\{ma\}.+?\{/wi\}", "", prompt)
    # prompt = re.sub(r"\{ma\}.+?\{/wi\}", "", prompt)
    # prompt = re.sub(r"\{ma\}.+?\{/wi\}", "", prompt)
    # prompt = re.sub(r"\{ma\}.+?\{/wi\}", "", prompt)
    # prompt = re.sub(r"\{ma\}.+?\{/wi\}", "", prompt)

    comfy_server = os.getenv("COMFYUI_SERVER")
    if not comfy_server:
        logger.error("COMFYUI_SERVER not configured; cannot use sdxl_turbo model")
        return {"status": "error", "file": None, "error": "COMFYUI_SERVER not configured"}

    cfg_path = os.path.join(os.path.dirname(__file__), cfg_filename)
    if not os.path.exists(cfg_path):
        logger.error("ComfyUI workflow template not found: %s", cfg_path)
        return {"status": "error", "file": None, "error": "missing workflow template"}

    try:
        with open(cfg_path, "r") as fh:
            payload = json.load(fh)
        safe_text = text.replace('"', '\\"').replace("\n", " ").replace("'", "\\'")
        safe_word = word.replace('"', '\\"').replace("\n", " ").replace("'", "\\'")
        # Try best-effort injections depending on template shape.
        try:
            # Some templates use numeric-string node keys like '6' and '13'.
            node6 = payload.get("6") if isinstance(payload, dict) else None
            if isinstance(node6, dict) and isinstance(node6.get("inputs"), dict):
                existing = node6["inputs"].get("text", "")
                payload["6"]["inputs"]["text"] = f"{safe_word}. {safe_text}. {existing}"

            node13 = payload.get("13") if isinstance(payload, dict) else None
            if isinstance(node13, dict) and isinstance(node13.get("inputs"), dict):
                payload["13"]["inputs"]["noise_seed"] = secrets.randbits(64)
        except Exception:
            # Non-fatal; continue and attempt other injection strategies.
            logger.debug("Node-specific prompt injection failed; falling back to generic injection")

        payload = {"prompt": payload}
        logger.info(f"Posting sdxl_turbo payload to ComfyUI at {comfy_server}\n{payload}")
        try:
            resp = requests.post(f"{comfy_server}/prompt", data=json.dumps(payload).encode("utf-8"), timeout=timeout)
            if resp.ok:
                logger.info("ComfyUI accepted prompt successfully.")
            else:
                logger.error(f"ComfyUI server returned HTTP {resp.status_code}: {resp.text}")
                return {"status": "error", "file": None, "error": f"ComfyUI HTTP {resp.status_code}"}
        except Exception as e:
            logger.exception(f"Error posting to ComfyUI server: {comfy_server}/prompt\n{e}")
            return {"status": "error", "file": None, "error": str(e)}
        try:
            prompt_id = resp.json().get("prompt_id")
            poll_start_time = time.time()
            logger.info(f"ComfyUI prompt accepted, prompt_id: {prompt_id}")
            poll_response = poll_comfyui_history(prompt_id)
            poll_elapsed = time.time() - poll_start_time
            # Check if polling was successful
            if poll_response is None:
                logger.error(f"Failed to get ComfyUI history for prompt_id: {prompt_id}")
                # Don't delete message on error, let it retry
#                apply_backoff()
#                continue
            
            logger.debug(f"Poll response: {poll_response}")
            logger.info(f"ComfyUI polling completed in {poll_elapsed:.2f} seconds")
            
            # Check if expected output exists
            if "27" not in poll_response or "images" not in poll_response["27"] or not poll_response["27"]["images"]:
                logger.error(f"ComfyUI output from job {prompt_id} missing expected image data, contained:\n{poll_response}")
            image_filename = poll_response["27"]["images"][0]["filename"]
#            ext = os.path.splitext(image_filename)[1][1:]
            image_path = os.path.join(os.getenv("COMFY_OUTPUT_FOLDER"), image_filename)

            # Copy the generated image to the desired output_path
            try:
                with open(image_path, "rb") as src, open(output_path, "wb") as dst:
                    dst.write(src.read())
                logger.info(f"Copied image from {image_path} to {output_path}")
                return {"status": "success", "file": output_path}
            except Exception as copy_err:
                logger.error(f"Failed to copy image from {image_path} to {output_path}: {copy_err}")
                return {"status": "error", "file": None, "error": f"Failed to copy image: {copy_err}"}

        except Exception:
            # Not JSON / no images in JSON — fall through to binary handling
            pass

        # If response is binary image data
        ctype = resp.headers.get("Content-Type", "")
        if ctype and ctype.startswith("image/"):
            with open(output_path, "wb") as f:
                f.write(resp.content)
            logger.info("Saved binary image from ComfyUI to: %s", output_path)
            return {"status": "success", "file": output_path}

        logger.error("Unknown ComfyUI response: %s %s %s", resp.status_code, resp.headers.get("Content-Type"), resp.json())
        return {"status": "error", "file": None, "error": "Unknown ComfyUI response"}

    except Exception as e:
        logger.exception("Error calling ComfyUI for %s: %s", output_path, e)
        return {"status": "error", "file": None, "error": str(e)}
