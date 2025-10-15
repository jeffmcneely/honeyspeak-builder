import requests
import boto3
import sys
import os
from libs.helper import (
    get_aws_secret,
    upload_file_to_s3,
    get_api_usage,
    update_api_usage, s3_file_exists
)
from rich.progress import Progress


def generate_image(word, key, iteration) -> bool:
    r = requests.post(
        "https://api.deepai.org/api/text2img",
        data={
            "text": f"{word}",
        },
        headers={"api-key": key},
    )

    if r.status_code == 200:
        image_url = r.json().get("output_url", "")
        image_req = requests.get(image_url)
        if image_req.status_code == 200:
            with open(f"{word}_{iteration}.jpg", "wb") as f:
                f.write(image_req.content)
                return True
    else:
        print(f"Error generating image for {word}: {r.status_code} - {r.text}")
        return False


def main():
    image_count = 3
    session = boto3.session.Session(profile_name="eslbuilder")
    secret_client = session.client(service_name="secretsmanager", region_name="us-west-2")
    s3 = session.client("s3")
    dynamo = session.client("dynamodb")

    secret = get_aws_secret(secret_client, "esl-writer", "us-west-2")
    if len(sys.argv) < 2:
        print("Usage: python image.py <wordlist_file>")
        sys.exit(1)
    print(f"opening {sys.argv[1]}")
    with open(sys.argv[1], "r") as f:
        wordlist = f.read().splitlines()
    new_usage_count = get_api_usage(s3, secret["bucket"], "image")
    print("Current API usage count:", new_usage_count)
    with Progress() as progress:
        task1 = progress.add_task("[red]word list", total=len(wordlist))
        for word in wordlist:
            task2 = progress.add_task(f"[green]generating {word}", total=image_count)
            for i in range(image_count):
                if s3_file_exists(s3, secret["bucket"], f"images/{word}_{i}.jpg"):
                    continue
                if generate_image(word, secret["deepai_key"], i):
                    new_usage_count += 1
                    upload_file_to_s3(
                        s3,
                        f"{word}_{i}.jpg",
                        secret["bucket"],
                        f"images/{word}_{i}.jpg",
                    )
                    os.remove(f"{word}_{i}.jpg")
                    update_api_usage(
                        s3, secret["bucket"], "image", new_usage_count
                    )
                progress.update(task2, advance=1)
#            task2.visible = False
            progress.remove_task(task2)
            progress.update(task1, advance=1)


if __name__ == "__main__":
    main()
