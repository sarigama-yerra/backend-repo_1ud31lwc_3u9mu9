"""
Database Schemas

Define your MongoDB collection schemas here using Pydantic models.
These schemas are used for data validation in your application.

Each Pydantic model represents a collection in your database.
Model name is converted to lowercase for the collection name:
- User -> "user" collection
- Product -> "product" collection
- BlogPost -> "blogs" collection
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Literal

# Example schemas (retain for reference)

class User(BaseModel):
    """
    Users collection schema
    Collection name: "user" (lowercase of class name)
    """
    name: str = Field(..., description="Full name")
    email: str = Field(..., description="Email address")
    address: str = Field(..., description="Address")
    age: Optional[int] = Field(None, ge=0, le=120, description="Age in years")
    is_active: bool = Field(True, description="Whether user is active")

class Product(BaseModel):
    """
    Products collection schema
    Collection name: "product" (lowercase of class name)
    """
    title: str = Field(..., description="Product title")
    description: Optional[str] = Field(None, description="Product description")
    price: float = Field(..., ge=0, description="Price in dollars")
    category: str = Field(..., description="Product category")
    in_stock: bool = Field(True, description="Whether product is in stock")

# Finance Optimizer Schemas

class Debt(BaseModel):
    name: str = Field(..., description="Debt name e.g., Credit Card")
    balance: float = Field(..., ge=0)
    interest_rate_apy: float = Field(..., ge=0, description="Annual interest rate as a percentage, e.g., 19.99 for 19.99%")
    minimum_payment_monthly: float = Field(0, ge=0)

class Expense(BaseModel):
    category: str
    amount_monthly: float = Field(..., ge=0)

class Scenario(BaseModel):
    """
    Generic scenario for both individuals and businesses
    Collection name: "scenario"
    """
    name: str = Field(..., description="Friendly name for the scenario")
    scenario_type: Literal["individual", "business"] = Field(...)
    inputs: Dict[str, object] = Field(default_factory=dict, description="Arbitrary input parameters used")
    results: Dict[str, object] = Field(default_factory=dict, description="Computed results snapshot")
    notes: Optional[str] = None

class Strategy(BaseModel):
    """
    Financial strategy plans for scenarios
    Collection name: "strategy"
    """
    title: str = Field(..., description="Strategy name")
    audience: Literal["individual", "business"] = Field("individual")
    kind: Literal["prebuilt", "generated"] = Field("generated")
    description: Optional[str] = Field(None, description="Short overview")
    steps: List[str] = Field(default_factory=list, description="Concrete action steps")
    assumptions: Dict[str, object] = Field(default_factory=dict, description="Inputs used or assumed")
    estimated_impact: Dict[str, float] = Field(default_factory=dict, description="Key metrics deltas e.g., savings_rate:+0.05")
    scenario_id: Optional[str] = Field(None, description="Related scenario document id if any")

# CDR (Banking) Schemas

class BankConnection(BaseModel):
    """
    Represents a user's consented bank connection via CDR
    Collection: "bankconnection"
    """
    provider: str = Field(..., description="Bank/provider code, e.g., NAB, CBA, WBC, ANZ")
    status: Literal["connected", "revoked"] = Field("connected")
    accounts_linked: int = Field(0)

class BankAccount(BaseModel):
    """
    Bank account summary
    Collection: "bankaccount"
    """
    provider: str
    account_id: str
    name: str
    bsb: Optional[str] = None
    number_masked: str
    balance: float = 0.0

class BankTransaction(BaseModel):
    """
    Bank transaction record
    Collection: "banktransaction"
    """
    provider: str
    account_id: str
    txn_id: str
    date: str
    description: str
    amount: float
    category: Optional[str] = None

# Gamification Schema

class GamificationProfile(BaseModel):
    """
    Single-profile gamification tracker
    Collection: "gamificationprofile" (use one document for now)
    """
    xp: int = 0
    level: int = 1
    badges: List[str] = Field(default_factory=list)
    streak_days: int = 0
    quests: List[Dict[str, object]] = Field(default_factory=list)

# Note: The Flames database viewer will automatically:
# 1. Read these schemas from GET /schema endpoint
# 2. Use them for document validation when creating/editing
# 3. Handle all database operations (CRUD) directly
# 4. You don't need to create any database endpoints!
