import json
import boto3
import random
from libs.helper import s3_presigned_url, get_aws_secret, get_random_item_from_dynamo, s3_file_exists

def lambda_handler(event, context):
    session = boto3.session.Session( region_name="us-west-2")
    secret = get_aws_secret(session, "prod/esl/reader", "us-west-2")
    entry = get_random_item_from_dynamo(session, "esl")

    
    word = entry.get("word", "")
    shortdef = entry.get("shortdef", "")
    url = []
    for i in range(3):
        if s3_file_exists(session, secret["bucket"], f"images/{word}_{i}.jpg"):
            url.append(s3_presigned_url(session, secret["bucket"], f"images/{word}_{i}.jpg")    )
            print(f"found {word}_{i}.jpg in S3")
    return {
        'statusCode': 200,
'headers': {
            'Access-Control-Allow-Headers': 'Content-Type',
            'Access-Control-Allow-Origin': secret['website'],
            'Access-Control-Allow-Methods': 'GET'
        },
        'body': json.dumps({"images": url, "shortdef": shortdef, "word": word, "audio": build_link(entry)}),
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
