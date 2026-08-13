import { Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import About from './pages/About'
import Contact from './pages/Contact'
import CopyrightPolicy from './pages/CopyrightPolicy'
import Home from './pages/Home'
import NotFound from './pages/NotFound'
import Partners from './pages/Partners'
import Press from './pages/Press'
import Privacy from './pages/Privacy'
import Production from './pages/Production'
import Roster from './pages/Roster'
import Terms from './pages/Terms'

export default function App() {
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route path="/" element={<Home />} />
        <Route path="/about" element={<About />} />
        <Route path="/production" element={<Production />} />
        <Route path="/roster" element={<Roster />} />
        <Route path="/partners" element={<Partners />} />
        <Route path="/press" element={<Press />} />
        <Route path="/contact" element={<Contact />} />
        <Route path="/copyright" element={<CopyrightPolicy />} />
        <Route path="/privacy" element={<Privacy />} />
        <Route path="/terms" element={<Terms />} />
        <Route path="*" element={<NotFound />} />
      </Route>
    </Routes>
  )
}
