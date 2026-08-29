import { BrowserRouter, Route, Routes } from "react-router-dom";

import { OrderList } from "@/components/OrderList";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<OrderList customerId="me" />} />
        <Route path="/orders/:id" element={<OrderList customerId="me" />} />
      </Routes>
    </BrowserRouter>
  );
}
