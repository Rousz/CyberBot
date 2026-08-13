import { useState, type FormEvent } from 'react'
import Button from '../../components/Button'
import Icon from '../../components/Icon'
import { site } from '../../data/site'

const inquiryTypes = [
  'Distributor / Industry Partner',
  'Artist',
  'Label',
  'Press',
  'Other',
]

const fieldClasses =
  'w-full border border-ink/20 bg-paper px-4 py-3.5 text-sm text-ink transition-colors placeholder:text-steel/70 hover:border-ink/40 focus:border-ink'

const labelClasses = 'mb-3 block text-[11px] font-semibold uppercase tracking-[0.16em] text-steel'

type Status = 'idle' | 'submitting' | 'success' | 'error'

export default function ContactForm() {
  const [status, setStatus] = useState<Status>('idle')
  const [message, setMessage] = useState('')

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const form = event.currentTarget
    const data = new FormData(form)

    if (data.get('_gotcha')) return

    if (site.formEndpoint.includes('YOUR_FORM_ID')) {
      setStatus('error')
      setMessage(`The form is not connected yet. Please email ${site.email} and we will respond directly.`)
      return
    }

    setStatus('submitting')

    try {
      const response = await fetch(site.formEndpoint, {
        method: 'POST',
        headers: { Accept: 'application/json' },
        body: data,
      })

      if (!response.ok) throw new Error('Request failed')

      form.reset()
      setStatus('success')
      setMessage('Thank you — your message has been sent. We will be in touch shortly.')
    } catch {
      setStatus('error')
      setMessage(`Your message could not be sent. Please email ${site.email} instead.`)
    }
  }

  if (status === 'success') {
    return (
      <div className="border border-ink/20 p-10">
        <h2 className="text-display-sm font-black">Message received.</h2>
        <p className="mt-4 text-sm leading-relaxed text-steel">{message}</p>
      </div>
    )
  }

  return (
    <form onSubmit={handleSubmit} noValidate={false} className="space-y-8">
      <input type="hidden" name="_subject" value="New enquiry — synoramusicgroup.com" />
      <input
        type="text"
        name="_gotcha"
        tabIndex={-1}
        autoComplete="off"
        aria-hidden="true"
        className="hidden"
      />

      <div className="grid gap-8 md:grid-cols-2">
        <div>
          <label htmlFor="name" className={labelClasses}>
            Name <span aria-hidden="true">*</span>
          </label>
          <input
            id="name"
            name="name"
            type="text"
            required
            autoComplete="name"
            className={fieldClasses}
          />
        </div>

        <div>
          <label htmlFor="email" className={labelClasses}>
            Email <span aria-hidden="true">*</span>
          </label>
          <input
            id="email"
            name="email"
            type="email"
            required
            autoComplete="email"
            className={fieldClasses}
          />
        </div>
      </div>

      <div className="grid gap-8 md:grid-cols-2">
        <div>
          <label htmlFor="organization" className={labelClasses}>
            Company / Project
          </label>
          <input
            id="organization"
            name="organization"
            type="text"
            autoComplete="organization"
            className={fieldClasses}
          />
        </div>

        <div>
          <label htmlFor="inquiryType" className={labelClasses}>
            I am a… <span aria-hidden="true">*</span>
          </label>
          <div className="relative">
            <select
              id="inquiryType"
              name="inquiryType"
              required
              defaultValue=""
              className={`${fieldClasses} appearance-none pr-12`}
            >
              <option value="" disabled>
                Select one
              </option>
              {inquiryTypes.map((type) => (
                <option key={type} value={type}>
                  {type}
                </option>
              ))}
            </select>
            <Icon
              name="chevronDown"
              className="pointer-events-none absolute right-4 top-1/2 h-4 w-4 -translate-y-1/2 text-steel"
            />
          </div>
        </div>
      </div>

      <div>
        <label htmlFor="message" className={labelClasses}>
          Message <span aria-hidden="true">*</span>
        </label>
        <textarea id="message" name="message" required rows={6} className={`${fieldClasses} resize-y`} />
      </div>

      <div className="flex flex-col gap-6 sm:flex-row sm:items-center">
        <Button type="submit" disabled={status === 'submitting'}>
          {status === 'submitting' ? 'Sending…' : 'Send Message'}
        </Button>
        <p className="text-xs leading-relaxed text-steel">
          Fields marked <span aria-hidden="true">*</span> are required.
        </p>
      </div>

      <p aria-live="polite" className="text-sm text-ink">
        {status === 'error' ? message : ''}
      </p>
    </form>
  )
}
