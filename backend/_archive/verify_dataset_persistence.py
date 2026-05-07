import json
from uuid import uuid4
from app.database import get_db_connection
from app.routers.query import create_saved_query, SavedQuery

def test_dataset_persistence():
    print("Testing dataset persistence...")
    
    # Define a test query
    test_query = SavedQuery(
        name="Verification Test Dataset",
        filters={
            "min_gap": 2.0,
            "ticker": "AAPL",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31"
        }
    )
    
    try:
        # We call the function directly. Note: it uses get_db_connection internally.
        result = create_saved_query(test_query)
        dataset_id = result["id"]
        print(f"✅ Dataset created with ID: {dataset_id}")
        
        # Verify dataset_pairs
        con = get_db_connection()
        count = con.execute("SELECT COUNT(*) FROM dataset_pairs WHERE dataset_id = ?", (dataset_id,)).fetchone()[0]
        print(f"📊 Rows in dataset_pairs: {count}")
        
        if count > 0:
            print("🚀 SUCCESS: combinations persisted!")
            # Show a sample
            sample = con.execute("SELECT ticker, date FROM dataset_pairs WHERE dataset_id = ? LIMIT 5", (dataset_id,)).fetchall()
            print(f"Sample pairs: {sample}")
        else:
            print("❌ FAILURE: no combinations persisted. Check filters or data.")
            
        # Cleanup (optional but good practice)
        # con.execute("DELETE FROM dataset_pairs WHERE dataset_id = ?", (dataset_id,))
        # con.execute("DELETE FROM datasets WHERE id = ?", (dataset_id,))
        # con.execute("DELETE FROM saved_queries WHERE id = ?", (dataset_id,))
        # print("Cleanup done.")
        
    except Exception as e:
        print(f"❌ Error during verification: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_dataset_persistence()
