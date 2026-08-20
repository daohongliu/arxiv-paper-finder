import { NavLink, Route, Routes } from "react-router-dom";
import Dashboard from "./pages/Dashboard";
import Papers from "./pages/Papers";
import PaperDetailPage from "./pages/PaperDetail";
import Review from "./pages/Review";
import Jobs from "./pages/Jobs";
import Eval from "./pages/Eval";

const NAV = [
  { to: "/", label: "Dashboard" },
  { to: "/papers", label: "Papers" },
  { to: "/review", label: "Review" },
  { to: "/jobs", label: "Jobs" },
  { to: "/eval", label: "Eval" },
];

export default function App() {
  return (
    <div className="flex min-h-screen">
      <aside className="fixed inset-y-0 left-0 w-52 border-r border-zinc-800 bg-zinc-950 p-4">
        <nav className="flex flex-col gap-1">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.to === "/"}
              className={({ isActive }) =>
                `rounded-lg px-3 py-2 text-sm transition-colors ${
                  isActive ? "bg-zinc-800 text-zinc-100" : "text-zinc-400 hover:bg-zinc-900 hover:text-zinc-200"
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </aside>
      <main className="ml-52 flex-1 p-6">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/papers" element={<Papers />} />
          <Route path="/papers/:id" element={<PaperDetailPage />} />
          <Route path="/review" element={<Review />} />
          <Route path="/jobs" element={<Jobs />} />
          <Route path="/eval" element={<Eval />} />
        </Routes>
      </main>
    </div>
  );
}
