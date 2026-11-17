// Routes: /  customer ordering · /status  platform status + recent orders.
// The admin page (/admin) arrives in Phase 3.
import { BrowserRouter, NavLink, Route, Routes } from "react-router-dom";
import CustomerPage from "./pages/CustomerPage";
import StatusPage from "./pages/StatusPage";
import "./styles.css";

export default function App() {
  return (
    <BrowserRouter>
      <nav>
        <span className="brand">RoboCoffee</span>
        <NavLink to="/" end>Order</NavLink>
        <NavLink to="/status">Status</NavLink>
      </nav>
      <Routes>
        <Route path="/" element={<CustomerPage />} />
        <Route path="/status" element={<StatusPage />} />
      </Routes>
    </BrowserRouter>
  );
}
