import { BrowserRouter, NavLink, Navigate, Route, Routes } from 'react-router-dom'
import DashboardPage from './pages/DashboardPage'
import UploadPage from './pages/UploadPage'

export default function App() {
  return (
    <BrowserRouter>
      <header className="app-header">
        <div className="app-header__inner">
          <span className="brand">
            <img src="/favicon.svg" alt="" width={22} height={22} />
            SLA Monitor
          </span>
          <nav>
            <NavLink to="/" end>
              Upload
            </NavLink>
            <NavLink to="/dashboard">Dashboard</NavLink>
          </nav>
        </div>
      </header>
      <main className="app-main">
        <Routes>
          <Route path="/" element={<UploadPage />} />
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/dashboard/:uploadId" element={<DashboardPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </main>
    </BrowserRouter>
  )
}
