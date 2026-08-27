import { Route, Routes } from "react-router-dom";
import { NavBar } from "./components/NavBar";
import { Dashboard } from "./views/Dashboard";
import { EventDetail } from "./views/EventDetail";
import { OrbitView } from "./views/OrbitView";

export default function App(): JSX.Element {
  return (
    <div className="app">
      <NavBar />
      <main className="app__content">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/events/:eventId" element={<EventDetail />} />
          <Route path="/orbit" element={<OrbitView />} />
          <Route path="/orbit/:noradId" element={<OrbitView />} />
        </Routes>
      </main>
    </div>
  );
}
