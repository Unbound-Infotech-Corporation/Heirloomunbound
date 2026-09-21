import { Link } from "react-router-dom";
import { VR_MATRIX_PATH, VR_SETUP_PATH } from "../../lib/vrCompat";

export default function VrSetupNav({ active }) {
  return (
    <nav className="vr-subnav" data-testid="vr-subnav">
      <Link
        to={VR_SETUP_PATH}
        className={active === "coach" ? "is-active" : ""}
        data-testid="vr-nav-coach"
      >
        Setup coach
      </Link>
      <Link
        to={VR_MATRIX_PATH}
        className={active === "matrix" ? "is-active" : ""}
        data-testid="vr-nav-matrix"
      >
        Compatibility matrix
      </Link>
      <Link
        to={`${VR_SETUP_PATH}#openxr`}
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
