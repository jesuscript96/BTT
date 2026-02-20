
from pydantic import BaseModel, Field
from typing import List, Optional, Union, Literal
from uuid import uuid4
from enum import Enum
from datetime import datetime

# --- Enums ---
class IndicatorType(str, Enum):
    SMA = "SMA"
    EMA = "EMA"
    WMA = "WMA"
    RVOL = "RVOL"
    VWAP = "VWAP"
    RSI = "RSI"
    MACD = "MACD"
    ATR = "ATR"
    CLOSE = "Close"
    OPEN = "Open"
    HIGH = "High"
    LOW = "Low"
    PMH = "Pre-Market High"
    PML = "Pre-Market Low"
    HOD = "High of Day"
    LOD = "Low of Day"
    Y_HIGH = "Yesterday High"
    Y_LOW = "Yesterday Low"
    Y_CLOSE = "Yesterday Close"
    CUSTOM = "Custom" # For arbitrary numbers

class Comparator(str, Enum):
    GT = "GREATER_THAN"
    LT = "LESS_THAN"
    GTE = "GREATER_THAN_OR_EQUAL"
    LTE = "LESS_THAN_OR_EQUAL"
    EQ = "EQUAL"
    CROSSES_ABOVE = "CROSSES_ABOVE"
    CROSSES_BELOW = "CROSSES_BELOW"
    # Special for price vs level distance
    DISTANCE_GT = "DISTANCE_GREATER_THAN"
    DISTANCE_LT = "DISTANCE_LESS_THAN"

class CandlePattern(str, Enum):
    RV = "RED_VOLUME" # Close < Open
    RV_PLUS = "RED_VOLUME_PLUS" # Close < Open AND Close < Prev Close
    GV = "GREEN_VOLUME" # Close > Open
    GV_PLUS = "GREEN_VOLUME_PLUS" # Close > Open AND Close > Prev Close
    DOJI = "DOJI"
    HAMMER = "HAMMER"
    SHOOTING_STAR = "SHOOTING_STAR"

class Timeframe(str, Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    M30 = "30m"
    H1 = "1h"
    D1 = "1d"

class RiskType(str, Enum):
    FIXED = "Fixed Amount"
    PERCENTAGE = "Percentage"
    ATR = "ATR Multiplier"
    MARKET_STRUCTURE = "Market Structure (HOD/LOD)"

# --- Component Models ---

class UniverseFilters(BaseModel):
    min_market_cap: Optional[float] = Field(None, description="Min Market Cap in USD")
    max_market_cap: Optional[float] = Field(None, description="Max Market Cap in USD")
    min_price: Optional[float] = Field(None, description="Min Price")
    max_price: Optional[float] = Field(None, description="Max Price")
    min_volume: Optional[float] = Field(None, description="Min Daily Volume")
    max_shares_float: Optional[float] = Field(None, description="Max Float shares")
    require_shortable: bool = Field(True, description="Must be HTB/ETB")
    exclude_dilution: bool = Field(True, description="Exclude active S-3/F-3")
    whitelist_sectors: List[str] = Field(default_factory=list)

class IndicatorConfig(BaseModel):
    name: IndicatorType
    period: Optional[int] = None # For SMA, EMA, RSI, etc.
    multiplier: Optional[float] = None # For bands, ATR, etc.
    offset: Optional[int] = 0 # Bars back (0 = current)

class ComparisonCondition(BaseModel):
    type: Literal["indicator_comparison"] = "indicator_comparison"
    source: IndicatorConfig
    comparator: Comparator
    target: Union[IndicatorConfig, float]  # Target can be another indicator OR a static number

class PriceLevelCondition(BaseModel):
    type: Literal["price_level_distance"] = "price_level_distance"
    source: Literal["Close", "High", "Low"] = "Close"
    level: IndicatorType # PMH, PML, Y_HIGH, etc.
    comparator: Literal["DISTANCE_GT", "DISTANCE_LT"] # Check distance
    value_pct: float # Percentage distance (e.g. 5.0 for 5%)

class CandleCondition(BaseModel):
    type: Literal["candle_pattern"] = "candle_pattern"
    pattern: CandlePattern
    lookback: int = 1 # How many bars back to check
    consecutive_count: int = 1 # e.g. 3 red candles in a row

# Recursive Entry Logic
class ConditionGroup(BaseModel):
    type: Literal["group"] = "group"
    operator: Literal["AND", "OR"] = "AND"
    conditions: List[Union['ConditionGroup', ComparisonCondition, PriceLevelCondition, CandleCondition]]

class EntryLogic(BaseModel):
    timeframe: Timeframe = Timeframe.M1
    root_condition: ConditionGroup

class RiskManagement(BaseModel):
    hard_stop: Optional[dict] = Field(default_factory=lambda: {"type": RiskType.PERCENTAGE, "value": 2.0})
    take_profit: Optional[dict] = Field(default_factory=lambda: {"type": RiskType.PERCENTAGE, "value": 6.0})
    trailing_stop: Optional[dict] = Field(default_factory=lambda: {"active": False, "type": "EMA13", "buffer_pct": 0.5})
    max_drawdown_daily: Optional[float] = None # Create circuit breaker

class StrategyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    universe_filters: UniverseFilters
    entry_logic: EntryLogic
    risk_management: RiskManagement

class Strategy(StrategyCreate):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

