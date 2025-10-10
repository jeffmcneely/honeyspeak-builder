import json
import boto3
import os
import logging
from libs.helper import (
    s3_presigned_url,
    get_aws_secret,
    get_random_item_from_dynamo,
    s3_file_exists,
)




def lambda_handler(event, context):
    bucket = os.environ.get("AWS_BUCKET", "")
    website = os.environ.get("AWS_WEBSITE", "https://esl.mcneely.io")
    loglevel = os.environ.get("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=loglevel)
    logging.debug(f"Received event: {event}")
    logging.debug(f"Received queryStringParameters: {event['queryStringParameters']}")
    logging.debug(f"Building session")
    session = boto3.session.Session(region_name="us-west-2")
    logging.debug(f"Creating S3 client")
    s3 = session.client("s3")
    logging.debug(f"S3 client created")

    logging.debug(f"Creating DynamoDB client")
    dynamo = session.client("dynamodb")
    logging.debug(f"DynamoDB client created")

    entry = get_random_item_from_dynamo(dynamo, "esl")
    word = entry.get("word", "")
    logging.debug(f"Got random item from DynamoDB: {word}")
    shortdefs = entry.get("shortdef", [])
    shortdef = ""
    for sd in shortdefs:
        shortdef = sd + ". "
    url = []
    if s3_file_exists(s3, bucket, f"audio/Joanna_{word}.mp3"):
        joanna = s3_presigned_url(s3, bucket, f"audio/Joanna_{word}.mp3")
        logging.debug(f"Found audio for Joanna")
    else:
        joanna = ""
    if s3_file_exists(s3, bucket, f"audio/Matthew_{word}.mp3"):
        matthew = s3_presigned_url(s3, bucket, f"audio/Matthew_{word}.mp3")
        logging.debug(f"Found audio for Matthew")
    else:
        matthew = ""

    for i in range(3):
        if s3_file_exists(s3, bucket, f"images/{word}_{i}.jpg"):
            logging.debug(f"found {word}_{i}.jpg in S3")
            url.append(s3_presigned_url(s3, bucket, f"images/{word}_{i}.jpg"))
            logging.debug(f"Added URL for {word}_{i}.jpg")
    return {
        "statusCode": 200,
        "headers": {
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Origin": website,
            "Access-Control-Allow-Methods": "GET",
        },
        "body": json.dumps(
            {
                "images": url,
                "shortdef": shortdef,
                "word": word,
                "female_audio": joanna,
                "male_audio": matthew,
                "audio": build_link(entry),
            }
        ),
    }


def build_link(entry: dict) -> str:
    """
    Build a link to the audio pronunciation file based on the provided parameters.
    """
    hwi = entry.get("hwi", {})
    prs_list = hwi.get("prs", [])
    if len(prs_list) == 0:
        return ""
    prs = prs_list[0]  # Use the first pronunciation entry
    language_code = "en"
    country_code = "us"
    format = "mp3"
    link = ""
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
