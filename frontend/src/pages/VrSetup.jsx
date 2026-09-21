import { useCallback, useEffect, useMemo, useState } from "react";
import { Link, useLocation, useSearchParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, CheckCircle2 } from "lucide-react";
import { api } from "../lib/api";
import {
  checklistForPath,
  coachHref,
  headsetById,
  headsetHintFromUa,
  listHeadsets,
  pathById,
  pathsForHeadset,
  recommendedPath,
  simplePath,
  softwareById,
  tierLabel,
  vrCatalog,
} from "../lib/vrCompat";
import { enterRoomVr, openXrSelfCheck, probeBrowserXr } from "../lib/vrRuntime";
import { HeadsetArt, StepArt } from "../components/studio/VrIllustrations";
import VrSetupNav, { OfficialLink } from "../components/studio/VrSetupNav";

const STEPS = ["headset", "path", "checklist", "openxr"];

export default function VrSetup() {
  const catalog = vrCatalog();
  const [params, setParams] = useSearchParams();
  const location = useLocation();
  const headsets = listHeadsets();
  const hinted = headsetHintFromUa(typeof navigator !== "undefined" ? navigator.userAgent : "");
  const headsetId = params.get("headset") || hinted?.id || "";
  const pathId = params.get("path") || "";
  const stepParam = params.get("step");
  const hashOpenXr = location.hash === "#openxr";
  const step = hashOpenXr ? "openxr" : STEPS.includes(stepParam) ? stepParam : headsetId ? (pathId ? "checklist" : "path") : "headset";

  const headset = headsetById(headsetId);
  const path = pathById(pathId) || (headset ? recommendedPath(headset) : null);
  const paths = pathsForHeadset(headset);
  const steps = checklistForPath(path?.id);
  const [probe, setProbe] = useState(null);
  const [serverProbe, setServerProbe] = useState(null);
  const [xrNote, setXrNote] = useState("");
  const [checked, setChecked] = useState({});

  const setSel = useCallback(
    (next) => {
      const merged = { headset: headsetId, path: pathId, step, ...next };
      const sp = new URLSearchParams();
      if (merged.headset) sp.set("headset", merged.headset);
      if (merged.path) sp.set("path", merged.path);
      if (merged.step) sp.set("step", merged.step);
      setParams(sp, { replace: false });
    },
    [headsetId, pathId, setParams, step],
  );

  useEffect(() => {
    probeBrowserXr().then(setProbe).catch(() => setProbe(null));
    const req = api?.get?.("/rooms/vr/probe");
    if (req && typeof req.then === "function") {
      req.then(({ data }) => setServerProbe(data)).catch(() => setServerProbe(null));
    }
  }, []);

  useEffect(() => {
    setChecked({});
  }, [path?.id]);

  const checks = useMemo(() => openXrSelfCheck(probe, serverProbe), [probe, serverProbe]);
  const rec = recommendedPath(headset);
  const simple = simplePath(headset);

  const tryVr = async () => {
    const result = await enterRoomVr();
    setXrNote(result.ok ? result.reason : result.reason);
    if (result.session) {
      result.session.addEventListener("end", () => setXrNote(""));
    }
  };

  return (
    <div className="px-4 sm:px-8 lg:px-16 py-12 max-w-4xl vr-setup" data-testid="vr-setup">
      <div className="mb-6 text-xs" style={{ color: "var(--text-muted)" }}>
        <Link to="/rooms" data-testid="vr-setup-back">
          ← rooms
        </Link>
      </div>
      <header className="mb-8">
        <div className="overline mb-3">heirloom room</div>
        <h1 className="font-serif text-4xl lg:text-5xl font-light tracking-tight">VR setup coach</h1>
        <p className="mt-3 text-base max-w-xl" style={{ color: "var(--text-secondary)" }}>
          Pick your headset. We only send you to official free software. OpenXR on the PC,
          WebXR in the headset browser. Virtual Desktop is paid optional polish — skip it
          unless you already own it.
        </p>
      </header>

      <VrSetupNav active={step === "openxr" ? "openxr" : "coach"} />

      <ol className="vr-steps" data-testid="vr-wizard-steps">
        {STEPS.map((id, i) => (
          <li key={id} className={step === id ? "is-active" : ""}>
            <button type="button" onClick={() => setSel({ step: id })} data-testid={`vr-step-${id}`}>
              {i + 1}. {id === "openxr" ? "Fix OpenXR" : id}
            </button>
          </li>
        ))}
      </ol>

      {step === "headset" ? (
        <section data-testid="vr-pick-headset">
          <div className="overline mb-4">your headset</div>
          <div className="vr-headset-grid">
            {headsets.map((h) => (
              <button
                key={h.id}
                type="button"
                data-testid={`vr-headset-${h.id}`}
                className={`vr-headset-card ${headsetId === h.id ? "is-active" : ""} ${h.deprecated ? "is-deprecated" : ""}`}
                onClick={() => setSel({ headset: h.id, path: h.recommended_path, step: "path" })}
              >
                <HeadsetArt id={h.art} />
                <strong>{h.short}</strong>
                <span className="vr-tier">
                  Tier {h.tier} · {tierLabel(h.tier)}
                </span>
                <span className="vr-headset-name">{h.name}</span>
              </button>
            ))}
          </div>
        </section>
      ) : null}

      {step === "path" && headset ? (
        <section data-testid="vr-pick-path">
          <div className="overline mb-2">how to connect</div>
          <h2 className="font-serif text-2xl mb-2">{headset.name}</h2>
          <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
            {headset.pain}
            {headset.host_note ? ` ${headset.host_note}` : ""}
          </p>
          <div className="space-y-3">
            {paths.map((p) => {
              const isRec = rec?.id === p.id;
              const isSimple = simple?.id === p.id;
              return (
                <button
                  key={p.id}
                  type="button"
                  data-testid={`vr-path-${p.id}`}
                  className={`vr-path-card ${pathId === p.id ? "is-active" : ""}`}
                  onClick={() => setSel({ path: p.id, step: "checklist" })}
                >
                  <div>
                    <strong>{p.label}</strong>
                    <p>{p.blurb}</p>
                  </div>
                  <div className="vr-path-flags">
                    {isRec ? <em>recommended</em> : null}
                    {isSimple ? <em className="is-simple">simplest</em> : null}
                    {p.hardware_paid ? <em className="is-hw">paid hardware</em> : null}
                    {p.optional_paid ? <em className="is-paid">paid optional</em> : <em className="is-free">free software</em>}
                  </div>
                </button>
              );
            })}
          </div>
        </section>
      ) : null}

      {step === "checklist" && headset && path ? (
        <section data-testid="vr-checklist">
          <div className="overline mb-2">checklist</div>
          <h2 className="font-serif text-2xl mb-1">{path.label}</h2>
          <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
            {path.blurb}
          </p>
          <ol className="vr-checklist">
            {steps.map((item, i) => {
              const sw = item.software ? softwareById(item.software) : null;
              const key = `${path.id}-${i}`;
              return (
                <li key={key} className="vr-check-item" data-testid={`vr-check-${i}`}>
                  <StepArt id={item.art} />
                  <div>
                    <label className="vr-check-label">
                      <input
                        type="checkbox"
                        checked={Boolean(checked[key])}
                        onChange={(e) => setChecked((c) => ({ ...c, [key]: e.target.checked }))}
                        data-testid={`vr-check-box-${i}`}
                      />
                      <span>
                        {i + 1}. {item.title}
                      </span>
                    </label>
                    <p>{item.body}</p>
                    {sw?.url ? (
                      <OfficialLink href={sw.url} testid={`vr-dl-${sw.id}`}>
                        {sw.free === false ? `Official paid: ${sw.name}` : `Download ${sw.name}`}
                      </OfficialLink>
                    ) : null}
                    {sw?.help_url ? (
                      <OfficialLink href={sw.help_url} testid={`vr-help-${sw.id}`}>
                        Vendor steps
                      </OfficialLink>
                    ) : null}
                    {sw?.requirements_url ? (
                      <OfficialLink href={sw.requirements_url} testid={`vr-req-${sw.id}`}>
                        PC requirements
                      </OfficialLink>
                    ) : null}
                  </div>
                </li>
              );
            })}
          </ol>
          <div className="mt-6 flex flex-wrap gap-3">
            <button
              type="button"
              className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded-sm"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
              onClick={() => setSel({ step: "openxr" })}
              data-testid="vr-goto-openxr"
            >
              Fix OpenXR <ArrowRight className="h-4 w-4" />
            </button>
            <Link to="/rooms" className="px-4 py-2 text-sm rounded-sm" style={{ border: "1px solid var(--border-default)" }}>
              Back to rooms
            </Link>
          </div>
        </section>
      ) : null}

      {step === "openxr" ? (
        <section id="openxr" data-testid="vr-openxr">
          <div className="overline mb-2">fix OpenXR</div>
          <h2 className="font-serif text-2xl mb-3">Self-check</h2>
          <p className="text-sm mb-6" style={{ color: "var(--text-secondary)" }}>
            {catalog.architecture.note}
          </p>
          <ul className="vr-selfcheck" data-testid="vr-selfcheck">
            {checks.map((item) => (
              <li key={item.id} data-testid={`vr-selfcheck-${item.id}`}>
                <CheckCircle2
                  className="h-4 w-4"
                  style={{ color: item.ok ? "#7d9a6a" : item.ok === false ? "#c95a5a" : "#888" }}
                />
                <div>
                  <strong>{item.label}</strong>
                  {item.detail ? <p>{item.detail}</p> : null}
                  <span>{item.ok === true ? "ok" : item.ok === false ? "needs work" : "unknown on this host"}</span>
                </div>
              </li>
            ))}
          </ul>
          <div className="surface p-5 mt-6">
            <div className="overline mb-2">Wi-Fi</div>
            <ul className="text-sm space-y-1" style={{ color: "var(--text-muted)" }}>
              {catalog.wifi_tips.map((tip) => (
                <li key={tip}>· {tip}</li>
              ))}
            </ul>
          </div>
          <div className="surface p-5 mt-4">
            <div className="overline mb-2">PC floor</div>
            <ul className="text-sm space-y-1" style={{ color: "var(--text-muted)" }}>
              {catalog.pc_requirements.baseline.map((tip) => (
                <li key={tip}>· {tip}</li>
              ))}
            </ul>
          </div>
          <p className="text-xs mt-4" style={{ color: "var(--text-muted)" }} data-testid="vr-legal">
            {catalog.legal.copy}
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={tryVr}
              data-testid="vr-setup-enter"
              className="inline-flex items-center gap-2 px-4 py-2 text-sm rounded-sm"
              style={{ background: "var(--accent)", color: "var(--text-inverse)" }}
            >
              Try Enter in VR
            </button>
            {headset ? (
              <Link
                to={coachHref(headset.id, path?.id)}
                className="inline-flex items-center gap-2 px-4 py-2 text-sm"
                style={{ color: "var(--accent)" }}
              >
                <ArrowLeft className="h-4 w-4" /> checklist
              </Link>
            ) : null}
          </div>
          {xrNote ? (
            <p className="text-sm mt-4" data-testid="vr-setup-xr-note" style={{ color: "var(--text-muted)" }}>
              {xrNote}
            </p>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
