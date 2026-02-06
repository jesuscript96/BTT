from pydantic import BaseModel, Field
from typing import List, Optional, Union, Literal
from uuid import uuid4
from enum import Enum

# --- Enums for TRS requirements ---
class IndicatorType(str, Enum):
    RVOL = "RVOL"
    EXTENSION = "Parabolic Extension"  # Price vs EMA/VWAP
    FFT = "Failed Follow Through"  # High of Day Trap
    SPREAD = "Spread Expansion"
    IMBALANCE = "Large Order Imbalance"
    RED_BARS = "Consecutive Red Bars"
    TIME_OF_DAY = "Time of Day"
    RELATIVE_STRENGTH = "Relative Strength" # vs SPY
    PRICE = "Price"
    VWAP = "VWAP"
    CUSTOM = "Custom"

class Operator(str, Enum):
    GT = ">"
    LT = "<"
    EQ = "=="
    GTE = ">="
    LTE = "<="

class RiskType(str, Enum):
    FIXED = "Fixed Price"
    PERCENT = "Percent"
    ATR = "ATR Multiplier"
    STRUCTURE = "Market Structure" # e.g. High of Day

# --- Models ---

class FilterSettings(BaseModel):
    min_market_cap: Optional[float] = Field(None, description="Minimum Market Cap in USD")
    max_market_cap: Optional[float] = Field(None, description="Maximum Market Cap in USD")
    max_shares_float: Optional[float] = Field(None, description="Max Float shares")
    require_shortable: bool = Field(True, description="Must be shortable (HTB/ETB)")
    exclude_dilution: bool = Field(True, description="Exclude tickers with active S-3 filings")

class Condition(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    indicator: IndicatorType
    operator: Operator
    value: Union[float, str]  # Value can be a number or string (e.g., "11:00")
    compare_to: Optional[str] = None # e.g., "EMA9", "VWAP"

class ConditionGroup(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    conditions: List[Condition] = []
    logic: Literal["AND", "OR"] = "AND"

class ExitLogic(BaseModel):
    stop_loss_type: RiskType
    stop_loss_value: float
    take_profit_type: RiskType
    take_profit_value: float
    trailing_stop_active: bool = False
    trailing_stop_type: Optional[str] = "EMA13"
    dilution_profit_boost: bool = Field(False, description="Increase TP if dilution is active")

class StrategyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    filters: FilterSettings
    entry_logic: List[ConditionGroup]
    exit_logic: ExitLogic

class Strategy(StrategyCreate):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: Optional[str] = None
