// src/components/TraceViewer.jsx
import { useState } from "react";
import React from "react";
export default function TraceViewer({ trace }) {
  const [expanded, setExpanded] = useState(new Set());

  if (!trace || trace.length === 0) {
    return null;
  }

  const toggle = (idx) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(idx) ? next.delete(idx) : next.add(idx);
      return next;
    });
  };

  return (
    <div>
      <div className="trace-header-row" onClick={() => {
        if (expanded.size === 0) {
          // expand all
          const all = new Set(trace.map((_, i) => i));
          setExpanded(all);
        } else {
          setExpanded(new Set());
        }
      }}>
        <span className="trace-hdr-lbl">
          Audit trail — {trace.length} steps
        </span>
        <span className="trace-toggle-btn">
          {expanded.size === 0 ? "Show ↓" : "Hide ↑"}
        </span>
      </div>

      {trace.map((item, i) => (
        <div className="trace-item" key={i}>
          <div className="trace-row" onClick={() => toggle(i)}>
            <div className="tstatus">
              <span className={`sbadge sb-${item.status}`}>{item.status}</span>
            </div>
            <div className="tstep-name">{item.step}</div>
            <div className="tagent">{item.agent}</div>
            <div
              className={`tchev ${expanded.has(i) ? "open" : ""}`}
            >
              ▾
            </div>
          </div>
          {expanded.has(i) && (
            <div className="tdetail">{item.detail}</div>
          )}
        </div>
      ))}
    </div>
  );
}