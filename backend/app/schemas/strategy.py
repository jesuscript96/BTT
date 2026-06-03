
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Union, Literal
from uuid import uuid4
from enum import Enum
from datetime import datetime

# --- Enums ---
class IndicatorType(str, Enum):
    # Trend / MA
    SMA = "SMA"
    EMA = "EMA"
    WMA = "WMA"
    VWAP = "VWAP"
    VWAP_SD_PLUS = "VWAP Sd+"
    VWAP_SD_MINUS = "VWAP Sd-"
    LINEAR_REGRESSION = "Linear Regression"
    ZIG_ZAG = "Zig Zag"
    ICHIMOKU = "Ichimoku Clouds"

    # Momentum
    RSI = "RSI"
    MACD = "MACD"
    STOCHASTIC = "Stochastic"
    MOMENTUM = "Momentum"
    CCI = "CCI"
    ROC = "ROC"
    DMI_PLUS = "DMI+"
    DMI_MINUS = "DMI-"
    WILLIAMS_R = "Williams %R"

    # Volatility
    ATR = "ATR"
    ADX = "ADX"
    BOLLINGER_BANDS = "Bollinger Bands"
    DONCHIAN = "Donchian"
    PARABOLIC_SAR = "Parabolic SAR"

    # Volume
    OBV = "OBV"
    VOLUME = "Volume"
    RVOL = "RVOL"
    AVOLUME = "Accumulated Volume"
    SMA_VOLUME = "SMA Volume"

    # Price Variables
    BAR_CLOSE = "Bar Close"
    BAR_OPEN = "Bar Open"
    HIGH_BAR = "High Bar"
    LOW_BAR = "Low Bar"
    PMH = "PM High"
    PML = "PM Low"
    PM_OPEN = "PM Open"
    AM_OPEN = "AM Open"
    RTH_HIGH = "RTH High"
    RTH_LOW = "RTH Low"
    RTH_OPEN = "RTH Open"
    Y_HIGH = "Yesterday High"
    Y_LOW = "Yesterday Low"
    Y_OPEN = "Yesterday Open"
    Y_CLOSE = "Yesterday Close"
    Y_VOLUME = "Yesterday Volume"
    MAX_X_DAYS = "High of last X days"
    MIN_X_DAYS = "Low of last X days"
    PREVIOUS_MAX = "Previous max"
    PREVIOUS_MIN = "Previous min"

    # Behavior Variables
    CONSECUTIVE_HIGHER_HIGHS = "Consecutive Higher Highs"
    CONSECUTIVE_LOWER_LOWS = "Consecutive Lower Lows"
    CONSECUTIVE_RED_CANDLES = "Consecutive Red Candles"
    CONSECUTIVE_GREEN_CANDLES = "Consecutive Green Candles"
    CONSECUTIVE_HIGHER_LOWS = "Consecutive Higher Lows"
    CONSECUTIVE_LOWER_HIGHS = "Consecutive Lower Highs"
    OPENING_RANGE_PLUS = "Opening Range +"
    OPENING_RANGE_MINUS = "Opening Range -"
    OPENING_RANGE_AM_PLUS = "Opening Range AM +"
    OPENING_RANGE_AM_MINUS = "Opening Range AM -"
    HEIKIN_ASHI = "Heikin-Ashi"
    CANDLE_RANGE_PCT = "Candle Range %"
    ELAPSED_TIME_LAST_HIGH = "Elapsed time from last High"
    
    # Time / Others
    TIME_OF_DAY = "Time of Day"
    RANGE_OF_TIME = "Range of Time"
    HIGH_LOW_FROM_TIME = "High/Low from x time"
    HIGH_LOW_FROM_HOUR_TIME = "High/Low from hour-time"

    # Existing / Retained Returns
    RET_PCT_PM = "Ret % PM"
    RET_PCT_RTH = "Ret % RTH"

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

