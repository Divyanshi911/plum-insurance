import os
import asyncio
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.tools.agent_tool import (
    AgentTool,
    ToolContext,
    BaseTool,
)
from google.adk.tools import FunctionTool
from google.adk.agents.callback_context import CallbackContext
from google.genai import types
from google.adk.runners import Runner
from typing import Optional
from pydantic import BaseModel, Field
from google.adk.events import Event, EventActions
# from tools import document_tool,decision_tool,extraction_tool,policy_tool,preprocessing_tool
from backend.tools.document_tool import document_tool_fn as document_tool
from backend.tools.decision_tool import decision_tool_fn as decision_tool
from backend.tools.extraction_tool import extraction_tool_fn as extraction_tool
from backend.tools.policy_tool import policy_tool_fn as policy_tool
from backend.tools.preprocessing_tool import preprocess_upload_files as preprocessing_tool
# orchestrator_agent.py
from backend.tools.preprocessing_tool import preprocess_upload_files
preprocessing_tool_wrapped = FunctionTool(func=preprocess_upload_files)
Model = "gemini-3.5-flash"

document_agent = LlmAgent(
    name='DocumentAgent',
    model=Model,
    instruction="""You are the DocumentGate Agent.""",
    description="""Your job is to verify that the correct types of documents have been uploaded for a claim, based on the policy’s document requirements.
        Inputs:
        * claim_category (e.g. CONSULTATION, DIAGNOSTIC, PHARMACY)
        * documents_meta: filenames and content types of uploaded documents
        * policy document_requirements from policy_terms.json
        You must:
        * Infer document types from filenames (PRESCRIPTION, HOSPITAL_BILL, LAB_REPORT, PHARMACY_BILL, DISCHARGE_SUMMARY, UNKNOWN).
        * Compare the inferred types against the required and optional types for the given claim_category.
        * If any required type is missing, return blocking errors with specific, actionable messages (e.g. “Missing HOSPITAL_BILL for CONSULTATION”).
        * If all required types are present, mark the gate as passed.
        * You must not call any LLM or apply monetary policy rules.
        * Your output must clearly list:
            uploaded_types
            required_types
            ok flag
            errors list, which can be turned into DocumentError objects and a trace step.
        Call [policy_tool] to check against all the policies and give results in json format to {doc_json}. 
        """,
    output_key="doc_json",
    tools=[document_tool], 
)

extraction_agent = LlmAgent(
    name='ExtractionAgent',
    model=Model,
    instruction="""You are the Extraction Agent for medical documents in a health insurance claims system.""",
    description="""Your job is to read preprocessed documents and extract structured JSON fields using an LLM.
        Inputs:
        * A list of PreprocessedDocument objects (already preprocessed from images or PDFs)
        * Optional doc_type hints (PRESCRIPTION, HOSPITAL_BILL, LAB_REPORT, PHARMACY_BILL, UNKNOWN)
        You must:
        * Build an extraction prompt based on the doc_type hint.
        * Call the LLM client with the prompt and either images or text from the preprocessed document.
        * Parse the JSON response from the LLM and normalize it into a consistent structure for each document:
        * filename
        * doc_type
        * fields (the raw extracted JSON)
        * confidence
        * low_confidence_fields
        * validation_issues
        * Record any LLM errors as extraction_errors and mark low_confidence when needed.
        You must not apply insurance policy rules or decide APPROVED/PARTIAL/REJECTED; you only extract information.
        Your output is a dict containing: extracted_documents, extraction_errors, and a low_confidence flag.
        Use [extraction_tool] to take out all the data and give it out in {extracted_json} in json format.""",
    output_key="extracted_json",
    tools=[extraction_tool], 
)

preprocessing_agent = LlmAgent(
    name='PreprocessingAgent',
    model=Model,
    instruction="""You are the Preprocessing Agent for a health insurance claims system.""",
    description="""Your job is to take uploaded documents (images or PDFs) and convert them into a clean, model‑ready format.
        You must:
        * For image files: convert bytes to images, deskew, denoise, enhance contrast, and output PNG bytes.
        * For PDFs:
        * If it is a text PDF: extract text.
        * If it is an image PDF: render each page to an image and preprocess it like an image file.
        * Attach any available document type hint (e.g. PRESCRIPTION, HOSPITAL_BILL) to each preprocessed document.
        You must not do any LLM extraction or policy reasoning.
        Your output is a list of PreprocessedDocument objects that downstream agents can use.

        Call the [preprocessing_tool] with the raw files and hints and give out the results in json format to {preprocessed_json}.""",
    output_key="preprocessed_json",
    tools=[preprocessing_tool], 
)

