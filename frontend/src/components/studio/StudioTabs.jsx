import { useEffect, useState } from "react";

/**
 * Tabbed panel strip (Project / Media Browser style).
 */
export default function StudioTabs({ tabs, defaultTab, activeTab: controlledTab, onTabChange, testId, className = "" }) {
  const first = defaultTab || tabs[0]?.id;
  const [internal, setInternal] = useState(first);
  const active = controlledTab ?? internal;

  useEffect(() => {
    if (controlledTab) setInternal(controlledTab);
  }, [controlledTab]);

  const current = tabs.find((t) => t.id === active) || tabs[0];

  const select = (id) => {
    if (!controlledTab) setInternal(id);
    onTabChange?.(id);
  };

  return (
    <div className={`studio-tabs ${className}`} data-testid={testId}>
      <div className="studio-tabs-bar" role="tablist">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={tab.id === active}
            className={`studio-tab ${tab.id === active ? "is-active" : ""}`}
            onClick={() => select(tab.id)}
            data-testid={tab.testId}
          >
            {tab.label}
          </button>
        ))}
      </div>
      <div className="studio-tabs-body" role="tabpanel">
        {current?.content}
      </div>
    </div>
  );
}
