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

// Parse a rupee amount typed by the user ("500", "1,250", "49.5") into integer paise. null if invalid.
export function parseRupees(input: string): number | null {
  const s = input.trim().replace(/,/g, '')
  if (!/^\d+(\.\d{1,2})?$/.test(s)) return null
  const [whole, frac = ''] = s.split('.')
  return Number(whole) * 100 + Number(frac.padEnd(2, '0'))
}

// Plain decimal string for <input type="number">, e.g. 27500 -> "275", 27550 -> "275.50".
// Empty or NaN returns "".
export function paiseToRupeesInput(paise: number): string {
  if (typeof paise !== 'number' || Number.isNaN(paise)) return ''
  const sign = paise < 0 ? '-' : ''
  const abs = Math.abs(paise)
  const rupees = Math.floor(abs / 100).toString()
  const rest = abs % 100
  if (rest === 0) {
    return `${sign}${rupees}`
  }
  return `${sign}${rupees}.${rest.toString().padStart(2, '0')}`
}
