from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
from datetime import datetime

from database import db, create_document, get_documents
from schemas import (
    Debt, Expense, Scenario, Strategy, StrategyAllocation,
    BankConnection, BankAccount, BankTransaction,
    GamificationProfile,
    UserProfile, BusinessProfile,
    IncomeEntry, ExpenseEntry,
    AccountMapping,
    StrategyApplyRequest, TransferInstruction, RoutingPlan,
    Asset, Liability, NetWorthSnapshot
)

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- Helpers ----------

def _now():
    return datetime.utcnow()

XP_RULES = {
    "save_scenario": 50,
    "generate_strategy": 10,
    "save_strategy": 75,
    "link_bank": 150,
    "create_profile": 40,
    "save_expenses_first": 30,
    "apply_strategy": 25,
}

BADGE_RULES = {
    "save_scenario": "Planner",
    "save_strategy": "Strategist",
    "link_bank": "Banked Up",
    "apply_strategy_first": "Allocator",
    "create_profile": "Getting Started",
}


async def _get_latest_profile(user_id: str) -> GamificationProfile:
    profs = await get_documents("gamificationprofile", {"user_id": user_id}, limit=1)
    if profs:
        p = profs[0]
        return GamificationProfile(**p)
    # create new
    data = GamificationProfile(user_id=user_id, xp=0, level=1, badges=[], streak_days=0, quests=[]).dict()
    await create_document("gamificationprofile", data)
    return GamificationProfile(**data)

async def _award_xp(user_id: str, key: str):
    add = XP_RULES.get(key, 0)
    if add <= 0:
        return
    profs = await get_documents("gamificationprofile", {"user_id": user_id}, limit=1)
    if profs:
        prof = profs[0]
        xp = prof.get("xp", 0) + add
        level = 1 + xp // 200
        badges = set(prof.get("badges", []))
        if key in BADGE_RULES:
            badges.add(BADGE_RULES[key])
        await create_document("gamificationprofile", {"user_id": user_id, "xp": xp, "level": level, "badges": list(badges)})
    else:
        xp = add
        level = 1 + xp // 200
        await create_document("gamificationprofile", {"user_id": user_id, "xp": xp, "level": level, "badges": []})

# ---------- CDR mock ----------

@app.post("/api/cdr/connect/start")
async def cdr_connect_start(provider: Dict[str, Any]):
    provider_name = provider.get("provider", "Unknown")
    await create_document("bankconnection", {"provider": provider_name, "status": "pending", "accounts_linked": 0})
    return {"status": "pending", "provider": provider_name}

@app.post("/api/cdr/connect/complete")
async def cdr_connect_complete(payload: Dict[str, Any]):
    provider = payload.get("provider", "DemoBank")
    # create sample accounts
    accounts = [
        {"id": "acc_demo_txn", "institution": provider, "name": "Everyday Account", "bsb": "123-456", "number": "001122", "type": "transaction", "balance": 3240.55},
        {"id": "acc_demo_save", "institution": provider, "name": "High Saver", "bsb": "123-456", "number": "007700", "type": "savings", "balance": 15000.0},
        {"id": "acc_demo_offset", "institution": provider, "name": "Home Loan Offset", "bsb": "123-456", "number": "009900", "type": "offset", "balance": 22000.0},
        {"id": "acc_demo_cc", "institution": provider, "name": "Visa Credit", "type": "credit", "balance": -1250.0},
    ]
    for a in accounts:
        await create_document("bankaccount", a)
    await create_document("bankconnection", {"provider": provider, "status": "connected", "accounts_linked": len(accounts)})
    # transactions for txn account
    txns = [
        {"account_id": "acc_demo_txn", "date": "2025-01-08", "description": "Salary", "amount": 3500.0, "category": "income"},
        {"account_id": "acc_demo_txn", "date": "2025-01-10", "description": "Groceries", "amount": -180.2, "category": "food"},
        {"account_id": "acc_demo_txn", "date": "2025-01-11", "description": "Utilities", "amount": -120.0, "category": "utilities"},
    ]
    for t in txns:
        await create_document("banktransaction", t)
    # award XP for linking
    user_id = payload.get("user_id", "demo-user")
    await _award_xp(user_id, "link_bank")
    return {"status": "connected", "accounts": accounts}

@app.get("/api/cdr/accounts")
async def cdr_accounts():
    accs = await get_documents("bankaccount", {}, limit=200)
    return {"accounts": accs}

@app.get("/api/cdr/transactions")
async def cdr_transactions(account_id: Optional[str] = None):
    query = {"account_id": account_id} if account_id else {}
    txns = await get_documents("banktransaction", query, limit=500)
    return {"transactions": txns}

# ---------- Gamification endpoints ----------

@app.get("/api/gamification/profile")
async def gamification_profile(user_id: str = "demo-user"):
    p = await _get_latest_profile(user_id)
    return p.dict()

@app.post("/api/gamification/award")
async def gamification_award(payload: Dict[str, Any]):
    user_id = payload.get("user_id", "demo-user")
    key = payload.get("key")
    await _award_xp(user_id, key)
    return {"ok": True}

