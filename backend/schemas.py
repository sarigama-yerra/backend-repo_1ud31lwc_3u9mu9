from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from datetime import datetime

# Existing models (as described in state)
class Debt(BaseModel):
    name: str
    balance: float
    interest_rate: float
    min_payment: float

class Expense(BaseModel):
    name: str
    amount: float
    frequency: str  # weekly | fortnightly | monthly | annual
    category: str
    deductible: bool = False

class Scenario(BaseModel):
    name: str
    assumptions: Dict[str, Any] = {}

class StrategyAllocation(BaseModel):
    bucket: str
    type: str = "percent"  # percent | fixed
    value: float  # percent (0-100) or fixed amount

class Strategy(BaseModel):
    name: str
    description: Optional[str] = None
    allocations: List[StrategyAllocation]
    preset: Optional[str] = None

# New CDR models
class BankConnection(BaseModel):
    provider: str
    status: str = "connected"  # connected | pending | failed
    accounts_linked: int = 0

class BankAccount(BaseModel):
    id: str
    institution: str
    name: str
    bsb: Optional[str] = None
    number: Optional[str] = None
    type: str = "transaction"  # transaction | savings | credit | loan | offset
    balance: float = 0.0

class BankTransaction(BaseModel):
    account_id: str
    date: str
    description: str
    amount: float
    category: Optional[str] = None

# Gamification
class GamificationProfile(BaseModel):
    user_id: str
    xp: int = 0
    level: int = 1
    badges: List[str] = []
    streak_days: int = 0
    quests: List[str] = []

# Profiles
class UserProfile(BaseModel):
    user_id: str
    name: str
    occupation: Optional[str] = None
    tax_resident: bool = True
    master_salary_account_id: Optional[str] = None
    income_frequency: Optional[str] = None  # weekly | fortnightly | monthly | annual

class BusinessProfile(BaseModel):
    business_id: str
    name: str
    abn_acn: Optional[str] = None
    industry: Optional[str] = None
    tax_resident: bool = True
    master_income_account_id: Optional[str] = None

# Income and expenses
class IncomeEntry(BaseModel):
    owner_type: str  # user | business
    owner_id: str
    amount: float
    frequency: str  # weekly | fortnightly | monthly | annual
    source: Optional[str] = None

class ExpenseEntry(BaseModel):
    owner_type: str  # user | business
    owner_id: str
    name: str
    amount: float
    frequency: str
    category: str
    deductible: bool = False

# Account mappings for buckets
class AccountMapping(BaseModel):
    owner_type: str  # user | business
    owner_id: str
    bucket: str
    bank_account_id: str

# Strategy application
class StrategyApplyRequest(BaseModel):
    owner_type: str
    owner_id: str
    income_total: Optional[float] = None  # if omitted, compute from income - expenses
    sync_frequency: Optional[str] = None  # weekly | fortnightly | monthly | annual

class TransferInstruction(BaseModel):
    source_account_id: str
    destination_account_id: str
    amount: float
    bucket: str

class RoutingPlan(BaseModel):
    owner_type: str
    owner_id: str
    strategy_id: str
    frequency: str
    transfers: List[TransferInstruction]

# Net worth snapshot
class Asset(BaseModel):
    owner_type: str
    owner_id: str
    name: str
    value: float
    category: Optional[str] = None

class Liability(BaseModel):
    owner_type: str
    owner_id: str
    name: str
    value: float
    category: Optional[str] = None

class NetWorthSnapshot(BaseModel):
    owner_type: str
    owner_id: str
    date: datetime
    assets: List[Asset] = []
    liabilities: List[Liability] = []

