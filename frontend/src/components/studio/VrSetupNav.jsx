import { Link, useLocation } from "react-router-dom";
import { openXrHref, vrMatrixHref, vrSetupBase } from "../../lib/vrCompat";

export default function VrSetupNav({ active }) {
  const location = useLocation();
  const setup = vrSetupBase(location.pathname);
  const matrix = vrMatrixHref(location.pathname);
  const openxr = openXrHref(location.pathname);
  return (
    <nav className="vr-subnav" data-testid="vr-subnav">
      <Link
        to={setup}
        className={active === "coach" ? "is-active" : ""}
        data-testid="vr-nav-coach"
      >
        Setup coach
      </Link>
      <Link
        to={matrix}
        className={active === "matrix" ? "is-active" : ""}
        data-testid="vr-nav-matrix"
      >
        Compatibility matrix
      </Link>
      <Link
        to={openxr}
        className={active === "openxr" ? "is-active" : ""}
        data-testid="vr-nav-openxr"
      >
        Fix OpenXR
      </Link>
    </nav>
  );
}

export function OfficialLink({ href, children, testid }) {
  if (!href) return null;
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      className="vr-official-link"
      data-testid={testid}
    >
      {children} ↗
    </a>
  );
}
