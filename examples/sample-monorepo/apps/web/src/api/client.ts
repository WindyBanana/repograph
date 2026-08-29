import axios from "axios";

const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8080";

export const http = axios.create({ baseURL: API_BASE, timeout: 8000 });

export interface Order {
  id: string;
  customer_id: string;
  status: string;
}

export async function listOrders(customerId: string): Promise<Order[]> {
  const { data } = await http.get(`/orders`, { params: { customer: customerId } });
  return data;
}

export async function createOrder(order: Partial<Order>): Promise<Order> {
  const { data } = await http.post("/orders", order);
  return data;
}
