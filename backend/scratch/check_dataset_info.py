import os
import sys
from dotenv import load_dotenv

load_dotenv()
sys.path.append(os.path.abspath('backend'))

from app.database import get_user_db_connection

con = get_user_db_connection(read_only=True)
print("Connected to User DB")

try:
    datasets = con.execute("SELECT * FROM datasets WHERE id = 'mock_dataset_1'").fetchdf()
    print("Dataset Row:")
    print(datasets)
    
    pairs_count = con.execute("SELECT COUNT(*) FROM dataset_pairs WHERE dataset_id = 'mock_dataset_1'").fetchone()[0]
    print(f"Number of dataset pairs in dataset_pairs: {pairs_count}")
    
    # Let's see if there are any sample rows
    if pairs_count > 0:
        sample_pairs = con.execute("SELECT * FROM dataset_pairs WHERE dataset_id = 'mock_dataset_1' LIMIT 5").fetchdf()
        print("Sample dataset pairs:")
        print(sample_pairs)
except Exception as e:
    print("Error:", e)
con.close()
