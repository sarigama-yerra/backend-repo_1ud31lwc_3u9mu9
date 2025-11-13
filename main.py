import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Literal, Optional, Dict

from database import db, create_document, get_documents
from schemas import Scenario, Strategy

app = FastAPI(title="Finance Optimizer AU")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class CashflowInput(BaseModel):
    income_monthly: float
    expenses_monthly: float
    savings_rate_target: Optional[float] = None  # 0-1

class TaxInput(BaseModel):
    entity: Literal["individual", "company", "sole_trader"]
    taxable_income: float

class SuperInput(BaseModel):
    salary: float
    concessional_contrib: float = 0.0  # pre-tax contributions


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


# --- AU Tax Calculators (2024-25 approximations) ---
# Note: Simplified rates; for guidance only

def calc_individual_tax_2024_25(income: float) -> float:
    # Resident tax rates (AUD) 2024-25, simplified incl. Medicare levy at 2% applied at end
    brackets = [
        (0, 18200, 0.0, 0),
        (18200, 45000, 0.16, 0),  # 16% over 18,200
        (45000, 135000, 0.30, 0), # 30% over 45,000
        (135000, 190000, 0.37, 0),# 37% over 135,000
        (190000, float('inf'), 0.45, 0) # 45% over 190,000
    ]
    tax = 0.0
    for low, high, rate, _ in brackets:
        if income > low:
            taxable_at_rate = min(income, high) - low
            tax += taxable_at_rate * rate
        else:
            break
    medicare = income * 0.02 if income > 30000 else 0  # rough threshold
    return max(tax + medicare, 0.0)


def calc_company_tax(income: float) -> float:
    # Base company tax rate (most base rate entities) ~25%
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
    target = payload.savings_rate_target if payload.savings_rate_target is not None else (surplus / payload.income_monthly if payload.income_monthly > 0 else 0)
    target_amount = payload.income_monthly * max(min(target, 1), 0)
    return {
        "surplus_monthly": round(surplus, 2),
        "savings_rate": round(target, 4),
        "target_savings_amount": round(target_amount, 2)
    }


@app.post("/api/super")
def calculate_super(payload: SuperInput):
    # Superannuation guarantee 2024-25: 11.5%
    sg_rate = 0.115
    sg = payload.salary * sg_rate
    concessional_cap = 27500.0
    excess = max(payload.concessional_contrib - concessional_cap, 0.0)
    return {
        "sg_employer": round(sg, 2),
        "concessional_cap": concessional_cap,
        "excess_contributions": round(excess, 2)
    }


