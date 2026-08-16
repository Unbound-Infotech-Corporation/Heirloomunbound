import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";

/**
 * Per-function model dropdown. Click a model → it's saved for that function
 * and returned so Twin / Interviewer / Focus can send it on the next call.
 *
 * `functionId` matches the Models studio catalog (chat, interview, tools, …).
 */
export default function FunctionModelPicker({ functionId, onChange, compact = false }) {
  const [studio, setStudio] = useState(null);
  const [saving, setSaving] = useState(false);

  const onChangeRef = useRef(onChange);
  onChangeRef.current = onChange;

  const load = useCallback(async () => {
    try {
      const { data } = await api.get("/models/studio");
      setStudio(data);
      const asg = data.assignments?.[functionId];
      if (asg && onChangeRef.current) onChangeRef.current(asg);
    } catch {
      /* page still works with Emergent default */
    }
  }, [functionId]);

  useEffect(() => { load(); }, [load]);

  if (!studio) {
    return (
      <span className="inline-flex items-center gap-1 text-xs" style={{ color: "var(--text-muted)" }}>
        <Loader2 className="h-3 w-3 animate-spin" />
      </span>
    );
  }

  const assignment = studio.assignments?.[functionId] || {};
  const options = studio.options || [];
  const value = assignment.option_id || "";

  const pick = async (optionId) => {
    if (!optionId || optionId === value) return;
    setSaving(true);
    try {
      const { data } = await api.post("/models/assign", { function: functionId, option_id: optionId });
      setStudio((s) => ({ ...s, assignments: { ...(s?.assignments || {}), [functionId]: data.assignment } }));
      if (onChangeRef.current) onChangeRef.current(data.assignment);
      toast.success("Using that model for this");
    } catch (e) {
      toast.error(e.response?.data?.detail || "Couldn't switch models");
    } finally {
      setSaving(false);
    }
  };

  return (
    <label
      className={`inline-flex items-center gap-2 ${compact ? "text-xs" : "text-sm"}`}
      style={{ color: "var(--text-secondary)" }}
      data-testid={`model-picker-${functionId}`}
    >
      <span className="hidden sm:inline" style={{ color: "var(--text-muted)" }}>model</span>
      <span className="relative inline-flex items-center">
        <select
          value={value}
          disabled={saving || options.length === 0}
          onChange={(e) => pick(e.target.value)}
          data-testid={`model-picker-select-${functionId}`}
          className="appearance-none pl-3 pr-8 py-1.5 rounded-sm text-xs border cursor-pointer"
          style={{
            background: "var(--surface-elev)",
            color: "var(--text-primary)",
            borderColor: "var(--border-default)",
            minWidth: compact ? 140 : 180,
          }}
        >
          {options.length === 0 && <option value="">Heirloom key · default</option>}
          {options.map((o) => (
            <option key={o.id} value={o.id}>{o.label}</option>
          ))}
        </select>
        <ChevronDown className="h-3 w-3 pointer-events-none absolute right-2" style={{ color: "var(--text-muted)" }} />
      </span>
      <Link
        to="/models"
        className="text-[11px] underline-offset-2 hover:underline"
        style={{ color: "var(--text-muted)" }}
        data-testid={`model-picker-more-${functionId}`}
      >
        more
      </Link>
    </label>
  );
}

/** Fields to merge into Twin / Interviewer / Focus API bodies. */
export function modelOverride(choice) {
  if (!choice?.provider || !choice?.model) return {};
  return { provider: choice.provider, model: choice.model };
}
