import os
import random
import string
from datetime import datetime, timedelta
from typing import List, Literal, Optional, Dict

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from database import db, create_document, get_documents
from schemas import Scenario, Strategy, BankConnection, BankAccount, BankTransaction, GamificationProfile

app = FastAPI(title="Finance Optimizer AU")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -------------------- Helpers --------------------
class CashflowInput(BaseModel):
    income_monthly: float
    expenses_monthly: float
    savings_rate_target: Optional[float] = None  # 0-1


class TaxInput(BaseModel):
    entity: Literal["individual", "company", "sole_trader"]
    taxable_income: float


class SuperInput(BaseModel):
    salary: float
    concessional_contrib: float = 0.0


FREQ_TO_MONTH = {
    "weekly": 52 / 12,
    "fortnightly": 26 / 12,
    "monthly": 1,
    "annual": 1 / 12,
}


def to_monthly(amount: float, frequency: str) -> float:
    return float(amount) * FREQ_TO_MONTH.get(frequency, 1)


# -------------------- Root & test --------------------
@app.get("/")
def read_root():
    return {"message": "Finance Optimizer AU Backend"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": None,
        "database_name": None,
        "connection_status": "Not Connected",
        "collections": []
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:80]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:80]}"
    return response


# -------------------- Gamification helpers --------------------

def _get_latest_profile() -> Dict[str, object]:
    try:
        items = get_documents("gamificationprofile", {}, 1)
        if items:
            return items[0]
    except Exception:
        pass
    return {"xp": 0, "level": 1, "badges": [], "streak_days": 0, "quests": []}


