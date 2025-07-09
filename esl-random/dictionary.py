import boto3
import json
from botocore.exceptions import ClientError
from libs.helper import (
    get_aws_secret,
    download_file_from_s3,
    put_item_in_dynamo,
    get_item_from_dynamo,
    get_api_usage,
    update_api_usage,
)
import sys
import requests
from rich.progress import Progress


def main():
    if len(sys.argv) < 2:
        print("Usage: python dictionary.py <wordlist_file>")
        sys.exit(1)
    print(f"opening {sys.argv[1]}")
    with open(sys.argv[1], "r") as f:
        wordlist = f.read().splitlines()

    session = boto3.session.Session(profile_name="eslbuilder", region_name="us-west-2")
    secret = get_aws_secret(session, "esl-writer", "us-west-2")
    bucket_name = secret["bucket"]
    usage_count = get_api_usage(session, bucket_name, "dictionary")
    print("Current API usage count:", usage_count)
    with Progress() as progress:
        task1 = progress.add_task("[red]word list", total=len(wordlist))

        for word in wordlist:
            progress.update(task1, advance=1)
            #            definition = get_item_from_dynamo(session, "esl", { "meta":{ "id":word}})
            definition = get_item_from_dynamo(session, "esl", {"word": word})
            if definition is None:
                task2 = progress.add_task(f"{word} defining", total=2)
                url = f"https://www.dictionaryapi.com/api/v3/references/learners/json/{word}?key={secret['dictionary_key']}"
                response = requests.get(url)
                if response.status_code == 200:
                    progress.update(task2, advance=1)
                    usage_count += 1
                    update_api_usage(session, bucket_name, "dictionary", usage_count)
                    data = response.json()
                    progress.update(task2, description=f"{word} storing", advance=1)

                    if isinstance(data, list):
                        all_str = True
                        for data_item in data:
                            if not isinstance(data_item, str):
                                all_str = False
                                break
                        if all_str:
                            print(f"Unexpected data format for {word}: {data}")
                            progress.remove_task(task2)
                            continue
                        store_data = data[0]
                    else:
                        store_data = data
                    store_data["word"] = word
                    put_item_in_dynamo(session, "esl", store_data)

                progress.remove_task(task2)


if __name__ == "__main__":
    main()