policy_agent = LlmAgent(
    name='PolicyAgent',
    model=Model,
    instruction="""You are the Policy Agent for a health insurance claims system.""",
    description="""Your job is to apply deterministic policy rules to a claim using policy_terms.json and the extracted document data.
        Inputs:
        * raw claim details (member_id, claim_category, treatment_date, claimed_amount)
        * policy_terms from policy_terms.json
        * extracted_documents and any extraction_errors
        * document_errors from DocumentGate
        You must:
        * Apply coverage rules for the relevant OPD category (e.g. consultation, diagnostic, pharmacy, dental, vision, alternative_medicine), including sub-limits, copay, and any special requirements such as prescriptions or reports.
        * Respect submission rules (deadlines, minimum claim amount) and relevant exclusions or waiting periods where applicable.
        * Use extracted fields (like amounts, dates, diagnosis) when available, and degrade gracefully when data is missing or low-confidence.
        * Build and return a Decision object:
          * decision: APPROVED, PARTIAL, REJECTED, or MANUAL_REVIEW
          * approved_amount and claimed_amount
          * reason: a clear human-readable explanation
          * confidence: numeric confidence for the decision
          * trace: steps explaining which rules were applied and what passed or failed
          * document_errors: any blocking document problems already found
        You must not call the LLM or do free-form reasoning; apply only the explicit rules defined in policy_terms.json.
        This agent wraps your deterministic policy logic (e.g. evaluate_consultation_claim, later extended to all categories) into a json output called {policy_json} by using
        [policy_tool].""",
    output_key="policy_json",
    tools=[policy_tool], 
)

decision_agent = LlmAgent(
    name='DecisionAgent',
    model=Model,
    instruction="""You are the Decision Agent.""",
    description="""Your job is to take the internal Decision object from the policy layer and convert it into a ClaimResponse that the frontend can consume.
                Inputs:
                * Decision: decision, approved_amount, claimed_amount, confidence, reason, trace, document_errors, notes, rejection_reasons
                You must:
                * Generate or accept a claim_id.
                * Map all fields from Decision into ClaimResponse.
                * Preserve the full trace and document_errors for explainability.
                * Ensure the object is consistent and ready to be serialized as JSON for the API.
                * You must not re-apply policy rules or call the LLM.
                * Your output is a single ClaimResponse model.
                This agent should use [decision_tool] and give out its response in json format to {decision_json}.
                """,
    output_key="decision_json",
    tools=[decision_tool], 
)
orchestrator = SequentialAgent(
            # model=Model,
            name='OrchestratorAgent',
            sub_agents=[
                preprocessing_agent,
                document_agent,
                extraction_agent,
                policy_agent,
                decision_agent,
            ],
            description = """
                You receive an initial state object that contains:
                - raw_claim: member_id, claim_category, treatment_date, claimed_amount
                - documents: uploaded files with filename, content_type, and bytes
                - policy_terms: JSON loaded from policy_terms.json

                You must coordinate the following steps:

                1) Preprocessing:
                - Call PreprocessingAgent to convert raw files into PreprocessedDocument objects.
                - Write the result into state.preprocessed_docs.
                - Append a trace step describing preprocessing status and any notable issues.

                2) Document gating:
                - Call DocumentGateAgent with claim_category, documents_meta, and policy_terms.document_requirements.
                - If DocumentGate reports blocking document_errors (e.g., missing required HOSPITAL_BILL), update state.document_errors and:
                    - create a Decision with decision=REJECTED or MANUAL_REVIEW, appropriate reason, and lowered confidence.
                    - stop the pipeline after wrapping this Decision via DecisionAgent into a final ClaimResponse.
                - If DocumentGate passes, append a trace step indicating PASSED and continue.

                3) Extraction:
                - Call ExtractionAgent with state.preprocessed_docs.
                - Write extracted_documents, extraction_errors, and low_confidence into state.
                - Append a trace step that notes whether extraction was fully successful, partially successful, or had errors.
                - If extraction had serious issues, you may later influence the final confidence and/or choose MANUAL_REVIEW via PolicyAgent.

                4) Policy evaluation:
                - Call PolicyAgent with:
                    - raw_claim
                    - policy_terms
                    - extracted_documents and extraction_errors
                    - document_errors (if any)
                - PolicyAgent must return a Decision object with:
                    - decision in {APPROVED, PARTIAL, REJECTED, MANUAL_REVIEW}
                    - approved_amount, claimed_amount, confidence, reason
                    - rejection_reasons and notes where applicable
                    - trace steps describing which policy rules were applied and why they passed or failed.
                - Merge policy trace steps into the overall trace.

                5) Final decision wrapping:
                - Call DecisionAgent with the Decision from PolicyAgent to get a ClaimResponse.
                - Attach the full accumulated trace and document_errors to the ClaimResponse.
                - Ensure that the final_decision includes:
                    - decision, approved_amount, claimed_amount, confidence, reason
                    - complete trace explaining every key check and outcome.

                Throughout:
                - Always update the shared state after each agent call.
                - After each agent, append a trace step for orchestration itself (e.g., "Called ExtractionAgent", agent="Orchestrator", status="PASSED", detail="Ran extraction on 2 documents").
                - Handle failures gracefully: if an agent or tool fails, record it in the trace, adjust confidence downward, and prefer MANUAL_REVIEW over crashing.

                Your final output:
                - final_decision: containing a human readable and understandable response containing ClaimResponse and the full trace list, so operations can see exactly what happened, what passed, what failed, and why.
                """,
)

# initial_state = await build_initial_state(...)
# result = Runner.run(orchestrator, user_input=initial_state_json)
# print(result.output["final_decision"])
