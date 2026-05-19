import os
from google.cloud import storage

def test_json_key():
    key_path = "gcs-key-2.json"
    bucket_name = "strategybuilderbbdd"
    
    print(f"Testing GCS access with {key_path}...")
    try:
        client = storage.Client.from_service_account_json(key_path)
        bucket = client.bucket(bucket_name)
        
        # Try listing blobs
        print(f"Listing blobs in {bucket_name}...")
        blobs = list(bucket.list_blobs(max_results=5))
        for blob in blobs:
            print(f" - {blob.name}")
        print("✅ Access successful!")
    except Exception as e:
        print(f"❌ Access failed: {e}")

if __name__ == "__main__":
    test_json_key()
