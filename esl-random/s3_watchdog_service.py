import os
import sys
import time
import boto3
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler

class S3UploadHandler(FileSystemEventHandler):
    def __init__(self, s3_client, bucket_name):
        self.s3 = s3_client
        self.bucket = bucket_name

    def on_created(self, event):
        if not event.is_directory:
            file_path = event.src_path
            file_name = os.path.basename(file_path)
            try:
                self.s3.upload_file(file_path, self.bucket, file_name)
                print(f"Uploaded {file_name} to S3 bucket {self.bucket}")
            except Exception as e:
                print(f"Failed to upload {file_name}: {e}")

def main(directories, bucket_name, region_name="us-west-2"):
    s3 = boto3.client("s3", region_name=region_name)
    event_handler = S3UploadHandler(s3, bucket_name)
    observer = Observer()
    for directory in directories:
        observer.schedule(event_handler, path=directory, recursive=False)
    observer.start()
    print(f"Watching directories: {directories}")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python s3_watchdog_service.py <bucket_name> <dir1> [<dir2> ...]")
        sys.exit(1)
    bucket = sys.argv[1]
    dirs = sys.argv[2:]
    main(dirs, bucket)