def _compute_level(xp: int) -> int:
    return max(1, 1 + xp // 200)


def _award_xp(amount: int, reason: str) -> Dict[str, object]:
    current = _get_latest_profile()
    xp = int(current.get("xp", 0)) + amount
    level = _compute_level(xp)
    badges = list(current.get("badges", []))
    if reason == "link_bank" and "Banked Up" not in badges:
        badges.append("Banked Up")
    if reason == "save_scenario" and "Planner" not in badges:
        badges.append("Planner")
    if reason == "save_strategy" and "Strategist" not in badges:
        badges.append("Strategist")
    if reason == "apply_strategy" and "Executor" not in badges:
        badges.append("Executor")
    if reason == "create_profile" and "Ready Player" not in badges:
        badges.append("Ready Player")
    profile = GamificationProfile(
        xp=xp, level=level, badges=badges, streak_days=current.get("streak_days", 0), quests=current.get("quests", [])
    )
    try:
        create_document("gamificationprofile", profile)
    except Exception:
        pass
    return profile.model_dump()


# -------------------- Calculators --------------------

def calc_individual_tax_2024_25(income: float) -> float:
    brackets = [
        (0, 18200, 0.0, 0),
        (18200, 45000, 0.16, 0),
        (45000, 135000, 0.30, 0),
        (135000, 190000, 0.37, 0),
        (190000, float('inf'), 0.45, 0)
    ]
    tax = 0.0
    for low, high, rate, _ in brackets:
        if income > low:
            taxable_at_rate = min(income, high) - low
            tax += taxable_at_rate * rate
        else:
            break
    medicare = income * 0.02 if income > 30000 else 0
    return max(tax + medicare, 0.0)


def calc_company_tax(income: float) -> float:
    return max(income * 0.25, 0.0)


def calc_sole_trader_tax(income: float) -> float:
    return calc_individual_tax_2024_25(income)


@app.post("/api/tax")
def calculate_tax(payload: TaxInput):
    if payload.taxable_income < 0:
        raise HTTPException(status_code=400, detail="Income must be non-negative")
    if payload.entity == "individual":
        tax = calc_individual_tax_2024_25(payload.taxable_income)
    elif payload.entity == "company":
        tax = calc_company_tax(payload.taxable_income)
    else:
        tax = calc_sole_trader_tax(payload.taxable_income)
    effective_rate = tax / payload.taxable_income if payload.taxable_income > 0 else 0
    return {"tax": round(tax, 2), "effective_rate": round(effective_rate, 4)}


@app.post("/api/cashflow")
def calculate_cashflow(payload: CashflowInput):
    surplus = payload.income_monthly - payload.expenses_monthly
    target = payload.savings_rate_target if payload.savings_rate_target is not None else (
        surplus / payload.income_monthly if payload.income_monthly > 0 else 0
    )
    target_amount = payload.income_monthly * max(min(target, 1), 0)
    return {
        "surplus_monthly": round(surplus, 2),
        "savings_rate": round(target, 4),
        "target_savings_amount": round(target_amount, 2)
    }


@app.post("/api/super")
def calculate_super(payload: SuperInput):
    sg_rate = 0.115
    sg = payload.salary * sg_rate
    concessional_cap = 27500.0
    excess = max(payload.concessional_contrib - concessional_cap, 0.0)
    return {
        "sg_employer": round(sg, 2),
        "concessional_cap": concessional_cap,
        "excess_contributions": round(excess, 2)
    }


# -------------------- Scenario + Strategies (existing) --------------------
class SaveScenarioInput(BaseModel):
    name: str
    scenario_type: Literal["individual", "business"]
    inputs: dict
    results: dict
    notes: Optional[str] = None


@app.post("/api/scenarios")
def save_scenario(payload: SaveScenarioInput):
    scenario = Scenario(
        name=payload.name,
        scenario_type=payload.scenario_type,
        inputs=payload.inputs,
        results=payload.results,
        notes=payload.notes,
    )
    try:
        inserted_id = create_document("scenario", scenario)
        _award_xp(50, "save_scenario")
        return {"id": inserted_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/scenarios")
def list_scenarios(limit: int = 20):
    try:
        docs = get_documents("scenario", {}, limit)
        for d in docs:
            if "_id" in d:
                d["id"] = str(d.pop("_id"))
        return docs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


PREBUILT_STRATEGIES: List[Dict] = [
    {
        "title": "Emergency Fund First",
        "audience": "individual",
        "kind": "prebuilt",
        "description": "Build 3–6 months of essential expenses before aggressive investing.",
        "steps": [
            "Open a high-interest savings account (separate).",
            "Automate transfers the day after payday to reach target.",
            "Pause discretionary spending >$X until 1 month buffer is built.",
            "Grow to 3–6 months based on job stability and dependants.",
        ],
        "estimated_impact": {"savings_rate": 0.05},
    },
    {
        "title": "Salary Sacrifice to Super (Tax-Efficient)",
        "audience": "individual",
        "kind": "prebuilt",
        "description": "Direct pre-tax dollars to super up to the concessional cap to lower taxable income.",
        "steps": [
            "Confirm current concessional contributions YTD (including employer SG).",
            "Elect salary sacrifice to stay below the $27,500 cap.",
            "Review marginal tax rate vs long-term liquidity needs.",
        ],
        "estimated_impact": {"effective_tax_rate": -0.02},
    },
    {
        "title": "Lean Operating Budget",
        "audience": "business",
        "kind": "prebuilt",
        "description": "Trim recurring expenses and renegotiate suppliers to widen margins.",
        "steps": [
            "List top 10 recurring costs; target 10–15% reduction.",
            "Bid out key suppliers; ask for volume discounts.",
            "Delay non-critical capex until cash conversion improves.",
        ],
        "estimated_impact": {"operating_margin": 0.03},
    },
]


class GenerateStrategyInput(BaseModel):
    scenario_type: Literal["individual", "business"]
    inputs: Dict[str, object] = {}
    results: Dict[str, object] = {}
    title: Optional[str] = None
    scenario_id: Optional[str] = None


@app.get("/api/strategies/prebuilt")
def get_prebuilt_strategies(audience: Optional[Literal["individual", "business"]] = None):
    items = [s for s in PREBUILT_STRATEGIES if (audience is None or s["audience"] == audience)]
    return items


class SaveStrategyInput(BaseModel):
    title: str
    audience: Literal["individual", "business"]
    kind: Literal["prebuilt", "generated", "custom"] = "custom"
    description: Optional[str] = None
    steps: List[str] = []
    assumptions: Dict[str, object] = {}
    estimated_impact: Dict[str, float] = {}
    scenario_id: Optional[str] = None
    allocations: List[Dict[str, object]] = Field(default_factory=list)


@app.post("/api/strategies")
def save_strategy(payload: SaveStrategyInput):
    doc = Strategy(
        title=payload.title,
        audience=payload.audience,
        kind=payload.kind,
        description=payload.description,
        steps=payload.steps,
        assumptions={**payload.assumptions, "allocations": payload.allocations},
        estimated_impact=payload.estimated_impact,
        scenario_id=payload.scenario_id,
    )
    try:
        inserted_id = create_document("strategy", doc)
        _award_xp(75, "save_strategy")
        return {"id": inserted_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/strategies")
def list_strategies(limit: int = 50, audience: Optional[Literal["individual", "business"]] = None):
    try:
        query: Dict[str, object] = {}
        if audience:
            query["audience"] = audience
        docs = get_documents("strategy", query, limit)
        for d in docs:
            if "_id" in d:
                d["id"] = str(d.pop("_id"))
        return docs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------- Profiles --------------------
class UserProfile(BaseModel):
    user_id: str
    name: str
    occupation: Optional[str] = None
    tax_residency: Literal["resident", "non_resident"] = "resident"
    income_frequency: Literal["weekly", "fortnightly", "monthly", "annual"] = "monthly"
    master_salary_account_id: Optional[str] = None


class BusinessProfile(BaseModel):
    business_id: str
    name: str
    abn_acn: Optional[str] = None
    industry: Optional[str] = None
    tax_residency: Literal["resident", "non_resident"] = "resident"
    master_income_account_id: Optional[str] = None


@app.post("/api/profile/user")
def save_user_profile(payload: UserProfile):
    try:
        inserted = create_document("userprofile", payload)
        _award_xp(40, "create_profile")
        return {"id": inserted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/profile/user")
def get_user_profiles(limit: int = 10):
    try:
        docs = get_documents("userprofile", {}, limit)
        for d in docs:
            if "_id" in d:
                d["id"] = str(d.pop("_id"))
        return {"items": docs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/profile/business")
def save_business_profile(payload: BusinessProfile):
    try:
        inserted = create_document("businessprofile", payload)
        _award_xp(40, "create_profile")
        return {"id": inserted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/profile/business")
def get_business_profiles(limit: int = 10):
    try:
        docs = get_documents("businessprofile", {}, limit)
        for d in docs:
            if "_id" in d:
                d["id"] = str(d.pop("_id"))
        return {"items": docs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------- Income & Expenses --------------------
class IncomeEntry(BaseModel):
    owner_type: Literal["user", "business"]
    owner_id: str
    source: str
    amount: float
    frequency: Literal["weekly", "fortnightly", "monthly", "annual"] = "monthly"


class ExpenseEntry(BaseModel):
    owner_type: Literal["user", "business"]
    owner_id: str
    name: str
    amount: float
    frequency: Literal["weekly", "fortnightly", "monthly", "annual"] = "monthly"
    category: Optional[str] = None
    deductible: bool = False


@app.post("/api/income")
def add_income(payload: IncomeEntry):
    try:
        inserted = create_document("incomeentry", payload)
        return {"id": inserted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/income")
def list_income(owner_type: Literal["user", "business"], owner_id: str, limit: int = 50):
    try:
        docs = get_documents("incomeentry", {"owner_type": owner_type, "owner_id": owner_id}, limit)
        for d in docs:
            if "_id" in d:
                d["id"] = str(d.pop("_id"))
        total_monthly = sum(to_monthly(d.get("amount", 0), d.get("frequency", "monthly")) for d in docs)
        return {"items": docs, "total_monthly": round(total_monthly, 2)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/expenses")
def add_expense(payload: ExpenseEntry):
    try:
        inserted = create_document("expenseentry", payload)
        return {"id": inserted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/expenses")
def list_expenses(owner_type: Literal["user", "business"], owner_id: str, limit: int = 100):
    try:
        docs = get_documents("expenseentry", {"owner_type": owner_type, "owner_id": owner_id}, limit)
        for d in docs:
            if "_id" in d:
                d["id"] = str(d.pop("_id"))
        total_monthly = sum(to_monthly(d.get("amount", 0), d.get("frequency", "monthly")) for d in docs)
        return {"items": docs, "total_monthly": round(total_monthly, 2)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------- Deductions (AU) --------------------
AU_DEDUCTIONS_BASE = [
    "Home office equipment (depreciating assets)",
    "Work-related travel (km or logbook method)",
    "Professional memberships and subscriptions",
    "Self-education and training directly related to work",
    "Phone and internet for work usage proportion",
]

INDUSTRY_SEEDS: Dict[str, List[str]] = {
    "horeca": ["Uniforms and laundering", "Food safety certifications", "Work footwear"],
    "speciality stores": ["Point-of-sale software", "Packaging for products", "In-store fixtures"],
    "it consulting": ["Cloud services for client delivery", "Software licences", "Laptop and accessories"],
    "healthcare": ["CPD courses", "Registration renewal", "Medical equipment and consumables"],
}


class DeductionCatalogItem(BaseModel):
    title: str
    occupation: Optional[str] = None
    industry: Optional[str] = None


@app.get("/api/deductions")
def get_deductions(occupation: Optional[str] = None, industry: Optional[str] = None):
    suggestions = list(AU_DEDUCTIONS_BASE)
    if industry and industry in INDUSTRY_SEEDS:
        suggestions.extend(INDUSTRY_SEEDS[industry])
    try:
        query: Dict[str, object] = {}
        if occupation:
            query["occupation"] = occupation
        if industry:
            query["industry"] = industry
        cat = get_documents("deductioncatalogitem", query, 100)
        suggestions.extend([c.get("title") for c in cat])
    except Exception:
        pass
    # Industry insights demo
    insights = [{"title": f"{industry.title() if industry else 'General'} cost-saving ideas", "type": "insight"}]
    return {"suggestions": suggestions, "insights": insights}


@app.post("/api/deductions/catalog")
def add_to_deduction_catalog(item: DeductionCatalogItem):
    try:
        inserted = create_document("deductioncatalogitem", item)
        return {"id": inserted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------- Account mappings --------------------
class AccountMapping(BaseModel):
    owner_type: Literal["user", "business"]
    owner_id: str
    bucket: str
    bank_account_id: str


@app.post("/api/account-mapping")
def save_account_mapping(payload: AccountMapping):
    try:
        inserted = create_document("accountmapping", payload)
        return {"id": inserted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/account-mapping")
def list_account_mappings(owner_type: Literal["user", "business"], owner_id: str, limit: int = 100):
    try:
        docs = get_documents("accountmapping", {"owner_type": owner_type, "owner_id": owner_id}, limit)
        for d in docs:
            if "_id" in d:
                d["id"] = str(d.pop("_id"))
        return {"items": docs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------- Strategy simulate/apply --------------------
class StrategySimulateRequest(BaseModel):
    owner_type: Literal["user", "business"]
    owner_id: str
    strategy_id: str  # using preset name for demo


class StrategyApplyRequest(StrategySimulateRequest):
    sync_frequency: Literal["weekly", "fortnightly", "monthly"] = "monthly"


DEFAULT_PRESETS: Dict[str, List[Dict[str, object]]] = {
    "Debt Free Fast": [
        {"bucket": "Debt", "type": "percent", "value": 40},
        {"bucket": "Essentials", "type": "percent", "value": 40},
        {"bucket": "Emergency", "type": "percent", "value": 10},
        {"bucket": "Investments", "type": "percent", "value": 10},
    ],
    "FIRE": [
        {"bucket": "Investments", "type": "percent", "value": 50},
        {"bucket": "Essentials", "type": "percent", "value": 30},
        {"bucket": "Emergency", "type": "percent", "value": 10},
        {"bucket": "Discretionary", "type": "percent", "value": 10},
    ],
    "Aggressive Investment": [
        {"bucket": "Investments", "type": "percent", "value": 60},
        {"bucket": "Essentials", "type": "percent", "value": 25},
        {"bucket": "Emergency", "type": "percent", "value": 5},
        {"bucket": "Discretionary", "type": "percent", "value": 10},
    ],
    "Balanced": [
        {"bucket": "Investments", "type": "percent", "value": 30},
        {"bucket": "Essentials", "type": "percent", "value": 45},
        {"bucket": "Emergency", "type": "percent", "value": 10},
        {"bucket": "Discretionary", "type": "percent", "value": 15},
    ],
}


def _load_allocations_for_strategy(name: str) -> List[Dict[str, object]]:
    # Try custom strategies first
    try:
        docs = get_documents("strategy", {"title": name}, 1)
        if docs:
            allocs = ((docs[0].get("assumptions") or {}).get("allocations") or [])
            if allocs:
                return allocs
    except Exception:
        pass
    return DEFAULT_PRESETS.get(name, DEFAULT_PRESETS["Balanced"])[:]


def _monthly_income_expenses(owner_type: str, owner_id: str) -> Dict[str, float]:
    incomes = get_documents("incomeentry", {"owner_type": owner_type, "owner_id": owner_id}, 1000)
    expenses = get_documents("expenseentry", {"owner_type": owner_type, "owner_id": owner_id}, 1000)
    inc_m = sum(to_monthly(i.get("amount", 0), i.get("frequency", "monthly")) for i in incomes)
    exp_m = sum(to_monthly(e.get("amount", 0), e.get("frequency", "monthly")) for e in expenses)
    return {"income_monthly": inc_m, "expenses_monthly": exp_m}


def _next_run_date(freq: str) -> str:
    today = datetime.utcnow().date()
    if freq == "weekly":
        d = today + timedelta(days=7)
    elif freq == "fortnightly":
        d = today + timedelta(days=14)
    else:
        # next month same day
        month = today.month + 1
        year = today.year + (1 if month > 12 else 0)
        month = 1 if month > 12 else month
        day = min(today.day, 28)
        d = datetime(year, month, day).date()
    return d.isoformat()


@app.post("/api/strategy/simulate")
def strategy_simulate(payload: StrategySimulateRequest):
    try:
        allocs = _load_allocations_for_strategy(payload.strategy_id)
        totals = _monthly_income_expenses(payload.owner_type, payload.owner_id)
        surplus = max(totals["income_monthly"] - totals["expenses_monthly"], 0)
        breakdown = []
        remaining = surplus
        fixed_sum = sum(a.get("value", 0) for a in allocs if a.get("type") == "fixed")
        for a in allocs:
            if a.get("type") == "fixed":
                amt = min(remaining, float(a.get("value", 0)))
                breakdown.append({"bucket": a.get("bucket"), "amount": round(amt, 2)})
                remaining -= amt
        percent_sum = sum(a.get("value", 0) for a in allocs if a.get("type") == "percent")
        for a in allocs:
            if a.get("type") == "percent" and percent_sum > 0:
                amt = remaining * (float(a.get("value", 0)) / 100.0)
                breakdown.append({"bucket": a.get("bucket"), "amount": round(amt, 2)})
        result = {
            "income_monthly": round(totals["income_monthly"], 2),
            "expenses_monthly": round(totals["expenses_monthly"], 2),
            "surplus_monthly": round(surplus, 2),
            "breakdown": breakdown,
        }
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class TransferInstruction(BaseModel):
    bucket: str
    source_account_id: Optional[str] = None
    destination_account_id: Optional[str] = None
    amount: float


@app.post("/api/strategy/apply")
def strategy_apply(payload: StrategyApplyRequest):
    try:
        sim = strategy_simulate(StrategySimulateRequest(owner_type=payload.owner_type, owner_id=payload.owner_id, strategy_id=payload.strategy_id))
        # load mappings
        mappings = get_documents("accountmapping", {"owner_type": payload.owner_type, "owner_id": payload.owner_id}, 100)
        map_by_bucket = {m.get("bucket").lower(): m.get("bank_account_id") for m in mappings}
        # determine master account
        source_account_id = None
        if payload.owner_type == "user":
            profs = get_documents("userprofile", {"user_id": payload.owner_id}, 1)
            if profs:
                source_account_id = profs[0].get("master_salary_account_id")
        else:
            profs = get_documents("businessprofile", {"business_id": payload.owner_id}, 1)
            if profs:
                source_account_id = profs[0].get("master_income_account_id")
        # transfers
        transfers: List[TransferInstruction] = []
        for item in sim.get("breakdown", []):
            dest = map_by_bucket.get(str(item.get("bucket", "")).lower())
            transfers.append(TransferInstruction(bucket=item.get("bucket"), source_account_id=source_account_id, destination_account_id=dest, amount=item.get("amount", 0)))
        # project balances
        accounts = get_documents("bankaccount", {}, 100)
        bal_by_id = {a.get("account_id"): float(a.get("balance", 0)) for a in accounts}
        projected: Dict[str, float] = dict(bal_by_id)
        for t in transfers:
            if t.source_account_id:
                projected[t.source_account_id] = projected.get(t.source_account_id, 0) - t.amount
            if t.destination_account_id:
                projected[t.destination_account_id] = projected.get(t.destination_account_id, 0) + t.amount
        plan = {
            "sync_frequency": payload.sync_frequency,
            "next_run": _next_run_date(payload.sync_frequency),
            "transfers": [ti.model_dump() for ti in transfers],
            "projected_balances": {k: round(v, 2) for k, v in projected.items()},
        }
        # store plan demo
        create_document("routingplan", plan)
        _award_xp(25, "apply_strategy")
        return plan
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------- Net worth --------------------
class Asset(BaseModel):
    name: str
    value: float


class Liability(BaseModel):
    name: str
    value: float


class NetWorthSnapshot(BaseModel):
    owner_type: Literal["user", "business"]
    owner_id: str
    date: str
    assets: List[Asset] = Field(default_factory=list)
    liabilities: List[Liability] = Field(default_factory=list)


@app.post("/api/networth/snapshot")
def save_networth_snapshot(payload: NetWorthSnapshot):
    try:
        inserted = create_document("networthsnapshot", payload)
        return {"id": inserted}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/networth")
def list_networth(owner_type: Literal["user", "business"], owner_id: str, limit: int = 100):
    try:
        docs = get_documents("networthsnapshot", {"owner_type": owner_type, "owner_id": owner_id}, limit)
        series = []
        for d in docs:
            assets_v = sum(float(a.get("value", 0)) for a in d.get("assets", []))
            liab_v = sum(float(l.get("value", 0)) for l in d.get("liabilities", []))
            series.append({
                "date": d.get("date"),
                "assets": round(assets_v, 2),
                "liabilities": round(liab_v, 2),
                "net_worth": round(assets_v - liab_v, 2),
            })
        series.sort(key=lambda x: x.get("date", ""))
        return {"series": series}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class NetWorthImportPayload(BaseModel):
    owner_type: Literal["user", "business"]
    owner_id: str
    rows: List[Dict[str, str]]  # {date, assets, liabilities}


@app.post("/api/networth/import")
def import_networth(payload: NetWorthImportPayload):
    try:
        for r in payload.rows:
            date = r.get("date")
            assets = float(r.get("assets", 0))
            liabilities = float(r.get("liabilities", 0))
            snap = NetWorthSnapshot(
                owner_type=payload.owner_type,
                owner_id=payload.owner_id,
                date=date,
                assets=[Asset(name="Total Assets", value=assets)],
                liabilities=[Liability(name="Total Liabilities", value=liabilities)],
            )
            create_document("networthsnapshot", snap)
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------- Industry insights --------------------
@app.get("/api/industry/insights")
def industry_insights(industry: str):
    ideas = INDUSTRY_SEEDS.get(industry, [])
    items = [{"title": i, "type": "tip"} for i in ideas]
    if not items:
        items = [{"title": "Optimise supplier contracts and review recurring SaaS.", "type": "tip"}]
    return items


# -------------------- CDR mock --------------------
class CdrStartInput(BaseModel):
    provider: Literal["NAB", "CBA", "WBC", "ANZ", "ING", "AMP"]


def _gen_id(prefix: str) -> str:
    return prefix + "_" + ''.join(random.choices(string.ascii_lowercase + string.digits, k=10))


@app.post("/api/cdr/connect/start")
def cdr_connect_start(payload: CdrStartInput):
    connection_id = _gen_id("cdr")
    redirect_url = f"https://cdr.mock/consent?connection_id={connection_id}&provider={payload.provider}"
    return {"connection_id": connection_id, "redirect_url": redirect_url}


class CdrCompleteInput(BaseModel):
    connection_id: Optional[str] = None
    provider: Literal["NAB", "CBA", "WBC", "ANZ", "ING", "AMP"]


@app.post("/api/cdr/connect/complete")
def cdr_connect_complete(payload: CdrCompleteInput):
    try:
        conn = BankConnection(provider=payload.provider, status="connected", accounts_linked=2)
        create_document("bankconnection", conn)

        checking_id = _gen_id("acct")
        savings_id = _gen_id("acct")
        accounts = [
            BankAccount(provider=payload.provider, account_id=checking_id, name="Everyday Account", bsb="083-001", number_masked="••• 123", balance=2450.75),
            BankAccount(provider=payload.provider, account_id=savings_id, name="High Interest Saver", bsb="083-002", number_masked="••• 789", balance=10250.40),
        ]
        for a in accounts:
            create_document("bankaccount", a)

        txns = [
            BankTransaction(provider=payload.provider, account_id=checking_id, txn_id=_gen_id("txn"), date="2025-11-01", description="Coffee Shop", amount=-5.5, category="Food & Drink"),
            BankTransaction(provider=payload.provider, account_id=checking_id, txn_id=_gen_id("txn"), date="2025-11-02", description="Grocery Store", amount=-86.2, category="Groceries"),
            BankTransaction(provider=payload.provider, account_id=savings_id, txn_id=_gen_id("txn"), date="2025-11-03", description="Interest", amount=8.34, category="Income"),
        ]
        for t in txns:
            create_document("banktransaction", t)

        _award_xp(150, "link_bank")

        return {"status": "connected", "accounts": [a.model_dump() for a in accounts]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/cdr/accounts")
def cdr_accounts(limit: int = 10):
    try:
        docs = get_documents("bankaccount", {}, limit)
        for d in docs:
            if "_id" in d:
                d["id"] = str(d.pop("_id"))
                d.setdefault("number", d.get("number_masked"))
        return {"accounts": docs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/cdr/transactions")
def cdr_transactions(account_id: Optional[str] = None, limit: int = 25):
    try:
        query: Dict[str, object] = {}
        if account_id:
            query["account_id"] = account_id
        docs = get_documents("banktransaction", query, limit)
        for d in docs:
            if "_id" in d:
                d["id"] = str(d.pop("_id"))
        return {"transactions": docs}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------------------- Gamification endpoints --------------------
@app.get("/api/gamification/profile")
def get_gamification_profile():
    profile = _get_latest_profile()
    profile.setdefault("xp", 0)
    profile.setdefault("level", _compute_level(profile.get("xp", 0)))
    profile.setdefault("badges", [])
    profile.setdefault("streak_days", 0)
    profile.setdefault("quests", [
        {"id": "q1", "title": "Run a tax calc", "xp": 10, "done": False},
        {"id": "q2", "title": "Save a scenario", "xp": 50, "done": False},
        {"id": "q3", "title": "Link a bank account", "xp": 150, "done": False},
    ])
    return profile


class AwardInput(BaseModel):
    amount: int
    reason: str


@app.post("/api/gamification/award")
def award_xp(payload: AwardInput):
    profile = _award_xp(payload.amount, payload.reason)
    return profile


# -------------------- Exports --------------------
@app.get("/api/export/routing-plan.csv")
def export_routing_csv(limit: int = 1):
    try:
        plans = get_documents("routingplan", {}, limit)
        if not plans:
            return "no data"
        p = plans[0]
        rows = ["bucket,source_account_id,destination_account_id,amount"]
        for t in p.get("transfers", []):
            rows.append(f"{t.get('bucket')},{t.get('source_account_id')},{t.get('destination_account_id')},{t.get('amount')}")
        return "\n".join(rows)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/export/networth.csv")
def export_networth_csv(owner_type: Literal["user", "business"] = "user", owner_id: str = "demo-user"):
    try:
        series = list_networth(owner_type=owner_type, owner_id=owner_id).get("series", [])  # type: ignore
        rows = ["date,assets,liabilities,net_worth"]
        for s in series:
            rows.append(f"{s.get('date')},{s.get('assets')},{s.get('liabilities')},{s.get('net_worth')}")
        return "\n".join(rows)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
