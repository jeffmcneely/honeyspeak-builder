# /opt/comfyui/custom_nodes/xtts_nodes.py
# pylance: ignore[reportMissingImports]
import os, time
from TTS.api import TTS
import folder_paths

#
# Node 1: XTTSLoader
#
class XTTSLoader:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                # Recommended default for XTTS v2 from Coqui
                "model_name": (
                    "STRING",
                    {"default": "tts_models/multilingual/multi-dataset/xtts_v2"},
                ),
                # Optional: load from a local dir you already downloaded
                "local_path": (
                    "STRING",
                    {"default": ""},
                ),
                "use_gpu": ("BOOLEAN", {"default": True}),
            }
        }

    RETURN_TYPES = ("XTTS_MODEL",)
    RETURN_NAMES = ("tts_model",)
    FUNCTION = "load"
    CATEGORY = "XTTS"

    def load(self, model_name, local_path, use_gpu):
        """
        Priority:
        - if local_path is non-empty, try to load from disk
        - else load by model_name from hub
        """
#        if local_path.strip():
            # expect local_path to point at a folder that has a full coqui model dump
#            tts = TTS(model_path=local_path.strip(), gpu=use_gpu)
#        else:
#        tts = TTS(model_name=model_name.strip(), gpu=use_gpu)
        tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2", gpu=True)

        return (tts,)


#
# Node 2: XTTSGenerateToFile
#
class XTTSGenerateToFile:
    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "tts_model": ("XTTS_MODEL",),
                "text": (
                    "STRING",
                    {"default": "Hello from XTTS."},
                ),
                # path to reference voice wav for cloning, can be empty
                "speaker_wav": (
                    "STRING",
                    {"default": ""},
                ),
                "language": (
                    "STRING",
                    {"default": "en"},
                ),
                "filename_prefix": (
                    "STRING",
                    {"default": "xtts"},
                ),
            }
        }

    RETURN_TYPES = ("AUDIO",)
    RETURN_NAMES = ("audio",)
    FUNCTION = "generate_to_file"
    CATEGORY = "XTTS"
    OUTPUT_NODE = True

    def generate_to_file(self, tts_model, text, speaker_wav, language, filename_prefix):
        import json
        
        outdir = folder_paths.get_output_directory()
        os.makedirs(outdir, exist_ok=True)

        ts = int(time.time())
        filename = f"{filename_prefix}_{ts}.wav"
        full_path = os.path.join(outdir, filename)

        # Write audio to disk using the model's built-in writer
        tts_model.tts_to_file(
            text=text,
            speaker_wav=speaker_wav or None,
            language=language,
            file_path=full_path,
        )

        # Return in ComfyUI audio format - similar to how LoadAudio nodes work
        # ComfyUI expects audio outputs to be in a specific format that includes waveform data
        # For now, we'll return metadata that can be picked up by the history endpoint
        result = {
            "filename": filename,
            "subfolder": "",
            "type": "output"
        }
        
        # Return as a list wrapped in a dict to match ComfyUI's audio output format
        return {"ui": {"audio": [result]}}


NODE_CLASS_MAPPINGS = {
    "XTTSLoader": XTTSLoader,
    "XTTSGenerateToFile": XTTSGenerateToFile,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "XTTSLoader": "XTTS • Load Model",
    "XTTSGenerateToFile": "XTTS • Generate To File",
}