class TakeProfitMode(str, Enum):
    FULL = "Full"
    PARTIAL = "Partial"

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
    period: Optional[int] = None  # For SMA, EMA, RSI, etc.

    @field_validator("name", mode="before")
    @classmethod
    def normalize_name(cls, v):
        if isinstance(v, str):
            # Alias map para compatibilidad con estrategias antiguas
            LEGACY_ALIASES = {
                "pre-market high": "PM High",
                "pre-market low": "PM Low",
                "max of last x days": "High of last X days",
                "min of last x days": "Low of last X days",
                "donchian channels": "Donchian",
                "pmh": "PM High",
                "pml": "PM Low",
            }
            val_lower = v.lower()
            if val_lower in LEGACY_ALIASES:
                v = LEGACY_ALIASES[val_lower]
            for item in IndicatorType:
                if item.value.lower() == v.lower():
                    return item
        return v
    period2: Optional[int] = None # Fast period, signal period, etc.
    period3: Optional[int] = None # Slow period, etc.
    stdDev: Optional[float] = None # Standard Deviation for BB
    multiplier: Optional[float] = None  # For bands, ATR, etc.
    offset: Optional[int] = 0  # Bars back (0 = current)
    overbought: Optional[float] = None  # e.g. RSI 70, Williams %R -20
    oversold: Optional[float] = None  # e.g. RSI 30, Williams %R -80
    consecutive_count: Optional[int] = None  # For consecutive red/highs/lows
    time_hour: Optional[int] = None  # For Time of Day (0-23)
    time_minute: Optional[int] = None  # For Time of Day (0-59)
    time_condition: Optional[Literal["BEFORE", "AFTER"]] = None
    days_lookback: Optional[int] = None
    calc_on_heikin: Optional[bool] = False

    # Added specific parameters
    macd_line: Optional[Literal["Signal", "MACD Line", "Histogram"]] = None
    band_line: Optional[Literal["Upper", "Lower", "Basis"]] = None
    orb_minutes: Optional[int] = None
    ha_option: Optional[Literal["Close Bar", "Open Bar", "High Bar", "Low Bar", "Consecutive Green", "Consecutive Red"]] = None
    time_from_hour: Optional[int] = None
    time_from_minute: Optional[int] = None
    range_minutes: Optional[int] = None
    return_pct: Optional[float] = None

    # New indicator-specific parameters
    deviationLevel: Optional[int] = None       # Linear Regression deviation (1, 2, 3)
    reversionPercentage: Optional[float] = None  # Zig Zag reversion %
    ichimoku_line: Optional[str] = None          # "Tenkan", "Kijun", "Senkou A", "Senkou B", "Chikou"
    min_af: Optional[float] = None               # Parabolic SAR min acceleration factor
    max_af: Optional[float] = None               # Parabolic SAR max acceleration factor

class ComparisonCondition(BaseModel):
    type: Literal["indicator_comparison"] = "indicator_comparison"
    source: IndicatorConfig
    comparator: Comparator
    target: Union[IndicatorConfig, float]
    timeframe: Optional[Timeframe] = None

class PriceLevelDistanceCondition(BaseModel):
    type: Literal["price_level_distance"] = "price_level_distance"
    source: IndicatorConfig
    level: IndicatorConfig
    comparator: Literal["DISTANCE_GT", "DISTANCE_LT"]
    value_pct: float
    position: Optional[Literal["above", "below", "any"]] = "any"
    timeframe: Optional[Timeframe] = None

class CandleCondition(BaseModel):
    type: Literal["candle_pattern"] = "candle_pattern"
    pattern: CandlePattern
    lookback: int = 1
    consecutive_count: int = 1
    timeframe: Optional[Timeframe] = None
    calc_on_heikin: Optional[bool] = False

# Recursive Entry Logic
AnyCondition = Union[ComparisonCondition, PriceLevelDistanceCondition, CandleCondition]

class ConditionGroup(BaseModel):
    type: Literal["group"] = "group"
    operator: Literal["AND", "OR"] = "AND"
    conditions: List[Union['ConditionGroup', AnyCondition]]

class EntryLogic(BaseModel):
    timeframe: Timeframe = Timeframe.M1
    root_condition: ConditionGroup

class ExitLogic(BaseModel):
    timeframe: Timeframe = Timeframe.M1
    root_condition: ConditionGroup

class PartialTakeProfit(BaseModel):
    distance_pct: float
    capital_pct: float

class RiskManagement(BaseModel):
    use_hard_stop: Optional[bool] = True
    use_take_profit: Optional[bool] = True
    take_profit_mode: Optional[TakeProfitMode] = TakeProfitMode.FULL
    accept_reentries: Optional[bool] = True
    hard_stop: Optional[dict] = Field(default_factory=lambda: {"type": RiskType.PERCENTAGE, "value": 2.0})
    take_profit: Optional[dict] = Field(default_factory=lambda: {"type": RiskType.PERCENTAGE, "value": 6.0})
    partial_take_profits: Optional[List[PartialTakeProfit]] = Field(default_factory=list)
    trailing_stop: Optional[dict] = Field(default_factory=lambda: {"active": False, "type": "Percentage", "buffer_pct": 0.5})
    max_drawdown_daily: Optional[float] = None  # Circuit breaker

class PostGapPrecondition(BaseModel):
    id: str
    day: Literal['gap_day', 'gap_1_day']
    metric: Literal['volume', 'close_vs_open', 'close_vs_high_low', 'close_vs_pm_high', 'close_vs_vwap', 'close_vs_sma', 'candle_range_pct']
    operator: Literal['>', '<', '> High', '< Low']
    value: Optional[float] = None
    sma_period: Optional[int] = None

class StrategyCreate(BaseModel):
    name: str
    description: Optional[str] = None
    bias: Literal['long', 'short'] = 'long'
    apply_day: Optional[Literal['gap_day', 'gap_1_day', 'gap_2_day']] = 'gap_day'
    postgap_preconditions: Optional[List[PostGapPrecondition]] = None
    universe_filters: Optional[UniverseFilters] = None
    entry_logic: EntryLogic
    exit_logic: Optional[ExitLogic] = None
    risk_management: RiskManagement

class Strategy(StrategyCreate):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now().isoformat())