# ---------- Profiles ----------

@app.post("/api/profile/user")
async def create_user_profile(profile: UserProfile):
    await create_document("userprofile", profile.dict())
    await _award_xp(profile.user_id, "create_profile")
    return {"ok": True}

@app.get("/api/profile/user")
async def get_user_profile(user_id: str):
    docs = await get_documents("userprofile", {"user_id": user_id}, limit=1)
    return docs[0] if docs else {}

@app.post("/api/profile/business")
async def create_business_profile(profile: BusinessProfile):
    await create_document("businessprofile", profile.dict())
    return {"ok": True}

@app.get("/api/profile/business")
async def get_business_profile(business_id: str):
    docs = await get_documents("businessprofile", {"business_id": business_id}, limit=1)
    return docs[0] if docs else {}

# ---------- Income & Expenses ----------

@app.post("/api/income")
async def add_income(entry: IncomeEntry):
    await create_document("incomeentry", entry.dict())
    return {"ok": True}

@app.get("/api/income")
async def list_income(owner_type: str, owner_id: str):
    docs = await get_documents("incomeentry", {"owner_type": owner_type, "owner_id": owner_id}, limit=500)
    return {"items": docs}

@app.post("/api/expenses")
async def add_expense(entry: ExpenseEntry):
    await create_document("expenseentry", entry.dict())
    return {"ok": True}

@app.get("/api/expenses")
async def list_expenses(owner_type: str, owner_id: str):
    docs = await get_documents("expenseentry", {"owner_type": owner_type, "owner_id": owner_id}, limit=1000)
    return {"items": docs}

# ---------- Deductions assistant ----------

AU_DEDUCTIONS = {
    "default": [
        "Work from home (fixed rate method)",
        "Phone & internet (work-related proportion)",
        "Tools & equipment (depreciation where applicable)",
        "Union or professional fees",
        "Training and certifications",
        "Protective clothing / PPE",
        "Vehicle expenses (if required for work)",
        "Software subscriptions",
    ],
    "teacher": ["Teaching aids", "Professional development", "Union fees"],
    "nurse": ["Uniform & laundry", "Registration fees", "CPD courses"],
    "it consultant": ["Laptop & peripherals", "Software & cloud services", "Home office"],
    "construction": ["Tools & PPE", "Union fees", "Vehicle costs"],
}

INDUSTRY_SEEDS = {
    "horeca": [
        {"title": "NSW Small Business Fees & Charges Rebate", "type": "grant"},
        {"title": "Energy efficiency upgrades for hospitality", "type": "benefit"},
    ],
    "speciality stores": [
        {"title": "Retail innovation grants", "type": "grant"},
        {"title": "Digital POS adoption incentives", "type": "benefit"},
    ],
    "it consulting": [
        {"title": "R&D tax incentive overview", "type": "benefit"},
        {"title": "Cyber security uplift grant", "type": "grant"},
    ],
    "healthcare": [
        {"title": "Practice digitisation rebates", "type": "benefit"},
        {"title": "Rural health support grants", "type": "grant"},
    ],
}

@app.get("/api/deductions")
async def get_deductions(occupation: Optional[str] = None, industry: Optional[str] = None):
    occ = (occupation or "").strip().lower()
    ind = (industry or "").strip().lower()
    base = AU_DEDUCTIONS["default"]
    extra = AU_DEDUCTIONS.get(occ, [])
    news = INDUSTRY_SEEDS.get(ind, [])
    return {"suggestions": base + extra, "insights": news}

# ---------- Strategies CRUD ----------

@app.post("/api/strategies")
async def save_strategy(strategy: Strategy):
    await create_document("strategy", strategy.dict())
    # Award XP
    await _award_xp("demo-user", "save_strategy")
    return {"ok": True}

@app.get("/api/strategies")
async def list_strategies():
    docs = await get_documents("strategy", {}, limit=200)
    return {"items": docs}

# ---------- Account mappings ----------

@app.post("/api/account-mapping")
async def set_account_mapping(mapping: AccountMapping):
    await create_document("accountmapping", mapping.dict())
    return {"ok": True}

@app.get("/api/account-mapping")
async def get_account_mappings(owner_type: str, owner_id: str):
    docs = await get_documents("accountmapping", {"owner_type": owner_type, "owner_id": owner_id}, limit=200)
    return {"items": docs}

# ---------- Strategy simulate/apply ----------

FREQ_TO_MONTHS = {
    "weekly": 52/12,
    "fortnightly": 26/12,
    "monthly": 1,
    "annual": 1/12,
}

def normalize(amount: float, freq: str) -> float:
    return amount * FREQ_TO_MONTHS.get(freq, 1)

