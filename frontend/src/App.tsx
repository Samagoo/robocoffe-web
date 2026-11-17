// Routes: /  customer ordering (temporary validation UI) · /admin  live orders · /status  platform status.
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import AdminPage from "./pages/AdminPage";
import CustomerPage from "./pages/CustomerPage";
import StatusPage from "./pages/StatusPage";
import "./styles.css";

export default function App() {
  return (
    <BrowserRouter>
      <nav>
        <span className="brand">RoboCoffee</span>
        <NavLink to="/" end>Order</NavLink>
        <NavLink to="/admin">Admin</NavLink>
        <NavLink to="/status">Status</NavLink>
      </nav>
      <Routes>
        <Route path="/" element={<CustomerPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="/status" element={<StatusPage />} />
      </Routes>
    </BrowserRouter>
  );
}
