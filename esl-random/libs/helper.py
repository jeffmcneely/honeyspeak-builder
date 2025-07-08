import boto3
from botocore.exceptions import ClientError
import json
import tempfile
from datetime import datetime

def get_aws_secret(session, secret_name, region_name=None) -> dict:
    """
    Fetch a secret value from AWS Secrets Manager.
    Returns the secret string for the given secret name.
    """

    if region_name is None:
        # Default to us-east-1 if not specified
        region_name = 'us-east-1'

    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        raise Exception(f"Unable to fetch secret {secret_name}: {e}")

    if 'SecretString' in get_secret_value_response:
        return json.loads(get_secret_value_response['SecretString'])
    else:
        # If the secret is binary
        import base64
        return json.loads(base64.b64decode(get_secret_value_response['SecretBinary']))

def upload_file_to_s3(session, file_path, bucket_name, object_name=None) -> bool:
    """
    Upload a file to an S3 bucket.
    :param session: boto3 session
    :param file_path: Path to the file to upload
    :param bucket_name: S3 bucket name
    :param object_name: S3 object name. If not specified, file_path's basename is used.
    :return: True if file was uploaded, else False
    """
    import os
    s3 = session.client('s3')
    if object_name is None:
        object_name = os.path.basename(file_path)
    try:
        s3.upload_file(file_path, bucket_name, object_name)
        return True
    except Exception as e:
        print(f"Error uploading {file_path} to S3: {e}")
        return False

def list_json_files_in_s3(bucket_name, prefix=None) -> list:
    """
    List all JSON files in the specified S3 bucket (optionally under a prefix).
    Returns a list of file keys ending with .json.
    """
    s3 = boto3.client('s3')
    kwargs = {'Bucket': bucket_name}
    if prefix:
        kwargs['Prefix'] = prefix
    json_files = []
    while True:
        response = s3.list_objects_v2(**kwargs)
        contents = response.get('Contents', [])
        for obj in contents:
            key = obj['Key']
            if key.endswith('.json'):
                json_files.append(key)
        if response.get('IsTruncated'):
            kwargs['ContinuationToken'] = response['NextContinuationToken']
        else:
            break
    return json_files

def download_file_from_s3(session, bucket_name: str, object_name: str, file_path: str) -> bool:
    """
    Download a file from an S3 bucket.
    :param session: boto3 session
    :param bucket_name: S3 bucket name
    :param object_name: S3 object key to download
    :param file_path: Local path to save the downloaded file
    :return: True if file was downloaded, else False
    """
    s3 = session.client('s3')
    try:
        s3.download_file(bucket_name, object_name, file_path)
        return True
    except Exception as e:
        print(f"Error downloading {object_name} from S3: {e}")
        return False

def get_api_usage(session, bucket_name: str, api_type: str) -> int:
    """
    Get the API usage count for a specific API type from S3.
    """
    try:
        if download_file_from_s3(session, bucket_name, f"api_usage/{api_type}.json", "/tmp/api_usage.json"):
            with open("/tmp/api_usage.json", "r") as f:
                api_usage = json.load(f)
                now = datetime.now()
                if api_type == "dictionary":
                    interval = f"{now.year}{now.month:02d}{now.day:02d}"
                elif api_type == "image":
                    interval = f"{now.year}{now.month:02d}"
                else:
                    raise ValueError(f"Unsupported API type: {api_type}")
            return api_usage.get(interval, 0)
        else:
            return 0
    except Exception as e:
        print(f"Error fetching API usage for {api_type}: {e}")
        return 0
def update_api_usage(session, bucket_name: str, api_type: str, usage_count: int) -> bool:
    """
    Update the API usage count for a specific API type in S3.
    """
    now = datetime.now()
    if api_type == "dictionary":
        interval = f"{now.year}{now.month:02d}{now.day:02d}"
    elif api_type == "image":
        interval = f"{now.year}{now.month:02d}"
    else:
        raise ValueError(f"Unsupported API type: {api_type}")
    try:
        api_usage = {}
        if download_file_from_s3(session, bucket_name, f"api_usage/{api_type}.json", "/tmp/api_usage.json"):
            with open("/tmp/api_usage.json", "r") as tmp_file:
                api_usage = json.load(tmp_file)
                now = datetime.now()
        api_usage[interval] = usage_count
        with open("/tmp/api_usage.json", "w") as tmp_file:
            json.dump(api_usage, tmp_file)
            tmp_file_path = tmp_file.name
        upload_file_to_s3(session, tmp_file_path, bucket_name, f"api_usage/{api_type}.json")    
        return True
    except Exception as e:
        print(f"Error updating API usage for {api_type}: {e}")
        return False

