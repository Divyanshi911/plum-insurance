// src/components/DecisionBadge.jsx
import React from "react";
const LABELS = {
  APPROVED: "Approved",
  PARTIAL: "Partial approval",
  REJECTED: "Rejected",
  MANUAL_REVIEW: "Manual review"
};

export default function DecisionBadge({ decision }) {
  if (!decision) return null;

  const label = LABELS[decision] || decision;

  return (
    <span className={`dec-badge db-${decision}`}>
      <span className="dec-dot" />
      {label}
    </span>
  );
}