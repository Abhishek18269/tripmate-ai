import { FormEvent, ReactNode, useEffect, useState } from 'react'
import { createRoot } from 'react-dom/client'
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from 'react-leaflet'
import { planTrip, replanTrip } from './api'
import type { TripPlan, TripRequest } from './types'
import './index.css'

const today = new Date().toISOString().slice(0, 10)
const browserTimeZone = Intl.DateTimeFormat().resolvedOptions().timeZone
const initial: TripRequest = {
  origin: '', destination: '', departure_date: today, return_date: today,
  travelers: 2, budget: 3000, currency: 'INR', preferences: ['historical', 'food'],
  transport_mode: 'car', max_travel_hours: 5, preferred_start_time: '07:00',
  preferred_return_time: '21:00', departure_timezone: browserTimeZone, optional_stops: [], requirements: '',
}
const interests = ['historical', 'nature', 'adventure', 'food', 'shopping', 'family-friendly']
const examples = [
  { label: 'Delhi to Agra', origin: 'Delhi', destination: 'Agra', budget: 7000, currency: 'INR' },
  { label: 'Mumbai to Goa', origin: 'Mumbai', destination: 'Goa', budget: 12000, currency: 'INR' },
  { label: 'Chennai to Pondicherry', origin: 'Chennai', destination: 'Puducherry', budget: 5000, currency: 'INR' },
  { label: 'Paris to Versailles', origin: 'Paris', destination: 'Versailles', budget: 350, currency: 'EUR' },
]