@app.post("/api/strategy/simulate")
async def simulate_strategy(payload: Dict[str, Any]):
    owner_type = payload.get("owner_type", "user")
    owner_id = payload.get("owner_id", "demo-user")
    # get incomes & expenses
    incomes = await get_documents("incomeentry", {"owner_type": owner_type, "owner_id": owner_id}, limit=1000)
    expenses = await get_documents("expenseentry", {"owner_type": owner_type, "owner_id": owner_id}, limit=2000)
    income_total_m = sum(normalize(i["amount"], i["frequency"]) for i in incomes)
    expense_total_m = sum(normalize(e["amount"], e["frequency"]) for e in expenses)
    net_m = max(income_total_m - expense_total_m, 0)
    # strategy
    strategy_id = payload.get("strategy_id")
    if not strategy_id:
        raise HTTPException(status_code=400, detail="strategy_id required")
    strategies = await get_documents("strategy", {"name": strategy_id}, limit=1)
    strategy = strategies[0] if strategies else None
    if not strategy:
        raise HTTPException(status_code=404, detail="strategy not found")
    allocations = strategy.get("allocations", [])
    breakdown = []
    for a in allocations:
        if a.get("type") == "fixed":
            amt = a.get("value", 0)
        else:
            amt = net_m * (a.get("value", 0) / 100.0)
        breakdown.append({"bucket": a.get("bucket"), "amount": round(amt, 2)})
    return {"income_monthly": round(income_total_m, 2), "expenses_monthly": round(expense_total_m, 2), "net_monthly": round(net_m, 2), "breakdown": breakdown}

@app.post("/api/strategy/apply")
async def apply_strategy(req: StrategyApplyRequest):
    owner_type = req.owner_type
    owner_id = req.owner_id
    # find default source account
    if owner_type == "user":
        profs = await get_documents("userprofile", {"user_id": owner_id}, limit=1)
        source = (profs[0] or {}).get("master_salary_account_id") if profs else None
    else:
        profs = await get_documents("businessprofile", {"business_id": owner_id}, limit=1)
        source = (profs[0] or {}).get("master_income_account_id") if profs else None
    if not source:
        raise HTTPException(status_code=400, detail="No master source account set")
    # compute monthly net
    incomes = await get_documents("incomeentry", {"owner_type": owner_type, "owner_id": owner_id}, limit=1000)
    expenses = await get_documents("expenseentry", {"owner_type": owner_type, "owner_id": owner_id}, limit=2000)
    income_total_m = sum(normalize(i["amount"], i["frequency"]) for i in incomes)
    expense_total_m = sum(normalize(e["amount"], e["frequency"]) for e in expenses)
    net_m = max(income_total_m - expense_total_m, 0)
    # get selected strategy by name in req.strategy_id
    # for simplicity, we use strategy_id as name
    strategies = await get_documents("strategy", {"name": req.dict().get("strategy_id", None)}, limit=1)
    strategy = strategies[0] if strategies else None
    if not strategy:
        raise HTTPException(status_code=404, detail="strategy not found")
    mappings = await get_documents("accountmapping", {"owner_type": owner_type, "owner_id": owner_id}, limit=200)
    map_idx = {(m["bucket"]).lower(): m["bank_account_id"] for m in mappings}
    transfers: List[TransferInstruction] = []
    for a in strategy.get("allocations", []):
        bucket = a.get("bucket")
        dest = map_idx.get(bucket.lower())
        if not dest:
            # skip buckets without mapping
            continue
        if a.get("type") == "fixed":
            amt = a.get("value", 0)
        else:
            amt = net_m * (a.get("value", 0) / 100.0)
        transfers.append(TransferInstruction(source_account_id=source, destination_account_id=dest, amount=round(amt, 2), bucket=bucket))
    plan = RoutingPlan(owner_type=owner_type, owner_id=owner_id, strategy_id=strategy.get("name"), frequency=req.sync_frequency or "monthly", transfers=transfers)
    await create_document("routingplan", plan.dict())
    await _award_xp(owner_id, "apply_strategy")
    # NOTE: demo only — no actual transfers
    return plan.dict()

# ---------- Net worth ----------

@app.post("/api/networth/snapshot")
async def add_snapshot(s: NetWorthSnapshot):
    await create_document("networthsnapshot", s.dict())
    return {"ok": True}

@app.get("/api/networth")
async def get_networth(owner_type: str, owner_id: str):
    snaps = await get_documents("networthsnapshot", {"owner_type": owner_type, "owner_id": owner_id}, limit=200)
    # compute series
    series = []
    for s in snaps:
        assets = sum(a.get("value", 0) for a in s.get("assets", []))
        liabilities = sum(l.get("value", 0) for l in s.get("liabilities", []))
        series.append({"date": s.get("date"), "net_worth": round(assets - liabilities, 2)})
    series.sort(key=lambda x: x["date"])  # chronological
    return {"series": series, "snapshots": snaps}

# ---------- Industry insights ----------

@app.get("/api/industry/insights")
async def industry_insights(industry: str):
    ind = industry.strip().lower()
    return {"items": INDUSTRY_SEEDS.get(ind, [])}

# ---------- Health check ----------

@app.get("/test")
async def test():
    # verify DB connection
    collist = await get_documents("bankconnection", {}, limit=1)
    return {"ok": True, "db_example": len(collist)}
