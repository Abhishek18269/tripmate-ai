import type { TripPlan, TripRequest } from './types'
const base = import.meta.env.VITE_API_BASE_URL || ''
async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${base}${path}`, { headers: { 'Content-Type': 'application/json' }, ...options })
  if (!response.ok) { const body = await response.json().catch(() => ({})); throw new Error(body.detail || 'TripMate could not complete that request.') }
  return response.status === 204 ? undefined as T : response.json()
}
export const planTrip = (trip: TripRequest) => request<TripPlan>('/api/trips/plan', { method: 'POST', body: JSON.stringify(trip) })
export const replanTrip = (trip: TripPlan, change_request: string, revised_budget?: number) => request<TripPlan>('/api/trips/replan', { method: 'POST', body: JSON.stringify({ trip, change_request, revised_budget }) })

