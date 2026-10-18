import { useEffect, useState } from 'react'

// Per-device preference stored in localStorage (memberships, chosen list, tab). Never data that must be shared.
export function usePreference<T>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(`dealscour:${key}`)
      return raw === null ? initial : (JSON.parse(raw) as T)
    } catch {
      return initial
    }
  })
  useEffect(() => {
    try {
      localStorage.setItem(`dealscour:${key}`, JSON.stringify(value))
    } catch {
      // private mode or blocked storage: the preference just isn't remembered
    }
  }, [key, value])
  return [value, setValue]
}
