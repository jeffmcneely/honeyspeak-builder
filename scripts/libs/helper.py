import boto3
from botocore.exceptions import ClientError
import json
import tempfile
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


def print_json_rich(data):
    """
    Pretty-print a Python object as JSON using the rich library.
    :param data: The Python object (dict, list, etc.) to print
    """
    try:
        from rich import print_json
        import json
        print_json(json.dumps(data))
    except ImportError:
        print("[rich not installed]", json.dumps(data, indent=2))
    except Exception as e:
        print(f"Error printing JSON with rich: {e}")



def upload_file_to_s3(s3, file_path, bucket_name, object_name=None) -> bool:
    """
    Upload a file to an S3 bucket.
    :param session: boto3 session
    :param file_path: Path to the file to upload
    :param bucket_name: S3 bucket name
    :param object_name: S3 object name. If not specified, file_path's basename is used.
    :return: True if file was uploaded, else False
    """
    import os

    if object_name is None:
        object_name = os.path.basename(file_path)
    try:
        s3.upload_file(file_path, bucket_name, object_name)
        return True
    except Exception as e:
        print(f"Error uploading {file_path} to S3: {e}")
        return False


def list_json_files_in_s3(s3, bucket_name: str, prefix=None) -> list:
    """
    List all JSON files in the specified S3 bucket (optionally under a prefix).
    Returns a list of file keys ending with .json.
    """
    kwargs = {"Bucket": bucket_name}
    if prefix:
        kwargs["Prefix"] = prefix
    json_files = []
    while True:
        response = s3.list_objects_v2(**kwargs)
        contents = response.get("Contents", [])
        for obj in contents:
            key = obj["Key"]
            if key.endswith(".json"):
                json_files.append(key)
        if response.get("IsTruncated"):
            kwargs["ContinuationToken"] = response["NextContinuationToken"]
        else:
            break
    return json_files


def download_file_from_s3(
    s3, bucket_name: str, object_name: str, file_path: str
) -> bool:
    """
    Download a file from an S3 bucket.
    :param s3: boto3 S3 client
    :param bucket_name: S3 bucket name
    :param object_name: S3 object key to download
    :param file_path: Local path to save the downloaded file
    :return: True if file was downloaded, else False
    """
    try:
        s3.download_file(bucket_name, object_name, file_path)
        return True
    except Exception as e:
        print(f"Error downloading {object_name} from S3: {e}")
        return False


# API usage tracking removed - now handled locally in dictionary.py


def s3_file_exists(s3, bucket_name: str, object_name: str) -> bool:
    """
    Check if a file exists in an S3 bucket.
    :param s3: boto3 S3 client
    :param bucket_name: S3 bucket name
    :param object_name: S3 object key to check
    :return: True if the file exists, else False
    """
    try:
        s3.head_object(Bucket=bucket_name, Key=object_name)
        return True
    except s3.exceptions.ClientError as e:
        if e.response["Error"]["Code"] == "404":
            return False
        else:
            print(f"Error checking existence of {object_name} in S3: {e}")
            return False


def polly_generate_audio(session, text: str, voice_id: str, engine: str = "standard", output_format: str = "mp3", file_path: str = "/tmp/polly_output.mp3") -> bool:
    """
    Generate an audio file from text using AWS Polly.
    :param session: boto3 session
    :param text: Text to synthesize
    :param voice_id: Polly voice ID (e.g., 'Joanna')
    :param output_format: Audio format (default 'mp3')
    :param file_path: Local path to save the audio file
    :return: True if successful, else False
    """
    polly = session.client("polly")
    try:
        response = polly.synthesize_speech(
            Text=text,
            OutputFormat=output_format,
            engine=engine,
            VoiceId=voice_id
        )
        with open(file_path, "wb") as f:
            f.write(response["AudioStream"].read())
        return True
    except Exception as e:
        print(f"Error generating audio with Polly: {e}")
        return False