# Scenario persistence endpoints using MongoDB via helper functions
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
        return {"id": inserted_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/scenarios")
def list_scenarios(limit: int = 20):
    try:
        docs = get_documents("scenario", {}, limit)
        # Convert ObjectId to string for JSON
        for d in docs:
            if "_id" in d:
                d["id"] = str(d.pop("_id"))
        return docs
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# -------- Strategies: Prebuilt + AI-like Generator (rule-based) --------

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


def _generate_individual_strategy(inputs: Dict[str, object], results: Dict[str, object]) -> Dict:
    income = float(inputs.get("incomeMonthly") or 0)
    expenses = float(inputs.get("expensesMonthly") or 0)
    savings_rate_target = float(inputs.get("savingsRateTarget") or 0)
    salary = float(inputs.get("salary") or 0)
    concessional = float(inputs.get("concessional") or 0)

    surplus = (results.get("cashflowResult") or {}).get("surplus_monthly")
    eff_rate = (results.get("taxResult") or {}).get("effective_rate")
    sg = (results.get("superResult") or {}).get("sg_employer")
    cap = (results.get("superResult") or {}).get("concessional_cap", 27500)

    steps = []
    assumptions = {
        "income_monthly": income,
        "expenses_monthly": expenses,
        "current_savings_rate_target": savings_rate_target,
        "salary": salary,
        "concessional": concessional,
        "employer_sg": sg,
        "concessional_cap": cap,
        "effective_tax_rate": eff_rate,
    }

    # Savings optimization
    if income > 0:
        current_rate = (surplus / income) if (surplus is not None and income > 0) else savings_rate_target
        desired = max(current_rate, savings_rate_target, 0.20)
        bump = 0.05 if desired < 0.25 else 0.02
        steps.append(f"Increase automated savings by {(bump*100):.0f}% of income until you reach {(max(desired, current_rate)+bump)*100:.0f}% savings rate.")

    # Expense cut
    if expenses > 0:
        steps.append("Identify top 3 expense categories and cap them at 80% of the current level for 90 days.")

    # Superannuation salary sacrifice
    if salary > 0:
        total_concessional = concessional + (sg or 0)
        remaining = max(cap - total_concessional, 0)
        if remaining > 0:
            steps.append(f"Salary sacrifice approximately ${min(remaining, 10000):,.0f} before 30 June to stay within the $27,500 concessional cap.")
        else:
            steps.append("You are at/over the concessional cap; avoid extra pre-tax contributions this year.")

    # Tax withholding tune
    if eff_rate is not None and eff_rate > 0.20:
        steps.append("Review PAYG withholding settings to reduce bill shock; consider quarterly check-ins.")

    estimated_impact = {
        "savings_rate": 0.03,
        "annual_tax": - (results.get("taxResult") or {}).get("tax", 0) * 0.02,
    }

    return {
        "title": "Personal Optimisation Plan",
        "audience": "individual",
        "kind": "generated",
        "description": "Personalised steps based on your income, spending and super setup.",
        "steps": steps,
        "assumptions": assumptions,
        "estimated_impact": estimated_impact,
    }


def _generate_business_strategy(inputs: Dict[str, object], results: Dict[str, object]) -> Dict:
    income = float(inputs.get("incomeMonthly") or 0)
    expenses = float(inputs.get("expensesMonthly") or 0)
    steps = [
        "Negotiate supplier contracts; target 5–10% reduction on top 5 costs.",
        "Shift fixed costs to variable where possible to improve resilience.",
        "Tighten AR collections; aim for DSO < 35 days.",
    ]
    if income and expenses:
        margin = (income - expenses) / income
        if margin < 0.15:
            steps.append("Introduce weekly spend reviews and require approvals >$1,000.")
    return {
        "title": "Business Cashflow Tune-Up",
        "audience": "business",
        "kind": "generated",
        "description": "Practical actions to widen margins and improve cash conversion.",
        "steps": steps,
        "assumptions": {"income_monthly": income, "expenses_monthly": expenses},
        "estimated_impact": {"operating_margin": 0.02},
    }


@app.get("/api/strategies/prebuilt")
def get_prebuilt_strategies(audience: Optional[Literal["individual", "business"]] = None):
    items = [s for s in PREBUILT_STRATEGIES if (audience is None or s["audience"] == audience)]
    return items


@app.post("/api/strategies/generate")
def generate_strategy(payload: GenerateStrategyInput):
    if payload.scenario_type == "individual":
        strat = _generate_individual_strategy(payload.inputs or {}, payload.results or {})
    else:
        strat = _generate_business_strategy(payload.inputs or {}, payload.results or {})

    # Attach optional info
    if payload.title:
        strat["title"] = payload.title
    if payload.scenario_id:
        strat["scenario_id"] = payload.scenario_id

    return strat


class SaveStrategyInput(BaseModel):
    title: str
    audience: Literal["individual", "business"]
    kind: Literal["prebuilt", "generated"]
    description: Optional[str] = None
    steps: List[str] = []
    assumptions: Dict[str, object] = {}
    estimated_impact: Dict[str, float] = {}
    scenario_id: Optional[str] = None


@app.post("/api/strategies")
def save_strategy(payload: SaveStrategyInput):
    doc = Strategy(**payload.model_dump())
    try:
        inserted_id = create_document("strategy", doc)
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


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
