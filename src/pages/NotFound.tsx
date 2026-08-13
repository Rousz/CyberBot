import Button from '../components/Button'
import Container from '../components/Container'
import PulseMark from '../components/PulseMark'
import Seo from '../components/Seo'

export default function NotFound() {
  return (
    <>
      <Seo title="Page Not Found" description="The page you were looking for could not be found." />

      <section className="on-dark flex min-h-[80svh] items-center bg-ink pb-24 pt-40 text-paper">
        <Container>
          <PulseMark className="h-4 w-8 text-paper/50" />
          <h1 className="mt-8 text-display-lg font-black">Page not found.</h1>
          <p className="mt-6 max-w-xl text-lead text-paper/70">
            The page you were looking for has moved or no longer exists.
          </p>
          <div className="mt-12">
            <Button to="/" tone="dark">
              Back to Home
            </Button>
          </div>
        </Container>
      </section>
    </>
  )
}
