// src/pages/SubmitClaim.jsx
import React, { useState, useEffect, useRef, Fragment } from "react";
import { submitClaim } from "../api/claims.js";
import DecisionBadge from "../components/DecisionBadge.jsx";
import TraceViewer from "../components/TraceViewer.jsx";

const CLAIM_CATEGORIES = [
  { id: "CONSULTATION", label: "Consultation" },
  { id: "DIAGNOSTIC", label: "Diagnostic / Lab" },
  { id: "PHARMACY", label: "Pharmacy" },
  { id: "DENTAL", label: "Dental" },
  { id: "VISION", label: "Vision" },
  { id: "ALTERNATIVE_MEDICINE", label: "Alternative medicine" },
];

const PROC_STEPS = [
  "Verifying documents...",
  "Extracting information from documents...",
  "Checking member & waiting periods...",
  "Applying coverage and limits...",
  "Calculating approved amount...",
  "Generating audit trail...",
];

function fmtINR(n) {
  if (isNaN(n)) return "0";
  return n.toLocaleString("en-IN");
}

export default function SubmitClaim() {
  const [mode, setMode] = useState("form"); // "form" | "processing" | "result"
  const [memberId, setMemberId] = useState("");
  const [claimCategory, setClaimCategory] = useState("");
  const [treatmentDate, setTreatmentDate] = useState("");
  const [claimedAmount, setClaimedAmount] = useState("");
  const [files, setFiles] = useState([]);

  const [processingStep, setProcessingStep] = useState(0);
  const [result, setResult] = useState(null);
  const [docErrors, setDocErrors] = useState([]);

  const fileInputRef = useRef(null);

  console.log("RENDER files:", files);

  // animate processing steps
  useEffect(() => {
    if (mode !== "processing") return;

    let i = 0;
    setProcessingStep(0);
    const interval = setInterval(() => {
      i++;
      setProcessingStep(i);
      if (i >= PROC_STEPS.length - 1) {
        clearInterval(interval);
      }
    }, 600);

    return () => clearInterval(interval);
  }, [mode]);

  const onFilesSelected = (e) => {
    const list = e.target.files;
    console.log("onFilesSelected fired, raw FileList:", list);
    if (!list || list.length === 0) return;

    const next = Array.from(list);
    console.log("about to setFiles with:", next);
    setFiles(next);

    // allow selecting the same file again later
    e.target.value = "";
  };

  const removeFile = (idx) => {
    setFiles((prev) => prev.filter((_, i) => i !== idx));
  };

  const canSubmit =
    memberId.trim() &&
    claimCategory &&
    treatmentDate &&
    claimedAmount &&
    files.length > 0;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!canSubmit) return;

    setMode("processing");
    setDocErrors([]);
    setResult(null);

    const formData = new FormData();
    formData.append("member_id", memberId.trim());
    formData.append("claim_category", claimCategory);
    formData.append("treatment_date", treatmentDate);
    formData.append("claimed_amount", claimedAmount);

    // Backend expects a single "file" field; send the first selected file
    if (files.length > 0) {
      formData.append("file", files[0]);
    }

    try {
      const res = await submitClaim(formData);

      // If backend ever returns only document_errors with no decision
      if (res.document_errors && res.document_errors.length > 0 && !res.decision) {
        setDocErrors(res.document_errors);
        setMode("form");
      } else {
        setResult(res);
        // small delay so processing animation feels natural
        setTimeout(() => setMode("result"), 700);
      }
    } catch (err) {
      console.error("Submit failed", err);
      setDocErrors([
        {
          type: "SYSTEM_ERROR",
          message:
            "Something went wrong while processing your claim. Please try again.",
        },
      ]);
      setMode("form");
    }
  };

  const resetForm = () => {
    setMemberId("");
    setClaimCategory("");
    setTreatmentDate("");
    setClaimedAmount("");
    setFiles([]);
    setDocErrors([]);
    setResult(null);
    setMode("form");
  };

  return (
    <div className="app">
      {/* Simple header */}
      <header className="header">
        <div className="logo">
          <div className="logo-mark">P</div>
          <div className="logo-text">
            <div className="logo-name">Plum</div>
            <div className="logo-tag">Health Claims Portal</div>
          </div>
        </div>
        <div className="header-badge">🔒 SSL secured</div>
      </header>

      {/* Form mode */}
      {mode === "form" && (
        <div className="card">
          {/* Steps */}
          <div className="steps">
            {["Details", "Documents", "Review"].map((lbl, i) => (
              <Fragment key={i}>
                <div className="step-item">
                  <div className={`step-dot ${i === 0 ? "active" : ""}`}>
                    {i + 1}
                  </div>
                  <span className={`step-lbl ${i === 0 ? "active" : ""}`}>
                    {lbl}
                  </span>
                </div>
                {i < 2 && <div className="step-line" />}
              </Fragment>
            ))}
          </div>

          <form className="fbody" onSubmit={handleSubmit}>
            <div className="ftitle">Submit a new claim</div>
              <div className="fsub">
                Enter your claim details and upload supporting medical documents.
              </div>

            {/* Member + claim info */}
            <div className="field-row" style={{ marginBottom: 16 }}>
              <div className="field">
                <label className="flbl">Member ID</label>
                <input
                  className="finput"
                  placeholder="EMP001"
                  value={memberId}
                  onChange={(e) => setMemberId(e.target.value)}
                  required
                />
              </div>
              <div className="field">
                <label className="flbl">Claim category</label>
                <select
                  className="finput"
                  value={claimCategory}
                  onChange={(e) => setClaimCategory(e.target.value)}
                  required
                >
                  <option value="">Select category</option>
                  {CLAIM_CATEGORIES.map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.label}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            <div className="field-row" style={{ marginBottom: 24 }}>
              <div className="field">
                <label className="flbl">Treatment date</label>
                <input
                  type="date"
                  className="finput"
                  value={treatmentDate}
                  onChange={(e) => setTreatmentDate(e.target.value)}
                  required
                />
              </div>
              <div className="field">
                <label className="flbl">Claimed amount</label>
                <div className="amt-wrap">
                  <span className="amt-pre">₹</span>
                  <input
                    className="finput amt"
                    type="number"
                    min="0"
                    step="1"
                    placeholder="0"
                    value={claimedAmount}
                    onChange={(e) => setClaimedAmount(e.target.value)}
                    required
                  />
                </div>
              </div>
            </div>

            {/* File upload */}
            <div style={{ marginBottom: 12 }}>
              <label className="flbl" htmlFor="claim-docs">
                Documents
              </label>
              <input
                ref={fileInputRef}
                type="file"
                multiple
                accept=".pdf,.jpg,.jpeg,.png,.heic"
                onChange={onFilesSelected}
                id="claim-docs"
                name="claim_docs"
              />
              {files.length > 0 && (
                <ul style={{ marginTop: 8, fontSize: 13 }}>
                  {files.map((f, idx) => (
                    <li key={idx}>
                      {f.name} ({(f.size / 1024).toFixed(1)} KB){" "}
                      <button
                        type="button"
                        style={{ marginLeft: 8 }}
                        onClick={() => removeFile(idx)}
                      >
                        ×
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {/* Document errors */}
            {docErrors.length > 0 && (
              <div
                style={{
                  marginTop: 12,
                  marginBottom: 12,
                  padding: "10px 12px",
                  borderRadius: 8,
                  background: "#FEF2F2",
                  border: "1px solid #FCA5A5",
                  fontSize: 13,
                  color: "#B91C1C",
                }}
              >
                {docErrors.map((err, i) => (
                  <div key={i} style={{ marginBottom: 4 }}>
                    {err.message}
                  </div>
                ))}
              </div>
            )}

            <div
              style={{ marginTop: 18, display: "flex", justifyContent: "flex-end" }}
            >
              <button
                type="submit"
                className="btn btn-submit"
                disabled={!canSubmit}
              >
                Submit claim →
              </button>
            </div>
          </form>
        </div>
      )}

      {/* Processing mode */}
      {mode === "processing" && (
        <div className="proc-view">
          <div className="spinner" />
          <div className="proc-title">Processing your claim</div>
          <div className="proc-sub">
            Our AI agents are reading your documents and checking your policy.
          </div>
          <div className="proc-steps">
            {PROC_STEPS.map((msg, i) => (
              <div
                key={i}
                className={`proc-step ${
                  i < processingStep ? "done" : i === processingStep ? "cur" : ""
                }`}
              >
                <div className="pcheck">{i < processingStep ? "✓" : ""}</div>
                {msg}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Result mode */}
      {mode === "result" && result && (
        <div className="result-card">
          <div className="dec-header">
            <div className="dec-top">
              <div>
                <div
                  style={{
                    fontSize: 11,
                    color: "var(--text-3)",
                    textTransform: "uppercase",
                    letterSpacing: "0.8px",
                    fontWeight: 700,
                    marginBottom: 10,
                  }}
                >
                  Claim decision
                </div>
                <DecisionBadge decision={result.decision} />
              </div>
              <div className="claim-ref-box">
                <div className="claim-ref-lbl">Claim ref</div>
                <div className="claim-ref-val">{result.claim_id}</div>
              </div>
            </div>

            <div className="amt-row">
              <div className="amt-block">
                <div className="amt-lbl">Approved amount</div>
                <div className="amt-big">₹{fmtINR(result.approved_amount || 0)}</div>
              </div>
              <div className="amt-strike">
                ₹{fmtINR(result.claimed_amount || 0)}
              </div>
            </div>

            <div className="conf-row">
              <div className="conf-lbl">Decision confidence</div>
              <div className="conf-bar">
                <div
                  className="conf-fill"
                  style={{
                    width: `${Math.round((result.confidence || 0) * 100)}%`,
                  }}
                />
              </div>
              <div className="conf-pct">
                {Math.round((result.confidence || 0) * 100)}%
              </div>
            </div>

            <div className="dec-reason">
              {result.reason || "No reason provided"}
            </div>
          </div>

          <TraceViewer trace={result.trace} />

          <div className="result-footer">
            <button className="btn btn-secondary" onClick={resetForm}>
              Submit another claim
            </button>
          </div>
        </div>
      )}
    </div>
  );
}