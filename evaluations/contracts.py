"""Versioned case contracts, separate from production scheduling and reply code."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Verdict = Literal["PASS", "FAIL", "NOT RUN"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)


class InputMessage(Contract):
    session: Literal["A", "B"] = "A"
    message: str = Field(min_length=1, max_length=4000)


class ExpectedCall(Contract):
    session: Literal["A", "B"] = "A"
    name: str
    arguments: dict


class Case(Contract):
    id: str
    title: str
    critical: bool
    rationale: str
    input: list[InputMessage] = Field(min_length=1)
    initial_db_state: dict
    expected_tool_calls: list[ExpectedCall]
    forbidden_actions: list[str]
    expected_db_state: dict
    expected_response_constraints: dict
    expected_raw_verdict: Verdict
    script: dict[str, list[dict]]
    exercise: Literal[
        "simple", "retry", "expired", "superseded", "confirmed", "conflict", "isolation_restart"
    ] = "simple"


class Dataset(Contract):
    version: str
    prompt_version: str
    clock: str
    catalog: dict
    cases: list[Case] = Field(min_length=20, max_length=25)
