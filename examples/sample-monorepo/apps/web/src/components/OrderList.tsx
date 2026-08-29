import { useEffect, useState } from "react";

import { listOrders, Order } from "@/api/client";

export function OrderList({ customerId }: { customerId: string }) {
  const [orders, setOrders] = useState<Order[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    listOrders(customerId).then(setOrders).catch((e) => setError(String(e)));
  }, [customerId]);

  if (error) return <div className="error" dangerouslySetInnerHTML={{ __html: error }} />;

  return (
    <ul>
      {orders.map((order) => (
        <li key={order.id}>
          {order.id} — {order.status}
        </li>
      ))}
    </ul>
  );
}
