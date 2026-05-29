plum-claims/
├── backend/
│   ├── main.py
│   ├── requirements.txt
│   │
│   ├── api/
│   │   └── routes/
│   │       └── claims.py              # POST /claims/submit
│   │
│   ├── schemas/
│   │   ├── claim.py                   # ClaimSubmission, ClaimResponse
│   │   ├── decision.py                # Decision, TraceStep, DocumentError
│   │   └── document.py                # DocType, ExtractedDoc
│   │
│   ├── agents/
│   │   └── orchestrator_agent.py      # single ADK LlmAgent with tools
│   │
│   ├── tools/
│   │   ├── document_tools.py          # DocumentGate (doc requirements check)
│   │   ├── preprocessing_tools.py     # image/pdf preprocessing wrappers
│   │   ├── extraction_tools.py        # calls vision LLM, returns ExtractedDoc
│   │   ├── policy_tools.py            # applies policy_terms.json logic
│   │   └── decision_tools.py          # builds final ClaimResponse + confidence
│   │
│   ├── llm/
│   │   ├── client.py                  # Gemini client, retries, error mapping
│   │   └── prompts.py                 # all prompts in one place
│   │
│   ├── core/
│   │   ├── tracing.py                 # TraceLogger
│   │   ├── errors.py                  # custom exceptions (LLMAuthError, etc.)
│   │   └── config.py                  # load .env, paths, policy_terms.json
│   │
│   ├── preprocessing/
│   │   ├── image.py                   # your img.py
│   │   └── pdf.py                     # your pdf.py
│   │
│   ├── data/
│   │   ├── policy_terms.json          # given file
│   │   └── test_cases.json            # from assignment package
│   │
│   └── tests/
│       ├── test_document_tools.py
│       ├── test_policy_tools.py
│       └── test_pipeline.py
│
├── frontend/
│   ├── package.json
│   └── src/
│       ├── App.jsx
│       ├── pages/
│       │   ├── SubmitClaim.jsx          # Claim form + file upload
│       │   └── ClaimDecision.jsx        # Decision result + trace viewer
│       ├── components/
│       │   ├── FileUpload.jsx           # Drag-and-drop multi-file upload
│       │   ├── DecisionBadge.jsx        # Colored APPROVED/REJECTED badge
│       │   ├── TraceViewer.jsx          # Expandable step-by-step audit trail
│       │   └── ErrorMessage.jsx         # Specific document error display
│       └── api/
│           └── claims.js                # Axios calls to backend
│
├── docs/
│   ├── architecture.md                  # DELIVERABLE: design + trade-offs
│   ├── component_contracts.md           # DELIVERABLE: input/output specs
│   └── eval_report.md                   # DELIVERABLE: 12 test case results
│
├── scripts/
│   └── run_evals.py                     # Batch run all 12 test cases
│
├── docker-compose.yml
└── README.md




Uploaded File (image or PDF)
         │
         ▼
  ┌─────────────┐
  │ Is it PDF?  │
  └──┬──────────┘
     │ Yes                    No (JPG/PNG)
     ▼                            │
Text PDF? ──Yes──► Extract text   │
     │                            │
     No                           │
     ▼                            ▼
Convert pages          Pre-process image
to images              (deskew, denoise,
     │                  contrast enhance)
     └──────────────────────┘
                 │
                 ▼
      Classify document type
      (Gemini Vision call 1)
                 │
                 ▼
      Extract structured data
      (Gemini Vision call 2
       with type-specific prompt)
                 │
                 ▼
      Validate + Score confidence
      (deterministic rules, no LLM)
                 │
                 ▼
      Return: structured JSON
            + confidence score
            + validation issues
            + low confidence fields