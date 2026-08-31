import { AppHeader } from "./Layout";

/**
 * The masthead is now the whole nav frame — see Layout.tsx (DESIGN.md §3).
 * This wrapper keeps App.tsx's `<NavBar />` mount point stable.
 */
export function NavBar(): JSX.Element {
  return <AppHeader />;
}
