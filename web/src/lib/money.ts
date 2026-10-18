// Display-only helper. All money arrives from the API as integer paise (ADR-009);
// never divide by 100 inline in components.
export function formatINR(paise: number): string {
  if (!Number.isInteger(paise)) throw new TypeError('paise must be an integer')
  const sign = paise < 0 ? '-' : ''
  const abs = Math.abs(paise)
  const rupees = Math.floor(abs / 100).toString()
  const rest = abs % 100
  const last3 = rupees.slice(-3)
  const head = rupees.slice(0, -3)
  const grouped = head ? head.replace(/\B(?=(\d{2})+(?!\d))/g, ',') + ',' + last3 : last3
  return `${sign}₹${grouped}${rest ? '.' + rest.toString().padStart(2, '0') : ''}`
}
