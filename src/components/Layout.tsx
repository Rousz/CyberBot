import { Outlet } from 'react-router-dom'
import Footer from './Footer'
import Nav from './Nav'
import ScrollManager from './ScrollManager'

export default function Layout() {
  return (
    <>
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[60] focus:bg-ink focus:px-5 focus:py-3 focus:text-xs focus:font-semibold focus:uppercase focus:tracking-[0.16em] focus:text-paper"
      >
        Skip to content
      </a>
      <ScrollManager />
      <Nav />
      <main id="main">
        <Outlet />
      </main>
      <Footer />
    </>
  )
}
