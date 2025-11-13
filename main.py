import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Literal, Optional
from math import pow

from database import db, create_document, get_documents
from schemas import Scenario

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
    last = 0
    for low, high, rate, base in brackets:
        if income > low:
            taxable_at_rate = min(income, high) - low
            tax += taxable_at_rate * rate
            last = high
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


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
