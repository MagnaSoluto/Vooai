import { useEffect } from "react";
import { BrowserRouter, Navigate, Route, Routes, useLocation } from "react-router-dom";
import Home from "./pages/Home.jsx";
import Results from "./pages/Results.jsx";
import About from "./pages/About.jsx";
import Dashboard from "./pages/Dashboard.jsx";
import Conta from "./pages/Conta.jsx";
import { trackPageview } from "./telemetry.js";

function PageviewBeacon() {
  const location = useLocation();
  useEffect(() => {
    trackPageview(location.pathname);
  }, [location.pathname]);
  return null;
}

export default function App() {
  return (
    <BrowserRouter>
      <PageviewBeacon />
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/resultado" element={<Results />} />
        <Route path="/dashboard" element={<Dashboard />} />
        <Route path="/metodo" element={<About />} />
        <Route path="/conta" element={<Conta />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
