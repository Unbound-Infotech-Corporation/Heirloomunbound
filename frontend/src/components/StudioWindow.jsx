import { useEffect, useRef, useState } from "react";

function StudioMenuBar({ menus, inline = false }) {
  const [openLabel, setOpenLabel] = useState(null);
  const barRef = useRef(null);

  useEffect(() => {
    const onDoc = (e) => {
      if (!barRef.current?.contains(e.target)) setOpenLabel(null);
    };
    document.addEventListener("pointerdown", onDoc);
    return () => document.removeEventListener("pointerdown", onDoc);
  }, []);

  return (
    <div
      className={inline ? "studio-menubar-inline" : "studio-window-menubar"}
      data-testid={inline ? "studio-app-menubar-menus" : "studio-window-menubar"}
      ref={barRef}
    >
      {menus.map((menu) => (
        <div className={`studio-menu ${openLabel === menu.label ? "is-open" : ""}`} key={menu.label}>
          <button
            type="button"
            className="studio-menu-trigger"
            aria-expanded={openLabel === menu.label}
            onClick={() => setOpenLabel((l) => (l === menu.label ? null : menu.label))}
          >
            {menu.label}
          </button>
          <div className="studio-menu-dropdown">
            {(menu.items || []).map((item, i) =>
              item.sep ? (
                <div key={`sep-${i}`} className="studio-menu-sep" />
              ) : (
                <button
                  key={item.label}
                  type="button"
                  className="studio-menu-item"
                  onClick={() => {
                    setOpenLabel(null);
                    item.onClick?.();
                  }}
                  disabled={item.disabled}
                >
                  <span>{item.label}</span>
                  {item.hint ? <span className="studio-menu-hint">{item.hint}</span> : null}
                </button>
              )
            )}
          </div>
        </div>
      ))}
    </div>
  );
}

/**
 * Photoshop-style floating document window: title bar, per-window menus,
 * optional context options bar, min/max/close chrome.
 */
export default function StudioWindow({
  title,
  menus = [],
  optionsBar,
  testId,
  onClose,
  children,
  status,
}) {
  const [maximized, setMaximized] = useState(true);
  const [pos, setPos] = useState({ x: 24, y: 24 });
  const drag = useRef(null);

  useEffect(() => {
    const onMove = (e) => {
      if (!drag.current) return;
      setPos({
        x: Math.max(0, e.clientX - drag.current.dx),
        y: Math.max(0, e.clientY - drag.current.dy),
      });
    };
    const onUp = () => {
      drag.current = null;
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    return () => {
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
    };
  }, []);

  const style = maximized
    ? { inset: 8 }
    : { left: pos.x, top: pos.y, width: 920, height: 640, maxWidth: "calc(100% - 32px)" };

  return (
    <div
      className={`studio-window ${maximized ? "is-max" : ""}`}
      data-testid={testId || "studio-window"}
      style={style}
    >
      <div
        className="studio-window-titlebar"
        onPointerDown={(e) => {
          if (maximized || e.target.closest("button")) return;
          drag.current = { dx: e.clientX - pos.x, dy: e.clientY - pos.y };
        }}
        data-testid="studio-window-titlebar"
      >
        <span className="studio-window-title">{title}</span>
        <div className="studio-window-controls">
          <button type="button" aria-label="Minimize" onClick={() => setMaximized(false)}>
            –
          </button>
          <button
            type="button"
            aria-label={maximized ? "Restore" : "Maximize"}
            onClick={() => setMaximized((m) => !m)}
            data-testid="studio-window-max"
          >
            □
          </button>
          {onClose ? (
            <button type="button" aria-label="Close" onClick={onClose} data-testid="studio-window-close">
              ×
            </button>
          ) : null}
        </div>
      </div>
      {menus.length > 0 ? <StudioMenuBar menus={menus} /> : null}
      {optionsBar ? (
        <div className="studio-options-bar" data-testid="studio-options-bar">
          {optionsBar}
        </div>
      ) : null}
      <div className="studio-window-body studio-window-body--pro">{children}</div>
      {status ? <div className="studio-window-status">{status}</div> : null}
    </div>
  );
}

export { StudioMenuBar };
