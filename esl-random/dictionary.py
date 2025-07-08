import boto3
import json
from botocore.exceptions import ClientError
from libs.helper import get_aws_secret, download_file_from_s3


def main():
    session = boto3.session.Session(profile_name="eslbuilder")
    secret = get_aws_secret(session, "esl-writer", "us-west-2")
    bucket_name = secret["bucket"]
    api_usage = download_file_from_s3(
        session, bucket_name, "api_usage.json", "/tmp/api_usage.json"
    )
    if api_usage:
        with open("/tmp/api_usage.json", "r") as f:
            usage_data = json.load(f)
        print("API Usage Data:")
        print(json.dumps(usage_data, indent=4))
    else:
        print("No API usage data found or failed to download.")
    # List all JSON files in the S3 bucket


if __name__ == "__main__":
    main()
