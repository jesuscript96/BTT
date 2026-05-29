from fastapi import APIRouter, HTTPException
from app.db.gcs_cache import get_strategies_df, get_saved_queries_df

router = APIRouter()


@router.get("/datasets")
def list_datasets():
    try:
        df = get_saved_queries_df()
        if df is None or df.empty:
            return []
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str):
    try:
        df = get_saved_queries_df()
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="Dataset not found")
        row = df[df["id"] == dataset_id]
        if row.empty:
            raise HTTPException(status_code=404, detail="Dataset not found")
        return row.iloc[0].to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strategies")
def list_strategies_backtester():
    try:
        df = get_strategies_df()
        if df is None or df.empty:
            return []
        return df.to_dict(orient="records")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/strategies/{strategy_id}")
def get_strategy_backtester(strategy_id: str):
    try:
        df = get_strategies_df()
        if df is None or df.empty:
            raise HTTPException(status_code=404, detail="Strategy not found")
        row = df[df["id"] == strategy_id]
        if row.empty:
            raise HTTPException(status_code=404, detail="Strategy not found")
        return row.iloc[0].to_dict()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
