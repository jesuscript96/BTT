import os
import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from dotenv import load_dotenv

load_dotenv("backend/.env")

def test_boto3_config(sig_version, region):
    print(f"\n--- Testing Sig: {sig_version}, Region: {region} ---")
    key = os.getenv("GCS_ACCESS_KEY_ID")
    secret = os.getenv("GCS_SECRET_ACCESS_KEY")
    bucket = os.getenv("GCS_BUCKET")
    
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    
    client = boto3.client(
        "s3",
        endpoint_url="https://storage.googleapis.com",
        aws_access_key_id=key,
        aws_secret_access_key=secret,
        region_name=region,
        config=Config(signature_version=sig_version) if sig_version else None,
        verify=False
    )
    
    try:
        # Try a simple HEAD or LIST
        client.list_objects_v2(Bucket=bucket, MaxKeys=1)
        print("List successful!")
        
        # Try upload
        print("Testing upload...")
        with open("test_file.txt", "w") as f:
            f.write("test")
        client.upload_file("test_file.txt", bucket, "test_file.txt")
        print("Upload successful!")
        return True
    except Exception as e:
        print(f"Failed: {e}")
        return False

if __name__ == "__main__":
    configs = [
        (None, "auto"),
        ("s3v4", "us-east-1"),
        ("s3v4", "auto"),
    ]
    for sig, reg in configs:
        if test_boto3_config(sig, reg):
            print(f"WINNER: Sig={sig}, Reg={reg}")
            break
