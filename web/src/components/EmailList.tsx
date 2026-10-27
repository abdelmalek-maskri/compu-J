import { useEffect, useRef } from 'react'
import type { Email } from '../api'
import { formatDate } from '../filters'

type Props = {
  emails: Email[]
  total: number
  selectedId: string | null
  onSelect: (id: string) => void
}

export function EmailList({ emails, total, selectedId, onSelect }: Props) {
  const selectedRef = useRef<HTMLLIElement>(null)

  // keyboard navigation can move the selection off screen
  useEffect(() => {
    selectedRef.current?.scrollIntoView({ block: 'nearest' })
  }, [selectedId])

  return (
    <>
      <p className="px-4 py-2 text-[12px] text-muted border-b border-rule" aria-live="polite">
        {emails.length === total ? `${total} emails` : `${emails.length} of ${total} emails`}
      </p>
      {emails.length === 0 ? (
        <p className="px-4 py-10 text-muted text-[14px]">
          Nothing matches. Try fewer words, or remove a filter above.
        </p>
      ) : (
        <ul aria-label="Emails">
          {emails.map((email) => {
            const selected = email.source_file === selectedId
            return (
              <li key={email.source_file} ref={selected ? selectedRef : undefined}>
                <button
                  type="button"
                  onClick={() => onSelect(email.source_file)}
                  aria-current={selected || undefined}
                  className={`block w-full text-left px-4 py-3 border-b border-rule ${
                    selected
                      ? 'bg-paper-deep shadow-[inset_3px_0_0_var(--color-accent)]'
                      : 'hover:bg-paper-deep/50'
                  }`}
                >
                  <span className="block font-serif font-semibold text-[15px] leading-snug line-clamp-2">
                    {email.folder_name}
                  </span>
                  <span className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-[12px] text-muted">
                    <span>{email.bank}</span>
                    <span className="tabular-nums">
                      {email.date
                        ? `${formatDate(email.date)}${email.date_confirmed ? '' : ' (not confirmed)'}`
                        : 'No publication date found'}
                    </span>
                    {email.primary_asset_tag && (
                      <span
                        className={`px-1.5 border ${
                          email.market_wrap === 'YES'
                            ? 'border-ink text-ink'
                            : 'border-rule text-ink'
                        }`}
                      >
                        {email.primary_asset_tag}
                      </span>
                    )}
                    {email.pdf_attachment && <span title="Has a PDF">PDF</span>}
                    {email.flag_count > 0 && (
                      <span className="bg-flag text-flag-ink px-1.5">
                        {email.flag_count === 1 ? '1 to check' : `${email.flag_count} to check`}
                      </span>
                    )}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      )}
    </>
  )
}
