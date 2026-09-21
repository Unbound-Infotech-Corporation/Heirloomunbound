import { Link } from "react-router-dom";
import {
  coachHref,
  matrixPathColumns,
  matrixRows,
  softwareById,
  vrCatalog,
} from "../lib/vrCompat";
import VrSetupNav, { OfficialLink } from "../components/studio/VrSetupNav";

function cellLabel(cell) {
  if (!cell.supported) return "—";
  const bits = [];
  if (cell.recommended) bits.push("R");
  if (cell.simple) bits.push("S");
  if (cell.hardwarePaid) bits.push("hw$");
  else if (cell.optionalPaid) bits.push("opt$");
  else bits.push("free");
  return bits.join(" · ");
}

export default function VrCompat() {
  const catalog = vrCatalog();
  const rows = matrixRows();
  const cols = matrixPathColumns();
  const software = Object.keys(catalog.software || {}).map((id) => softwareById(id));

  return (
    <div className="px-4 sm:px-8 lg:px-12 py-12 max-w-6xl" data-testid="vr-matrix">
      <div className="mb-6 text-xs" style={{ color: "var(--text-muted)" }}>
        <Link to="/rooms">← rooms</Link>
      </div>
      <header className="mb-8">
        <div className="overline mb-3">heirloom room</div>
        <h1 className="font-serif text-4xl font-light tracking-tight">Headset compatibility</h1>
        <p className="mt-3 text-sm max-w-2xl" style={{ color: "var(--text-secondary)" }}>
          R = recommended · S = simplest · free software · hw$ = paid hardware · opt$ = paid
          optional (Virtual Desktop). Markdown copy:{" "}
          <code className="text-xs">docs/vr-compatibility.md</code>
        </p>
      </header>
      <VrSetupNav active="matrix" />

      <div className="vr-matrix-wrap" data-testid="vr-matrix-table">
        <table className="vr-matrix">
          <thead>
            <tr>
              <th>Headset</th>
              {cols.map((col) => (
                <th key={col.id} title={col.label}>
                  {col.label.replace(" (paid, optional)", "").replace(" (USB)", "")}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map(({ headset, cells }) => (
              <tr key={headset.id} data-testid={`vr-matrix-row-${headset.id}`}>
                <th>
                  <Link to={coachHref(headset.id)} data-testid={`vr-matrix-link-${headset.id}`}>
                    {headset.short}
                    <span>
                      Tier {headset.tier}
                      {headset.deprecated ? " · deprecated" : ""}
                    </span>
                  </Link>
                </th>
                {cells.map((cell) => (
                  <td
                    key={cell.pathId}
                    className={
                      cell.supported
                        ? cell.recommended
                          ? "is-rec"
                          : cell.optionalPaid
                            ? "is-paid"
                            : "is-yes"
                        : "is-no"
                    }
                  >
                    {cell.supported ? (
                      <Link to={coachHref(headset.id, cell.pathId)}>{cellLabel(cell)}</Link>
                    ) : (
                      "—"
                    )}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <section className="mt-10" data-testid="vr-downloads">
        <div className="overline mb-3">official downloads</div>
        <ul className="vr-download-list">
          {software.map((item) => (
            <li key={item.id}>
              <strong>{item.name}</strong>
              <span>{item.free === false ? "paid optional" : "free"}</span>
              <OfficialLink href={item.url} testid={`vr-matrix-dl-${item.id}`}>
                {item.kind === "paid_optional" ? "Official store" : "Download"}
              </OfficialLink>
            </li>
          ))}
        </ul>
        <p className="text-xs mt-4" style={{ color: "var(--text-muted)" }}>
          {catalog.legal.copy}
        </p>
      </section>
    </div>
  );
}
