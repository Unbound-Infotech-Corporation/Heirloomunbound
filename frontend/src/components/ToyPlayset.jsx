import { Link } from "react-router-dom";

/** Painted-wood card that sits on the dark library table. */
export function ToyDesk({ children, className = "", testid }) {
  return (
    <section className={`toy-desk ${className}`.trim()} data-testid={testid}>
      <span className="toy-screw toy-screw-tl" aria-hidden="true" />
      <span className="toy-screw toy-screw-tr" aria-hidden="true" />
      <span className="toy-screw toy-screw-bl" aria-hidden="true" />
      <span className="toy-screw toy-screw-br" aria-hidden="true" />
      {children}
    </section>
  );
}

/** Round window for the twin's face — photo, video, or a painted smile. */
export function ToyPorthole({ src, videoSrc, alt = "Your twin", status, onVideoEnded }) {
  return (
    <div className="toy-porthole" data-testid="toy-porthole">
      {videoSrc ? (
        <video
          key={videoSrc}
          src={videoSrc}
          autoPlay
          playsInline
          onEnded={onVideoEnded}
        />
      ) : src ? (
        <img src={src} alt={alt} />
      ) : (
        <div className="toy-face-paint" aria-hidden="true">
          <span className="toy-eye toy-eye-l" />
          <span className="toy-eye toy-eye-r" />
          <span className="toy-smile" />
        </div>
      )}
      {status ? <div className="toy-porthole-status">{status}</div> : null}
    </div>
  );
}

/** Giant plastic knob. Use `to` for a link, `onClick` for a button. */
export function ToyKnob({
  to,
  onClick,
  color = "tomato",
  children,
  testid,
  disabled,
  type = "button",
  title,
  className = "",
  ...rest
}) {
  const cls = `toy-knob toy-knob-${color} ${className}`.trim();
  const { "data-testid": dataTid, ...fwd } = rest;
  const tid = testid || dataTid;
  if (to) {
    return (
      <Link to={to} className={cls} data-testid={tid} title={title} {...fwd}>
        {children}
      </Link>
    );
  }
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled}
      className={cls}
      data-testid={tid}
      title={title}
      {...fwd}
    >
      {children}
    </button>
  );
}

/** Traffic-light bead for Windows Safety. */
export function ToyLight({ state = "unknown", label, testid }) {
  const kind = state === "on" || state === "off" ? state : "unknown";
  return (
    <div className="toy-light-row" data-testid={testid}>
      <span className={`toy-light toy-light-${kind}`} aria-hidden="true" />
      <span className="toy-light-label">{label}</span>
    </div>
  );
}
