import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthDialog } from './components/AuthDialog'
import { Header } from './components/Header'
import { Toasts } from './components/Toasts'
import { Home } from './pages/Home'
import { Planner } from './pages/Planner'
import { Shared } from './pages/Shared'
import { Trips } from './pages/Trips'

const queryClient = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } })

export function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Header />
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/plan" element={<Planner />} />
          <Route path="/plan/:tripId" element={<Planner />} />
          <Route path="/trips" element={<Trips />} />
          <Route path="/shared/:slug" element={<Shared />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
        <AuthDialog />
        <Toasts />
      </BrowserRouter>
    </QueryClientProvider>
  )
}
