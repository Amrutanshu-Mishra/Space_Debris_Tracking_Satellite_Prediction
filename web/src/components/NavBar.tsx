import { NavLink } from "react-router-dom";

// TODO(dashboard): replace with the real nav once the layout is designed.
export function NavBar(): JSX.Element {
  return (
    <nav className="navbar">
      <span className="navbar__brand">PRAHARI</span>
      <NavLink to="/" end>
        Dashboard
      </NavLink>
      <NavLink to="/orbit">Orbit View</NavLink>
    </nav>
  );
}
