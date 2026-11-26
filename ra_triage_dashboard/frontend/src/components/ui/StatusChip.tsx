import React from "react";

export type ChipTone = "ok" | "warn" | "fail" | "neutral";

export interface StatusChipProps {
  label: string;
  tone?: ChipTone;
}

export const StatusChip: React.FC<StatusChipProps> = ({ label, tone = "neutral" }) => (
  <span className={`status-chip ${tone}`}>{label}</span>
);
