import { useEffect, useRef, useState } from "react";

/**
 * Photoshop-style floating document window: title bar, per-window menus,
 * min/max/close chrome. Close navigates to /today unless onClose is given.
 */
export default function StudioWindow({
  title,
  menus = [],
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
        x: e.clientX - drag.current.dx,
        y: e.clientY - drag.current.dy,
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
          if (maximized) return;
          const r = e.currentTarget.getBoundingClientRect();
          drag.current = { dx: e.clientX - r.left, dy: e.clientY - (r.top - 0) };
          setPos((p) => p);
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
      {menus.length > 0 && (
        <div className="studio-window-menubar" data-testid="studio-window-menubar">
          {menus.map((menu) => (
            <div className="studio-menu" key={menu.label}>
              <button type="button" className="studio-menu-trigger">
                {menu.label}
              </button>
              <div className="studio-menu-dropdown">
                {(menu.items || []).map((item, i) =>
                  item.sep ? (
                    <div key={i} className="studio-menu-sep" />
                  ) : (
                    <button
                      key={item.label}
                      type="button"
                      className="studio-menu-item"
                      onClick={item.onClick}
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
      )}
      <div className="studio-window-body">{children}</div>
      {status ? <div className="studio-window-status">{status}</div> : null}
    </div>
  );
}