function App() {
  const [form, setForm] = useState<TripRequest>(initial)
  const [trip, setTrip] = useState<TripPlan | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [change, setChange] = useState('')

  const update = <K extends keyof TripRequest>(key: K, value: TripRequest[K]) => setForm(current => ({ ...current, [key]: value }))
  const loadExample = (example: typeof examples[number]) => { setForm(current => ({ ...current, ...example })); setTrip(null) }
  const submit = async (event: FormEvent) => {
    event.preventDefault(); setLoading(true); setError('')
    try { setTrip(await planTrip(form)); setTimeout(() => document.getElementById('itinerary')?.scrollIntoView({ behavior: 'smooth' }), 50) }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to plan your trip.') }
    finally { setLoading(false) }
  }
  const replan = async () => {
    if (!trip || !change.trim()) return
    setLoading(true); setError('')
    try { setTrip(await replanTrip(trip, change, form.budget)); setChange('') }
    catch (err) { setError(err instanceof Error ? err.message : 'Unable to revise your trip.') }
    finally { setLoading(false) }
  }

  return <>
    <header className="mx-auto flex max-w-6xl items-center justify-between px-5 py-5">
      <a className="flex items-center gap-2 text-xl font-black" href="#top"><span className="grid h-9 w-9 place-items-center rounded-xl bg-coral text-white">*</span>TripMate <span className="text-coral">AI</span></a>
      <span className="hidden rounded-full bg-white px-4 py-2 text-xs font-bold text-slate-600 shadow-sm sm:block">Worldwide travel planning</span>
    </header>
    <main id="top">
      <section className="relative overflow-hidden px-5 pb-12 pt-8">
        <div className="absolute -right-20 top-0 h-72 w-72 rounded-full bg-orange-200/50 blur-3xl" />
        <div className="mx-auto grid max-w-6xl gap-10 lg:grid-cols-[1fr_.95fr] lg:items-center">
          <div>
            <p className="pill inline-block">Destination-neutral, tool-first planning</p>
            <h1 className="mt-5 max-w-2xl text-5xl font-black leading-[.97] tracking-tight sm:text-6xl">Your journey,<br /><span className="text-coral">intelligently</span> planned.</h1>
            <p className="mt-5 max-w-xl text-lg leading-8 text-slate-600">Enter any origin and destination. TripMate plans within your budget, looks up stays, and provides map and booking hand-offs. Live train and bus timetables appear when a map timetable provider is enabled.</p>
            <div className="mt-6 flex flex-wrap gap-3 text-sm font-semibold text-slate-600"><span>Places and routes</span><span>Honest estimates</span><span>Stays and ticket links</span></div>
          </div>
          <form onSubmit={submit} className="relative rounded-3xl bg-white p-5 shadow-float sm:p-7">
            <div className="mb-4 flex items-center justify-between"><div><h2 className="text-xl font-black">Plan a trip</h2><p className="text-sm text-slate-500">Any city or region. Refine the plan later.</p></div><span className="pill">Worldwide lookup</span></div>
            <div className="mb-4"><p className="label">Try an example</p><div className="mt-2 flex flex-wrap gap-2">{examples.map(example => <button type="button" key={example.label} onClick={() => loadExample(example)} className="rounded-full bg-slate-100 px-3 py-1.5 text-xs font-bold text-slate-600 transition hover:bg-slate-200">{example.label}</button>)}</div></div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="From"><input required placeholder="e.g. Hyderabad" className="field" value={form.origin} onChange={e => update('origin', e.target.value)} /></Field>
              <Field label="To"><input required placeholder="e.g. Hampi" className="field" value={form.destination} onChange={e => update('destination', e.target.value)} /></Field>
              <Field label="Departure"><input required type="date" className="field" value={form.departure_date} onChange={e => update('departure_date', e.target.value)} /></Field>
              <Field label="Return"><input type="date" className="field" value={form.return_date || ''} onChange={e => update('return_date', e.target.value || undefined)} /></Field>
              <Field label="Travelers"><input required min="1" max="20" type="number" className="field" value={form.travelers} onChange={e => update('travelers', Number(e.target.value))} /></Field>
              <Field label="Budget"><div className="flex gap-2"><select className="field w-20" value={form.currency} onChange={e => update('currency', e.target.value)}><option>INR</option><option>USD</option><option>EUR</option></select><input required min="1" type="number" className="field" value={form.budget} onChange={e => update('budget', Number(e.target.value))} /></div></Field>
            </div>
            <div className="mt-4"><p className="label">What do you enjoy?</p><div className="mt-2 flex flex-wrap gap-2">{interests.map(interest => <button type="button" key={interest} onClick={() => update('preferences', form.preferences.includes(interest) ? form.preferences.filter(x => x !== interest) : [...form.preferences, interest])} className={`rounded-full px-3 py-1.5 text-xs font-bold transition ${form.preferences.includes(interest) ? 'bg-ink text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>{interest}</button>)}</div></div>
            <details className="mt-4"><summary className="cursor-pointer text-sm font-bold text-moss">More trip preferences</summary><div className="mt-3 grid gap-3 sm:grid-cols-2"><Field label="Transport"><select className="field" value={form.transport_mode} onChange={e => update('transport_mode', e.target.value as TripRequest['transport_mode'])}><option value="car">Car</option><option value="train">Train</option><option value="bus">Bus</option><option value="transit">Transit</option><option value="walk">Walk</option></select></Field><Field label="Max travel hours"><input min="1" max="72" type="number" className="field" value={form.max_travel_hours || ''} onChange={e => update('max_travel_hours', Number(e.target.value) || undefined)} /></Field><Field label="Start time"><input type="time" className="field" value={form.preferred_start_time} onChange={e => update('preferred_start_time', e.target.value)} /></Field><Field label="Return by"><input type="time" className="field" value={form.preferred_return_time || ''} onChange={e => update('preferred_return_time', e.target.value || undefined)} /></Field></div><textarea className="field mt-3 min-h-20" placeholder="Accessibility needs, optional stops, or other requirements" value={form.requirements || ''} onChange={e => update('requirements', e.target.value)} /></details>
            {error && <p role="alert" className="mt-4 rounded-xl bg-red-50 p-3 text-sm text-red-700">{error}</p>}
            <button disabled={loading} className="mt-5 w-full rounded-xl bg-coral px-5 py-3 font-bold text-white shadow-lg shadow-coral/20 transition hover:-translate-y-0.5 disabled:cursor-wait disabled:opacity-60">{loading ? 'Building your trip plan...' : 'Plan my journey'}</button>
          </form>
        </div>
      </section>
      <section className="border-y border-orange-100 bg-white/70 px-5 py-6"><div className="mx-auto flex max-w-6xl flex-wrap justify-between gap-4 text-sm"><span><b>1.</b> Read constraints</span><span><b>2.</b> Find local places and stays</span><span><b>3.</b> Check time and budget</span><span><b>4.</b> Hand off to booking providers</span></div></section>
      {trip && <Results trip={trip} loading={loading} change={change} setChange={setChange} replan={replan} />}
    </main>
    <footer className="mx-auto max-w-6xl px-5 py-10 text-sm text-slate-500">TripMate AI. Built with Gemma 4, FastAPI, OpenStreetMap, Leaflet and open data. Verify operating hours, availability, prices, tickets and accommodation terms with the provider before payment.</footer>
  </>
}

function Field({ label, children }: { label: string; children: ReactNode }) { return <label><span className="label">{label}</span>{children}</label> }

function RouteViewport({ positions, fallback }: { positions: [number, number][]; fallback: [number, number] }) {
  const map = useMap()
  useEffect(() => {
    if (positions.length > 1) map.fitBounds(positions, { padding: [28, 28], maxZoom: 11 })
    else map.setView(fallback, 11)
  }, [map, positions, fallback])
  return null
}

function Results({ trip, loading, change, setChange, replan }: { trip: TripPlan; loading: boolean; change: string; setChange: (value: string) => void; replan: () => void }) {
  const day = trip.itinerary[0]
  const stopPositions = trip.itinerary.flatMap(item => item.stops.map(stop => [stop.place.location.lat, stop.place.location.lon] as [number, number]))
  const positions = (trip.route.geometry.length ? trip.route.geometry : stopPositions) as [number, number][]
  const center: [number, number] = [trip.destination.lat, trip.destination.lon]
  const budgetRemaining = Math.max(0, trip.request.budget - trip.total_cost)
  return <section id="itinerary" className="mx-auto max-w-6xl px-5 py-14">
    <div className="mb-7 flex flex-wrap items-end justify-between gap-3"><div><p className="pill">{trip.ai_mode === 'gemma-4' ? 'Gemma 4 assisted' : trip.ai_mode === 'deterministic-demo' ? 'Demo plan' : 'Tool-based plan'}</p><h2 className="mt-3 text-3xl font-black">{trip.title}</h2><p className="mt-2 max-w-2xl text-slate-600">{trip.summary}</p></div><button onClick={() => window.print()} className="rounded-xl border border-slate-200 bg-white px-4 py-2 text-sm font-bold">Print plan</button></div>
    <div className="grid gap-5 lg:grid-cols-[1.05fr_.95fr]">
      <div className="space-y-5">
        <div className="grid grid-cols-3 gap-3">{[[trip.route.distance_km !== undefined ? `${trip.route.distance_km} km` : 'Open map', 'road distance, one way'], [trip.route.duration_minutes !== undefined ? `${trip.route.duration_minutes} min` : 'Check provider', 'route time'], [`${trip.currency} ${budgetRemaining.toLocaleString()}`, 'budget remaining']].map(([value, label]) => <div key={label} className="rounded-2xl bg-ink p-4 text-white"><div className="text-lg font-black">{value}</div><div className="mt-1 text-xs text-white/65">{label}</div></div>)}</div>
        <div className="overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-sm"><div className="h-[340px]"><MapContainer center={center} zoom={11} className="h-full w-full" scrollWheelZoom={false}><RouteViewport positions={positions} fallback={center} /><TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />{positions.length > 1 && <Polyline positions={positions} pathOptions={{ color: '#ff765e', weight: 4 }} />}<Marker position={[trip.origin.lat, trip.origin.lon]}><Popup><b>Start: {trip.origin.label}</b></Popup></Marker>{trip.itinerary.flatMap(item => item.stops).map(stop => <Marker key={stop.place.id} position={[stop.place.location.lat, stop.place.location.lon]}><Popup><b>{stop.order}. {stop.place.name}</b><br />{stop.place.source}</Popup></Marker>)}</MapContainer></div><p className="px-4 py-3 text-xs text-slate-500">Route source: {trip.route.source}. {trip.route.verified ? 'Provider-supplied road route; the map is fitted to the full journey.' : 'No live transit distance is claimed; use the map link for current details.'}</p></div>
        <div className="rounded-3xl bg-white p-5 shadow-sm"><h3 className="font-black">Replan with new constraints</h3><p className="mt-1 text-sm text-slate-500">Try “make it more nature-focused”, “one stop is unavailable”, or revise the budget.</p><div className="mt-3 flex gap-2"><input className="field mt-0" value={change} onChange={e => setChange(e.target.value)} placeholder="What changed?" /><button disabled={loading || !change.trim()} onClick={replan} className="rounded-xl bg-moss px-4 text-sm font-bold text-white disabled:opacity-50">Replan</button></div></div>
      </div>
      <div className="space-y-5">
        <div className="rounded-3xl bg-white p-5 shadow-sm"><div className="flex items-center justify-between"><h3 className="font-black">{day.title}</h3><span className="text-xs font-bold text-slate-500">{day.date}</span></div>{day.stops.length ? <ol className="mt-4 space-y-3">{day.stops.map(stop => <li key={stop.place.id} className="relative rounded-2xl border border-slate-100 p-4"><span className="absolute -left-2 top-4 grid h-6 w-6 place-items-center rounded-full bg-coral text-xs font-black text-white">{stop.order}</span><div className="ml-3"><div className="flex gap-2"><h4 className="font-bold">{stop.place.name}</h4>{!stop.place.verified && <span className="text-xs text-amber-700">Verify</span>}</div><p className="mt-1 text-sm text-slate-600">{stop.arrival_time}-{stop.departure_time} · {stop.visit_minutes} min</p><p className="mt-2 text-xs leading-5 text-slate-500">{stop.reason}</p>{stop.place.opening_hours && <p className="mt-1 text-xs">Hours: {stop.place.opening_hours} ({stop.place.source})</p>}{stop.place.booking_url ? <a className="mt-2 inline-block text-xs font-bold text-moss underline" href={stop.place.booking_url} target="_blank" rel="noreferrer">Official ticket link</a> : stop.place.official_url && <a className="mt-2 inline-block text-xs font-bold text-moss underline" href={stop.place.official_url} target="_blank" rel="noreferrer">Official site</a>}</div></li>)}</ol> : <p className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-800">No stop fits the time constraints. Adjust the form and try again.</p>}<p className="mt-4 text-xs text-slate-500">{day.meal_breaks[0]} Includes {day.buffer_minutes} minutes of buffer.</p></div>
        {trip.itinerary.slice(1).map(item => <DayPlan key={item.date} day={item} />)}
        <TransitSchedule trip={trip} />
        <BookingOptions trip={trip} />
        <AccommodationOptions trip={trip} />
        <div className="rounded-3xl bg-white p-5 shadow-sm"><h3 className="font-black">Budget breakdown</h3>{trip.cost_items.map(item => <div key={item.label} className="mt-3 flex justify-between gap-3 text-sm"><span>{item.label}<small className="block text-xs text-slate-400">{item.estimated ? 'Planning cap. ' : ''}{item.source}</small></span><b>{trip.currency} {item.amount.toLocaleString()}</b></div>)}<div className="mt-4 flex justify-between border-t pt-3 font-black"><span>Planned allowance</span><span>{trip.currency} {trip.total_cost.toLocaleString()}</span></div><div className="mt-2 flex justify-between text-sm font-bold text-moss"><span>Protected booking buffer</span><span>{trip.currency} {budgetRemaining.toLocaleString()}</span></div></div>
        <div className="rounded-3xl border border-amber-200 bg-amber-50 p-5"><h3 className="font-black text-amber-900">Before you go</h3><ul className="mt-2 space-y-2 text-sm text-amber-900">{trip.warnings.map((warning, index) => <li key={index}>• {warning}</li>)}</ul></div>
        <details className="rounded-2xl bg-white p-4 text-sm shadow-sm"><summary className="cursor-pointer font-bold">Agent tool trace</summary><ul className="mt-3 space-y-2 text-slate-600">{trip.tool_events.map((event, index) => <li key={index}><b className="capitalize">{event.tool}</b> · {event.status} — {event.detail}</li>)}</ul></details>
      </div>
    </div>
  </section>
}

function DayPlan({ day }: { day: TripPlan['itinerary'][number] }) {
  return <div className="rounded-3xl bg-white p-5 shadow-sm"><div className="flex items-center justify-between"><h3 className="font-black">{day.title}</h3><span className="text-xs font-bold text-slate-500">{day.date}</span></div>{day.stops.length ? <ol className="mt-4 space-y-3">{day.stops.map(stop => <li key={stop.place.id} className="relative rounded-2xl border border-slate-100 p-4"><span className="absolute -left-2 top-4 grid h-6 w-6 place-items-center rounded-full bg-coral text-xs font-black text-white">{stop.order}</span><div className="ml-3"><div className="flex gap-2"><h4 className="font-bold">{stop.place.name}</h4>{!stop.place.verified && <span className="text-xs text-amber-700">Verify</span>}</div><p className="mt-1 text-sm text-slate-600">{stop.arrival_time} to {stop.departure_time} · {stop.visit_minutes} min</p><p className="mt-2 text-xs leading-5 text-slate-500">{stop.reason}</p>{stop.place.opening_hours && <p className="mt-1 text-xs">Hours: {stop.place.opening_hours} ({stop.place.source})</p>}{stop.place.official_url && <a className="mt-2 inline-block text-xs font-bold text-moss underline" href={stop.place.official_url} target="_blank" rel="noreferrer">{stop.place.source.includes('OpenStreetMap') ? 'View on OpenStreetMap' : 'Official site'}</a>}</div></li>)}</ol> : <p className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-800">No stop fits the selected travel time. Try a later return time or a shorter route.</p>}<p className="mt-4 text-xs text-slate-500">{day.meal_breaks[0]} Includes {day.buffer_minutes} minutes of buffer.</p></div>
}

function formatProviderTime(value?: string) {
  if (!value) return 'Not supplied'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })
}

function TransitSchedule({ trip }: { trip: TripPlan }) {
  const isTransit = ['bus', 'train', 'transit'].includes(trip.request.transport_mode)
  if (!isTransit) return null
  const segments = trip.route.transit_segments || []
  return <div className="rounded-3xl bg-white p-5 shadow-sm"><h3 className="font-black">Departure and route details</h3>{segments.length ? <><p className="mt-1 text-xs text-slate-500">Live provider schedule. Times are shown in your browser's time zone; recheck availability before payment.</p><div className="mt-3 space-y-3">{segments.map((segment, index) => <div key={`${segment.line || segment.mode}-${index}`} className="rounded-2xl border border-slate-100 p-3"><div className="flex items-center justify-between gap-2"><b className="text-sm">{segment.line || segment.vehicle || segment.mode}</b><span className="text-xs uppercase text-slate-500">{segment.mode}</span></div>{segment.headsign && <p className="mt-1 text-xs text-slate-600">Towards {segment.headsign}</p>}<div className="mt-2 grid grid-cols-2 gap-2 text-xs"><span><b>Departs</b><br />{formatProviderTime(segment.departure_time)}{segment.departure_stop && <><br />{segment.departure_stop}</>}</span><span><b>Arrives</b><br />{formatProviderTime(segment.arrival_time)}{segment.arrival_stop && <><br />{segment.arrival_stop}</>}</span></div><p className="mt-2 text-xs text-slate-500">{segment.duration_minutes ? `${segment.duration_minutes} min` : 'Duration not supplied'}{segment.stop_count !== undefined ? ` · ${segment.stop_count} stops` : ''}</p></div>)}</div>{trip.route.fare_amount !== undefined && <p className="mt-3 text-sm font-bold text-moss">Provider fare: {trip.route.fare_currency || trip.currency} {trip.route.fare_amount.toLocaleString()} <span className="font-normal text-slate-500">(confirm before booking)</span></p>}</> : <div className="mt-3 rounded-2xl bg-amber-50 p-3 text-sm text-amber-900"><b>Schedule not yet connected.</b><p className="mt-1">Requested departure: {trip.request.departure_date} at {trip.request.preferred_start_time}. Open the booking link below for current departures, or add a Google Maps Routes API key to enable live times in TripMate.</p></div>}</div>
}

function BookingOptions({ trip }: { trip: TripPlan }) {
  if (!trip.ticket_booking_options.length) return null
  return <div className="rounded-3xl bg-white p-5 shadow-sm"><h3 className="font-black">Tickets and transport</h3><p className="mt-1 text-xs text-slate-500">TripMate does not purchase tickets. These links open provider or route searches where you can verify availability and complete booking.</p><div className="mt-3 space-y-3">{trip.ticket_booking_options.map(option => <div key={option.id} className="rounded-2xl border border-slate-100 p-3"><div className="flex items-center justify-between gap-2"><b className="text-sm">{option.title}</b><span className="text-xs text-slate-500">{option.provider}</span></div><p className="mt-1 text-xs text-slate-500">{option.description}</p><a className="mt-2 inline-block text-xs font-bold text-moss underline" href={option.url} target="_blank" rel="noreferrer">{option.category === 'official_ticket' ? 'Check official tickets' : 'Open booking search'}</a></div>)}</div></div>
}

function AccommodationOptions({ trip }: { trip: TripPlan }) {
  if (!trip.accommodation_suggestions.length) return null
  return <div className="rounded-3xl bg-white p-5 shadow-sm"><h3 className="font-black">Where to stay</h3><p className="mt-1 text-xs text-slate-500">Compare live price, rooms, accessibility and cancellation terms before reserving.</p><div className="mt-3 space-y-3">{trip.accommodation_suggestions.map(stay => <div key={stay.id} className="rounded-2xl border border-slate-100 p-3"><div className="flex items-center justify-between gap-2"><b className="text-sm">{stay.name}</b><span className="text-xs capitalize text-slate-500">{stay.kind}</span></div><p className="mt-1 text-xs text-slate-500">{stay.description}</p><div className="mt-2 flex gap-3">{stay.official_url && <a className="text-xs font-bold text-moss underline" href={stay.official_url} target="_blank" rel="noreferrer">Official site</a>}{stay.booking_url && <a className="text-xs font-bold text-moss underline" href={stay.booking_url} target="_blank" rel="noreferrer">{stay.booking_action === 'official_site' ? 'Reserve with property' : 'Search stays'}</a>}</div></div>)}</div></div>
}

createRoot(document.getElementById('root')!).render(<App />)
