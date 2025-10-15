from libs.helper import polly_generate_audio, get_item_from_dynamo, get_aws_secret, list_items_in_dynamo,upload_file_to_s3
from rich.progress import Progress



def main():
    import boto3
    session = boto3.session.Session(profile_name="eslbuilder", region_name="us-west-2")
    secret_client = session.client(service_name="secretsmanager", region_name="us-west-2")
    s3 = session.client("s3")
    dynamo = session.client("dynamodb")
    secret = get_aws_secret(secret_client, "esl-writer", "us-west-2")

    word_list = list_items_in_dynamo(dynamo, "esl")
    with Progress() as progress:
        task1 = progress.add_task("[red]word list", total=len(word_list))

        for entry in word_list:
            word = entry.get("word", "")
            get_item_from_dynamo(dynamo, "esl", {"word": word})
            task2 = progress.add_task(f"[yellow] voicing {word}", total=2)
            shortdefs = entry.get("shortdef", [])
            shortdef = ""
            for sd in shortdefs:
                shortdef = sd + ". "
            for voice in ['Matthew', 'Joanna']:
                if polly_generate_audio(session, shortdef, voice, "neural", "mp3"):
                    upload_file_to_s3(s3, "/tmp/polly_output.mp3", secret['bucket'], f"audio/{voice}_{uuid}.mp3")
                    progress.update(task2, advance=1, description=f"[green] {voice} audio generated for {word}")
            progress.update(task1, advance=1)
            progress.remove_task(task2)
if __name__ == "__main__":
    main()