import json
import boto3


def lambda_handler(event, context):
    # TODO implement
    return {
        'statusCode': 200,
        'body': json.dumps('Hello from Lambda!')
    }


def list_json_files_in_s3(bucket_name, prefix=None):
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


def get_aws_secret(secret_name, region_name=None):
    """
    Fetch a secret value from AWS Secrets Manager.
    Returns the secret string for the given secret name.
    """
    import boto3
    from botocore.exceptions import ClientError

    if region_name is None:
        # Default to us-east-1 if not specified
        region_name = 'us-east-1'

    session = boto3.session.Session()
    client = session.client(
        service_name='secretsmanager',
        region_name=region_name
    )

    try:
        get_secret_value_response = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        raise Exception(f"Unable to fetch secret {secret_name}: {e}")

    if 'SecretString' in get_secret_value_response:
        return get_secret_value_response['SecretString']
    else:
        # If the secret is binary
        import base64
        return base64.b64decode(get_secret_value_response['SecretBinary'])

def build_link(prs: dict) -> str:
    """
    Build a link to the audio pronunciation file based on the provided parameters.
    """

    language_code = "en"
    country_code = "us"
    format = "mp3"
    "link" = ""
    if "sound" in prs and "audio" in prs["sound"]:
        audio = prs["sound"]["audio"]
        if audio.startswith("bix"):
            subdirectory = "bix"
        elif audio.startswith("gg"):
            subdirectory = "gg"
        elif audio[0].isdigit() or not audio[0].isalpha():
            subdirectory = "number"
        else:
            subdirectory = audio[0].lower()
        link = f"https://media.merriam-webster.com/audio/prons/{language_code}/{country_code}/{format}/{subdirectory}/{audio}.{format}"
    return link
